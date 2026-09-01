#!/usr/bin/env python3
"""
Gamelist Media Editor — local Flask app for EmulationStation / RetroBat gamelist.xml.

Architecture
------------
* Bound to 127.0.0.1 only (local tool, not exposed on the LAN).
* Starts **without** a gamelist; the user opens one via /api/open-gamelist
  (or passes a path on the CLI / drops a file onto the .exe).
* Media files live under the gamelist folder (images/, videos/, manuals/).
* XML is cached by mtime; writes are serialized with a process lock.
* ScreenScraper, Arcade Database and Steam scrapers share the same apply contract.
* PyInstaller: templates/static from sys._MEIPASS; writable config next to the .exe.

Entry points: ``main()`` (source or frozen), routes under ``/api/…``.
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
import subprocess
from urllib.parse import urlparse, unquote

from flask import Flask, render_template, request, jsonify, send_from_directory
from lxml import etree
import requests
import logging

log = logging.getLogger("gamelist-editor")
if not log.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

def resource_path(*parts):
    """Bundled resources (PyInstaller _MEIPASS) or source tree."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts) if parts else base


def app_data_dir():
    """Writable directory next to the .exe (or next to app.py in source mode)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# Writable app dir (config next to .exe); BUNDLE_DIR holds templates/static
APP_DIR = app_data_dir()
BUNDLE_DIR = resource_path()

app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)


def api_err(message, status=400, code=None, **extra):
    """Consistent JSON error payload for the frontend."""
    payload = {"error": str(message), "ok": False}
    if code:
        payload["code"] = code
    payload.update(extra)
    return jsonify(payload), status


# Root of the current gamelist + media folders (set via /api/open-gamelist or CLI)
BASE_DIR = APP_DIR
_LOCALE_DIR = resource_path("static", "locales")
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


# Active gamelist path (None until the user opens one or passes a CLI arg)
XML_PATH = None


def set_gamelist_path(path):
    """
    Point the editor at another gamelist.xml (absolute path).
    Updates XML_PATH + BASE_DIR, clears the parse cache.
    Raises FileNotFoundError / ValueError on bad input.
    """
    global XML_PATH, BASE_DIR
    if not path or not str(path).strip():
        raise ValueError(st("server.open_empty_path"))
    path = os.path.abspath(str(path).strip().strip('"').strip("'"))
    if not os.path.isfile(path):
        raise FileNotFoundError(st("server.open_not_found", path=path))
    if not path.lower().endswith(".xml"):
        raise ValueError(st("server.open_not_xml"))
    # Validate parse once before switching
    try:
        etree.parse(path, etree.XMLParser(remove_blank_text=True))
    except etree.XMLSyntaxError as e:
        raise ValueError(st("server.open_bad_xml", detail=e)) from e
    XML_PATH = path
    BASE_DIR = os.path.dirname(path)
    _xml_cache["mtime"] = None
    _xml_cache["tree"] = None
    return {
        "xml_path": XML_PATH,
        "base_dir": BASE_DIR,
        "system": get_system_info(),
    }


def has_gamelist():
    """True when a valid gamelist.xml path is loaded."""
    return bool(XML_PATH) and os.path.isfile(XML_PATH)


def require_gamelist():
    """Return an error response if no gamelist is loaded, else None."""
    if not has_gamelist():
        return api_err(st("server.no_gamelist"), 400, code="no_gamelist")
    return None


# Max size for media downloaded from a URL (bytes)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

MEDIA_DIRS = {
    "image": "images", "video": "videos", "marquee": "images",
    "manual": "manuals", "boxback": "images", "thumbnail": "images",
    "fanart": "images", "map": "images",
    "cartridge": "images", "boxart": "images", "mix": "images",
    "bezel": "images",
}
META_FIELDS = {
    "rating", "releasedate", "developer", "publisher",
    "family", "players", "lang", "region", "genre",
    "kidgame", "hidden", "favorite", "arcadesystemname",
}
BOOL_META_FIELDS = {"kidgame", "hidden", "favorite"}
P2K_TYPES = ("p2k", "padtokey", "pad2key", "pad-to-key")

# --- XML cache + process lock -------------------------------------------------
# Cache avoids re-parsing a large gamelist on every API call.
# _xml_io_lock serializes backup/save so concurrent requests cannot interleave writes.
_xml_cache = {"mtime": None, "tree": None}
_xml_io_lock = threading.Lock()  # serialize read-modify-write of the XML file


def load_xml():
    """Parse gamelist.xml; reuse cached tree if file mtime unchanged."""
    if not has_gamelist():
        raise FileNotFoundError(st("server.no_gamelist"))
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
        if not has_gamelist():
            raise FileNotFoundError(st("server.no_gamelist"))
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
    """Keep a ROM stem usable as ``game-image.png`` (no path separators)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name or "unknown"


def get_base_name(game_elem):
    """File stem of ``<path>`` without extension, sanitized."""
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
            "cartridge": game.findtext("cartridge", "") or "",
            "boxart": game.findtext("boxart", "") or "",
            "fanart": game.findtext("fanart", "") or "",
            "mix": game.findtext("mix", "") or "",
            "map": game.findtext("map", "") or "",
            "rating": game.findtext("rating", "") or "",
            "releasedate": game.findtext("releasedate", "") or "",
            "developer": game.findtext("developer", "") or "",
            "publisher": game.findtext("publisher", "") or "",
            "family": game.findtext("family", "") or "",
            "players": game.findtext("players", "") or "",
            "lang": game.findtext("lang", "") or "",
            "region": game.findtext("region", "") or "",
            "genre": game.findtext("genre", "") or "",
            "kidgame": game.findtext("kidgame", "") or "",
            "hidden": game.findtext("hidden", "") or "",
            "favorite": game.findtext("favorite", "") or "",
            "arcadesystemname": game.findtext("arcadesystemname", "") or "",
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


# Script endpoints (ScreenScraper image.php, etc.) are not real file types.
_FAKE_EXTS = {
    ".php", ".asp", ".aspx", ".jsp", ".cgi", ".html", ".htm",
    ".exe", ".dll", ".json", ".xml", ".txt",
}
_MEDIA_EXTS = {
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
    if ext in _MEDIA_EXTS and ext not in _FAKE_EXTS:
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

    ScreenScraper URLs often end with ``image.php`` — that suffix is ignored.
    Returns the dest filename (not a path).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url_not_allowed")
    r = requests.get(
        url,
        headers=headers or {"User-Agent": APP_UA},
        timeout=timeout,
        stream=True,
    )
    r.raise_for_status()
    cl = r.headers.get("content-length")
    if cl and str(cl).isdigit() and int(cl) > MAX_DOWNLOAD_BYTES:
        r.close()
        raise ValueError("too_large")
    chunks = []
    written = 0
    for chunk in r.iter_content(8192):
        if not chunk:
            continue
        written += len(chunk)
        if written > MAX_DOWNLOAD_BYTES:
            raise ValueError("too_large")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ValueError("empty")
    if field == "boxback" and is_ss_green_placeholder(data):
        raise ValueError("green_placeholder")
    ext = resolve_media_ext(url, r.headers.get("content-type"), field, data[:64])
    filename = f"{base_name}-{field}{ext}"
    dest = os.path.join(media_dir, filename)
    with open(dest, "wb") as f:
        f.write(data)
    return filename


def pad2key_dest(game):
    """RetroBat: same folder as the ROM, same basename, extension .keys."""
    path_rel = game.findtext("path", "") or ""
    full = resolve_under_base(path_rel) if path_rel else None
    if full:
        return os.path.splitext(full)[0] + ".keys"
    return os.path.join(BASE_DIR, get_base_name(game) + ".keys")


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


_MAME_DRIVERS = None


def load_mame_drivers():
    """sourcefile stem → short board name (cps1 → CPS1). Cached."""
    global _MAME_DRIVERS
    if _MAME_DRIVERS is not None:
        return _MAME_DRIVERS
    path = resource_path("static", "mame_drivers.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        _MAME_DRIVERS = {str(k).lower(): str(v) for k, v in raw.items()}
    except Exception:
        _MAME_DRIVERS = {}
    return _MAME_DRIVERS


_DRIVER_PREFIXES = (
    ("segas16", "System 16"),
    ("sega16", "System 16"),
    ("segas32", "System 32"),
    ("sega32", "System 32"),
    ("gaelco", "Gaelco"),
    ("cps3", "CPS3"),
    ("cps2", "CPS2"),
    ("cps1", "CPS1"),
    ("neogeo", "Neo-Geo"),
    ("hng64", "Hyper Neo-Geo 64"),
    ("playch", "PlayChoice-10"),
    ("vsnes", "Vs. System"),
    ("decocass", "DECO Cassette"),
    ("konamigx", "Konami GX"),
    ("namcos", "Namco"),
    ("taito_type_x", "Taito Type X"),
    ("taitotx", "Taito Type X"),
    ("typex", "Taito Type X"),
    ("atomiswave", "Atomiswave"),
    ("lindbergh", "Lindbergh"),
    ("chihiro", "Chihiro"),
    ("triforce", "Triforce"),
    ("model3", "Model 3"),
    ("model2", "Model 2"),
    ("model1", "Model 1"),
    ("stv", "ST-V"),
    ("naomi2", "NAOMI 2"),
    ("naomi", "NAOMI"),
    ("cave", "Cave"),
    ("pgm", "PolyGame Master"),
    ("zn2", "ZN-2"),
    ("zn1", "ZN-1"),
    ("zn", "ZN"),
    ("taito_", "Taito"),
    ("taito", "Taito"),
    ("konami", "Konami"),
    ("mid", "Midway"),
    ("irem", "Irem"),
    ("sega", "Sega"),
    ("atari", "Atari"),
    ("namco", "Namco"),
)


def pretty_arcade_system(sourcefile, romset=""):
    """cps1.cpp → CPS1. Empty when the driver is named after this single game."""
    if not sourcefile:
        return ""
    path = str(sourcefile).replace("\\", "/").strip()
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    rom = os.path.splitext(os.path.basename(str(romset).replace("\\", "/")))[0].lower()
    if rom and stem == rom:
        return ""
    mapped = load_mame_drivers().get(stem)
    if mapped:
        return mapped
    for prefix, label in _DRIVER_PREFIXES:
        if stem.startswith(prefix):
            return label
    pretty = stem.replace("_", " ").replace("-", " ").strip()
    return pretty.title() if pretty else ""


def adb_fetch_driver(romset):
    """Read « Driver source: capcom/cps1.cpp » from the ADB game page."""
    if not romset:
        return ""
    try:
        _throttle_api("adb")
        r = requests.get(
            "https://adb.arcadeitalia.net/dettaglio_mame.php",
            params={"game_name": romset},
            headers={"User-Agent": APP_UA},
            timeout=25,
        )
        r.raise_for_status()
        m = re.search(
            r"Driver source:.*?<span class=\"dettaglio\">\s*([^<]+?\.cpp)",
            r.text,
            re.I | re.S,
        )
        return (m.group(1).strip() if m else "")
    except Exception:
        return ""


def find_mame_listxml():
    """Look for a MAME -listxml dump near the gamelist or RetroBat tree."""
    candidates = []
    if BASE_DIR:
        candidates.extend([
            os.path.join(BASE_DIR, "mame.xml"),
            os.path.join(BASE_DIR, "mame", "mame.xml"),
            os.path.join(os.path.dirname(BASE_DIR), "mame.xml"),
        ])
        root = BASE_DIR
        for _ in range(5):
            parent = os.path.dirname(root)
            if parent == root:
                break
            root = parent
            candidates.extend([
                os.path.join(root, "mame.xml"),
                os.path.join(root, "bios", "mame", "mame.xml"),
                os.path.join(root, "emulators", "mame", "mame.xml"),
                os.path.join(root, "emulators", "mame", "hash", "mame.xml"),
            ])
    candidates.append(os.path.join(APP_DIR, "mame.xml"))
    seen = set()
    for p in candidates:
        if not p or p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p) and os.path.getsize(p) > 1000:
            return p
    return None


def index_mame_listxml(path):
    """romset name → sourcefile from MAME -listxml (machine or game tags)."""
    idx, clones = {}, {}
    for _event, elem in etree.iterparse(path, events=("end",), tag=("machine", "game")):
        name = (elem.get("name") or "").strip()
        src = (elem.get("sourcefile") or "").strip()
        cloneof = (elem.get("cloneof") or "").strip()
        if name:
            if src:
                idx[name.lower()] = src
            if cloneof:
                clones[name.lower()] = cloneof.lower()
        elem.clear()
    for name, parent in clones.items():
        if name not in idx and parent in idx:
            idx[name] = idx[parent]
    return idx



# --- ScreenScraper ------------------------------------------------------------
# Developer credentials are obfuscated (NOT secret): they identify *this app*
# on the SS API. End users may add their member login for a quota boost.
SS_API = "https://api.screenscraper.fr/api2"
SS_SOFTNAME = "GamelistMediaEditor"
APP_VERSION = "1.3.0"
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


# ES field → ScreenScraper type. No fallback to another artwork kind if missing.
SS_MEDIA_PREF = {
    "image": ["ss"],
    "video": ["video-normalized"],
    "marquee": ["wheel-hd"],
    "manual": ["manuel"],
    "boxback": ["box-2D-back"],
    "boxart": ["box-3D"],
    "cartridge": ["support-2D"],
    "fanart": ["fanart"],
    "mix": ["mixrbv2"],
    "map": ["maps"],
    "thumbnail": ["box-2D"],
    "bezel": ["bezel-16-9"],
}

# User-configurable type (Outils → ScreenScraper). Only that type is requested.
SS_MEDIA_CHOICES = {
    "image": ("ss", "sstitle"),
    "boxart": ("box-2D", "box-3D"),
    "mix": ("mixrbv1", "mixrbv2"),
}
SS_MEDIA_DEFAULTS = {
    "image": "ss",
    "boxart": "box-3D",
    "mix": "mixrbv2",
}


def ss_config_path():
    """Config lives next to the .exe / app.py (writable), not next to the XML."""
    return os.path.join(APP_DIR, SS_CONFIG_NAME)


def normalize_ss_media_types(raw):
    """Keep only allowed image/boxart/mix types; fill defaults for missing keys."""
    out = dict(SS_MEDIA_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for field, allowed in SS_MEDIA_CHOICES.items():
        val = str(raw.get(field) or "").strip()
        for opt in allowed:
            if val.lower() == opt.lower():
                out[field] = opt
                break
    return out


def ss_media_pref(cfg=None):
    """Exact SS type per field. Configurable fields use only the saved choice."""
    cfg = cfg or load_ss_config()
    chosen = cfg.get("media_types") or SS_MEDIA_DEFAULTS
    prefs = {k: list(v) for k, v in SS_MEDIA_PREF.items()}
    for field, first in chosen.items():
        if field not in prefs or not first:
            continue
        prefs[field] = [first]
    return prefs


def load_ss_config():
    """User boost credentials + region + media type prefs (local file)."""
    path = ss_config_path()
    defaults = {
        "ssid": "",
        "sspassword": "",
        "prefer_region": "fr",
        "media_types": dict(SS_MEDIA_DEFAULTS),
    }
    if not os.path.isfile(path):
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return defaults
        for k in ("ssid", "sspassword", "prefer_region"):
            if k in data and data[k] is not None:
                defaults[k] = str(data[k]).strip()
        defaults["media_types"] = normalize_ss_media_types(data.get("media_types"))
        return defaults
    except Exception:
        return defaults


def save_ss_config(data):
    """Persist user boost, region and media type prefs (never write built-in dev password)."""
    cfg = load_ss_config()
    for k in ("ssid", "prefer_region"):
        if k in data and data[k] is not None:
            cfg[k] = str(data[k]).strip()
    if data.get("sspassword"):
        cfg["sspassword"] = str(data["sspassword"])
    if data.get("clear_sspassword"):
        cfg["sspassword"] = ""
    if "media_types" in data:
        cfg["media_types"] = normalize_ss_media_types(data.get("media_types"))
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
        "media_types": normalize_ss_media_types(cfg.get("media_types")),
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
        # ScreenScraper matches the *inner* ROM CRC (No-Intro), not the outer ZIP CRC.
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
_STEAM_MIN_INTERVAL = 0.45
_ss_last_call = 0.0
_adb_last_call = 0.0
_steam_last_call = 0.0
_api_throttle_lock = threading.Lock()


def _throttle_api(service):
    """Serialize and space calls per service (one logical client)."""
    global _ss_last_call, _adb_last_call, _steam_last_call
    with _api_throttle_lock:
        now = time.time()
        if service == "ss":
            wait = _SS_MIN_INTERVAL - (now - _ss_last_call)
            if wait > 0:
                time.sleep(wait)
            _ss_last_call = time.time()
        elif service == "steam":
            wait = _STEAM_MIN_INTERVAL - (now - _steam_last_call)
            if wait > 0:
                time.sleep(wait)
            _steam_last_call = time.time()
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
    prefs_l = [t.strip().lower() for t in preferred_types]
    candidates = []
    for m in medias:
        if not isinstance(m, dict):
            continue
        mtype = (m.get("type") or "").strip().lower()
        url = m.get("url") or ""
        if not url:
            continue
        region = (m.get("region") or "").lower()
        try:
            type_rank = prefs_l.index(mtype)
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


def parse_ss_game(jeu, prefer_region="fr", media_pref=None):
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
    family = ""
    familles = jeu.get("familles") or jeu.get("famille") or []
    if isinstance(familles, dict):
        familles = [familles]
    if isinstance(familles, list) and familles:
        f0 = familles[0]
        if isinstance(f0, dict):
            family = _ss_pick_text(f0.get("noms") or f0.get("nom"), prefer_region)
        elif isinstance(f0, str):
            family = f0.strip()
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
    region = ""
    regions = jeu.get("regions") or jeu.get("region") or {}
    if isinstance(regions, dict):
        region = (regions.get("text") or "").strip().split(",")[0].strip().lower()
        if not region:
            inner = regions.get("region") or regions.get("regions") or []
            if isinstance(inner, list) and inner:
                r0 = inner[0]
                region = (r0.get("text") if isinstance(r0, dict) else str(r0)).strip().lower()
            elif isinstance(inner, dict):
                region = (inner.get("text") or "").strip().lower()
            elif isinstance(inner, str):
                region = inner.strip().lower()
    elif isinstance(regions, list) and regions:
        r0 = regions[0]
        region = (r0.get("text") if isinstance(r0, dict) else str(r0)).strip().lower()
    elif isinstance(regions, str):
        region = regions.split(",")[0].strip().lower()
    if "," in region:
        region = region.split(",")[0].strip()
    medias = jeu.get("medias") or []
    media_out = {}
    prefs_map = media_pref or ss_media_pref()
    for field, prefs in prefs_map.items():
        url, mtype = _ss_pick_media(medias, prefs, prefer_region)
        if url:
            media_out[field] = {"url": url, "type": mtype}
    p2k_url, p2k_type = _ss_pick_media(medias, P2K_TYPES, prefer_region)
    if p2k_url:
        media_out["pad2key"] = {"url": p2k_url, "type": p2k_type}
    return {
        "ss_id": str(jeu.get("id") or ""),
        "name": name,
        "desc": desc,
        "rating": rating,
        "releasedate": releasedate,
        "developer": developer,
        "publisher": publisher,
        "family": family,
        "genre": genre,
        "players": players,
        "lang": lang,
        "region": region,
        "arcadesystemname": "",
        "medias": media_out,
    }



# --- HTTP routes --------------------------------------------------------------
# JSON APIs return {ok:false, error, code?} on failure (see api_err).
# Mutating routes that need a loaded gamelist call require_gamelist() first.

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
        if not has_gamelist():
            return jsonify({
                "games": [],
                "system": None,
                "xml_path": None,
                "base_dir": None,
                "loaded": False,
            })
        return jsonify({
            "games": get_games(load_xml()),
            "system": get_system_info(),
            "xml_path": XML_PATH,
            "base_dir": BASE_DIR,
            "loaded": True,
        })
    except Exception as e:
        log.exception("api_games failed")
        return api_err(st("server.xml_read", detail=e), 500, code="xml_read")


@app.route("/api/session")
def api_session():
    """Current gamelist path + system badge info (no full game list)."""
    loaded = has_gamelist()
    return jsonify({
        "xml_path": XML_PATH if loaded else None,
        "base_dir": BASE_DIR if loaded else None,
        "system": get_system_info() if loaded else None,
        "version": APP_VERSION,
        "loaded": loaded,
        "frozen": bool(getattr(sys, "frozen", False)),
    })


@app.route("/api/browse")
def api_browse():
    """
    List folders + .xml files for the in-app file picker.
    Query: ?path=  (optional). Default = parent of current gamelist.xml.
    Local-only tool — directory listing is intentional.
    """
    raw = (request.args.get("path") or "").strip().strip('"').strip("'")
    if raw:
        target = os.path.abspath(raw)
    else:
        # Default: parent of current gamelist, else common RetroBat/ES folders, else home
        if has_gamelist():
            start = BASE_DIR if os.path.isdir(BASE_DIR) else os.path.dirname(XML_PATH)
            parent = os.path.dirname(start)
            target = parent if parent and os.path.isdir(parent) else start
        else:
            candidates = []
            home = os.path.expanduser("~")
            for p in (
                os.path.join(home, "RetroBat", "roms"),
                os.path.join(home, "emulationstation", "roms"),
                "C:\\RetroBat\\roms",
                "D:\\RetroBat\\roms",
                "E:\\RetroBat\\roms",
                home,
            ):
                if p and os.path.isdir(p):
                    candidates.append(p)
            target = candidates[0] if candidates else (home if os.path.isdir(home) else os.getcwd())

    if os.path.isfile(target):
        target = os.path.dirname(target)

    if not os.path.isdir(target):
        return api_err(st("server.browse_not_dir", path=target), 404, code="browse_not_dir")

    try:
        names = os.listdir(target)
    except OSError as e:
        return api_err(st("server.browse_denied", path=target, detail=e), 403, code="browse_denied")

    dirs = []
    xmls = []
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(target, name)
        try:
            if os.path.isdir(full):
                dirs.append({"name": name, "path": full})
            elif os.path.isfile(full) and name.lower().endswith(".xml"):
                xmls.append({
                    "name": name,
                    "path": full,
                    "is_gamelist": name.lower() == "gamelist.xml",
                })
        except OSError:
            continue

    dirs.sort(key=lambda d: d["name"].lower())
    xmls.sort(key=lambda f: (not f["is_gamelist"], f["name"].lower()))

    parent = os.path.dirname(target)
    # On Windows, dirname("C:\\") == "C:\\" — treat as no parent
    has_parent = bool(parent) and parent != target and os.path.isdir(parent)

    # Drive roots on Windows (C:\, D:\, …)
    drives = []
    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.isdir(root):
                drives.append({"name": f"{letter}:", "path": root})

    return jsonify({
        "path": target,
        "parent": parent if has_parent else None,
        "dirs": dirs,
        "files": xmls,
        "drives": drives,
    })


@app.route("/api/open-gamelist", methods=["POST"])
def api_open_gamelist():
    """
    Switch the editor to another gamelist.xml without restarting the server.
    Body: { "path": "C:\\RetroBat\\roms\\snes\\gamelist.xml" }
    Local-only tool (bound to 127.0.0.1) — absolute paths are intentional.
    """
    body = request.get_json(silent=True) or {}
    raw = body.get("path") or body.get("xml") or ""
    try:
        info = set_gamelist_path(raw)
        games = get_games(load_xml())
        return jsonify({
            "success": True,
            "xml_path": info["xml_path"],
            "base_dir": info["base_dir"],
            "system": info["system"],
            "games": games,
            "count": len(games),
        })
    except FileNotFoundError as e:
        return api_err(str(e), 404, code="open_not_found")
    except ValueError as e:
        return api_err(str(e), 400, code="open_invalid")
    except Exception as e:
        log.exception("open-gamelist failed")
        return api_err(st("server.open_failed", detail=e), 500, code="open_failed")


@app.route("/api/upload/<int:index>/<field>", methods=["POST"])
def upload(index, field):
    err = require_gamelist()
    if err:
        return err
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
            ext = os.path.splitext(file.filename)[1].lower()
            if ext == ".jpeg":
                ext = ".jpg"
            if ext not in _MEDIA_EXTS:
                head = file.stream.read(64)
                file.stream.seek(0)
                ext = ext_from_magic(head) or default_ext_for_field(field)
            new_filename = f"{base_name}-{field}{ext}"
            file.save(os.path.join(media_dir, new_filename))
            rel_path = f"./{media_dir_name}/{new_filename}"
        elif url:
            try:
                new_filename = download_remote_media(
                    url, media_dir, base_name, field, timeout=20
                )
                rel_path = f"./{media_dir_name}/{new_filename}"
            except ValueError as e:
                if str(e) == "url_not_allowed":
                    return api_err(st("server.url_not_allowed"), 400, code="url_not_allowed")
                if str(e) == "too_large":
                    return api_err(st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024)), 400, code="file_too_large")
                if str(e) == "green_placeholder":
                    return api_err(st("server.green_placeholder"), 400, code="green_placeholder")
                return api_err(st("server.download_failed", detail=e), 400, code="download_failed")
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
    err = require_gamelist()
    if err:
        return err
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
    err = require_gamelist()
    if err:
        return err
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
    err = require_gamelist()
    if err:
        return err
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
    err = require_gamelist()
    if err:
        return err
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
            if field in BOOL_META_FIELDS:
                value = "true" if value.lower() in ("true", "1", "yes", "on") else ""
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
    err = require_gamelist()
    if err:
        return err
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
    err = require_gamelist()
    if err:
        return err
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


@app.route("/api/fill-arcadesystem", methods=["POST"])
def fill_arcadesystem():
    """Fill <arcadesystemname> from a MAME -listxml dump (mame.xml)."""
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    xml_path = (body.get("xml_path") or "").strip() or find_mame_listxml()
    if not xml_path or not os.path.isfile(xml_path):
        return api_err(st("server.mame_xml_missing"), 404, code="mame_xml_missing")
    try:
        idx = index_mame_listxml(xml_path)
    except Exception as e:
        return api_err(st("server.mame_xml_bad", detail=e), 400, code="mame_xml_bad")
    if not idx:
        return api_err(st("server.mame_xml_empty"), 400, code="mame_xml_empty")

    do_backup = bool(body.get("backup", False))
    backup_path = backup_xml() if do_backup else None
    overwrite = bool(body.get("overwrite", False))
    tree = load_xml()
    filled, skipped, missing = 0, 0, 0
    for game in tree.getroot().findall("game"):
        existing = (game.findtext("arcadesystemname") or "").strip()
        if existing and not overwrite:
            skipped += 1
            continue
        path = game.findtext("path", "") or ""
        romset = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0].lower()
        src = idx.get(romset)
        name = pretty_arcade_system(src, romset) if src else ""
        if not name:
            missing += 1
            continue
        elem = game.find("arcadesystemname")
        if elem is None:
            elem = etree.SubElement(game, "arcadesystemname")
        elem.text = name
        filled += 1
    if filled:
        save_xml(tree)
    return jsonify({
        "success": True,
        "filled": filled,
        "skipped": skipped,
        "missing": missing,
        "source": xml_path,
        "machines": len(idx),
        "backup": backup_path,
    })


@app.route("/api/delete-game/<int:index>", methods=["POST"])
def delete_game(index):
    """Delete ROM + media files on disk + XML entry for the game."""
    err = require_gamelist()
    if err:
        return err
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
            "thumbnail", "fanart", "map", "boxfront", "boxart", "cartridge", "mix",
            "bezel",
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
        keys_path = pad2key_dest(game)
        if keys_path and os.path.isfile(keys_path):
            try:
                os.remove(keys_path)
                deleted_files.append(os.path.relpath(keys_path, BASE_DIR))
            except OSError:
                failed_files.append(keys_path)
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
        if "media_types" in body:
            payload["media_types"] = body.get("media_types") or {}
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
    err = require_gamelist()
    if err:
        return err
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
        parsed = parse_ss_game(jeu, prefer, ss_media_pref(cfg))
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
    err = require_gamelist()
    if err:
        return err
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
        "players": "players", "lang": "lang", "region": "region",
        "family": "family", "kidgame": "kidgame",
        "arcadesystemname": "arcadesystemname",
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
                        errors.append(st("server.rating_range_value", value=value))
                        continue
                except ValueError:
                    errors.append(st("server.rating_invalid_value", value=value))
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

    # Media fields — download. Thumbnail is always applied when SS has box-2D.
    medias = proposed.get("medias") or {}
    base_name = get_base_name(game)
    media_fields = [f for f in fields if f in MEDIA_DIRS]
    if "thumbnail" not in media_fields:
        media_fields.append("thumbnail")
    if "bezel" not in media_fields:
        media_fields.append("bezel")
    for field in media_fields:
        info = medias.get(field) or {}
        url = (info.get("url") or "").strip()
        if not url:
            if field in ("thumbnail", "bezel"):
                continue
            errors.append(f"{field}: {st('server.no_ss_url')}")
            continue
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        try:
            new_filename = download_remote_media(
                url, media_dir, base_name, field, timeout=40
            )
            rel_path = f"./{media_dir_name}/{new_filename}"
            old_rel = game.findtext(field, "") or ""
            if old_rel and resolve_under_base(old_rel) != resolve_under_base(rel_path):
                safe_delete_file(old_rel)
            elem = game.find(field)
            if elem is None:
                elem = etree.SubElement(game, field)
            elem.text = rel_path
            applied.append(field)
        except ValueError as e:
            if str(e) == "too_large":
                errors.append(f"{field}: {st('server.file_too_large', n=MAX_DOWNLOAD_BYTES // (1024*1024))}")
            elif str(e) == "url_not_allowed":
                errors.append(f"{field}: {st('server.url_not_http')}")
            elif str(e) == "green_placeholder":
                continue
            else:
                errors.append(f"{field}: {e}")
        except Exception as e:
            errors.append(f"{field}: {e}")

    p2k = (medias.get("pad2key") or {})
    p2k_url = (p2k.get("url") or "").strip()
    if p2k_url:
        try:
            dest = pad2key_dest(game)
            download_pad2key(p2k_url, dest)
            applied.append("pad2key")
        except Exception as e:
            errors.append(f"pad2key: {e}")

    if applied:
        save_xml(tree)

    return jsonify({
        "success": True,
        "applied": applied,
        "errors": errors,
    })




# --- Arcade Database (Arcade Italia) ------------------------------------------
# Best suited to MAME / FBNeo romset names. Same proposed/apply shape as SS.
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


def arcade_system_from_adb(item):
    """Map ADB romset → driver file → short board name (CPS1, Neo-Geo…)."""
    if not isinstance(item, dict):
        return ""
    romset = (item.get("game_name") or "").strip()
    src = (item.get("sourcefile") or item.get("source_file") or item.get("driver") or "").strip()
    if not src:
        src = adb_fetch_driver(romset)
    name = pretty_arcade_system(src, romset)
    if name:
        return name
    for key in ("hardware", "system"):
        val = (item.get(key) or "").strip()
        if val:
            return val
    return ""


def enrich_adb_item_media(item):
    """Merge QUERY_MAME_MEDIA URLs (pcb, decal, cabinet, flyer, …) into the item."""
    if not item or not isinstance(item, dict):
        return item
    gname = (item.get("game_name") or "").strip()
    if not gname:
        return item
    ok, data, _ = adb_request("query_mame_media", {"game_name": gname})
    if not ok or not isinstance(data, dict):
        return item
    results = data.get("result") or []
    if not results or not isinstance(results[0], dict):
        return item
    for k, v in results[0].items():
        if isinstance(k, str) and k.startswith("url_") and v:
            item[k] = v
    return item


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
    # Arcade mapping (MAME / FBNeo / NeoGeo / Atomiswave / …):
    # PCB → Support (cartridge), CABINET → Boxart, FLYER → Boxback, DECAL → Marquee
    u, t = pick_url("url_image_decal")
    if u:
        medias["marquee"] = {"url": u, "type": t}
    u, t = pick_url("url_manual")
    if u:
        medias["manual"] = {"url": u, "type": t}
    u, t = pick_url("url_image_cabinet")
    if u:
        medias["boxart"] = {"url": u, "type": t}
    u, t = pick_url("url_image_flyer")
    if u:
        medias["boxback"] = {"url": u, "type": t}
    u, t = pick_url("url_image_pcb")
    if u:
        medias["cartridge"] = {"url": u, "type": t}

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
        "family": (item.get("serie") or "").strip(),
        "arcadesystemname": arcade_system_from_adb(item),
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
    err = require_gamelist()
    if err:
        return err
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
        item = enrich_adb_item_media(item)
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
                parsed = parse_adb_game(enrich_adb_item_media(full[0]))
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
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    fields = list(body.get("fields") or [])
    proposed = body.get("proposed") or {}
    if (proposed.get("arcadesystemname") or "").strip() and "arcadesystemname" not in fields:
        fields.append("arcadesystemname")
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
        "players": "players", "lang": "lang", "region": "region",
        "family": "family", "kidgame": "kidgame",
        "arcadesystemname": "arcadesystemname",
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
                    errors.append(st("server.rating_range_value", value=value))
                    continue
            except ValueError:
                errors.append(st("server.rating_invalid_value", value=value))
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
            errors.append(f"{field}: {st('server.no_adb_url')}")
            continue
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        try:
            new_filename = download_remote_media(
                url, media_dir, base_name, field,
                headers={"User-Agent": ADB_UA},
                timeout=40,
            )
            rel_path = f"./{media_dir_name}/{new_filename}"
            old_rel = game.findtext(field, "") or ""
            if old_rel and resolve_under_base(old_rel) != resolve_under_base(rel_path):
                safe_delete_file(old_rel)
            elem = game.find(field)
            if elem is None:
                elem = etree.SubElement(game, field)
            elem.text = rel_path
            applied.append(field)
        except ValueError as e:
            if str(e) == "too_large":
                errors.append(f"{field}: {st('server.file_too_large', n=MAX_DOWNLOAD_BYTES // (1024*1024))}")
            elif str(e) == "url_not_allowed":
                errors.append(f"{field}: {st('server.url_not_http')}")
            elif str(e) == "green_placeholder":
                continue
            else:
                errors.append(f"{field}: {e}")
        except Exception as e:
            errors.append(f"{field}: {e}")

    if applied:
        save_xml(tree)

    return jsonify({"success": True, "applied": applied, "errors": errors, "source": "arcadeitalia"})




# --- Steam store trailers -----------------------------------------------------
# Unofficial store API + legacy progressive MP4 on the Steam CDN.
# movie_max.mp4 ≈ best quality (often 1080p); movie480.mp4 = 480p fallback.
STEAM_APPDETAILS = "https://store.steampowered.com/api/appdetails"
STEAM_STORESEARCH = "https://store.steampowered.com/api/storesearch/"
STEAM_SEARCHAPPS = "https://steamcommunity.com/actions/SearchApps/"
STEAM_UA = f"{APP_UA} (Steam trailer; +https://github.com/Kraran/gamelist-media-editor)"
STEAM_CDN_MP4 = "https://cdn.akamai.steamstatic.com/steam/apps/{mid}/{name}"


def _steam_https(url):
    url = (url or "").strip()
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


def _steam_headers():
    return {"User-Agent": STEAM_UA, "Accept": "application/json"}


def parse_steam_appid(text):
    """Extract a Steam AppID from an URL, path, or bare number."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    m = re.search(r"(?:store\.steampowered\.com/app/|/app/)(\d{1,10})", s, re.I)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{1,10}", s):
        return s
    return None


def steam_probe(url, timeout=12):
    """HEAD a Steam CDN URL.

    Returns (exists, size_or_none).
    exists is False on 404/410/empty HTML error pages — never treat that as 'unknown size'.
    """
    url = _steam_https(url)
    if not url:
        return False, None
    try:
        r = requests.head(
            url,
            headers={"User-Agent": STEAM_UA},
            timeout=timeout,
            allow_redirects=True,
        )
        if r.status_code in (404, 410, 403):
            return False, None
        if r.status_code >= 400:
            return False, None
        ct = (r.headers.get("Content-Type") or "").lower()
        if "text/html" in ct:
            return False, None
        cl = r.headers.get("Content-Length")
        size = int(cl) if cl and str(cl).isdigit() else None
        if size is not None and size < 4096:
            return False, None
        return True, size
    except requests.RequestException:
        return False, None


def steam_cdn_mp4(movie_id, quality):
    name = "movie_max.mp4" if quality == "max" else "movie480.mp4"
    return STEAM_CDN_MP4.format(mid=movie_id, name=name)


def steam_pick_video(movie):
    """
    Choose a progressive MP4 for one Steam movie.
    Prefer max if it exists and size <= 50 MB, else 480p.
    Returns dict or None when this movie has no downloadable MP4.
    """
    if not isinstance(movie, dict):
        return None
    mid = movie.get("id")
    if mid in (None, ""):
        return None
    mp4 = movie.get("mp4") or {}
    if not isinstance(mp4, dict):
        mp4 = {}
    url_max = _steam_https(mp4.get("max") or "") or steam_cdn_mp4(mid, "max")
    url_480 = _steam_https(mp4.get("480") or "") or steam_cdn_mp4(mid, "480")

    exists_max, size_max = steam_probe(url_max)
    exists_480, size_480 = steam_probe(url_480)

    def usable(exists, size):
        if not exists:
            return False
        if size is None:
            return True
        return 0 < size <= MAX_DOWNLOAD_BYTES

    chosen = quality = size = None
    fallback = fallback_size = None

    if usable(exists_max, size_max):
        chosen, quality, size = url_max, "max", size_max
    elif usable(exists_480, size_480):
        chosen, quality, size = url_480, "480", size_480

    if chosen and quality == "max" and exists_480 and url_480 != chosen:
        fallback, fallback_size = url_480, size_480

    if not chosen:
        return None
    return {
        "url": chosen,
        "fallback_url": fallback or "",
        "type": f"steam-mp4-{quality}",
        "quality": quality,
        "bytes": size,
        "fallback_bytes": fallback_size,
        "movie_id": str(mid),
        "trailer": (movie.get("name") or "").strip(),
        "highlight": bool(movie.get("highlight")),
    }


_STEAM_FR_NAME = re.compile(
    r"(?:^|[\s\-_\(\[/])(fr|fra|french|fran[cç]ais|vf|vff|vofr|france)(?:$|[\s\-_\.\)\]])",
    re.I,
)


def steam_movie_is_french(name):
    """True when the trailer title looks localized in French."""
    return bool(_STEAM_FR_NAME.search(name or ""))


def steam_request_appdetails(appid, lang="french", cc="FR", timeout=25):
    """Return (ok, data_or_error, status). data is the inner app payload."""
    _throttle_api("steam")
    try:
        r = requests.get(
            STEAM_APPDETAILS,
            params={"appids": str(appid), "l": lang, "cc": cc},
            headers=_steam_headers(),
            timeout=timeout,
        )
        if r.status_code != 200:
            return False, st("server.steam_http", status=r.status_code), r.status_code
        payload = r.json()
        block = payload.get(str(appid)) or payload.get(appid)
        if not isinstance(block, dict) or not block.get("success"):
            return False, st("server.steam_app_missing", id=appid), 404
        data = block.get("data") or {}
        if not isinstance(data, dict):
            return False, st("server.steam_app_missing", id=appid), 404
        return True, data, r.status_code
    except requests.Timeout:
        return False, st("server.steam_timeout"), 504
    except Exception as e:
        return False, st("server.steam_error", detail=e), 502


def steam_search(term, timeout=20):
    """Return list of {ss_id, name, score, system} candidates."""
    term = (term or "").strip()
    if not term:
        return []
    found = []
    _throttle_api("steam")
    try:
        r = requests.get(
            STEAM_STORESEARCH,
            params={"term": term, "l": "french", "cc": "FR"},
            headers=_steam_headers(),
            timeout=timeout,
        )
        if r.status_code == 200:
            items = (r.json() or {}).get("items") or []
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    aid = it.get("id")
                    name = (it.get("name") or "").strip()
                    if not aid or not name:
                        continue
                    found.append({
                        "ss_id": str(aid),
                        "name": name,
                        "names": [name],
                        "system": "Steam",
                        "score": round(name_similarity(term, name), 3),
                        "appid": str(aid),
                    })
    except Exception:
        pass
    if found:
        return found
    # Fallback community search
    _throttle_api("steam")
    try:
        from urllib.parse import quote
        r = requests.get(
            STEAM_SEARCHAPPS + quote(term),
            headers=_steam_headers(),
            timeout=timeout,
        )
        if r.status_code == 200:
            items = r.json() or []
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    aid = it.get("appid") or it.get("id")
                    name = (it.get("name") or "").strip()
                    if not aid or not name:
                        continue
                    found.append({
                        "ss_id": str(aid),
                        "name": name,
                        "names": [name],
                        "system": "Steam",
                        "score": round(name_similarity(term, name), 3),
                        "appid": str(aid),
                    })
    except Exception:
        pass
    return found


def parse_steam_game(data, video_info):
    """Map Steam appdetails + chosen trailer → SS-shaped proposed dict."""
    name = (data.get("name") or "").strip()
    desc = (data.get("short_description") or data.get("about_the_game") or "").strip()
    # strip simple HTML from about_the_game if used
    if desc and "<" in desc:
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
    developers = data.get("developers") or []
    publishers = data.get("publishers") or []
    developer = ", ".join(developers) if isinstance(developers, list) else str(developers or "")
    publisher = ", ".join(publishers) if isinstance(publishers, list) else str(publishers or "")
    releasedate = ""
    rd = data.get("release_date") or {}
    date_txt = (rd.get("date") or "") if isinstance(rd, dict) else ""
    digits = "".join(c for c in date_txt if c.isdigit())
    if len(digits) >= 8:
        releasedate = digits[:8] + "T000000"
    elif len(digits) == 4:
        releasedate = digits + "0101T000000"
    genre = ""
    genres = data.get("genres") or []
    if isinstance(genres, list) and genres:
        g0 = genres[0]
        if isinstance(g0, dict):
            genre = (g0.get("description") or "").strip().upper()
    medias = {}
    if video_info and video_info.get("url"):
        medias["video"] = {
            "url": video_info["url"],
            "fallback_url": video_info.get("fallback_url") or "",
            "type": video_info.get("type") or "steam-mp4",
            "quality": video_info.get("quality") or "",
            "bytes": video_info.get("bytes"),
            "trailer": video_info.get("trailer") or "",
        }
    return {
        "ss_id": str(data.get("steam_appid") or ""),
        "steam_appid": str(data.get("steam_appid") or ""),
        "name": name,
        "desc": desc,
        "rating": "",
        "releasedate": releasedate,
        "developer": developer,
        "publisher": publisher,
        "genre": genre,
        "players": "",
        "lang": "fr",
        "medias": medias,
        "source": "steam",
        "trailer": (video_info or {}).get("trailer") or "",
        "video_quality": (video_info or {}).get("quality") or "",
        "video_bytes": (video_info or {}).get("bytes"),
    }


def steam_choose_movie(movies):
    """Prefer a French-titled trailer when one exists, else the newest."""
    if not isinstance(movies, list):
        return None, None
    usable = []
    for movie in movies:
        if not isinstance(movie, dict) or movie.get("id") is None:
            continue
        info = steam_pick_video(movie)
        if info:
            usable.append((movie, info))
    if not usable:
        return None, None
    french = [pair for pair in usable if steam_movie_is_french(pair[0].get("name"))]
    pool = french or usable
    pool.sort(key=lambda pair: int(pair[0].get("id") or 0), reverse=True)
    return pool[0]


def steam_load_app(appid):
    """French store page first; fall back to English movies if FR has none."""
    ok_fr, data_fr, status_fr = steam_request_appdetails(appid, lang="french", cc="FR")
    if not ok_fr:
        return steam_request_appdetails(appid, lang="english", cc="US")
    movies = data_fr.get("movies") or []
    if not movies:
        ok_en, data_en, _ = steam_request_appdetails(appid, lang="english", cc="US")
        if ok_en and isinstance(data_en, dict):
            data_fr["movies"] = data_en.get("movies") or []
    return True, data_fr, status_fr


@app.route("/api/steam/scrape/<int:index>", methods=["POST"])
def api_steam_scrape(index):
    """
    Look up a Steam store trailer for the current game.
    Body optional: { "appid": "400" } or { "gameid": "400" } after a candidate pick.
    French store text when available. Newest French trailer if named as such,
    else newest trailer. movie_max.mp4 if <= 50 MB else movie480.mp4.
    """
    err = require_gamelist()
    if err:
        return err
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")

    body = request.get_json(silent=True) or {}
    force_id = str(body.get("appid") or body.get("gameid") or "").strip()
    path_rel = game.findtext("path", "") or ""
    rom_name = os.path.basename(path_rel) if path_rel else ""
    local_name = game.findtext("name", "") or os.path.splitext(rom_name)[0]
    _, system_folder = detect_system_id()

    appid = parse_steam_appid(force_id) or parse_steam_appid(local_name) or parse_steam_appid(path_rel)

    def current_map():
        return adb_current_from_game(game)

    def finish(data, method):
        movies = data.get("movies") or []
        movie, video_info = steam_choose_movie(movies)
        if not video_info:
            return api_err(
                st("server.steam_no_movies", name=data.get("name") or appid or "?"),
                404,
                code="steam_no_movies",
            )
        parsed = parse_steam_game(data, video_info)
        return jsonify({
            "success": True,
            "match_method": method,
            "source": "steam",
            "system_folder": system_folder,
            "rom_name": rom_name,
            "local_name": local_name,
            "proposed": parsed,
            "current": current_map(),
            "steam_appid": parsed.get("steam_appid"),
            "trailer": video_info.get("trailer"),
            "video_quality": video_info.get("quality"),
            "video_bytes": video_info.get("bytes"),
        })

    if appid:
        ok, data, _ = steam_load_app(appid)
        if not ok:
            return api_err(str(data), 404, code="steam_app_missing")
        return finish(data, "appid")

    search_name = clean_game_name(local_name) or clean_game_name(rom_name) or local_name
    candidates = steam_search(search_name)
    if not candidates:
        return api_err(
            st("server.steam_not_found", name=local_name or rom_name or "?"),
            404,
            code="steam_not_found",
        )

    by_id = {}
    for c in candidates:
        sid = c.get("ss_id")
        if not sid:
            continue
        if sid not in by_id or c.get("score", 0) > by_id[sid].get("score", 0):
            by_id[sid] = c
    candidates = sorted(by_id.values(), key=lambda c: c.get("score", 0), reverse=True)

    if len(candidates) == 1 and candidates[0].get("score", 0) >= 0.85:
        ok, data, _ = steam_load_app(candidates[0]["ss_id"])
        if ok:
            return finish(data, "name-unique")

    if candidates[0].get("score", 0) >= 0.95 and (
        len(candidates) == 1 or candidates[0]["score"] > candidates[1].get("score", 0) + 0.15
    ):
        ok, data, _ = steam_load_app(candidates[0]["ss_id"])
        if ok:
            return finish(data, "name-unique")

    return jsonify({
        "success": True,
        "need_choice": True,
        "match_method": "search",
        "source": "steam",
        "system_folder": system_folder,
        "rom_name": rom_name,
        "local_name": local_name,
        "search": search_name,
        "candidates": candidates[:15],
        "message": st("server.steam_candidates"),
    })


@app.route("/api/steam/apply/<int:index>", methods=["POST"])
def api_steam_apply(index):
    """Apply selected Steam fields. Video: max then 480p fallback if over 50 MB."""
    err = require_gamelist()
    if err:
        return err
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
        "players": "players", "lang": "lang", "region": "region",
        "family": "family", "kidgame": "kidgame",
        "arcadesystemname": "arcadesystemname",
    }

    for field in fields:
        if field not in meta_map:
            continue
        value = (proposed.get(field) or "").strip()
        if field == "name" and not value:
            errors.append(st("server.name_empty_ignored"))
            continue
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

    def download_url(url, dest):
        r = requests.get(
            _steam_https(url),
            headers={"User-Agent": STEAM_UA},
            timeout=60,
            stream=True,
        )
        r.raise_for_status()
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
                    raise ValueError("too_large")
                f.write(chunk)
        return written

    for field in fields:
        if field not in MEDIA_DIRS:
            continue
        info = medias.get(field) or {}
        urls = []
        if info.get("url"):
            urls.append(info["url"])
        if info.get("fallback_url") and info["fallback_url"] not in urls:
            urls.append(info["fallback_url"])
        if not urls:
            errors.append(f"{field}: {st('server.no_steam_url')}")
            continue
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        dest = os.path.join(media_dir, f"{base_name}-{field}.mp4")
        last_err = None
        saved = False
        for url in urls:
            parsed = urlparse(_steam_https(url))
            if parsed.scheme not in ("http", "https"):
                last_err = "URL non http(s)"
                continue
            try:
                download_url(url, dest)
                saved = True
                break
            except ValueError:
                last_err = st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024 * 1024))
                continue
            except Exception as e:
                last_err = str(e)
                continue
        if not saved:
            errors.append(f"{field}: {last_err or st('server.steam_too_large')}")
            continue
        rel_path = f"./{media_dir_name}/{base_name}-{field}.mp4"
        old_rel = game.findtext(field, "") or ""
        if old_rel and resolve_under_base(old_rel) != resolve_under_base(rel_path):
            safe_delete_file(old_rel)
        elem = game.find(field)
        if elem is None:
            elem = etree.SubElement(game, field)
        elem.text = rel_path
        applied.append(field)

    if applied:
        save_xml(tree)
    return jsonify({"success": True, "applied": applied, "errors": errors, "source": "steam"})


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
        _close_ui_window()
        os._exit(0)

    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"success": True, "message": st("server.shutdown")})


# Chromium "app mode" window (no tabs / address bar). Process is watched so
# closing the window also stops the local server.
_UI_PROC = None


def _chromium_candidates():
    """Known Edge / Chrome / Brave install paths (Windows + a few extras)."""
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    pfx86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    local = os.environ.get("LOCALAPPDATA") or ""
    return [
        os.path.join(pfx86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(local, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(local, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
    ]


def _is_chromium_exe(path):
    name = os.path.basename(path or "").lower()
    return name in {
        "msedge.exe", "chrome.exe", "brave.exe", "chromium.exe",
        "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
    }


def _windows_http_progid():
    """User's default HTTP handler ProgId (ChromeHTML, MSEdgeHTM, FirefoxURL…)."""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            progid, _ = winreg.QueryValueEx(key, "ProgId")
        return (progid or "").strip()
    except Exception:
        return ""


def _exe_from_progid(progid):
    """Resolve a Windows ProgId to its .exe path."""
    if not progid or os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command") as key:
            cmd, _ = winreg.QueryValueEx(key, None)
        cmd = (cmd or "").strip()
        if cmd.startswith('"'):
            end = cmd.find('"', 1)
            if end > 1:
                return cmd[1:end]
        return cmd.split()[0] if cmd else None
    except Exception:
        return None


def _find_app_mode_browser():
    """
    Prefer the *default* browser when it is Chromium-based (supports --app=).
    Otherwise use Edge / Chrome / Brave if installed.
    Returns exe path or None.
    """
    progid = _windows_http_progid().lower()
    default_exe = _exe_from_progid(_windows_http_progid())
    if default_exe and os.path.isfile(default_exe) and _is_chromium_exe(default_exe):
        return default_exe
    # ProgId hint even if command path is odd
    if "chrome" in progid or "edge" in progid or "brave" in progid:
        for path in _chromium_candidates():
            if not path or not os.path.isfile(path):
                continue
            base = os.path.basename(path).lower()
            if "chrome" in progid and "chrome" in base:
                return path
            if "edge" in progid and "msedge" in base:
                return path
            if "brave" in progid and "brave" in base:
                return path
    for path in _chromium_candidates():
        if path and os.path.isfile(path):
            return path
    return None


def _close_ui_window():
    """Terminate the dedicated app-mode window if we started it."""
    global _UI_PROC
    proc = _UI_PROC
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
    except Exception:
        pass
    _UI_PROC = None


def _watch_ui_process():
    """If the user closes the app window, stop the local server too."""
    time.sleep(3)
    proc = _UI_PROC
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.wait()
    except Exception:
        return
    os._exit(0)


def _open_browser(url):
    """
    Open a dedicated Chromium app window (no tabs / address bar) when possible.
    Fallback: system default browser (with normal chrome).
    """
    global _UI_PROC
    exe = _find_app_mode_browser()
    if exe:
        profile = os.path.join(APP_DIR, "app-window")
        try:
            os.makedirs(profile, exist_ok=True)
        except OSError:
            profile = None
        cmd = [
            exe,
            f"--app={url}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--window-size=1280,840",
        ]
        if profile:
            cmd.append(f"--user-data-dir={profile}")
        try:
            _UI_PROC = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            threading.Thread(target=_watch_ui_process, daemon=True).start()
            log.info("App window: %s", exe)
            return
        except Exception as e:
            log.warning("App window failed (%s), fallback browser", e)
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def main():
    """Entry point for source runs and the frozen Windows .exe."""
    global XML_PATH, BASE_DIR
    if getattr(sys, "frozen", False):
        try:
            import multiprocessing
            multiprocessing.freeze_support()
        except Exception:
            pass

    print("=" * 60)
    print(f"  Gamelist Media Editor v{APP_VERSION}")
    print("=" * 60)
    print()

    # Optional CLI path still supported (drag-drop onto .exe / Lancer.bat)
    xml_arg = None
    if len(sys.argv) > 1:
        xml_arg = sys.argv[1].strip().strip('"').strip("'")
    if xml_arg:
        try:
            info = set_gamelist_path(xml_arg)
            print(f"  XML            : {info['xml_path']}")
            print(f"  Dossier medias : {info['base_dir']}")
        except Exception as e:
            print(f"  [WARN] Impossible d'ouvrir le gamelist fourni : {e}")
            print("  Demarre sans gamelist — utilise le menu « Gamelist… ».")
            XML_PATH = None
            BASE_DIR = APP_DIR
            _xml_cache["mtime"] = None
            _xml_cache["tree"] = None
    else:
        print("  Aucun gamelist charge.")
        print("  Ouvre un fichier via le bouton « Gamelist… » dans l'interface.")

    url = "http://127.0.0.1:5050"
    print()
    print(f"  Interface : {url}")
    print("  Fenetre application (sans barre d'adresse) si Edge/Chrome/Brave est dispo")
    print("  (Fermer la fenetre, Ctrl+C ou bouton Quitter pour arreter)")
    print("=" * 60)

    # Open the browser shortly after the server starts (exe-friendly)
    threading.Timer(0.9, lambda: _open_browser(url)).start()

    # use_reloader=False required for PyInstaller / single process
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
