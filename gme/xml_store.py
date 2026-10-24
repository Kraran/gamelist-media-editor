"""The open gamelist.xml: path, cached parse tree, serialized writes, game lookup.

XML_PATH and BASE_DIR change when another gamelist is opened: other modules
must read them as ``xml_store.XML_PATH`` / ``xml_store.BASE_DIR``, never import
the names (they would keep a stale copy)."""

import os
import re
import shutil
import threading

from lxml import etree

from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st
from gme.paths import APP_DIR


# Root of the current gamelist + media folders (set via /api/open-gamelist or CLI)
BASE_DIR = APP_DIR

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
    return {"xml_path": XML_PATH, "base_dir": BASE_DIR}


def close_gamelist():
    """Forget the current gamelist (media root back to the app folder)."""
    global XML_PATH, BASE_DIR
    XML_PATH = None
    BASE_DIR = APP_DIR
    _xml_cache["mtime"] = None
    _xml_cache["tree"] = None


def has_gamelist():
    """True when a valid gamelist.xml path is loaded."""
    return bool(XML_PATH) and os.path.isfile(XML_PATH)


def require_gamelist():
    """Return an error response if no gamelist is loaded, else None."""
    if not has_gamelist():
        return api_err(st("server.no_gamelist"), 400, code="no_gamelist")
    return None


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
    """Write XML to disk (atomically: never empty or half-written) and refresh cache."""
    with _xml_io_lock:
        atomic_write(XML_PATH, etree.tostring(tree, pretty_print=True, xml_declaration=True, encoding="UTF-8"))
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


# --- Game identity guard ------------------------------------------------------
# Routes address a game by its position in gamelist.xml (<int:index>). If the
# XML changes between the moment the UI loaded the list and the action (edit
# outside the app, another tab, a scrape modal left open…), that position can
# point at ANOTHER game — fatal for /api/delete-game. The UI therefore sends
# the game's <path> as ?path=…; before the view runs we check it against the
# game at that index and, if it moved, re-point the request at the game that
# owns this path. No unique match → 409 so the UI reloads its list.
# Requests without ?path= (scripts, older UI) keep the plain index behaviour.

def find_game_index_by_path(path):
    """XML indexes of the games whose <path> equals ``path``."""
    games = load_xml().getroot().findall("game")
    return [i for i, game in enumerate(games) if (game.findtext("path", "") or "") == path]


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


# Fields sent with the game list. The description is not: it is the bulk of a
# large gamelist (30 000 MAME games) and is fetched when a game is opened.
LIST_FIELDS = frozenset((
    "path", "name",
    "image", "video", "marquee", "manual", "boxback", "cartridge", "boxart",
    "fanart", "mix", "map",
    "rating", "releasedate", "developer", "publisher", "family", "players",
    "lang", "region", "genre", "kidgame", "hidden", "favorite", "arcadesystemname",
))


def game_fields(game, index, fields=LIST_FIELDS):
    """One pass over a <game>'s children. Empty fields are omitted.

    Same values as ``findtext`` (first occurrence of a tag wins), about 20x
    faster than one ``findtext`` per field on large gamelists.
    """
    out = {"index": index, "path": "", "name": ""}
    seen = set()
    for child in game:
        tag = child.tag
        if not isinstance(tag, str) or tag not in fields or tag in seen:
            continue                      # comments, unknown tags, duplicates
        seen.add(tag)
        if child.text:
            out[tag] = child.text
    if not out["name"]:
        out["name"] = os.path.basename(out["path"]) if out["path"] else f"Jeu {index}"
    return out


def get_games(tree):
    """Sorted game list for the UI (no description). Each item keeps its XML index."""
    games = [game_fields(g, i) for i, g in enumerate(tree.getroot().iterchildren("game"))]
    games.sort(key=lambda g: g["name"].lower())
    return games
