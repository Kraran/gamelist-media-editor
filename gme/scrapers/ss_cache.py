"""Disk cache of ScreenScraper game answers, so a rescrape costs no quota.

Only game lookups are cached: ``jeuInfos.php`` (hash, ROM name or game id)
and ``jeuRecherche.php`` (name search). Each answer is one gzip file in
``<app folder>/cache/ss-api/``, named after a SHA-256 of the endpoint and
the request parameters. Credentials (devid, devpassword, ssid, sspassword)
and output options are removed before the key is computed and are never
written; the member block of the answer (``response.ssuser``: quotas,
login name) is not stored either, so a cached answer never feeds stale
limits to ``ss_limits.GATE``.

* A hit sends nothing: it takes no thread and counts neither in the requests
  per minute nor in the daily quota.
* Errors are never stored (quota, ban, login, network, server). "Game not
  found" (HTTP 404) and empty searches are kept for one day at most (they
  also count in ScreenScraper's daily "not found" quota), real answers for
  ``cache_days`` (Settings › ScreenScraper, default 30).
* ``refresh_scope()`` bypasses the cache for a forced rescrape: the request
  is sent and its answer replaces the cached one.
"""

import gzip
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager

from gme.fsutil import atomic_write
from gme.log import log
from gme.paths import APP_DIR

CACHE_DIR = os.path.join(APP_DIR, "cache", "ss-api")
CACHEABLE = frozenset({"jeuInfos.php", "jeuRecherche.php"})
SECRET_PARAMS = frozenset({"devid", "devpassword", "ssid", "sspassword", "softname", "output"})
DEFAULT_DAYS = 30
MAX_DAYS = 365
NEGATIVE_TTL = 24 * 3600
VERSION = 1

_local = threading.local()
_stats_lock = threading.Lock()


def normalize_days(raw):
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return n if 1 <= n <= MAX_DAYS else DEFAULT_DAYS


def clean_params(params):
    """Request parameters without credentials, sorted, as strings."""
    return {str(k): str(v) for k, v in sorted((params or {}).items())
            if k not in SECRET_PARAMS and v is not None and v != ""}


def key_for(endpoint, params):
    blob = json.dumps({"v": VERSION, "endpoint": endpoint, "params": clean_params(params)},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _path(key):
    return os.path.join(CACHE_DIR, key + ".json.gz")


# --- forced rescrape, and "did this scrape use the cache?" -----------------------
@contextmanager
def refresh_scope(enabled=True):
    """Requests of this thread inside the block skip the cache (answers are stored)."""
    previous = getattr(_local, "refresh", False)
    _local.refresh = bool(enabled)
    try:
        yield
    finally:
        _local.refresh = previous


def refreshing():
    return getattr(_local, "refresh", False)


@contextmanager
def track():
    """Collect the cache hits of this thread: ``{"hits": n, "sent": n, "oldest": ts}``."""
    previous = getattr(_local, "track", None)
    info = {"hits": 0, "sent": 0, "oldest": None}
    _local.track = info
    try:
        yield info
    finally:
        _local.track = previous


def _note(hit, stored_at=None):
    info = getattr(_local, "track", None)
    if info is None:
        return
    if hit:
        info["hits"] += 1
        if stored_at and (info["oldest"] is None or stored_at < info["oldest"]):
            info["oldest"] = stored_at
    else:
        info["sent"] += 1


def note_sent():
    _note(False)


# --- read / write ----------------------------------------------------------------
def get(endpoint, params, ttl_days):
    """``(ok, data_or_error, status)`` from the cache, or None (miss, expired, unreadable)."""
    if endpoint not in CACHEABLE or refreshing():
        return None
    path = _path(key_for(endpoint, params))
    try:
        with gzip.open(path, "rb") as stream:
            entry = json.loads(stream.read().decode("utf-8"))
        if entry.get("v") != VERSION or entry.get("endpoint") != endpoint:
            return None
        stored = float(entry["time"])
        ttl = ttl_days * 86400
        if entry.get("negative") or entry.get("short"):
            ttl = min(ttl, NEGATIVE_TTL)
        if time.time() - stored > ttl:
            return None
        _note(True, stored)
        if entry.get("negative"):
            return False, entry["error"], int(entry.get("status") or 404)
        return True, entry["data"], 200
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        return None


def _strip_user(data):
    """The answer without the member block (quotas, login name)."""
    data = dict(data)
    response = data.get("response")
    if isinstance(response, dict):
        data["response"] = {k: v for k, v in response.items() if k != "ssuser"}
    header = data.get("header")
    if isinstance(header, dict):
        data["header"] = {k: v for k, v in header.items() if k in ("success", "error")}
    return data


def _is_empty_search(endpoint, data):
    if endpoint != "jeuRecherche.php":
        return False
    response = data.get("response") or {}
    jeux = response.get("jeux") or response.get("jeu") or []
    if isinstance(jeux, dict):
        jeux = [jeux]
    return not [j for j in jeux if isinstance(j, dict) and j.get("id")]


def _write(endpoint, params, entry):
    entry.update({"v": VERSION, "endpoint": endpoint, "time": time.time()})
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        payload = gzip.compress(json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 6)
        atomic_write(_path(key_for(endpoint, params)), payload)
    except OSError as e:
        log.warning("ScreenScraper cache: could not store an answer (%s)", e)


def put(endpoint, params, data):
    """Store a successful JSON answer (an empty search for one day at most)."""
    if endpoint not in CACHEABLE or not isinstance(data, dict):
        return
    entry = {"data": _strip_user(data)}
    if _is_empty_search(endpoint, data):
        entry["short"] = True               # nothing found: kept one day at most
    _write(endpoint, params, entry)


def put_not_found(endpoint, params, message, status=404):
    """Store "game not found" for one day at most (it counts in the daily KO quota)."""
    if endpoint not in CACHEABLE:
        return
    _write(endpoint, params, {"negative": True, "error": str(message), "status": status})


def stats():
    """``{"entries": n, "bytes": n}`` of the cache folder."""
    entries = size = 0
    try:
        for e in os.scandir(CACHE_DIR):
            if e.is_file() and e.name.endswith(".json.gz"):
                entries += 1
                try:
                    size += e.stat().st_size
                except OSError:
                    pass
    except FileNotFoundError:
        pass
    return {"entries": entries, "bytes": size}


def clear():
    """Delete every cached answer; returns how many were removed."""
    removed = 0
    with _stats_lock:
        try:
            items = list(os.scandir(CACHE_DIR))
        except FileNotFoundError:
            return 0
        for e in items:
            if e.is_file() and (e.name.endswith(".json.gz") or e.name.endswith(".tmp")):
                try:
                    os.remove(e.path)
                    removed += 1
                except OSError:
                    pass
    return removed


def prune(ttl_days=DEFAULT_DAYS):
    """Delete answers older than the lifetime (start-up)."""
    removed = 0
    now = time.time()
    try:
        items = list(os.scandir(CACHE_DIR))
    except FileNotFoundError:
        return 0
    for e in items:
        try:
            if now - e.stat().st_mtime > ttl_days * 86400 or e.name.endswith(".tmp"):
                os.remove(e.path)
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("ScreenScraper cache: %d old answer(s) removed", removed)
    return removed
