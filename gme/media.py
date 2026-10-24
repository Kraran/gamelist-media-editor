"""Media files: extension detection, downloads, placeholders, Pad2Key, safe deletion."""

import os
from urllib.parse import unquote, urlparse

import requests

from gme import remote_cache, xml_store
from gme.fsutil import atomic_write
from gme.version import APP_UA
from gme.xml_store import get_base_name, resolve_under_base


# Max size for media downloaded from a URL (bytes)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


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


# Script endpoints (ScreenScraper image.php, etc.) are not real file types.
_FAKE_EXTS = {
    ".php", ".asp", ".aspx", ".jsp", ".cgi", ".html", ".htm",
    ".exe", ".dll", ".json", ".xml", ".txt",
}
MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".mp4", ".webm", ".avi", ".mkv", ".mp3",
    ".pdf",
}


def ext_from_magic(data):
    """Detect image/video/pdf from the first bytes. None if unknown."""
    if not data or len(data) < 12:
        head = data or b""
    else:
        head = data
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return ".gif"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head.startswith(b"BM"):
        return ".bmp"
    if head.startswith(b"%PDF"):
        return ".pdf"
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return ".mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    return None


def ext_from_content_type(ct, field=None):
    """Map Content-Type to an extension, or None if not a real media type."""
    ct = (ct or "").split(";")[0].strip().lower()
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "application/pdf": ".pdf",
        "application/x-pdf": ".pdf",
    }
    if ct in mapping:
        return mapping[ct]
    if ct.startswith("image/"):
        return ".png"
    if ct.startswith("video/"):
        return ".mp4"
    if "pdf" in ct:
        return ".pdf"
    return None


def ext_from_url_path(url):
    """Use the URL path extension only if it is a real media suffix."""
    if not url:
        return None
    path = unquote(urlparse(url).path or "")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext in MEDIA_EXTS and ext not in _FAKE_EXTS:
        return ext
    return None


def resolve_media_ext(url, content_type, field, head=b""):
    """Prefer file signature, then Content-Type, then a real URL suffix."""
    return (
        ext_from_magic(head)
        or ext_from_content_type(content_type, field)
        or ext_from_url_path(url)
        or default_ext_for_field(field)
    )


def is_ss_green_placeholder(data):
    """True if the image is a flat lime-green ScreenScraper boxback dummy.

    SS often returns a solid #00FF00 PNG/JPEG when box-2D-back is missing.
    We treat that as « no media » so we do not pollute images/ nor the XML.
    """
    if not data or len(data) < 24:
        return False
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data)).convert("RGB")
        extrema = im.getextrema()
        if not extrema or len(extrema) < 3:
            return False
        (rmin, rmax), (gmin, gmax), (bmin, bmax) = extrema[:3]
        if rmax - rmin > 24 or gmax - gmin > 24 or bmax - bmin > 24:
            return False
        r = (rmin + rmax) // 2
        g = (gmin + gmax) // 2
        b = (bmin + bmax) // 2
        return g >= 170 and r <= 60 and b <= 60
    except Exception:
        return _png_is_solid_green(data)


def _png_is_solid_green(data):
    """Stdlib fallback: 8-bit non-interlaced PNG, RGB / RGBA / palette."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    import struct
    import zlib
    pos = 8
    ihdr = plte = None
    idats = []
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        start = pos + 8
        end = start + length
        if end + 4 > len(data):
            break
        chunk = data[start:end]
        if ctype == b"IHDR":
            ihdr = chunk
        elif ctype == b"PLTE":
            plte = chunk
        elif ctype == b"IDAT":
            idats.append(chunk)
        elif ctype == b"IEND":
            break
        pos = end + 4
    if not ihdr or len(ihdr) < 13 or not idats:
        return False
    width, height, bit, color, comp, filt, inter = struct.unpack(">IIBBBBB", ihdr[:13])
    if inter or bit != 8 or color not in (2, 3, 6) or width <= 0 or height <= 0:
        return False
    if width * height > 8_000_000:
        return False
    try:
        raw = zlib.decompress(b"".join(idats))
    except Exception:
        return False
    bpp = {2: 3, 6: 4, 3: 1}[color]
    stride = width * bpp
    expected = (stride + 1) * height
    if len(raw) < expected:
        return False
    prev = bytearray(stride)
    rmin = gmin = bmin = 255
    rmax = gmax = bmax = 0

    def _paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    off = 0
    for _y in range(height):
        ftype = raw[off]
        row = bytearray(raw[off + 1:off + 1 + stride])
        off += 1 + stride
        if ftype == 1:
            for i in range(stride):
                row[i] = (row[i] + (row[i - bpp] if i >= bpp else 0)) & 255
        elif ftype == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 255
        elif ftype == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) // 2)) & 255
        elif ftype == 4:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev[i]
                ul = prev[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + _paeth(left, up, ul)) & 255
        elif ftype != 0:
            return False
        prev = row
        if color == 3:
            if not plte or len(plte) < 3:
                return False
            for i in range(width):
                idx = row[i] * 3
                if idx + 2 >= len(plte):
                    return False
                r, g, b = plte[idx], plte[idx + 1], plte[idx + 2]
                rmin, rmax = min(rmin, r), max(rmax, r)
                gmin, gmax = min(gmin, g), max(gmax, g)
                bmin, bmax = min(bmin, b), max(bmax, b)
        else:
            for i in range(0, stride, bpp):
                r, g, b = row[i], row[i + 1], row[i + 2]
                rmin, rmax = min(rmin, r), max(rmax, r)
                gmin, gmax = min(gmin, g), max(gmax, g)
                bmin, bmax = min(bmin, b), max(bmax, b)
        if rmax - rmin > 24 or gmax - gmin > 24 or bmax - bmin > 24:
            return False
    r = (rmin + rmax) // 2
    g = (gmin + gmax) // 2
    b = (bmin + bmax) // 2
    return g >= 170 and r <= 60 and b <= 60


def download_remote_media(url, media_dir, base_name, field, headers=None, timeout=40):
    """Download a remote media file and save it with a real image/video/pdf extension.

    A copy already downloaded for the scrape preview (``remote_cache``) is
    reused, so applying a previewed image costs no second download.
    ScreenScraper URLs often end with ``image.php`` — that suffix is ignored.
    Returns the dest filename (not a path).
    """
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("url_not_allowed")
    data = remote_cache.get(url)
    content_type = None
    if data is None:
        data, content_type = remote_cache.fetch(
            url,
            headers=headers or {"User-Agent": APP_UA},
            timeout=timeout,
            max_bytes=MAX_DOWNLOAD_BYTES,
        )
    if field == "boxback" and is_ss_green_placeholder(data):
        raise ValueError("green_placeholder")
    ext = resolve_media_ext(url, content_type, field, data[:64])
    filename = f"{base_name}-{field}{ext}"
    atomic_write(os.path.join(media_dir, filename), data)
    return filename


def pad2key_dest(game):
    """RetroBat: same folder as the ROM, same basename, extension .keys."""
    path_rel = game.findtext("path", "") or ""
    full = resolve_under_base(path_rel) if path_rel else None
    if full:
        return os.path.splitext(full)[0] + ".keys"
    return os.path.join(xml_store.BASE_DIR, get_base_name(game) + ".keys")


def download_pad2key(url, dest):
    """Download a RetroBat ``.keys`` (Pad2Key) file next to the ROM."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url_not_allowed")
    r = requests.get(url, headers={"User-Agent": APP_UA}, timeout=40)
    r.raise_for_status()
    data = r.content or b""
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("too_large")
    if not data:
        raise ValueError("empty")
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return dest
