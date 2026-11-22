"""New gamelist from a ROM folder (Gamelist… › Create a gamelist here).

POST /api/new-gamelist/preview  {"folder": "…", "exts": "zip, 7z" | null, "strip_tags": false}
POST /api/new-gamelist          same body: writes <folder>/gamelist.xml and opens it

The folder is scanned like Actions › Check ROMs does (media folders skipped,
disc tracks belong to their .cue/.gdi/.m3u, a romset's CHD folder is not a
game), with the extensions usual for the system the folder name gives, or the
ones the user typed. Each ROM gets a ``<game>`` with ``<path>`` and ``<name>``
(the file name without extension, optionally without its (…) / […] tags).

An existing gamelist.xml is never replaced: the interface opens it and runs
Check ROMs, which adds the missing ROMs after a preview and a backup. ROM files
are only listed, never opened (except .cue/.gdi/.m3u), moved or renamed.
"""

import os
import re

from flask import Blueprint, jsonify, request
from lxml import etree

from gme import recent, xml_store
from gme.bulk import clean_name
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.romcheck import ROM_EXTS, find_roms
from gme.systems import detect_system_id, get_system_info
from gme.xml_store import get_games, load_xml, set_gamelist_path

bp = Blueprint("newgamelist", __name__)

PREVIEW_ROWS = 1000
_ARCADE = ("zip", "7z")
_CD = ("cue", "chd", "iso", "m3u")
# Usual ROM extensions per system folder (RetroBat / Batocera es_systems). A
# folder not listed here gets every extension Check ROMs knows.
SYSTEM_EXTS = {
    "nes": ("nes", "unf", "unif", "fds", "zip", "7z"),
    "famicom": ("nes", "unf", "unif", "fds", "zip", "7z"),
    "fds": ("fds", "nes", "zip", "7z"),
    "snes": ("sfc", "smc", "fig", "swc", "bs", "st", "zip", "7z"),
    "sfc": ("sfc", "smc", "fig", "swc", "bs", "st", "zip", "7z"),
    "n64": ("n64", "z64", "v64", "ndd", "zip", "7z"),
    "gb": ("gb", "sgb", "zip", "7z"),
    "gbc": ("gbc", "gb", "zip", "7z"),
    "gba": ("gba", "zip", "7z"),
    "nds": ("nds", "dsi", "zip", "7z"),
    "virtualboy": ("vb", "vboy", "zip", "7z"),
    "pokemini": ("min", "zip", "7z"),
    "megadrive": ("md", "gen", "smd", "bin", "zip", "7z"),
    "genesis": ("md", "gen", "smd", "bin", "zip", "7z"),
    "mastersystem": ("sms", "bin", "zip", "7z"),
    "gamegear": ("gg", "zip", "7z"),
    "sg1000": ("sg", "sc", "zip", "7z"),
    "sega32x": ("32x", "bin", "zip", "7z"),
    "segacd": _CD + ("bin",),
    "megacd": _CD + ("bin",),
    "saturn": _CD + ("ccd", "mds"),
    "dreamcast": ("gdi", "cdi", "chd", "m3u"),
    "psx": _CD + ("pbp", "img", "bin"),
    "ps2": ("iso", "chd", "cso", "bin", "m3u"),
    "psp": ("iso", "cso", "pbp", "chd"),
    "gamecube": ("iso", "rvz", "gcm", "gcz", "ciso", "nkit"),
    "wii": ("iso", "rvz", "wbfs", "wia", "ciso"),
    "pcengine": ("pce", "zip", "7z"),
    "pcenginecd": _CD + ("ccd",),
    "supergrafx": ("sgx", "pce", "zip", "7z"),
    "atari2600": ("a26", "bin", "zip", "7z"),
    "atari5200": ("a52", "bin", "zip", "7z"),
    "atari7800": ("a78", "bin", "zip", "7z"),
    "atarilynx": ("lnx", "zip", "7z"),
    "lynx": ("lnx", "zip", "7z"),
    "jaguar": ("j64", "jag", "zip", "7z"),
    "colecovision": ("col", "cv", "bin", "rom", "zip", "7z"),
    "intellivision": ("int", "bin", "rom", "zip", "7z"),
    "vectrex": ("vec", "bin", "zip", "7z"),
    "odyssey2": ("o2", "bin", "zip", "7z"),
    "vc4000": ("bin", "rom", "zip", "7z"),
    "channelf": ("chf", "bin", "zip", "7z"),
    "wonderswan": ("ws", "zip", "7z"),
    "wonderswancolor": ("wsc", "ws", "zip", "7z"),
    "wswan": ("ws", "zip", "7z"),
    "wswanc": ("wsc", "ws", "zip", "7z"),
    "ngp": ("ngp", "zip", "7z"),
    "ngpc": ("ngc", "ngp", "zip", "7z"),
    "neogeocd": _CD,
    "msx": ("rom", "mx1", "mx2", "dsk", "cas", "zip", "7z"),
    "msx2": ("rom", "mx1", "mx2", "dsk", "cas", "zip", "7z"),
    "c64": ("d64", "d71", "d81", "t64", "tap", "prg", "crt", "g64", "x64", "m3u", "zip", "7z"),
    "amiga500": ("adf", "adz", "dms", "ipf", "hdf", "lha", "uae", "m3u", "zip", "7z"),
    "amiga1200": ("adf", "adz", "dms", "ipf", "hdf", "lha", "uae", "m3u", "zip", "7z"),
    "amstradcpc": ("dsk", "cdt", "sna", "m3u", "zip", "7z"),
    "zxspectrum": ("tzx", "tap", "z80", "sna", "trd", "scl", "dsk", "zip", "7z"),
    "atarist": ("st", "msa", "stx", "dim", "ipf", "m3u", "zip", "7z"),
    "pico8": ("p8", "png"),
    "tic80": ("tic",),
}
for _arcade in ("mame", "arcade", "fbneo", "fba", "neogeo", "cps1", "cps2", "cps3", "hbmame", "mame2003",
                "mame2010", "atomiswave", "naomi", "naomi2", "cave", "gaelco", "segastv", "model2", "zinc"):
    SYSTEM_EXTS.setdefault(_arcade, _ARCADE)
_EXT = re.compile(r"^[a-z0-9+_-]{1,12}$")


class NewGamelistError(ValueError):
    def __init__(self, key, status=400, **params):
        super().__init__(key)
        self.key, self.status, self.params = key, status, params


def default_exts(folder_name):
    return list(SYSTEM_EXTS.get((folder_name or "").lower(), ()))


def _folder(body):
    raw = str(body.get("folder") or "").strip().strip('"').strip("'")
    if not raw:
        raise NewGamelistError("newgl.no_folder")
    folder = os.path.abspath(raw)
    if not os.path.isdir(folder):
        raise NewGamelistError("newgl.not_dir", 404, path=raw)
    return folder


def _exts(body, folder_name):
    raw = body.get("exts")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default_exts(folder_name), False
    items = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw))
    exts = []
    for item in items:
        ext = str(item).strip().lower().lstrip("*").lstrip(".")
        if not ext:
            continue
        if not _EXT.match(ext) or ext in ("xml", "bak"):
            raise NewGamelistError("newgl.bad_ext", ext=str(item))
        if ext not in exts:
            exts.append(ext)
    return exts, True


def _plan(body):
    folder = _folder(body)
    _sid, system = detect_system_id(folder)
    exts, custom = _exts(body, system)
    strip_tags = bool(body.get("strip_tags"))
    paths, arcade = find_roms(folder, (), (), system, nested=False, exts=set(exts) if exts else None,
                              xml_path=os.path.join(folder, "gamelist.xml"))
    roms = []
    for full in paths:
        rel = "./" + os.path.relpath(full, folder).replace(os.sep, "/")
        roms.append({"path": rel, "name": clean_name(full.rstrip("\\/"), strip_tags) or os.path.basename(full)})
    return {
        "folder": folder,
        "system": system,
        "label": os.path.basename(os.path.normpath(folder)),
        "exts": exts,
        "default_exts": default_exts(system),
        "custom": custom,
        "all_exts": not exts,
        "arcade": arcade,
        "exists": os.path.isfile(os.path.join(folder, "gamelist.xml")),
        "xml_path": os.path.join(folder, "gamelist.xml"),
        "roms": roms,
    }


def _error(e):
    return api_err(st(e.key, **e.params), e.status, code=e.key.replace(".", "_"))


@bp.route("/api/new-gamelist/preview", methods=["POST"])
def api_new_gamelist_preview():
    try:
        plan = _plan(request.get_json(silent=True) or {})
    except NewGamelistError as e:
        return _error(e)
    out = dict(plan)
    out["total"] = len(plan["roms"])
    out["roms"] = plan["roms"][:PREVIEW_ROWS]
    out["known_exts"] = len(ROM_EXTS)
    return jsonify(out)


@bp.route("/api/new-gamelist", methods=["POST"])
def api_new_gamelist():
    try:
        plan = _plan(request.get_json(silent=True) or {})
    except NewGamelistError as e:
        return _error(e)
    xml_path = plan["xml_path"]
    if plan["exists"]:
        return api_err(st("newgl.exists"), 409, code="newgl_exists", xml_path=xml_path)
    if not plan["roms"]:
        return api_err(st("newgl.no_roms"), 400, code="newgl_no_roms")
    root = etree.Element("gameList")
    for rom in plan["roms"]:
        game = etree.SubElement(root, "game")
        etree.SubElement(game, "path").text = rom["path"]
        etree.SubElement(game, "name").text = rom["name"]
    data = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    try:
        if os.path.exists(xml_path):                     # created meanwhile: never replaced
            return api_err(st("newgl.exists"), 409, code="newgl_exists", xml_path=xml_path)
        atomic_write(xml_path, data)
    except OSError as e:
        return api_err(st("newgl.write_failed", detail=e), 500, code="newgl_write_failed")
    log.info("New gamelist %s with %d games", xml_path, len(plan["roms"]))
    info = set_gamelist_path(xml_path)
    recent.remember(info["xml_path"])
    games = get_games(load_xml())
    return jsonify({
        "success": True,
        "created": len(plan["roms"]),
        "xml_path": info["xml_path"],
        "base_dir": info["base_dir"],
        "system": get_system_info(),
        "games": games,
        "count": len(games),
        "session_id": xml_store.SESSION_ID,
    })
