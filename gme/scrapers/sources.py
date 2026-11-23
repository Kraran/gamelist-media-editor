"""Fallback scrape sources: settings, answer cache and shared helpers.

ScreenScraper stays the main source. LaunchBox Games Database, TheGamesDB
and IGDB only fill what it does not have (game unknown there, a missing
field or media, or its quota reached), in the order and for the fields set in
Settings › Fallback sources. Everything is off until the user turns a source on.

Settings live in ``sources_config.json`` next to the app (gitignored), like
``screenscraper_config.json``. The TheGamesDB key and the IGDB client secret
are never sent back to the interface (only ``*_set`` flags) and never written
to the log; the IGDB access token is kept in memory only.

Answers of TheGamesDB and IGDB are cached on disk (``cache/sources-api``,
gzip) for the ScreenScraper cache duration: a rescrape costs no allowance.
Keys are removed before the cache key is computed; errors are never cached.
"""

import gzip
import hashlib
import json
import os
import re
import threading
import time

from gme.fsutil import atomic_write
from gme.log import log
from gme.paths import APP_DIR

CONFIG_NAME = "sources_config.json"
CACHE_DIR = os.path.join(APP_DIR, "cache", "sources-api")
FALLBACKS = ("launchbox", "thegamesdb", "igdb")
ALL_SOURCES = ("screenscraper",) + FALLBACKS
LABELS = {"screenscraper": "ScreenScraper", "launchbox": "LaunchBox",
          "thegamesdb": "TheGamesDB", "igdb": "IGDB"}
SECRETS = ("tgdb_apikey", "igdb_client_secret")
NEGATIVE_TTL = 24 * 3600

# What each source can give (gamelist field names)
SUPPORTED = {
    "launchbox": ("name", "desc", "rating", "releasedate", "developer", "publisher", "genre", "players",
                  "image", "titleshot", "thumbnail", "boxart", "boxback", "marquee", "wheel",
                  "cartridge", "fanart"),
    "thegamesdb": ("name", "desc", "releasedate", "developer", "publisher", "genre", "players",
                   "image", "titleshot", "thumbnail", "boxback", "marquee", "wheel", "fanart"),
    "igdb": ("name", "desc", "rating", "releasedate", "developer", "publisher", "genre",
             "image", "thumbnail", "fanart"),
}
# Filled by default when a source is turned on: everything but the name (the
# gamelist name is the user's; a fallback name is only proposed when asked).
DEFAULT_FIELDS = {src: [f for f in fields if f != "name"] for src, fields in SUPPORTED.items()}

_lock = threading.Lock()


def config_path():
    return os.path.join(APP_DIR, CONFIG_NAME)


def _defaults():
    return {
        "order": list(ALL_SOURCES),
        "enabled": {src: False for src in FALLBACKS},
        "fields": {src: list(DEFAULT_FIELDS[src]) for src in FALLBACKS},
        "on_ss_quota": "continue",
        "tgdb_apikey": "",
        "igdb_client_id": "",
        "igdb_client_secret": "",
    }


def normalize_order(raw):
    out = [s for s in (raw if isinstance(raw, list) else []) if s in ALL_SOURCES]
    out = list(dict.fromkeys(out))
    return out + [s for s in ALL_SOURCES if s not in out]


def _normalize(data):
    cfg = _defaults()
    if not isinstance(data, dict):
        return cfg
    cfg["order"] = normalize_order(data.get("order"))
    enabled = data.get("enabled") if isinstance(data.get("enabled"), dict) else {}
    cfg["enabled"] = {src: bool(enabled.get(src, False)) for src in FALLBACKS}
    fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
    for src in FALLBACKS:
        if isinstance(fields.get(src), list):
            cfg["fields"][src] = [f for f in SUPPORTED[src] if f in fields[src]]
    cfg["on_ss_quota"] = "stop" if data.get("on_ss_quota") == "stop" else "continue"
    for key in ("tgdb_apikey", "igdb_client_id", "igdb_client_secret"):
        if data.get(key):
            cfg[key] = str(data[key]).strip()
    return cfg


def load_config():
    path = config_path()
    if not os.path.isfile(path):
        return _defaults()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _normalize(json.load(f))
    except (OSError, ValueError):
        return _defaults()


def save_config(body):
    """Merge ``body`` (from the interface) into the saved settings."""
    with _lock:
        cfg = load_config()
        if "order" in body:
            cfg["order"] = normalize_order(body.get("order"))
        if isinstance(body.get("enabled"), dict):
            for src in FALLBACKS:
                if src in body["enabled"]:
                    cfg["enabled"][src] = bool(body["enabled"][src])
        if isinstance(body.get("fields"), dict):
            for src in FALLBACKS:
                if isinstance(body["fields"].get(src), list):
                    cfg["fields"][src] = [f for f in SUPPORTED[src] if f in body["fields"][src]]
        if body.get("on_ss_quota") in ("continue", "stop"):
            cfg["on_ss_quota"] = body["on_ss_quota"]
        for key in ("tgdb_apikey", "igdb_client_id", "igdb_client_secret"):
            if body.get(key):
                cfg[key] = str(body[key]).strip()
            if body.get("clear_" + key):
                cfg[key] = ""
        atomic_write(config_path(), json.dumps(cfg, indent=2, ensure_ascii=False).encode("utf-8"))
    return cfg


def configured(src, cfg):
    """Has the source what it needs to answer (a key, a downloaded base)?"""
    if src == "thegamesdb":
        return bool(cfg.get("tgdb_apikey"))
    if src == "igdb":
        return bool(cfg.get("igdb_client_id") and cfg.get("igdb_client_secret"))
    if src == "launchbox":
        from gme.scrapers import launchbox
        return launchbox.ready()
    return True


def active_fallbacks(cfg=None):
    """Enabled and configured fallback sources, in the user's order."""
    cfg = cfg or load_config()
    return [s for s in cfg["order"] if s in FALLBACKS and cfg["enabled"].get(s) and configured(s, cfg)]


def continue_on_ss_block(cfg=None):
    """A ScreenScraper quota does not stop a batch: the fallbacks go on alone."""
    cfg = cfg or load_config()
    return cfg.get("on_ss_quota") != "stop" and bool(active_fallbacks(cfg))


# --- never leak a key ---------------------------------------------------------------
_SECRET_QS = re.compile(r"(apikey|client_secret|client_id|access_token)=[^&\s'\"]+", re.I)
_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+")


def redact(text, cfg=None):
    """``text`` without keys, tokens or URLs carrying them (errors, logs)."""
    out = _BEARER.sub("Bearer [hidden]", _SECRET_QS.sub(r"\1=[hidden]", str(text or "")))
    cfg = cfg or load_config()
    for key in SECRETS + ("igdb_client_id",):
        value = cfg.get(key)
        if value and len(value) >= 6:
            out = out.replace(value, "[hidden]")
    return out


# --- answer cache (TheGamesDB, IGDB) ---------------------------------------------------
def _cache_days():
    from gme.scrapers import ss, ss_cache
    cfg = ss.load_ss_config()
    if cfg.get("cache_enabled", True) is False:
        return 0
    return ss_cache.normalize_days(cfg.get("cache_days"))


def _cache_path(source, key_parts):
    blob = json.dumps({"v": 1, "source": source, "key": key_parts}, sort_keys=True, ensure_ascii=False)
    return os.path.join(CACHE_DIR, source + "-" + hashlib.sha256(blob.encode("utf-8")).hexdigest() + ".json.gz")


def cache_get(source, key_parts, refresh=False):
    """A cached answer (``key_parts`` must not hold any key), or None."""
    days = _cache_days()
    if not days or refresh:
        return None
    path = _cache_path(source, key_parts)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            entry = json.load(f)
    except (OSError, ValueError):
        return None
    ttl = NEGATIVE_TTL if entry.get("empty") else days * 86400
    if time.time() - float(entry.get("time") or 0) > ttl:
        return None
    return entry.get("data")


def cache_put(source, key_parts, data, empty=False):
    if not _cache_days():
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        blob = json.dumps({"time": time.time(), "empty": bool(empty), "data": data}, ensure_ascii=False)
        atomic_write(_cache_path(source, key_parts), gzip.compress(blob.encode("utf-8")))
    except OSError as exc:
        log.warning("Fallback source cache not written: %s", exc)


class Throttle:
    """One request at a time for a source, at least ``interval`` seconds apart."""

    def __init__(self, interval):
        self.interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def __enter__(self):
        self._lock.acquire()
        wait = self.interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        return self

    def __exit__(self, *exc):
        self._last = time.monotonic()
        self._lock.release()
        return False


# --- titles ---------------------------------------------------------------------------
_TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_ROM_EXT = re.compile(r"\.[A-Za-z0-9]{1,4}$")


def norm_title(name, rom=False):
    """A title reduced for comparisons: no tags, accents, punctuation, "The"."""
    import unicodedata
    s = str(name or "")
    if rom:
        s = _ROM_EXT.sub("", os.path.basename(s))
        s = s.replace("_", " ")
    prev = None
    while prev != s:
        prev, s = s, _TAGS.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r",\s*the\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    if s.startswith("the "):
        s = s[4:]
    return s


def query_names(game, proposed_name=""):
    """Names to look a game up with, best first: ScreenScraper's, the gamelist's, the ROM's."""
    path = game.findtext("path", "") or ""
    out = []
    for raw, rom in ((proposed_name, False), (game.findtext("name", "") or "", False), (path, True)):
        n = norm_title(raw, rom=rom)
        if n and n not in [o[0] for o in out]:
            title = _TAGS.sub("", _ROM_EXT.sub("", os.path.basename(raw)) if rom else raw).replace("_", " ").strip()
            out.append((n, title))
    return out


def iso_to_es(date):
    """``YYYY-MM-DD`` / ``YYYY`` → EmulationStation ``YYYYMMDDT000000``."""
    digits = re.sub(r"\D", "", str(date or ""))[:8]
    if len(digits) == 4:
        digits += "0101"
    if len(digits) != 8:
        return ""
    return digits + "T000000"


# Region names of the preferred region (Settings › ScreenScraper), for picking
# among a game's images (LaunchBox) — the rest follow in a common order.
_REGION_NAMES = {
    "fr": ("France", "Europe"), "de": ("Germany", "Europe"), "es": ("Spain", "Europe"),
    "it": ("Italy", "Europe"), "uk": ("United Kingdom", "Europe"), "pt": ("Portugal", "Europe"),
    "eu": ("Europe",), "us": ("North America", "United States"), "jp": ("Japan",),
    "wor": ("World",), "br": ("Brazil",), "kr": ("Korea",), "asi": ("Asia",),
}
_REGION_TAIL = ("World", "", "Europe", "North America", "United States", "United Kingdom", "Japan")


def region_order(prefer):
    out = list(_REGION_NAMES.get(prefer or "fr", ())) + list(_REGION_TAIL)
    return list(dict.fromkeys(out))
