"""Media files: extension detection, downloads, placeholders, Pad2Key, safe deletion."""

import mimetypes
import os
from urllib.parse import unquote, urlparse

import requests

from gme import esde, fsutil, remote_cache, xml_store
from gme.scrapers import ss_limits
from gme.fsutil import atomic_write
from gme.log import log
from gme.version import APP_UA
from gme.xml_store import get_base_name, resolve_under_base


# Max size for media downloaded from a URL (bytes)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


# --- Files shared between games ----------------------------------------------
# Two games (or two tags of one game) may point to the same file: a box art
# reused for a clone, a ROM listed twice. A file still used elsewhere is never
# deleted nor overwritten, and what is deleted goes to the Recycle Bin.

# Tags that never hold a file path; every other tag may (<image>, <wheel>, <path>…)
NOT_FILE_TAGS = {"name", "desc", "rating", "releasedate", "developer", "publisher", "genre",
                 "players", "lang", "region", "family", "favorite", "hidden", "kidgame",
                 "playcount", "lastplayed", "arcadesystemname", "genreid", "sortname", "md5",
                 "crc32", "cheevosid", "gametime"}


def file_path(value):
    """Absolute path of a path written in the gamelist, or None (empty, URL, steam://)."""
    value = (value or "").strip()
    if not value or "://" in value:
        return None
    if xml_store.PROFILE is not None and value.replace("\\", "/").startswith(esde.PREFIX):
        return esde.resolve(xml_store.PROFILE, value)
    if not os.path.isabs(value):
        clean = value.replace("\\", "/")
        while clean.startswith("./"):
            clean = clean[2:]
        value = os.path.join(xml_store.rom_dir(), clean)
    return os.path.normpath(value)


def file_key(value):
    """Comparable form of a path written in the gamelist (same file = same key), or None."""
    full = file_path(value)
    return os.path.normcase(full) if full else None


def _file_tags(game):
    for child in game:
        if isinstance(child.tag, str) and child.tag not in NOT_FILE_TAGS and child.text:
            yield child


def file_in_use(game, value, skip_tag=None):
    """True when a tag of the gamelist other than ``game``'s ``skip_tag`` points to ``value``.

    The other tags of ``game`` count (its thumbnail may be its image file).
    """
    key = file_key(value)
    root = game.getparent()
    if not key or root is None:
        return False
    name = os.path.basename(key).lower()
    for other in root.iterfind("game"):
        for child in _file_tags(other):
            if other is game and child.tag == skip_tag:
                continue
            text = child.text.strip().replace("\\", "/")
            if text.rsplit("/", 1)[-1].lower() == name and file_key(text) == key:
                return True
    return False


def files_used_by_others(game):
    """Keys of every file the other games of the gamelist point to."""
    root = game.getparent()
    used = set()
    if root is None:
        return used
    for other in root.iterfind("game"):
        if other is game:
            continue
        for child in _file_tags(other):
            key = file_key(child.text)
            if key:
                used.add(key)
    return used


def media_filename(game, field, ext, media_dir_name):
    """``<rom>-<field><ext>``, or ``<rom>-<field>-2<ext>``… when that file belongs to another tag."""
    base = get_base_name(game)
    n = 1
    while True:
        name = f"{base}-{field}{ext}" if n == 1 else f"{base}-{field}-{n}{ext}"
        rel = f"./{media_dir_name}/{name}"
        if not os.path.exists(os.path.join(xml_store.BASE_DIR, media_dir_name, name)) \
                or not file_in_use(game, rel, skip_tag=field):
            return name
        n += 1


def media_dest(game, field, ext):
    """``(absolute path, gamelist value)`` where a new ``field`` file with ``ext`` goes.

    Classic layout: ``./images/<rom>-<field><ext>`` next to the gamelist.
    ES-DE: ``downloaded_media/<system>/<type>/<rom><ext>`` (the name is what
    links the media to the game). The folder is created.
    """
    if xml_store.PROFILE is not None:
        full, value = esde.target(xml_store.PROFILE, game, field, ext)
        if not full:
            raise ValueError("bad_media_path")
    else:
        folder = xml_store.MEDIA_DIRS[field]
        name = media_filename(game, field, ext, folder)
        full, value = os.path.join(xml_store.BASE_DIR, folder, name), f"./{folder}/{name}"
    os.makedirs(os.path.dirname(full), exist_ok=True)
    return full, value


def remove_media(game, field):
    """ES-DE: a media is its file, so removing it from a game moves the file to
    the Recycle Bin (with the same file under another extension). Classic layout:
    nothing (the tag goes, the file stays). Returns the paths moved."""
    if xml_store.PROFILE is None:
        return []
    value = (game.findtext(field, "") or "").strip()
    full = esde.resolve(xml_store.PROFILE, value) if value else None
    if not full:
        return []
    moved = []
    for path in [full] + esde.siblings(full, field):
        if os.path.isfile(path):
            try:
                fsutil.trash(path)
                moved.append(path)
            except Exception as e:  # no Recycle Bin on this drive, locked file: keep it
                log.warning("Could not move the media %s to the Recycle Bin (%s)", path, e)
    return moved


def discard_old_media(game, field, old_rel, new_rel):
    """After ``field`` moved from ``old_rel`` to ``new_rel``: the old file goes to the
    Recycle Bin, unless another tag still uses it. Returns True if it was moved.

    ES-DE: the same media under another extension (``.jpg`` beside the new
    ``.png``) goes too, or ES-DE could keep showing it."""
    moved = _discard_old_file(game, field, old_rel, new_rel)
    if xml_store.PROFILE is not None and field in esde.FOLDERS:
        new_full = esde.resolve(xml_store.PROFILE, new_rel)
        for other in esde.siblings(new_full, field) if new_full else ():
            try:
                fsutil.trash(other)
                moved = True
            except Exception as e:
                log.warning("Could not move the replaced media %s to the Recycle Bin (%s)", other, e)
    return moved


def _discard_old_file(game, field, old_rel, new_rel):
    old_key = file_key(old_rel)
    if not old_key or old_key == file_key(new_rel) or file_in_use(game, old_rel, skip_tag=field):
        return False
    full = resolve_under_base(old_rel)
    if not full or not os.path.isfile(full):
        return False
    try:
        fsutil.trash(full)
        return True
    except Exception as e:  # no Recycle Bin on this drive, locked file: keep it
        log.warning("Could not move the replaced media %s to the Recycle Bin (%s)", full, e)
        return False


def default_ext_for_field(field):
    if field == "music":
        return ".mp3"
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
    ".mp4", ".webm", ".avi", ".mkv",
    ".mp3", ".ogg", ".wav", ".flac",
    ".pdf",
}
AUDIO_EXTS = {".mp3", ".ogg", ".wav", ".flac"}
# Windows' registry may not know these: /media/ would serve them as octet-stream
for _ext, _mime in ((".mp3", "audio/mpeg"), (".ogg", "audio/ogg"), (".wav", "audio/wav"),
                    (".flac", "audio/flac")):
    mimetypes.add_type(_mime, _ext)


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
    if head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0 and head[1] & 0x06):
        return ".mp3"                     # ID3 tag, or an MPEG audio frame header
    if head.startswith(b"OggS"):
        return ".ogg"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head.startswith(b"fLaC"):
        return ".flac"
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
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/flac": ".flac",
    }
    if ct in mapping:
        return mapping[ct]
    if ct.startswith("image/"):
        return ".png"
    if ct.startswith("video/"):
        return ".mp4"
    if ct.startswith("audio/"):
        return ".mp3"
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


# --- Downloaded image check (scrapes) ------------------------------------------
# A source sometimes answers with a broken file, an HTML error page, a 1x1
# pixel or a flat placeholder instead of a real picture. A scrape must not
# write it (nor point the gamelist at it): the media is reported as failed.
MIN_IMAGE_SIDE = 16            # px: a smaller width or height is a placeholder, not art
MIN_IMAGE_PIXELS = 32 * 32     # px²: same for the area (a 600x1 strip is not a picture)
UNIFORM_MAX_RANGE = 10         # 0-255: every channel varies less than this → one colour
_NOT_IMAGE_FIELDS = {"video", "manual", "music"}
_NOT_IMAGE_EXTS = {".mp4", ".webm", ".avi", ".mkv", ".pdf"} | AUDIO_EXTS


class MediaRejected(ValueError):
    """A downloaded image is not usable: ``code`` is image_unreadable, image_too_small or image_uniform."""

    def __init__(self, code, **params):
        super().__init__(code)
        self.code, self.params = code, params


def check_image(data):
    """Raise MediaRejected unless ``data`` decodes as a real, non-uniform picture."""
    import io
    import warnings
    from PIL import Image
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                im.load()                         # decodes the pixels: truncated files fail here
                width, height = im.size
                if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE or width * height < MIN_IMAGE_PIXELS:
                    raise MediaRejected("image_too_small", w=width, h=height)
                rgba = im.convert("RGBA")
    except MediaRejected:
        raise
    except Exception as e:                        # not an image, corrupt, truncated, bomb
        raise MediaRejected("image_unreadable") from e
    if uniform_colour(rgba) is not None:
        raise MediaRejected("image_uniform")


def uniform_colour(rgba):
    """``"transparent"``, ``"#rrggbb"`` when an RGBA picture is a single colour, else None.

    Measured on a small copy (averaging removes JPEG noise): fully transparent,
    or every channel (alpha included) within ``UNIFORM_MAX_RANGE``.
    """
    from PIL import Image
    small = rgba.copy()
    small.thumbnail((64, 64), Image.Resampling.BOX)
    (amin, amax) = small.getextrema()[3]
    if amax == 0:
        return "transparent"
    rgb = small.convert("RGB")
    rgb_ranges = [hi - lo for lo, hi in rgb.getextrema()]
    if amax - amin <= UNIFORM_MAX_RANGE and max(rgb_ranges) <= UNIFORM_MAX_RANGE:
        r, g, b = (round(sum(lo_hi) / 2) for lo_hi in rgb.getextrema())
        return "#%02x%02x%02x" % (r, g, b)
    return None


def must_check_image(field, data):
    """Image fields are checked; videos, manuals (and a video or PDF file) are not."""
    return field not in _NOT_IMAGE_FIELDS and ext_from_magic(data[:64]) not in _NOT_IMAGE_EXTS


def download_remote_media(url, media_dir, base_name, field, headers=None, timeout=40, filename_for=None,
                          check=False):
    """Download a remote media file and save it with a real image/video/pdf extension.

    A copy already downloaded for the scrape preview (``remote_cache``) is
    reused, so applying a previewed image costs no second download.
    ScreenScraper URLs often end with ``image.php`` — that suffix is ignored.
    ``filename_for(ext)`` names the file (default ``<base_name>-<field><ext>``).
    ``check`` (scrapes): an image that fails ``check_image`` raises MediaRejected
    and nothing is written.
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
    if check and must_check_image(field, data):
        check_image(data)
    ext = resolve_media_ext(url, content_type, field, data[:64])
    filename = filename_for(ext) if filename_for else f"{base_name}-{field}{ext}"
    atomic_write(os.path.join(media_dir, filename), data)
    _note_written()
    return filename


def pad2key_dest(game):
    """RetroBat: same folder as the ROM, same basename, extension .keys."""
    path_rel = game.findtext("path", "") or ""
    full = resolve_under_base(path_rel) if path_rel else None
    if full:
        return os.path.splitext(full)[0] + ".keys"
    if xml_store.PROFILE is not None:
        return os.path.join(xml_store.rom_dir(), get_base_name(game) + ".keys")
    return os.path.join(xml_store.BASE_DIR, get_base_name(game) + ".keys")


def download_pad2key(url, dest):
    """Download a RetroBat ``.keys`` (Pad2Key) file next to the ROM."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url_not_allowed")
    if ss_limits.is_ss_url(url):         # a ScreenScraper API call: member's limits
        with ss_limits.GATE.slot():
            r = requests.get(url, headers={"User-Agent": APP_UA}, timeout=40)
        ss_limits.GATE.note_status(r.status_code)
    else:
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
    _note_written()
    return dest


def _note_written():
    """The undo step of this request says media files were written (gme.history)."""
    try:
        from gme import history
        history.note_written()
    except Exception:  # pragma: no cover
        pass
