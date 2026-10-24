"""Small list thumbnails, generated once and cached on disk.

GET /api/thumb?path=./images/x.png returns a 112x84 cover-cropped image (2x the
56x42 list cell, sharp on high-DPI screens). Thumbnails live in
``<app folder>/cache/thumbs``; the cache key includes the source's size and
modification time, so replacing an image refreshes its thumbnail.
"""

import hashlib
import io
import os
import threading

from flask import Blueprint, request, send_file

from gme import xml_store
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.log import log
from gme.paths import APP_DIR

bp = Blueprint("thumbs", __name__)

THUMB_SIZE = (112, 84)
THUMB_VERSION = "1"                     # bump to invalidate every cached thumbnail
CACHE_DIR = os.path.join(APP_DIR, "cache", "thumbs")
CACHE_MAX_FILES = 20000                 # pruned (oldest first) at start-up
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

_fmt_lock = threading.Lock()
_fmt = None


def _output_format():
    """WebP when Pillow supports it (small, keeps transparency), else PNG/JPEG."""
    global _fmt
    with _fmt_lock:
        if _fmt is None:
            try:
                from PIL import features
                _fmt = "WEBP" if features.check("webp") else "PNG"
            except Exception:
                _fmt = "PNG"
        return _fmt


def cache_key(full_path):
    st = os.stat(full_path)
    raw = f"{os.path.normcase(full_path)}|{st.st_mtime_ns}|{st.st_size}|{THUMB_SIZE}|{THUMB_VERSION}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def make_thumb(full_path, key):
    """Create the cached thumbnail for ``full_path``; returns (path, mimetype)."""
    from PIL import Image, ImageOps

    fmt = _output_format()
    ext, mime = {"WEBP": (".webp", "image/webp"), "PNG": (".png", "image/png")}[fmt]
    dest = os.path.join(CACHE_DIR, key + ext)
    if os.path.isfile(dest):
        return dest, mime
    with Image.open(full_path) as im:
        im.draft("RGB", (THUMB_SIZE[0] * 2, THUMB_SIZE[1] * 2))   # fast JPEG decode at reduced size
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        im = ImageOps.fit(im, THUMB_SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
        buf = io.BytesIO()
        if fmt == "WEBP":
            im.save(buf, fmt, quality=80, method=4)
        else:
            im.save(buf, fmt, optimize=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    atomic_write(dest, buf.getvalue())
    return dest, mime


@bp.route("/api/thumb")
def api_thumb():
    rel = request.args.get("path", "")
    full = xml_store.resolve_under_base(rel) if xml_store.has_gamelist() else None
    if not full or not os.path.isfile(full):
        return api_err("Not found", 404, code="not_found")
    if os.path.splitext(full)[1].lower() not in _IMAGE_EXTS:
        return api_err("Not an image", 415, code="not_image")
    key = cache_key(full)
    if key in request.if_none_match:
        return "", 304, {"ETag": f'"{key}"', "Cache-Control": "no-cache"}
    try:
        path, mime = make_thumb(full, key)
    except Exception as e:                       # corrupt or unsupported image
        log.info("Thumbnail failed for %s: %s", rel, e)
        return api_err("Unreadable image", 415, code="unreadable_image")
    resp = send_file(path, mimetype=mime, etag=key, max_age=0, conditional=True)
    resp.headers["Cache-Control"] = "no-cache"   # revalidate (cheap 304), never stale
    return resp


def prune_cache(max_files=CACHE_MAX_FILES):
    """Keep the thumbnail cache bounded: delete the oldest files beyond ``max_files``."""
    try:
        entries = [e for e in os.scandir(CACHE_DIR) if e.is_file()]
    except FileNotFoundError:
        return 0
    if len(entries) <= max_files:
        return 0
    entries.sort(key=lambda e: e.stat().st_atime)
    removed = 0
    for e in entries[: len(entries) - max_files]:
        try:
            os.remove(e.path)
            removed += 1
        except OSError:
            pass
    log.info("Thumbnail cache: %d old file(s) removed", removed)
    return removed
