"""Media proposed by a scraper: previewed before applying, downloaded once.

The scrape dialog shows each proposed image next to the current one. Those
images come from ScreenScraper or Arcade Database, and every ScreenScraper
media download counts in the member's daily quota. So a proposed image is
downloaded once, when it is previewed, kept in ``<app folder>/cache/remote``,
and applying it later reuses that copy instead of downloading it again.

Previews are addressed by a key, never by URL: a scrape registers the URLs it
proposes (``register``) and the page asks for ``/api/scrape/preview/<key>``.
The server only ever fetches URLs a scraper gave it, and ScreenScraper URLs,
which carry the member's login, never appear in an address or a log line.
"""

import hashlib
import os
import re
import threading
import time
from collections import OrderedDict
from io import BytesIO
from urllib.parse import urlparse

import requests
from flask import Blueprint, send_file

from gme.fsutil import atomic_write
from gme.http import api_err
from gme.log import log
from gme.paths import APP_DIR
from gme.version import APP_UA

bp = Blueprint("remote_cache", __name__)

CACHE_DIR = os.path.join(APP_DIR, "cache", "remote")
CACHE_TTL = 24 * 3600                   # a scraper's answer for one game: reused within a day
CACHE_MAX_FILES = 600                   # pruned (oldest first) at start-up
MAX_PREVIEW_BYTES = 20 * 1024 * 1024    # images only; videos and manuals are not previewed
_REGISTRY_MAX = 4000

_registry = OrderedDict()               # key -> (url, headers)
_registry_lock = threading.Lock()
_host_locks = {}                        # one download at a time per host (ScreenScraper threads)
_host_locks_guard = threading.Lock()
_KEY_RE = re.compile(r"^[0-9a-f]{40}$")

_IMAGE_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def key_for(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _path(key):
    return os.path.join(CACHE_DIR, key)


def register(url, headers=None):
    """Remember a proposed media URL and return its preview key."""
    key = key_for(url)
    with _registry_lock:
        _registry[key] = (url, dict(headers or {}))
        _registry.move_to_end(key)
        while len(_registry) > _REGISTRY_MAX:
            _registry.popitem(last=False)
    return key


def _registered(key):
    with _registry_lock:
        return _registry.get(key)


def get(url=None, key=None):
    """Bytes of a cached download still within its lifetime, else None."""
    key = key or key_for(url)
    path = _path(key)
    try:
        if time.time() - os.path.getmtime(path) > CACHE_TTL:
            return None
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def put(url, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        atomic_write(_path(key_for(url)), data)
    except OSError as e:
        log.warning("Remote cache: could not store a download (%s)", e)


def _host_lock(url):
    host = (urlparse(url).hostname or "").lower()
    with _host_locks_guard:
        return _host_locks.setdefault(host, threading.Lock())


def fetch(url, headers=None, timeout=40, max_bytes=50 * 1024 * 1024):
    """Download ``url`` into memory (bytes, content type).

    Raises ValueError("url_not_allowed" | "too_large" | "empty"), or a
    requests exception on a network or HTTP error.
    """
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("url_not_allowed")
    with _host_lock(url):
        r = requests.get(url, headers=headers or {"User-Agent": APP_UA}, timeout=timeout, stream=True)
        try:
            r.raise_for_status()
            cl = r.headers.get("content-length")
            if cl and str(cl).isdigit() and int(cl) > max_bytes:
                raise ValueError("too_large")
            chunks, written = [], 0
            for chunk in r.iter_content(65536):
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("too_large")
                chunks.append(chunk)
        finally:
            r.close()
    data = b"".join(chunks)
    if not data:
        raise ValueError("empty")
    return data, r.headers.get("content-type")


def image_type(data):
    """MIME type of a PNG / JPEG / GIF / WebP / BMP, else None."""
    head = data[:16]
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    for magic, mime in _IMAGE_TYPES:
        if head.startswith(magic):
            return mime
    return None


def prune_cache(max_files=CACHE_MAX_FILES):
    """Delete expired downloads, then the oldest beyond ``max_files``."""
    try:
        entries = [e for e in os.scandir(CACHE_DIR) if e.is_file()]
    except FileNotFoundError:
        return 0
    now = time.time()
    keep, removed = [], 0
    for e in entries:
        try:
            expired = now - e.stat().st_mtime > CACHE_TTL
        except OSError:
            continue
        if expired or e.name.endswith(".tmp"):
            try:
                os.remove(e.path)
                removed += 1
            except OSError:
                pass
        else:
            keep.append(e)
    if len(keep) > max_files:
        keep.sort(key=lambda e: e.stat().st_mtime)
        for e in keep[: len(keep) - max_files]:
            try:
                os.remove(e.path)
                removed += 1
            except OSError:
                pass
    if removed:
        log.info("Remote media cache: %d old file(s) removed", removed)
    return removed


@bp.route("/api/scrape/preview/<key>")
def api_scrape_preview(key):
    """A proposed image, downloaded on first view and kept for the apply step."""
    if not _KEY_RE.match(key or ""):
        return api_err("bad key", 400, code="bad_key")
    data = get(key=key)
    if data is None:
        entry = _registered(key)
        if not entry:
            return api_err("unknown preview", 404, code="unknown_preview")
        url, headers = entry
        try:
            data, _ = fetch(url, headers=headers, timeout=30, max_bytes=MAX_PREVIEW_BYTES)
        except ValueError as e:
            return api_err(str(e), 422, code=str(e))
        except Exception as e:  # network / HTTP error from the source
            log.info("Preview download failed: %s", type(e).__name__)
            return api_err("download failed", 502, code="download_failed")
        if image_type(data):
            put(url, data)
    mime = image_type(data)
    if not mime:
        return api_err("not an image", 415, code="not_image")
    resp = send_file(BytesIO(data), mimetype=mime, max_age=3600)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp
