#!/usr/bin/env python3
"""
Gamelist Media Editor — local Flask app for EmulationStation / RetroBat gamelist.xml.

Bound to 127.0.0.1 only. Edits media paths and metadata, with optional .bak backups.
"""
import os
import sys
import re
import shutil
import threading
import time
import hashlib
import json
import zlib
from urllib.parse import urlparse, unquote, quote

from flask import Flask, render_template, request, jsonify, send_from_directory
from lxml import etree
import requests
import logging

log = logging.getLogger("gamelist-editor")

app = Flask(__name__)


def api_err(message, status=400, code=None, **extra):
    """Consistent JSON error payload for the frontend."""
    payload = {"error": str(message), "ok": False}
    if code:
        payload["code"] = code
    payload.update(extra)
    return jsonify(payload), status


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCALE_DIR = os.path.join(BASE_DIR, "static", "locales")
_LOCALE_CACHE = {}


def load_locale_dict(code):
    """Load static/locales/{code}.json (cached). Falls back to fr."""
    code = (code or "fr")[:2].lower()
    if code in _LOCALE_CACHE:
        return _LOCALE_CACHE[code]
    path = os.path.join(_LOCALE_DIR, f"{code}.json")
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        if code != "fr":
            return load_locale_dict("fr")
    _LOCALE_CACHE[code] = data
    return data


def get_request_locale():
    """Prefer X-Locale (frontend), then Accept-Language, else fr."""
    try:
        h = (request.headers.get("X-Locale") or "").strip().lower()
        if len(h) >= 2 and h[:2].isalpha():
            return h[:2]
        al = (request.headers.get("Accept-Language") or "").lower()
        if al.startswith("en"):
            return "en"
    except RuntimeError:
        # Outside request context
        pass
    return "fr"


def st(key, **params):
    """Server-side translation. key e.g. 'server.invalid_field'."""
    data = load_locale_dict(get_request_locale())
    parts = str(key).split(".")
    cur = data
    found = True
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            found = False
            break
    if not found or not isinstance(cur, str):
        # fallback French
        cur = load_locale_dict("fr")
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return str(key)
        if not isinstance(cur, str):
            return str(key)
    for k, v in params.items():
        cur = cur.replace("{" + str(k) + "}", str(v))
    return cur


XML_PATH = os.path.join(BASE_DIR, "gamelist.xml")

# Max size for media downloaded from a URL (bytes)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

MEDIA_DIRS = {
    "image": "images", "video": "videos", "marquee": "images",
    "manual": "manuals", "boxback": "images", "thumbnail": "images",
    "fanart": "images", "map": "images",
}
META_FIELDS = {
    "rating", "releasedate", "developer", "publisher",
    "family", "players", "lang", "genre",
}

# --- XML cache + process lock ------------------------------------------------
_xml_cache = {"mtime": None, "tree": None}
_xml_io_lock = threading.Lock()  # serialize read-modify-write of the XML file


def load_xml():
    """Parse gamelist.xml; reuse cached tree if file mtime unchanged."""
    try:
        mtime = os.path.getmtime(XML_PATH)
    except OSError:
        mtime = None
    if _xml_cache["tree"] is not None and _xml_cache["mtime"] == mtime:
        return _xml_cache["tree"]
    tree = etree.parse(XML_PATH, etree.XMLParser(remove_blank_text=True))
    _xml_cache["tree"] = tree
    _xml_cache["mtime"] = mtime
    return tree


def save_xml(tree):
    """Write XML to disk and refresh cache (serialized)."""
    with _xml_io_lock:
        tree.write(XML_PATH, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        try:
            _xml_cache["mtime"] = os.path.getmtime(XML_PATH)
            _xml_cache["tree"] = tree
        except OSError:
            _xml_cache["mtime"] = None
            _xml_cache["tree"] = None


def backup_xml():
    """Copy gamelist.xml → gamelist.xml.bak (same folder). Returns backup path."""
    with _xml_io_lock:
        if not os.path.isfile(XML_PATH):
            raise FileNotFoundError(st("server.xml_missing", path=XML_PATH))
        bak_path = XML_PATH + ".bak"
        shutil.copy2(XML_PATH, bak_path)
        return bak_path


def get_game_elem(index):
    """
    Return (tree, game_elem) for the game at XML index.
    Raises IndexError if out of range.
    """
    tree = load_xml()
    games = tree.getroot().findall("game")
    if not (0 <= index < len(games)):
        raise IndexError("invalid_index")
    return tree, games[index]


def resolve_under_base(rel_path):
    """
    Resolve a relative media path under BASE_DIR.
    Returns absolute path, or None if empty / path traversal / outside base.
    """
    if not rel_path:
        return None
    # Normalize separators; strip only leading "./" (not "../")
    clean = str(rel_path).replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    clean = clean.lstrip("/")
    if not clean or ".." in clean.split("/"):
        return None
    full = os.path.normpath(os.path.join(BASE_DIR, clean))
    base = os.path.normpath(BASE_DIR)
    try:
        if os.path.commonpath([base, full]) != base:
            return None
    except ValueError:
        # Different drives on Windows
        return None
    return full


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name or "unknown"


def get_base_name(game_elem):
    path = game_elem.findtext("path", "") or ""
    if path:
        return sanitize_filename(os.path.splitext(os.path.basename(path))[0])
    return sanitize_filename(game_elem.findtext("name", "unknown") or "unknown")


def get_games(tree):
    """Build sorted game list for the UI. Each item keeps original XML index."""
    games = []
    for i, game in enumerate(tree.getroot().findall("game")):
        path = game.findtext("path", "") or ""
        name = game.findtext("name", "") or (os.path.basename(path) if path else f"Jeu {i}")
        games.append({
            "index": i, "path": path, "name": name,
            "desc": game.findtext("desc", "") or "",
            "image": game.findtext("image", "") or "",
            "video": game.findtext("video", "") or "",
            "marquee": game.findtext("marquee", "") or "",
            "manual": game.findtext("manual", "") or "",
            "boxback": game.findtext("boxback", "") or "",
            "rating": game.findtext("rating", "") or "",
            "releasedate": game.findtext("releasedate", "") or "",
            "developer": game.findtext("developer", "") or "",
            "publisher": game.findtext("publisher", "") or "",
            "family": game.findtext("family", "") or "",
            "players": game.findtext("players", "") or "",
            "lang": game.findtext("lang", "") or "",
            "genre": game.findtext("genre", "") or "",
        })
    games.sort(key=lambda g: g["name"].lower())
    return games


def safe_delete_file(rel_path):
    """Delete a media file under BASE_DIR. Returns True if deleted."""
    full = resolve_under_base(rel_path)
    if not full or not os.path.isfile(full):
        return False
    try:
        os.remove(full)
        return True
    except OSError:
        return False


def default_ext_for_field(field):
    if field == "video":
        return ".mp4"
    if field == "manual":
        return ".pdf"
    return ".png"


def ext_from_content_type(ct, field):
    ct = (ct or "").lower()
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    if "mp4" in ct:
        return ".mp4"
    if "webm" in ct:
        return ".webm"
    if "pdf" in ct:
        return ".pdf"
    return default_ext_for_field(field)



# --- ScreenScraper -----------------------------------------------------------
SS_API = "https://api.screenscraper.fr/api2"
SS_SOFTNAME = "GamelistMediaEditor"
APP_VERSION = "1.1.1"
APP_UA = f"{SS_SOFTNAME}/{APP_VERSION}"
SS_CONFIG_NAME = "screenscraper_config.json"


def _ss_unmask(blob: str) -> str:
    """De-obfuscate built-in developer credentials (XOR + base64).
    This is NOT real encryption — the key ships with the app. It only avoids
    leaving plaintext in the source for casual reading.
    """
    import base64
    key = b"GamelistMediaEditor/SS/v1"
    raw = base64.b64decode(blob.encode("ascii"))
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode("utf-8")


# Developer credentials identify *this software* (not end users).
_SS_DEV_ID = _ss_unmask("DBMMFw0H")
_SS_DEV_PASS = _ss_unmask("MhQnVQNdKjx7DFY=")

# RetroBat / ES folder name → ScreenScraper systemeid (subset; unknown → None)
SS_SYSTEM_MAP = {
    # Nintendo
    "nes": 3, "famicom": 3, "snes": 4, "sfc": 4, "n64": 14, "gba": 12, "gb": 9, "gbc": 10,
    "nds": 15, "3ds": 17, "n3ds": 17, "gamecube": 13, "gc": 13, "wii": 16, "wiiu": 18,
    "switch": 225, "virtualboy": 11, "pokemini": 211, "fds": 106, "satellaview": 107,
    "sufami": 108, "gameandwatch": 52, "gw": 52,
    # Sega
    "megadrive": 1, "genesis": 1, "mastersystem": 2, "sms": 2, "gamegear": 21, "gg": 21,
    "saturn": 22, "dreamcast": 23, "sega32x": 19, "32x": 19, "segacd": 20, "megacd": 20,
    "sg1000": 109, "naomi": 142, "naomi2": 142, "atomiswave": 148, "model2": 149, "model3": 150,
    # Sony
    "psx": 57, "ps1": 57, "ps2": 58, "ps3": 59, "ps4": 60, "psp": 61, "psvita": 62, "vita": 62,
    # Microsoft
    "xbox": 32, "xbox360": 33, "xboxone": 34,
    # NEC
    "pcengine": 31, "tg16": 31, "pcenginecd": 114, "tg16cd": 114, "supergrafx": 105, "pcfx": 72,
    # SNK
    "neogeo": 142, "neogeocd": 70, "ngp": 25, "ngpc": 82,
    # Atari
    "atari2600": 26, "atari5200": 40, "atari7800": 41, "atarilynx": 28, "lynx": 28,
    "atarijaguar": 27, "jaguar": 27, "atarist": 42, "atari800": 43, "atarixe": 43,
    # Commodore / Amiga (RetroBat folders)
    "c64": 66, "commodore64": 66, "amiga": 64, "amiga500": 64, "amiga600": 64,
    "amiga1200": 64, "amiga4000": 64, "amiga1000": 64, "amiga3000": 64,
    "amigacd32": 130, "amigacdtv": 129, "cd32": 130,
    "vic20": 118, "c128": 67, "plus4": 119, "pet": 120,
    # Other computers
    "amstradcpc": 65, "cpc": 65, "zxspectrum": 76, "spectrum": 76, "zx81": 77,
    "msx": 113, "msx1": 113, "msx2": 116, "msxturbor": 118,
    "pc": 135, "dos": 135, "pc98": 122, "pc88": 121, "x68000": 79, "x68000": 79,
    "apple2": 86, "apple2gs": 217, "macintosh": 146, "mac": 146,
    "thomson": 141, "mo5": 141, "to7": 141, "oric": 131, "dragon32": 91,
    "trsdos": 100, "coco": 144,
    # Arcade / multi
    "arcade": 75, "mame": 75, "mame2003": 75, "mame2010": 75, "fbneo": 75, "fba": 75,
    "neogeo": 142, "daphne": 49, "singe": 49, "atomiswave": 148,
    # Other consoles
    "3do": 29, "colecovision": 48, "intellivision": 115, "odyssey2": 104, "channelf": 80,
    "vectrex": 102, "wonderswan": 45, "wonderswancolor": 46, "wswan": 45, "wswanc": 46,
    "supervision": 207, "wasm4": 0, "scummvm": 123, "easyrpg": 231, "pico8": 211,
    "gx4000": 87, "supernes": 4,
}


# ES field → preferred ScreenScraper media type(s), first match wins
SS_MEDIA_PREF = {
    "image": ["ss", "sstitle", "mixrbv1", "mixrbv2", "box-2D", "screenshot"],
    "video": ["video-normalized", "video"],
    "marquee": ["wheel-hd", "wheel", "screenmarquee", "marquee"],
    "manual": ["manuel", "manual"],
    "boxback": ["box-2D-back", "box-texture-back", "box-2D"],
}


def ss_config_path():
    """Config lives next to app.py (not next to the XML)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), SS_CONFIG_NAME)


def load_ss_config():
    """User boost credentials + region (local file). Dev credentials are built-in."""
    path = ss_config_path()
    defaults = {
        "ssid": "",
        "sspassword": "",
        "prefer_region": "fr",
    }
    if not os.path.isfile(path):
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return defaults
        for k in defaults:
            if k in data and data[k] is not None:
                defaults[k] = str(data[k]).strip()
        return defaults
    except Exception:
        return defaults


def save_ss_config(data):
    """Persist user boost + region only (never write built-in dev password to disk)."""
    cfg = load_ss_config()
    for k in ("ssid", "prefer_region"):
        if k in data and data[k] is not None:
            cfg[k] = str(data[k]).strip()
    if data.get("sspassword"):
        cfg["sspassword"] = str(data["sspassword"])
    if data.get("clear_sspassword"):
        cfg["sspassword"] = ""
    # Drop legacy keys if present
    cfg.pop("devid", None)
    cfg.pop("devpassword", None)
    path = ss_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


def ss_public_config(cfg=None):
    """Config for the UI — no developer secrets."""
    cfg = cfg or load_ss_config()
    return {
        "ssid": cfg.get("ssid") or "",
        "sspassword_set": bool(cfg.get("sspassword")),
        "prefer_region": cfg.get("prefer_region") or "fr",
        "softname": SS_SOFTNAME,
        "configured": True,
        "user_boost": bool(cfg.get("ssid") and cfg.get("sspassword")),
    }


def detect_system_id():
    """Guess ScreenScraper systemeid from parent folder of gamelist.xml."""
    folder = os.path.basename(os.path.normpath(BASE_DIR)).lower().strip()
    if folder in SS_SYSTEM_MAP:
        sid = SS_SYSTEM_MAP[folder]
        return (sid if sid else None), folder
    # strip common prefixes
    for prefix in ("roms-", "rom-", "sys-"):
        if folder.startswith(prefix):
            key = folder[len(prefix):]
            if key in SS_SYSTEM_MAP:
                sid = SS_SYSTEM_MAP[key]
                return (sid if sid else None), key
    # Heuristics: amiga500 → amiga, megadrive_* etc.
    prefixes = (
        ("amiga", 64), ("c64", 66), ("nes", 3), ("snes", 4), ("mame", 75),
        ("fbneo", 75), ("psx", 57), ("ps1", 57), ("ps2", 58), ("psp", 61),
        ("megadrive", 1), ("genesis", 1), ("n64", 14), ("gba", 12),
        ("dos", 135), ("pc", 135), ("zx", 76), ("msx", 113),
    )
    for pref, sid in prefixes:
        if folder.startswith(pref):
            return sid, folder
    return None, folder



def get_system_info():
    """Human-readable system label from the gamelist parent folder."""
    sid, folder = detect_system_id()
    # Prefer original folder casing from BASE_DIR
    display = os.path.basename(os.path.normpath(BASE_DIR)) or folder or "—"
    return {
        "folder": folder or display.lower(),
        "label": display,
        "id": sid,
    }


def file_hashes(path, max_bytes=None):
    """Return crc32 (hex upper), md5, sha1, size for a ROM file."""
    size = os.path.getsize(path)
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    crc = 0
    read = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            if max_bytes is not None and read + len(chunk) > max_bytes:
                chunk = chunk[: max_bytes - read]
            md5.update(chunk)
            sha1.update(chunk)
            crc = zlib.crc32(chunk, crc) & 0xFFFFFFFF
            read += len(chunk)
            if max_bytes is not None and read >= max_bytes:
                break
    return {
        "crc": f"{crc:08X}",
        "md5": md5.hexdigest(),
        "sha1": sha1.hexdigest(),
        "size": size,
        "source": "file",
    }


def rom_identification(path):
    """
    Build the best ScreenScraper identification for a ROM path.
    For .zip: hash the *inner* ROM (No-Intro style) — SS matches that CRC, not the zip's.
    """
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    info = {"outer_name": os.path.basename(path), "outer_size": os.path.getsize(path)}

    if ext == ".zip":
        try:
            import zipfile
            with zipfile.ZipFile(path, "r") as zf:
                # Prefer real ROM members (skip .txt, .nfo, directories)
                skip_ext = {".txt", ".nfo", ".diz", ".url", ".xml", ".htm", ".html"}
                members = [
                    m for m in zf.infolist()
                    if not m.is_dir() and os.path.splitext(m.filename)[1].lower() not in skip_ext
                ]
                if not members:
                    members = [m for m in zf.infolist() if not m.is_dir()]
                if members:
                    # Largest member is usually the ROM
                    members.sort(key=lambda m: m.file_size, reverse=True)
                    member = members[0]
                    md5 = hashlib.md5()
                    sha1 = hashlib.sha1()
                    crc = 0
                    with zf.open(member, "r") as f:
                        while True:
                            chunk = f.read(1024 * 1024)
                            if not chunk:
                                break
                            md5.update(chunk)
                            sha1.update(chunk)
                            crc = zlib.crc32(chunk, crc) & 0xFFFFFFFF
                    info.update({
                        "crc": f"{crc:08X}",
                        "md5": md5.hexdigest(),
                        "sha1": sha1.hexdigest(),
                        "size": member.file_size,
                        "source": "zip-inner",
                        "inner_name": os.path.basename(member.filename),
                    })
                    return info
        except Exception as e:
            info["zip_error"] = str(e)

    # Plain file (or zip fallback)
    try:
        h = file_hashes(path)
        info.update(h)
        return info
    except OSError as e:
        info["error"] = str(e)
        return info


_SS_NAME_STRIP = re.compile(
    r"\s*[\(\[].*?[\)\]]\s*|\s*[Tt]he\s+",
    re.UNICODE,
)


def clean_game_name(name):
    """Strip region/dump tags for softer name matching."""
    if not name:
        return ""
    base = os.path.splitext(os.path.basename(name))[0]
    # remove (...) and [...] groups repeatedly
    prev = None
    while prev != base:
        prev = base
        base = re.sub(r"\s*[\(\[].*?[\)\]]", "", base)
    base = re.sub(r"[._]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip().lower()
    if base.startswith("the "):
        base = base[4:]
    return base


def name_similarity(a, b):
    """Rough 0..1 similarity for ranking search candidates."""
    ca, cb = clean_game_name(a), clean_game_name(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    if ca in cb or cb in ca:
        return 0.85
    # token overlap
    ta, tb = set(ca.split()), set(cb.split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(len(ta), len(tb))


def extract_ss_names(jeu):
    """All display names from a SS jeu object."""
    names = []
    noms = jeu.get("noms") or jeu.get("nom")
    if isinstance(noms, list):
        for n in noms:
            if isinstance(n, dict):
                t = (n.get("text") or n.get("nom") or "").strip()
                if t:
                    names.append(t)
            elif isinstance(n, str) and n.strip():
                names.append(n.strip())
    elif isinstance(noms, dict):
        t = (noms.get("text") or noms.get("nom") or "").strip()
        if t:
            names.append(t)
    elif isinstance(noms, str) and noms.strip():
        names.append(noms.strip())
    return names


def ss_candidate_summary(jeu, query_name=""):
    """Compact candidate for the UI picker."""
    names = extract_ss_names(jeu)
    best = names[0] if names else f"#{jeu.get('id')}"
    score = max((name_similarity(query_name, n) for n in names), default=0.0)
    systeme = jeu.get("systeme") or {}
    sys_name = ""
    if isinstance(systeme, dict):
        sys_name = (systeme.get("text") or systeme.get("nom") or "").strip()
    return {
        "ss_id": str(jeu.get("id") or ""),
        "name": best,
        "names": names[:6],
        "system": sys_name,
        "score": round(score, 3),
    }


# Minimum interval between outbound API calls (politeness + avoid bursts)
_SS_MIN_INTERVAL = 1.1
_ADB_MIN_INTERVAL = 0.45
_ss_last_call = 0.0
_adb_last_call = 0.0
_api_throttle_lock = threading.Lock()


def _throttle_api(service):
    """Serialize and space calls per service (one logical client)."""
    global _ss_last_call, _adb_last_call
    with _api_throttle_lock:
        now = time.time()
        if service == "ss":
            wait = _SS_MIN_INTERVAL - (now - _ss_last_call)
            if wait > 0:
                time.sleep(wait)
            _ss_last_call = time.time()
        else:
            wait = _ADB_MIN_INTERVAL - (now - _adb_last_call)
            if wait > 0:
                time.sleep(wait)
            _adb_last_call = time.time()


def format_ss_error(raw, status=200):
    """Map ScreenScraper error text → localized message."""
    t = (raw or "").strip()
    low = t.lower()
    if not t and status == 429:
        return st("server.ss_429")
    if status == 503:
        return st("server.ss_503")
    if any(k in low for k in ("login", "identifiant", "password", "mot de passe", "bad ident")):
        return st("server.ss_login")
    if "api closed" in low or "api ferm" in low or "fermee" in low or "fermée" in low:
        return st("server.ss_api_closed")
    if any(
        k in low
        for k in (
            "quota", "overquota", "over quota", "trop de requ", "demande",
            "threads", "thread", "maxthreads", "limit", "limite",
            "exceed", "depass", "dépass",
        )
    ):
        return st("server.ss_quota")
    if status == 429 or "429" in low:
        return st("server.ss_too_many")
    if t.startswith("Erreur") or t.startswith("API"):
        return t[:400]
    if status != 200:
        return st("server.ss_http", status=status, detail=t[:250])
    return t[:400] if t else st("server.ss_error", status=status)


def format_adb_error(raw, status=200):
    """Map Arcade Database error → localized message."""
    t = (raw or "").strip()
    low = t.lower()
    if status == 503 or "503" in low or "maintenance" in low:
        return st("server.adb_503")
    if status == 429 or any(k in low for k in ("rate", "limit", "quota", "too many", "trop")):
        return st("server.adb_rate")
    if status == 403:
        return st("server.adb_403")
    if t:
        return t[:400]
    return st("server.adb_error", status=status)


def ss_request(endpoint, extra_params=None, timeout=25):
    """
    Call ScreenScraper API2. Returns (ok, data_or_error_str, http_status).
    Built-in developer credentials + optional user ssid/sspassword for quota boost.
    Throttled to avoid burst / quota spikes.
    """
    cfg = load_ss_config()
    params = {
        "devid": _SS_DEV_ID,
        "devpassword": _SS_DEV_PASS,
        "softname": SS_SOFTNAME,
        "output": "json",
    }
    if cfg.get("ssid") and cfg.get("sspassword"):
        params["ssid"] = cfg["ssid"]
        params["sspassword"] = cfg["sspassword"]
    if extra_params:
        params.update({k: v for k, v in extra_params.items() if v is not None and v != ""})
    url = f"{SS_API}/{endpoint}"
    _throttle_api("ss")
    try:
        r = requests.get(
            url,
            params=params,
            headers={"User-Agent": APP_UA},
            timeout=timeout,
        )
        body = r.text or ""
        if r.status_code == 429:
            return False, format_ss_error(body, 429), 429
        if r.status_code == 503:
            return False, format_ss_error(body, 503), 503
        if r.status_code != 200:
            return False, format_ss_error(body, r.status_code), r.status_code
        stripped = body.strip()
        if stripped.startswith("Erreur") or stripped.lower().startswith("api closed"):
            return False, format_ss_error(stripped, r.status_code), r.status_code
        try:
            data = r.json()
        except Exception:
            # Plain-text quota messages sometimes without "Erreur" prefix
            if any(k in stripped.lower() for k in ("quota", "thread", "limit")):
                return False, format_ss_error(stripped, r.status_code), r.status_code
            return False, f"Réponse non JSON: {stripped[:300]}", r.status_code
        header = data.get("header") or {}
        err = (header.get("error") or "").strip()
        if err and err not in ("OK", "0", "none", "null"):
            if header.get("success") not in ("true", True, "1", 1):
                return False, format_ss_error(err, r.status_code), r.status_code
        return True, data, r.status_code
    except requests.Timeout:
        return False, "Délai d'attente ScreenScraper dépassé — le serveur est peut-être surchargé.", 504
    except requests.RequestException as e:
        return False, f"Réseau ScreenScraper: {e}", 502


def _ss_pick_text(entries, prefer_region="fr", key_region="region", key_text="text"):
    """Pick best localized text from list of {region, text} or similar."""
    if not entries:
        return ""
    if isinstance(entries, str):
        return entries.strip()
    if isinstance(entries, dict):
        # single object
        return (entries.get(key_text) or entries.get("nom") or entries.get("synopsis") or "").strip()
    if not isinstance(entries, list):
        return str(entries).strip()
    prefer = [prefer_region, "fr", "eu", "wor", "us", "jp", "ss"]
    # dedupe prefer order
    seen = set()
    order = []
    for r in prefer:
        if r not in seen:
            order.append(r)
            seen.add(r)
    by_region = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        reg = (e.get(key_region) or e.get("langue") or "").lower()
        txt = (e.get(key_text) or e.get("nom") or e.get("synopsis") or "").strip()
        if txt:
            by_region[reg] = txt
    for r in order:
        if r in by_region:
            return by_region[r]
    # any
    for v in by_region.values():
        return v
    return ""


def _ss_pick_media(medias, preferred_types, prefer_region="fr"):
    """Return best media URL for preferred types."""
    if not medias:
        return None, None
    if not isinstance(medias, list):
        medias = [medias]
    prefer = [prefer_region, "wor", "eu", "us", "jp", "ss", ""]
    candidates = []
    for m in medias:
        if not isinstance(m, dict):
            continue
        mtype = (m.get("type") or "").lower()
        url = m.get("url") or ""
        if not url:
            continue
        region = (m.get("region") or "").lower()
        try:
            type_rank = preferred_types.index(mtype)
        except ValueError:
            continue
        try:
            region_rank = prefer.index(region) if region in prefer else len(prefer)
        except ValueError:
            region_rank = len(prefer)
        candidates.append((type_rank, region_rank, url, mtype, region))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (x[0], x[1]))
    best = candidates[0]
    return best[2], best[3]


def parse_ss_game(jeu, prefer_region="fr"):
    """Map ScreenScraper jeu object → ES-oriented dict."""
    if not jeu or not isinstance(jeu, dict):
        return None
    noms = jeu.get("noms") or jeu.get("nom")
    name = _ss_pick_text(noms, prefer_region)
    if not name and isinstance(noms, list) and noms:
        name = _ss_pick_text(noms, prefer_region, key_text="text")
    synopsis = jeu.get("synopsis") or []
    desc = _ss_pick_text(synopsis, prefer_region, key_text="text")
    # rating: note is often /20
    note = jeu.get("note") or {}
    rating = ""
    try:
        raw = note.get("text") if isinstance(note, dict) else note
        if raw not in (None, ""):
            val = float(str(raw).replace(",", "."))
            # SS notes are typically 0–20
            if val > 1.0:
                val = val / 20.0
            rating = f"{max(0.0, min(1.0, val)):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        pass
    # dates
    dates = jeu.get("dates") or []
    releasedate = ""
    date_txt = _ss_pick_text(dates, prefer_region, key_text="text")
    if date_txt:
        digits = "".join(c for c in date_txt if c.isdigit())
        if len(digits) >= 8:
            releasedate = digits[:8] + "T000000"
        elif len(digits) == 4:
            releasedate = digits + "0101T000000"
    developer = ""
    dev = jeu.get("developpeur") or jeu.get("developer")
    if isinstance(dev, dict):
        developer = (dev.get("text") or dev.get("nom") or "").strip()
    elif isinstance(dev, str):
        developer = dev.strip()
    publisher = ""
    ed = jeu.get("editeur") or jeu.get("publisher")
    if isinstance(ed, dict):
        publisher = (ed.get("text") or ed.get("nom") or "").strip()
    elif isinstance(ed, str):
        publisher = ed.strip()
    # genre: first genre name
    genre = ""
    genres = jeu.get("genres") or []
    if isinstance(genres, list) and genres:
        g0 = genres[0]
        if isinstance(g0, dict):
            gn = g0.get("noms") or g0.get("nom")
            genre = _ss_pick_text(gn, prefer_region).upper()
    players = ""
    joueurs = jeu.get("joueurs") or {}
    if isinstance(joueurs, dict):
        players = (joueurs.get("text") or "").strip()
    elif isinstance(joueurs, str):
        players = joueurs.strip()
    lang = ""
    langues = jeu.get("langues") or {}
    if isinstance(langues, dict):
        lang = (langues.get("text") or "").strip().split(",")[0].strip().lower()
    elif isinstance(langues, str):
        lang = langues.split(",")[0].strip().lower()
    medias = jeu.get("medias") or []
    media_out = {}
    for field, prefs in SS_MEDIA_PREF.items():
        url, mtype = _ss_pick_media(medias, prefs, prefer_region)
        if url:
            media_out[field] = {"url": url, "type": mtype}
    return {
        "ss_id": str(jeu.get("id") or ""),
        "name": name,
        "desc": desc,
        "rating": rating,
        "releasedate": releasedate,
        "developer": developer,
        "publisher": publisher,
        "genre": genre,
        "players": players,
        "lang": lang,
        "medias": media_out,
    }



# --- Routes ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    """Browsers often request /favicon.ico at the site root."""
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    return send_from_directory(static_dir, "favicon.ico", mimetype="image/x-icon")


@app.route("/api/games")
def api_games():
    try:
        return jsonify({
            "games": get_games(load_xml()),
            "system": get_system_info(),
        })
    except Exception as e:
        log.exception("api_games failed")
        return api_err(st("server.xml_read", detail=e), 500, code="xml_read")


@app.route("/api/upload/<int:index>/<field>", methods=["POST"])
def upload(index, field):
    if field not in MEDIA_DIRS:
        return api_err(st("server.invalid_field"), 400, code="invalid_field")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    try:
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        base_name = get_base_name(game)
        file = request.files.get("file")
        url = (request.form.get("url") or "").strip()
        rel_path = new_filename = None

        if file and file.filename:
            # Size limit (same as URL downloads)
            try:
                file.stream.seek(0, os.SEEK_END)
                size = file.stream.tell()
                file.stream.seek(0)
            except Exception:
                size = None
            if size is not None and size > MAX_DOWNLOAD_BYTES:
                return api_err(st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024)), 400, code="file_too_large")
            ext = os.path.splitext(file.filename)[1].lower() or default_ext_for_field(field)
            new_filename = f"{base_name}-{field}{ext}"
            file.save(os.path.join(media_dir, new_filename))
            rel_path = f"./{media_dir_name}/{new_filename}"
        elif url:
            try:
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https"):
                    return api_err(st("server.url_not_allowed"), 400, code="url_not_allowed")
                ext = os.path.splitext(unquote(parsed.path))[1].lower()
                if not ext or len(ext) > 6:
                    ext = ""
                r = requests.get(
                    url,
                    headers={"User-Agent": APP_UA},
                    timeout=20,
                    stream=True,
                )
                r.raise_for_status()
                if not ext:
                    ext = ext_from_content_type(r.headers.get("content-type"), field)
                cl = r.headers.get("content-length")
                if cl is not None:
                    try:
                        if int(cl) > MAX_DOWNLOAD_BYTES:
                            r.close()
                            return api_err(st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024)), 400, code="file_too_large")
                    except ValueError:
                        pass
                new_filename = f"{base_name}-{field}{ext}"
                dest = os.path.join(media_dir, new_filename)
                written = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_DOWNLOAD_BYTES:
                            f.close()
                            try:
                                os.remove(dest)
                            except OSError:
                                pass
                            return api_err(st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024)), 400, code="file_too_large")
                        f.write(chunk)
                rel_path = f"./{media_dir_name}/{new_filename}"
            except requests.RequestException as e:
                return api_err(st("server.download_failed", detail=e), 400, code="download_failed")
            except Exception as e:
                return api_err(st("server.download_failed", detail=e), 400, code="download_failed")
        else:
            return api_err(st("server.no_file_url"), 400, code="no_file_url")

        # Remove previous media file if path changes (e.g. .png → .jpg)
        old_rel = game.findtext(field, "") or ""
        if old_rel and resolve_under_base(old_rel) != resolve_under_base(rel_path):
            safe_delete_file(old_rel)

        elem = game.find(field)
        if elem is None:
            elem = etree.SubElement(game, field)
        elem.text = rel_path
        save_xml(tree)
        return jsonify({
            "success": True, "path": rel_path,
            "filename": new_filename, "field": field,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/clear/<int:index>/<field>", methods=["POST"])
def clear_field(index, field):
    """
    Remove the XML media tag only (file on disk is kept).
    Use delete-game to remove files from disk.
    """
    if field not in MEDIA_DIRS:
        return api_err(st("server.invalid_field"), 400, code="invalid_field")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    try:
        elem = game.find(field)
        if elem is not None:
            game.remove(elem)
            save_xml(tree)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/desc/<int:index>", methods=["POST"])
def update_desc(index):
    try:
        data = request.get_json(silent=True) or {}
        new_desc = data.get("desc", "") or ""
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return api_err(st("server.invalid_index"), 404, code="invalid_index")
        elem = game.find("desc")
        if elem is None:
            name_elem = game.find("name")
            if name_elem is not None:
                elem = etree.Element("desc")
                name_elem.addnext(elem)
            else:
                elem = etree.SubElement(game, "desc")
        elem.text = new_desc
        save_xml(tree)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/name/<int:index>", methods=["POST"])
def update_name(index):
    try:
        data = request.get_json(silent=True) or {}
        new_name = (data.get("name") or "").strip()
        if not new_name:
            return api_err(st("server.empty_name"), 400, code="empty_name")
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return api_err(st("server.invalid_index"), 404, code="invalid_index")
        elem = game.find("name")
        if elem is None:
            elem = etree.Element("name")
            game.insert(0, elem)
        elem.text = new_name
        save_xml(tree)
        return jsonify({"success": True, "name": new_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/meta/<int:index>", methods=["POST"])
def update_meta(index):
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            return api_err(st("server.no_data"), 400, code="no_data")
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return api_err(st("server.invalid_index"), 404, code="invalid_index")
        updated = {}
        for field, value in data.items():
            if field not in META_FIELDS:
                continue
            value = (value or "").strip()
            if field == "rating" and value:
                try:
                    fval = float(value)
                    if not (0.0 <= fval <= 1.0):
                        return api_err(st("server.rating_range"), 400, code="rating_range")
                    value = f"{fval:.2f}".rstrip("0").rstrip(".") if fval != 0 else "0"
                except ValueError:
                    return api_err(st("server.rating_invalid"), 400, code="rating_invalid")
            if field == "lang" and value:
                value = value.lower()
            elem = game.find(field)
            if value == "":
                if elem is not None:
                    game.remove(elem)
            else:
                if elem is None:
                    elem = etree.SubElement(game, field)
                elem.text = value
            updated[field] = value
        save_xml(tree)
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/backup", methods=["POST"])
def api_backup():
    """Manual backup of gamelist.xml → gamelist.xml.bak"""
    try:
        backup_path = backup_xml()
        return jsonify({
            "success": True,
            "backup": backup_path,
            "filename": os.path.basename(backup_path),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/purge-regions", methods=["POST"])
def purge_regions():
    try:
        body = request.get_json(silent=True) or {}
        do_backup = bool(body.get("backup", False))
        backup_path = None
        if do_backup:
            backup_path = backup_xml()

        tree = load_xml()
        root = tree.getroot()
        count = 0
        for game in root.findall("game"):
            for region_elem in list(game.findall("region")):
                game.remove(region_elem)
                count += 1
        save_xml(tree)
        return jsonify({
            "success": True,
            "removed": count,
            "backup": backup_path,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/delete-game/<int:index>", methods=["POST"])
def delete_game(index):
    """Delete ROM + media files on disk + XML entry for the game."""
    try:
        body = request.get_json(silent=True) or {}
        do_backup = bool(body.get("backup", False))
        backup_path = None
        if do_backup:
            backup_path = backup_xml()

        tree = load_xml()
        root = tree.getroot()
        games = root.findall("game")
        if not (0 <= index < len(games)):
            return api_err(st("server.invalid_index"), 404, code="invalid_index")
        game = games[index]
        name = game.findtext("name", "") or st("server.game_fallback", index=index)
        media_tags = [
            "path", "image", "video", "marquee", "manual", "boxback",
            "thumbnail", "fanart", "map", "boxfront", "cartridge", "mix",
        ]
        deleted_files, failed_files = [], []
        for tag in media_tags:
            rel = game.findtext(tag, "") or ""
            if not rel:
                continue
            if safe_delete_file(rel):
                deleted_files.append(rel)
            else:
                full = resolve_under_base(rel)
                if full and os.path.exists(full):
                    failed_files.append(rel)
        root.remove(game)
        save_xml(tree)
        return jsonify({
            "success": True, "name": name,
            "deleted_files": deleted_files, "failed_files": failed_files,
            "backup": backup_path,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/ss/config", methods=["GET", "POST"])
def api_ss_config():
    """Load or save user boost credentials (local file only, gitignored)."""
    if request.method == "GET":
        return jsonify(ss_public_config())
    try:
        body = request.get_json(silent=True) or {}
        current = load_ss_config()
        payload = {}
        if "ssid" in body:
            payload["ssid"] = (body.get("ssid") or "").strip()
        if "prefer_region" in body:
            payload["prefer_region"] = (body.get("prefer_region") or "fr").strip()
        if body.get("sspassword"):
            payload["sspassword"] = body["sspassword"]
        if body.get("clear_sspassword"):
            payload["clear_sspassword"] = True
        merged = dict(current)
        merged.update(payload)
        cfg = save_ss_config(merged)
        return jsonify({"success": True, "config": ss_public_config(cfg)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ss/test", methods=["POST"])
def api_ss_test():
    """Test API (built-in dev credentials + optional user boost)."""
    cfg = load_ss_config()
    # Prefer user info if user creds present
    if cfg.get("ssid") and cfg.get("sspassword"):
        ok, data, status = ss_request("ssuserInfos.php")
        if ok:
            user = (data.get("response") or {}).get("ssuser") or {}
            return jsonify({
                "success": True,
                "mode": "user",
                "id": user.get("id") or cfg.get("ssid"),
                "level": user.get("niveau") or user.get("level") or "",
                "maxthreads": user.get("maxthreads") or "",
                "requeststoday": user.get("requetesauj") or user.get("requeststoday") or "",
                "raw_keys": list(user.keys())[:20] if isinstance(user, dict) else [],
            })
        # fall through to infra test with error note
        user_err = data
    else:
        user_err = None
    ok, data, status = ss_request("ssinfraInfos.php")
    if ok:
        return jsonify({
            "success": True,
            "mode": "infra",
            "message": st("server.ss_dev_ok"),
            "user_error": user_err if user_err else None,
        })
    return jsonify({"error": str(data)}), 400


@app.route("/api/ss/scrape/<int:index>", methods=["POST"])
def api_ss_scrape(index):
    """
    Look up a game on ScreenScraper.
    1) Prefer CRC/MD5 of the ROM (inner file if .zip)
    2) If ambiguous / not found → return ranked candidates for the user to pick
    Optional body: { "gameid": "12345" } to force a specific SS game.
    """
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    cfg = load_ss_config()
    body = request.get_json(silent=True) or {}
    force_id = str(body.get("gameid") or "").strip()

    path_rel = game.findtext("path", "") or ""
    rom_name = os.path.basename(path_rel) if path_rel else ""
    local_name = game.findtext("name", "") or os.path.splitext(rom_name)[0]
    system_id, system_folder = detect_system_id()
    prefer = cfg.get("prefer_region") or "fr"

    rom_full = resolve_under_base(path_rel) if path_rel else None
    hash_info = rom_identification(rom_full) if rom_full else None
    api_errors = []  # collect real SS messages (auth, not found, …)

    def full_from_jeu(jeu, match_method):
        parsed = parse_ss_game(jeu, prefer)
        if not parsed:
            return None
        current = {
            "name": game.findtext("name", "") or "",
            "desc": game.findtext("desc", "") or "",
            "rating": game.findtext("rating", "") or "",
            "releasedate": game.findtext("releasedate", "") or "",
            "developer": game.findtext("developer", "") or "",
            "publisher": game.findtext("publisher", "") or "",
            "genre": game.findtext("genre", "") or "",
            "players": game.findtext("players", "") or "",
            "lang": game.findtext("lang", "") or "",
        }
        for f in MEDIA_DIRS:
            current[f] = game.findtext(f, "") or ""
        return {
            "success": True,
            "match_method": match_method,
            "system_id": system_id,
            "system_folder": system_folder,
            "rom_name": rom_name,
            "hash": hash_info,
            "proposed": parsed,
            "current": current,
        }

    # --- Forced game id (user picked a candidate) ---
    if force_id:
        extra = {"gameid": force_id}
        if system_id:
            extra["systemeid"] = str(system_id)
        ok, data, _ = ss_request("jeuInfos.php", extra)
        if not ok:
            return api_err(st("server.ss_gameid_error", id=force_id, detail=data), 404, code="ss_gameid")
        jeu = (data.get("response") or {}).get("jeu")
        if isinstance(jeu, list):
            jeu = jeu[0] if jeu else None
        result = full_from_jeu(jeu, "gameid")
        if not result:
            return api_err(st("server.ss_empty_gameid"), 404, code="ss_empty")
        return jsonify(result)

    # --- 1) Hash / exact ROM identification (several variants) ---
    def try_jeu_infos(extra, method):
        ok, data, _ = ss_request("jeuInfos.php", extra)
        if not ok:
            api_errors.append(f"{method}: {data}")
            return None
        jeu = (data.get("response") or {}).get("jeu")
        if isinstance(jeu, list):
            jeu = jeu[0] if jeu else None
        return full_from_jeu(jeu, method)

    if hash_info and hash_info.get("crc"):
        id_romnom = hash_info.get("inner_name") or rom_name
        base_hash = {
            "romtype": "rom",
            "crc": hash_info["crc"],
            "md5": hash_info.get("md5") or "",
            "sha1": hash_info.get("sha1") or "",
            "romtaille": str(hash_info.get("size") or ""),
        }
        attempts = []
        # A) inner name + system
        if id_romnom and system_id:
            attempts.append(({**base_hash, "romnom": id_romnom, "systemeid": str(system_id)}, "hash"))
        # B) outer name + system
        if rom_name and system_id and rom_name != id_romnom:
            attempts.append(({**base_hash, "romnom": rom_name, "systemeid": str(system_id)}, "hash-zipname"))
        # C) CRC only + system (no romnom — SS can match on hash alone)
        if system_id:
            attempts.append(({**base_hash, "systemeid": str(system_id)}, "hash-nosystemname"))
        # D) inner name, no system (system map wrong?)
        if id_romnom:
            attempts.append(({**base_hash, "romnom": id_romnom}, "hash-nosystem"))
        # E) CRC only, no system
        attempts.append((dict(base_hash), "hash-crc-only"))

        seen = set()
        for extra, method in attempts:
            key = tuple(sorted((k, str(v)) for k, v in extra.items()))
            if key in seen:
                continue
            seen.add(key)
            result = try_jeu_infos(extra, method)
            if result:
                return jsonify(result)

    # --- 2) Search by cleaned name → candidates (never auto-pick a weak match) ---
    search_name = clean_game_name(local_name) or clean_game_name(rom_name) or local_name
    # Use a slightly cleaned display name for recherche (keep some structure)
    recherche = re.sub(r"[\\(\\[].*?[\\)\\]]", "", local_name or rom_name)
    recherche = re.sub(r"\\s+", " ", recherche).strip()
    if not recherche:
        recherche = local_name or rom_name

    def run_search(params):
        ok, data, _ = ss_request("jeuRecherche.php", params)
        found = []
        if not ok:
            api_errors.append(f"search: {data}")
            return found
        response = data.get("response") or {}
        jeux = response.get("jeux") or response.get("jeu") or []
        if isinstance(jeux, dict):
            jeux = [jeux]
        if not isinstance(jeux, list):
            return found
        for jeu in jeux:
            if not isinstance(jeu, dict) or not jeu.get("id"):
                continue
            found.append(ss_candidate_summary(jeu, local_name or rom_name))
        return found

    candidates = []
    if system_id:
        candidates = run_search({"recherche": recherche, "systemeid": str(system_id)})
    if not candidates:
        candidates = run_search({"recherche": recherche})
    # Also try cleaned name if different
    if not candidates and search_name and search_name != recherche.lower():
        if system_id:
            candidates = run_search({"recherche": search_name, "systemeid": str(system_id)})
        if not candidates:
            candidates = run_search({"recherche": search_name})
    # Deduplicate by ss_id, keep best score
    by_id = {}
    for c in candidates:
        sid = c.get("ss_id")
        if not sid:
            continue
        if sid not in by_id or c.get("score", 0) > by_id[sid].get("score", 0):
            by_id[sid] = c
    candidates = sorted(by_id.values(), key=lambda c: c.get("score", 0), reverse=True)

    # Strong unique match by name → auto-select only if score is very high and unique
    if len(candidates) == 1 and candidates[0].get("score", 0) >= 0.85:
        ok3, data3, _ = ss_request("jeuInfos.php", {
            "gameid": candidates[0]["ss_id"],
            "systemeid": str(system_id) if system_id else None,
        })
        if ok3:
            jeu = (data3.get("response") or {}).get("jeu")
            if isinstance(jeu, list):
                jeu = jeu[0] if jeu else None
            result = full_from_jeu(jeu, "name-unique")
            if result:
                return jsonify(result)

    if candidates:
        return jsonify({
            "success": True,
            "need_choice": True,
            "match_method": "search",
            "system_id": system_id,
            "system_folder": system_folder,
            "rom_name": rom_name,
            "local_name": local_name,
            "search": recherche,
            "hash": hash_info,
            "candidates": candidates[:15],
            "message": st("server.ss_candidates"),
        })

    # Prefer showing login/config errors over a generic "not found"
    login_err = next(
        (
            e for e in api_errors
            if any(
                k in e.lower()
                for k in (
                    "login", "identifiant", "manquants",
                    "quota", "thread", "limite", "limit", "429", "503",
                    "fermée", "fermee", "closed", "trop de requ",
                )
            )
        ),
        None,
    )
    if login_err:
        msg = login_err
    elif api_errors:
        msg = st("server.ss_not_found") + " — " + str(api_errors[-1])
    else:
        msg = st("server.ss_not_found")
    if system_id:
        msg += f" (SS id={system_id}, {system_folder})"
    else:
        msg += f" ({system_folder})"
    return jsonify({
        "error": msg,
        "api_errors": api_errors[-6:],
        "system_id": system_id,
        "system_folder": system_folder,
        "rom_name": rom_name,
        "local_name": local_name,
        "search": recherche,
        "hash": hash_info,
    }), 404


@app.route("/api/ss/apply/<int:index>", methods=["POST"])
def api_ss_apply(index):
    """
    Apply selected ScreenScraper fields to the game.
    Body: { "fields": ["desc","image",...], "proposed": { ... from scrape ... } }
    Media fields: download from proposed.medias[field].url via existing upload logic.
    """
    body = request.get_json(silent=True) or {}
    fields = body.get("fields") or []
    proposed = body.get("proposed") or {}
    if not fields:
        return api_err(st("server.no_fields"), 400, code="no_fields")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")

    applied = []
    errors = []

    meta_map = {
        "name": "name", "desc": "desc", "rating": "rating",
        "releasedate": "releasedate", "developer": "developer",
        "publisher": "publisher", "genre": "genre",
        "players": "players", "lang": "lang",
    }

    # Text / meta fields
    for field in fields:
        if field in meta_map:
            value = (proposed.get(field) or "").strip()
            if field == "name" and not value:
                errors.append(st("server.name_empty_ignored"))
                continue
            if field == "rating" and value:
                try:
                    fval = float(value)
                    if not (0.0 <= fval <= 1.0):
                        errors.append(f"rating hors plage: {value}")
                        continue
                except ValueError:
                    errors.append(f"rating invalide: {value}")
                    continue
            if field == "lang" and value:
                value = value.lower()
            tag = meta_map[field]
            elem = game.find(tag)
            if value == "":
                if elem is not None:
                    game.remove(elem)
            else:
                if elem is None:
                    if tag == "name":
                        elem = etree.Element("name")
                        game.insert(0, elem)
                    elif tag == "desc":
                        name_elem = game.find("name")
                        elem = etree.Element("desc")
                        if name_elem is not None:
                            name_elem.addnext(elem)
                        else:
                            game.append(elem)
                    else:
                        elem = etree.SubElement(game, tag)
                elem.text = value
            applied.append(field)

    # Media fields — download
    medias = proposed.get("medias") or {}
    base_name = get_base_name(game)
    for field in fields:
        if field not in MEDIA_DIRS:
            continue
        info = medias.get(field) or {}
        url = (info.get("url") or "").strip()
        if not url:
            errors.append(f"{field}: pas d'URL ScreenScraper")
            continue
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                errors.append(f"{field}: URL non http(s)")
                continue
            r = requests.get(
                url,
                headers={"User-Agent": APP_UA},
                timeout=40,
                stream=True,
            )
            r.raise_for_status()
            ext = os.path.splitext(unquote(parsed.path))[1].lower()
            if not ext or len(ext) > 6:
                ext = ext_from_content_type(r.headers.get("content-type"), field)
            new_filename = f"{base_name}-{field}{ext}"
            dest = os.path.join(media_dir, new_filename)
            written = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        f.close()
                        try:
                            os.remove(dest)
                        except OSError:
                            pass
                        raise ValueError(st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024)))
                    f.write(chunk)
            rel_path = f"./{media_dir_name}/{new_filename}"
            old_rel = game.findtext(field, "") or ""
            if old_rel and resolve_under_base(old_rel) != resolve_under_base(rel_path):
                safe_delete_file(old_rel)
            elem = game.find(field)
            if elem is None:
                elem = etree.SubElement(game, field)
            elem.text = rel_path
            applied.append(field)
        except Exception as e:
            errors.append(f"{field}: {e}")

    if applied:
        save_xml(tree)

    return jsonify({
        "success": True,
        "applied": applied,
        "errors": errors,
    })




# --- Arcade Database (Arcade Italia) -----------------------------------------
ADB_API = "https://adb.arcadeitalia.net/service_scraper.php"
ADB_UA = f"{APP_UA} (ArcadeDB scraper; +https://github.com/Kraran/gamelist-media-editor)"


def adb_request(ajax, params, timeout=30):
    """Call Arcade Database scraper API. Returns (ok, data_or_error, status).
    Throttled (ADB recommends a single polite client per IP).
    """
    q = {"ajax": ajax}
    q.update({k: v for k, v in (params or {}).items() if v is not None and v != ""})
    _throttle_api("adb")
    try:
        r = requests.get(
            ADB_API,
            params=q,
            headers={"User-Agent": ADB_UA, "Accept": "application/json"},
            timeout=timeout,
        )
        body = r.text or ""
        if r.status_code in (429, 503, 403):
            return False, format_adb_error(body, r.status_code), r.status_code
        if r.status_code != 200:
            return False, format_adb_error(body, r.status_code), r.status_code
        try:
            data = r.json()
        except Exception:
            low = body.lower()
            if any(k in low for k in ("limit", "quota", "maintenance", "503")):
                return False, format_adb_error(body, r.status_code), r.status_code
            return False, f"Réponse non JSON: {body[:300]}", r.status_code
        # Some error payloads still return 200 with empty/error flag
        if isinstance(data, dict):
            err = data.get("error") or data.get("message") or ""
            if err and not data.get("result"):
                return False, format_adb_error(str(err), r.status_code), r.status_code
        return True, data, r.status_code
    except requests.Timeout:
        return False, "Délai d'attente Arcade Database dépassé — serveur lent ou saturé.", 504
    except requests.RequestException as e:
        return False, f"Réseau Arcade Database: {e}", 502


def parse_adb_game(item):
    """Map one ADB result object → same proposed shape as ScreenScraper."""
    if not item or not isinstance(item, dict):
        return None
    title = (item.get("title") or item.get("short_title") or item.get("game_name") or "").strip()
    history = (item.get("history") or "").strip()
    # Strip excessive copyright footer if present at end — keep history text as-is
    manufacturer = (item.get("manufacturer") or "").strip()
    genre = (item.get("genre") or "").strip()
    if genre:
        genre = genre.upper()
    players = item.get("nplayers") or item.get("players") or ""
    if players is not None:
        players = str(players).strip()
    year = str(item.get("year") or "").strip()
    releasedate = ""
    digits = "".join(c for c in year if c.isdigit())
    if len(digits) >= 4:
        releasedate = digits[:4] + "0101T000000"
    rating = ""
    try:
        rate = item.get("rate")
        if rate not in (None, ""):
            val = float(rate)
            # ADB rate often 0–100
            if val > 1.0:
                val = val / 100.0
            rating = f"{max(0.0, min(1.0, val)):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        pass
    lang = ""
    languages = (item.get("languages") or "").strip()
    if languages:
        lang = languages.split(",")[0].split("/")[0].strip().lower()[:2]

    def pick_url(*keys):
        for k in keys:
            u = (item.get(k) or "").strip()
            if u and u.startswith("http"):
                return u, k
        return None, None

    medias = {}
    u, t = pick_url("url_image_ingame", "url_image_title", "url_image_select")
    if u:
        medias["image"] = {"url": u, "type": t}
    u, t = pick_url("url_video_shortplay_hd", "url_video_shortplay")
    if u:
        medias["video"] = {"url": u, "type": t}
    u, t = pick_url("url_image_marquee", "url_image_logo", "url_image_flyer")
    if u:
        medias["marquee"] = {"url": u, "type": t}
    u, t = pick_url("url_manual")
    if u:
        medias["manual"] = {"url": u, "type": t}
    u, t = pick_url("url_image_box", "url_image_cabinet", "url_image_flyer")
    if u:
        medias["boxback"] = {"url": u, "type": t}

    return {
        "ss_id": str(item.get("game_name") or ""),  # romset id used as key
        "adb_romset": str(item.get("game_name") or ""),
        "name": title,
        "desc": history,
        "rating": rating,
        "releasedate": releasedate,
        "developer": manufacturer,
        "publisher": manufacturer,
        "genre": genre,
        "players": players,
        "lang": lang,
        "medias": medias,
        "source": "arcadeitalia",
        "cloneof": (item.get("cloneof") or "").strip(),
        "status": (item.get("status") or "").strip(),
    }


def adb_current_from_game(game):
    current = {
        "name": game.findtext("name", "") or "",
        "desc": game.findtext("desc", "") or "",
        "rating": game.findtext("rating", "") or "",
        "releasedate": game.findtext("releasedate", "") or "",
        "developer": game.findtext("developer", "") or "",
        "publisher": game.findtext("publisher", "") or "",
        "genre": game.findtext("genre", "") or "",
        "players": game.findtext("players", "") or "",
        "lang": game.findtext("lang", "") or "",
    }
    for f in MEDIA_DIRS:
        current[f] = game.findtext(f, "") or ""
    return current


@app.route("/api/adb/scrape/<int:index>", methods=["POST"])
def api_adb_scrape(index):
    """
    Look up a game on Arcade Database (MAME romset name).
    Optional body: { "romset": "mslug" } to force a specific set.
    """
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="bad_index")

    body = request.get_json(silent=True) or {}
    force_romset = str(body.get("romset") or body.get("gameid") or "").strip()

    path_rel = game.findtext("path", "") or ""
    rom_name = os.path.basename(path_rel) if path_rel else ""
    romset = force_romset or os.path.splitext(rom_name)[0]
    # Clean common extra suffixes in non-pure MAME names
    if not force_romset:
        romset = romset.strip()
    local_name = game.findtext("name", "") or romset
    system_id, system_folder = detect_system_id()

    if not romset:
        return api_err(
            st("server.adb_no_romset"),
            400,
            code="no_romset",
        )

    # 1) Exact query (with parent fallback for clones)
    ok, data, _ = adb_request("query_mame", {
        "game_name": romset,
        "use_parent": "1",
        "lang": "en",
    })
    results = []
    if ok:
        results = (data.get("result") or []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            results = []

    # 2) If forced romset but empty, fail
    if force_romset and not results:
        return api_err(
            st("server.adb_romset_missing", romset=force_romset),
            404,
            code="adb_not_found",
            romset=force_romset,
        )

    # 3) Fuzzy list if exact miss
    if not results:
        ok2, data2, _ = adb_request("query_mame_like", {"game_name": romset})
        if ok2:
            results = (data2.get("result") or []) if isinstance(data2, dict) else []
            if not isinstance(results, list):
                results = []
        elif not ok:
            return api_err(str(data), 502, code="adb_error")

    if not results:
        return api_err(
            st("server.adb_not_found", romset=romset, folder=system_folder),
            404,
            code="adb_not_found",
            romset=romset,
            system_folder=system_folder,
        )

    # Single exact-ish match → full proposal
    if len(results) == 1 or force_romset:
        item = results[0]
        # If we only had lightweight "like" results, re-fetch full data
        gname = (item.get("game_name") or "").strip()
        if gname and ("history" not in item or "url_image_ingame" not in item):
            ok3, data3, _ = adb_request("query_mame", {
                "game_name": gname,
                "use_parent": "1",
                "lang": "en",
            })
            if ok3:
                full = (data3.get("result") or []) if isinstance(data3, dict) else []
                if full:
                    item = full[0]
        parsed = parse_adb_game(item)
        if not parsed:
            return api_err(st("server.adb_unusable"), 502)
        return jsonify({
            "success": True,
            "match_method": "romset" if force_romset or len(results) == 1 else "search",
            "source": "arcadeitalia",
            "system_id": system_id,
            "system_folder": system_folder,
            "rom_name": rom_name,
            "romset": romset,
            "proposed": parsed,
            "current": adb_current_from_game(game),
        })

    # Multiple candidates
    candidates = []
    for item in results[:15]:
        gname = (item.get("game_name") or "").strip()
        title = (item.get("title") or item.get("short_title") or gname).strip()
        score = name_similarity(romset, gname) if gname else 0.0
        score = max(score, name_similarity(local_name, title))
        candidates.append({
            "ss_id": gname,  # reused by UI as id key
            "name": title,
            "names": [title, gname] if gname and gname != title else [title],
            "system": (item.get("manufacturer") or "")[:40],
            "score": round(score, 3),
            "romset": gname,
        })
    candidates.sort(key=lambda c: c.get("score", 0), reverse=True)

    # Strong unique name match → fetch full record
    if candidates and candidates[0]["score"] >= 0.95 and (
        len(candidates) == 1 or candidates[0]["score"] > candidates[1]["score"] + 0.15
    ):
        gname = candidates[0]["ss_id"]
        ok3, data3, _ = adb_request("query_mame", {
            "game_name": gname,
            "use_parent": "1",
            "lang": "en",
        })
        if ok3:
            full = (data3.get("result") or []) if isinstance(data3, dict) else []
            if full:
                parsed = parse_adb_game(full[0])
                if parsed:
                    return jsonify({
                        "success": True,
                        "match_method": "name-unique",
                        "source": "arcadeitalia",
                        "system_id": system_id,
                        "system_folder": system_folder,
                        "rom_name": rom_name,
                        "romset": romset,
                        "proposed": parsed,
                        "current": adb_current_from_game(game),
                    })

    return jsonify({
        "success": True,
        "need_choice": True,
        "match_method": "search",
        "source": "arcadeitalia",
        "system_id": system_id,
        "system_folder": system_folder,
        "rom_name": rom_name,
        "romset": romset,
        "local_name": local_name,
        "search": romset,
        "candidates": candidates,
        "message": "Plusieurs romsets possibles sur Arcade Database — choisis le bon.",
    })


@app.route("/api/adb/apply/<int:index>", methods=["POST"])
def api_adb_apply(index):
    """Apply selected Arcade Database fields — same contract as /api/ss/apply."""
    body = request.get_json(silent=True) or {}
    fields = body.get("fields") or []
    proposed = body.get("proposed") or {}
    if not fields:
        return api_err(st("server.no_fields"), 400, code="no_fields")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="bad_index")

    applied = []
    errors = []
    meta_map = {
        "name": "name", "desc": "desc", "rating": "rating",
        "releasedate": "releasedate", "developer": "developer",
        "publisher": "publisher", "genre": "genre",
        "players": "players", "lang": "lang",
    }

    for field in fields:
        if field not in meta_map:
            continue
        value = (proposed.get(field) or "").strip()
        if field == "name" and not value:
            errors.append(st("server.name_empty_ignored"))
            continue
        if field == "rating" and value:
            try:
                fval = float(value)
                if not (0.0 <= fval <= 1.0):
                    errors.append(f"rating hors plage: {value}")
                    continue
            except ValueError:
                errors.append(f"rating invalide: {value}")
                continue
        if field == "lang" and value:
            value = value.lower()
        tag = meta_map[field]
        elem = game.find(tag)
        if value == "":
            if elem is not None:
                game.remove(elem)
        else:
            if elem is None:
                if tag == "name":
                    elem = etree.Element("name")
                    game.insert(0, elem)
                elif tag == "desc":
                    name_elem = game.find("name")
                    elem = etree.Element("desc")
                    if name_elem is not None:
                        name_elem.addnext(elem)
                    else:
                        game.append(elem)
                else:
                    elem = etree.SubElement(game, tag)
            elem.text = value
        applied.append(field)

    medias = proposed.get("medias") or {}
    base_name = get_base_name(game)
    for field in fields:
        if field not in MEDIA_DIRS:
            continue
        info = medias.get(field) or {}
        url = (info.get("url") or "").strip()
        if not url:
            errors.append(f"{field}: pas d'URL Arcade Database")
            continue
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                errors.append(f"{field}: URL non http(s)")
                continue
            r = requests.get(
                url,
                headers={"User-Agent": ADB_UA},
                timeout=40,
                stream=True,
            )
            r.raise_for_status()
            ext = os.path.splitext(unquote(parsed.path))[1].lower()
            if not ext or len(ext) > 6:
                ext = ext_from_content_type(r.headers.get("content-type"), field)
            new_filename = f"{base_name}-{field}{ext}"
            dest = os.path.join(media_dir, new_filename)
            written = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        f.close()
                        try:
                            os.remove(dest)
                        except OSError:
                            pass
                        raise ValueError(
                            st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024))
                        )
                    f.write(chunk)
            rel_path = f"./{media_dir_name}/{new_filename}"
            old_rel = game.findtext(field, "") or ""
            if old_rel and resolve_under_base(old_rel) != resolve_under_base(rel_path):
                safe_delete_file(old_rel)
            elem = game.find(field)
            if elem is None:
                elem = etree.SubElement(game, field)
            elem.text = rel_path
            applied.append(field)
        except Exception as e:
            errors.append(f"{field}: {e}")

    if applied:
        save_xml(tree)

    return jsonify({"success": True, "applied": applied, "errors": errors, "source": "arcadeitalia"})



@app.route("/media/<path:filepath>")
def serve_media(filepath):
    """Serve a media file only if it resolves under BASE_DIR."""
    full = resolve_under_base(filepath)
    if not full or not os.path.isfile(full):
        return st("server.file_not_found"), 404
    return send_from_directory(os.path.dirname(full), os.path.basename(full))


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Stop the Flask server (exit 0 so Lancer.bat can close without pause)."""
    def _stop():
        time.sleep(0.35)
        os._exit(0)

    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"success": True, "message": st("server.shutdown")})


if __name__ == "__main__":
    print("=" * 60)
    print(f"  Gamelist Media Editor v{APP_VERSION}")
    print("=" * 60)
    print()
    if len(sys.argv) > 1:
        xml_arg = sys.argv[1].strip().strip('"').strip("'")
    else:
        print("Indique le chemin complet vers ton fichier gamelist.xml")
        print("(tu peux glisser-deposer le fichier dans le terminal)")
        print()
        xml_arg = input("Chemin du gamelist.xml : ").strip().strip('"').strip("'")
    if not xml_arg:
        print("Aucun fichier indique. Arret.")
        sys.exit(1)
    xml_arg = os.path.abspath(xml_arg)
    if not os.path.isfile(xml_arg):
        print(f"\nErreur : fichier introuvable ->\n  {xml_arg}")
        sys.exit(1)
    XML_PATH = xml_arg
    BASE_DIR = os.path.dirname(xml_arg)
    _xml_cache["mtime"] = None
    _xml_cache["tree"] = None
    print()
    print(f"  XML            : {XML_PATH}")
    print(f"  Dossier medias : {BASE_DIR}")
    print()
    print("  Ouvre http://127.0.0.1:5050 dans ton navigateur")
    print("  (Ctrl+C pour arreter le serveur)")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5050, debug=False)
