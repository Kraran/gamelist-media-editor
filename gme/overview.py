"""Multi-system overview: every system folder of a ``roms`` root at a glance.

``POST /api/overview/scan {path, refresh}`` resolves the root (the ``roms``
folder itself, or a RetroBat / Batocera / Recalbox folder that contains one),
lists its system folders (a ``gamelist.xml`` or ROM files) and starts a
background scan; ``GET /api/overview`` returns the progress and the systems
scanned so far; ``POST /api/overview/stop`` stops it. ``GET /api/overview/systems``
is the quick list of the system switcher (no scan).

Every system is read on its own, never through the open gamelist: games,
games whose ROM is missing, ROM files not in the gamelist, media present /
broken (tag pointing to a missing file) / missing per media tag, and missing
metadata. Nothing is ever written. Results are kept in memory per folder and
reused while the gamelist and the media folders keep the same date (Refresh
rescans everything). Systems are scanned on a few threads, one directory
listing per folder instead of one ``stat`` per file, so large collections and
network shares stay quick.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request
from lxml import etree

from gme import esde, recent, xml_store
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.romcheck import ROM_EXTS, SUBFOLDER_EXTS, _SCHEME, _ext, find_roms
from gme.systems import SS_SYSTEM_MAP

bp = Blueprint("overview", __name__)

WORKERS = 4
META_FIELDS = ("desc", "genre", "releasedate", "developer", "publisher", "rating", "players")
# Folders of a roms root that are never systems.
NOT_SYSTEMS = {
    "bios", "saves", "states", "screenshots", "cheats", "music", "themes", "decorations",
    "downloaded_images", "downloaded_media", "downloaded_videos", "media", "images", "videos",
    "manuals", "system", "configs", "cache", "logs", "lost+found", "$recycle.bin",
    "system volume information", "kodi", "overlays", "shaders", "splash", "userdata",
}
# Friendly names of the common EmulationStation folders (unknown: the folder name).
SYSTEM_NAMES = {
    "3do": "3DO", "3ds": "Nintendo 3DS", "32x": "Sega 32X", "amiga": "Amiga", "amiga500": "Amiga 500",
    "amiga1200": "Amiga 1200", "amigacd32": "Amiga CD32", "amstradcpc": "Amstrad CPC",
    "apple2": "Apple II", "arcadia": "Emerson Arcadia 2001", "arcade": "Arcade", "atari2600": "Atari 2600", "atari5200": "Atari 5200",
    "atari7800": "Atari 7800", "atari800": "Atari 800", "atarijaguar": "Atari Jaguar",
    "atarilynx": "Atari Lynx", "atarist": "Atari ST", "atomiswave": "Atomiswave", "c64": "Commodore 64",
    "cdi": "Philips CD-i", "colecovision": "ColecoVision", "cps1": "Capcom CPS-1", "cps2": "Capcom CPS-2",
    "cps3": "Capcom CPS-3", "daphne": "Daphne (LaserDisc)", "dos": "MS-DOS", "dreamcast": "Sega Dreamcast",
    "famicom": "Famicom", "fbneo": "FinalBurn Neo", "fds": "Famicom Disk System",
    "gameandwatch": "Game & Watch", "gamecube": "Nintendo GameCube", "gamegear": "Sega Game Gear",
    "gb": "Game Boy", "gba": "Game Boy Advance", "gbc": "Game Boy Color", "gc": "Nintendo GameCube",
    "genesis": "Sega Genesis", "gg": "Sega Game Gear", "intellivision": "Intellivision",
    "jaguar": "Atari Jaguar", "lynx": "Atari Lynx", "mame": "MAME", "mastersystem": "Sega Master System",
    "megacd": "Sega Mega-CD", "megadrive": "Sega Mega Drive", "msx": "MSX", "msx1": "MSX", "msx2": "MSX2",
    "n64": "Nintendo 64", "naomi": "Sega NAOMI", "nds": "Nintendo DS", "neogeo": "Neo-Geo",
    "neogeocd": "Neo-Geo CD", "nes": "Nintendo (NES)", "ngp": "Neo-Geo Pocket",
    "ngpc": "Neo-Geo Pocket Color", "o2em": "Videopac / Odyssey²", "odyssey2": "Videopac / Odyssey²",
    "openbor": "OpenBOR", "pc": "PC", "pc88": "NEC PC-88", "pc98": "NEC PC-98", "pcengine": "PC Engine",
    "pcenginecd": "PC Engine CD", "pcfx": "PC-FX", "pico8": "PICO-8", "pokemini": "Pokémon mini",
    "ports": "Ports", "ps2": "PlayStation 2", "ps3": "PlayStation 3", "psp": "PlayStation Portable",
    "psvita": "PlayStation Vita", "psx": "PlayStation", "ps1": "PlayStation", "satellaview": "Satellaview",
    "saturn": "Sega Saturn", "scummvm": "ScummVM", "sega32x": "Sega 32X", "segacd": "Sega CD",
    "sg1000": "Sega SG-1000", "sfc": "Super Famicom", "snes": "Super Nintendo", "steam": "Steam",
    "supergrafx": "PC Engine SuperGrafx", "switch": "Nintendo Switch", "thomson": "Thomson MO/TO",
    "ti99": "TI-99/4A", "tic80": "TIC-80", "vectrex": "Vectrex", "vic20": "Commodore VIC-20",
    "virtualboy": "Virtual Boy", "vc4000": "Interton VC 4000", "wii": "Nintendo Wii", "wiiu": "Nintendo Wii U",
    "windows": "Windows", "wswan": "WonderSwan", "wswanc": "WonderSwan Color", "x68000": "Sharp X68000",
    "xbox": "Xbox", "zx81": "ZX81", "zxspectrum": "ZX Spectrum", "model2": "Sega Model 2",
    "model3": "Sega Model 3", "channelf": "Fairchild Channel F", "videopac": "Videopac",
    "neogeo64": "Hyper Neo-Geo 64", "triforce": "Triforce", "xbox360": "Xbox 360",
}

_cache = {}                 # folder key -> (signature, result)
_cache_lock = threading.Lock()
_state_lock = threading.Lock()
_job = {"root": None, "state": "idle", "systems": [], "done": 0, "total": 0, "current": "",
        "started": 0.0, "finished": 0.0, "stop": None, "id": 0}


def _key(path):
    return os.path.normcase(os.path.normpath(path))


def friendly_name(folder):
    return SYSTEM_NAMES.get((folder or "").lower(), folder)


# --- root and system folders -------------------------------------------------

def _looks_like_system(path, name):
    if name.lower() in NOT_SYSTEMS or name.startswith("."):
        return False
    if os.path.isfile(os.path.join(path, "gamelist.xml")):
        return True
    try:
        with os.scandir(path) as it:
            for i, e in enumerate(it):
                if i > 2000:                       # a huge folder without a gamelist: look no further
                    break
                ext = _ext(e.name)
                if ext in ROM_EXTS or (ext in SUBFOLDER_EXTS and e.is_dir()):
                    return True
    except OSError:
        return False
    return False


def list_systems(root):
    """The system folders of ``root``, sorted by name."""
    out = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name.lower())
    except OSError:
        return out
    is_esde = esde.is_home(os.path.dirname(os.path.normpath(root)))
    for e in entries:
        try:
            if not e.is_dir():
                continue
        except OSError:
            continue
        if is_esde and e.name in esde.NOT_SYSTEMS:
            continue
        if not _looks_like_system(e.path, e.name):
            continue
        xml = os.path.join(e.path, "gamelist.xml")
        out.append({
            "folder": e.name,
            "label": friendly_name(e.name),
            "path": e.path,
            "xml": xml if os.path.isfile(xml) else None,
            "known": e.name.lower() in SS_SYSTEM_MAP,
        })
    return out


def resolve_root(path):
    """The roms folder for ``path`` (``…/roms`` itself, its parent, a system folder or a gamelist.xml)."""
    raw = str(path or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError(st("server.open_empty_path"))
    full = os.path.abspath(raw)
    # ES-DE: its folder, the portable install, es_settings.xml or a gamelist → ES-DE/gamelists
    home = esde.find_home(full)
    if home and list_systems(os.path.join(home, "gamelists")):
        return os.path.join(home, "gamelists")
    if os.path.isfile(full):
        full = os.path.dirname(full)
    if not os.path.isdir(full):
        raise FileNotFoundError(st("server.browse_not_dir", path=full))
    if list_systems(full):
        # A system folder itself (snes/ with its gamelist): its parent is the root.
        if os.path.isfile(os.path.join(full, "gamelist.xml")):
            parent = os.path.dirname(full)
            if parent != full and len(list_systems(parent)) > 1:
                return parent
        return full
    for sub in ("roms", "ROMS", "Roms", os.path.join("share", "roms"), os.path.join("userdata", "roms")):
        cand = os.path.join(full, sub)
        if os.path.isdir(cand) and list_systems(cand):
            return cand
    if os.path.isfile(os.path.join(full, "gamelist.xml")):
        parent = os.path.dirname(full)
        if parent != full and list_systems(parent):
            return parent
    raise ValueError(st("server.overview_no_systems", path=full))


# --- one system ---------------------------------------------------------------

class _Listing:
    """Names of a folder's entries, read once (one listing instead of one stat per file)."""

    def __init__(self):
        self._dirs = {}

    def exists(self, full):
        folder, name = os.path.split(full)
        k = _key(folder)
        names = self._dirs.get(k)
        if names is None:
            try:
                names = {os.path.normcase(n) for n in os.listdir(folder)}
            except OSError:
                names = set()
            self._dirs[k] = names
        return os.path.normcase(name) in names


def _resolve(base, value):
    """Absolute path of a gamelist path under ``base`` (None: outside, URL, empty)."""
    if not value or _SCHEME.match(value):
        return None
    clean = value.replace("\\", "/")
    if os.path.isabs(value):
        return os.path.normpath(value)
    while clean.startswith("./"):
        clean = clean[2:]
    clean = clean.lstrip("/")
    if not clean or ".." in clean.split("/"):
        return None
    return os.path.normpath(os.path.join(base, clean))


def _signature(path):
    sig = []
    for rel in ("gamelist.xml", "", "images", "videos", "manuals", "music"):
        try:
            st_ = os.stat(os.path.join(path, rel) if rel else path)
            sig.append((rel, st_.st_mtime_ns, st_.st_size if rel else 0))
        except OSError:
            sig.append((rel, None, None))
    layout = esde.layout_for_gamelist(os.path.join(path, "gamelist.xml"))
    if layout is not None:                    # ES-DE: the ROM folder and the media folders
        for full in [layout.rom_dir] + [os.path.join(layout.media_dir, f) for f in esde.FOLDERS.values()]:
            try:
                st_ = os.stat(full)
                sig.append((full, st_.st_mtime_ns, 0))
            except OSError:
                sig.append((full, None, None))
    return tuple(sig)


def scan_system(system):
    """Counts for one system folder (see the module docstring)."""
    path = system["path"]
    out = dict(system)
    out.update({"games": 0, "roms_missing": 0, "roms_unlisted": 0, "roms": 0, "error": None,
                "media": {f: {"present": 0, "broken": 0, "missing": 0} for f in xml_store.MEDIA_DIRS},
                "meta_missing": {f: 0 for f in META_FIELDS}, "scraped": 0, "hidden": 0})
    listing = _Listing()
    listed, used_exts, nested = set(), set(), False
    xml = system.get("xml")
    layout = esde.layout_for_gamelist(xml) if xml else None
    index = None
    if layout is not None:                    # ES-DE: ROMs elsewhere, media found by name
        path = layout.rom_dir
        out["media"] = {f: {"present": 0, "broken": 0, "missing": 0} for f in esde.FIELDS}
        out["profile"] = "esde"
        index = esde.MediaIndex(layout)
    if xml:
        try:
            tree = etree.parse(xml, etree.XMLParser(remove_blank_text=True, huge_tree=True))
        except (etree.XMLSyntaxError, OSError) as e:
            out["error"] = "bad_xml"
            out["error_detail"] = str(e)[:300]
            return out
        games = tree.getroot().findall("game")
        out["games"] = len(games)
        for game in games:
            text = {c.tag: (c.text or "").strip() for c in reversed(game) if isinstance(c.tag, str)}
            rom = text.get("path", "")
            full = _resolve(path, rom)
            if full is not None:
                listed.add(_key(full))
                if _ext(full):
                    used_exts.add(_ext(full))
                if "/" in rom.lstrip("./").replace("\\", "/"):
                    nested = True
                if not listing.exists(full):
                    out["roms_missing"] += 1
            has_media = False
            stem = esde.rom_stem(layout, rom) if index is not None else None
            for field, counts in out["media"].items():
                if index is not None:
                    found = bool(stem) and index.lookup(field, stem) is not None
                    counts["present" if found else "missing"] += 1
                    has_media = has_media or found
                    continue
                value = text.get(field, "")
                if not value:
                    counts["missing"] += 1
                    continue
                mfull = _resolve(path, value)
                if "://" in value or (mfull is not None and listing.exists(mfull)):
                    counts["present"] += 1
                    has_media = True
                else:
                    counts["broken"] += 1
            for field in META_FIELDS:
                if not text.get(field):
                    out["meta_missing"][field] += 1
            out["scraped"] += bool(text.get("desc")) or has_media
            out["hidden"] += text.get("hidden", "").lower() in ("true", "1", "yes")
    try:
        roms, _ = find_roms(path, listed, used_exts, system["folder"], nested, xml_path=xml)
    except OSError:
        roms = []
    out["roms"] = len(roms)
    out["roms_unlisted"] = sum(1 for r in roms if _key(r) not in listed)
    return out


def cached_scan(system, refresh=False):
    k = _key(system["path"])
    sig = _signature(system["path"])
    with _cache_lock:
        hit = _cache.get(k)
    if hit and not refresh and hit[0] == sig:
        return dict(hit[1], cached=True)
    result = scan_system(system)
    with _cache_lock:
        _cache[k] = (sig, result)
    return dict(result, cached=False)


# --- background job -------------------------------------------------------------

def _public():
    with _state_lock:
        return {k: (list(v) if k == "systems" else v) for k, v in _job.items() if k != "stop"}


def _run(job_id, systems, refresh, stop):
    results = [None] * len(systems)

    def one(i):
        if stop.is_set():
            return
        with _state_lock:
            if _job["id"] == job_id:
                _job["current"] = systems[i]["folder"]
        try:
            res = cached_scan(systems[i], refresh)
        except Exception as e:                     # one broken folder never stops the overview
            log.exception("overview: scan of %s failed", systems[i]["path"])
            res = dict(systems[i], error="scan_failed", error_detail=str(e)[:300])
        results[i] = res
        with _state_lock:
            if _job["id"] == job_id:
                _job["done"] += 1
                _job["systems"] = [r for r in results if r is not None]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(one, range(len(systems))))
    with _state_lock:
        if _job["id"] == job_id:
            _job["systems"] = [r for r in results if r is not None]
            _job["state"] = "stopped" if stop.is_set() else "done"
            _job["current"] = ""
            _job["finished"] = time.time()


def start(root, refresh=False):
    systems = list_systems(root)
    stop = threading.Event()
    with _state_lock:
        if _job["stop"] is not None:
            _job["stop"].set()
        _job.update({"root": root, "state": "running", "systems": [], "done": 0, "total": len(systems),
                     "current": "", "started": time.time(), "finished": 0.0, "stop": stop,
                     "id": _job["id"] + 1})
        job_id = _job["id"]
    threading.Thread(target=_run, args=(job_id, systems, refresh, stop), daemon=True,
                     name="gme-overview").start()
    return _public()


def current_root():
    """The root of the overview, else the recent root that contains the open gamelist."""
    with _state_lock:
        root = _job["root"]
    if root:
        return root
    if xml_store.has_gamelist():
        parent = _key(os.path.dirname(xml_store.BASE_DIR))
        for r in recent.recent_roots():
            if _key(r) == parent and os.path.isdir(r):
                return r
    return None


def reset():
    """Tests: forget the job and the cache."""
    with _state_lock:
        if _job["stop"] is not None:
            _job["stop"].set()
        _job.update({"root": None, "state": "idle", "systems": [], "done": 0, "total": 0, "current": "",
                     "stop": None})
    with _cache_lock:
        _cache.clear()


def wait(timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if _public()["state"] != "running":
            return True
        time.sleep(0.02)
    return False


# --- routes -------------------------------------------------------------------------

def _recent_payload():
    from gme import network
    return [{"path": p, "exists": network.quick_exists(p, os.path.isdir)} for p in recent.recent_roots()]


@bp.route("/api/overview/scan", methods=["POST"])
def api_overview_scan():
    body = request.get_json(silent=True) or {}
    raw = body.get("path")
    try:
        root = resolve_root(raw) if raw else current_root()
        if not root:
            raise ValueError(st("server.open_empty_path"))
    except FileNotFoundError as e:
        if raw:
            recent.forget_root(os.path.abspath(str(raw).strip().strip('"').strip("'")))
        return api_err(str(e), 404, code="browse_not_dir", recent=_recent_payload())
    except ValueError as e:
        return api_err(str(e), 400, code="overview_no_systems")
    recent.remember_root(root)
    data = start(root, bool(body.get("refresh")))
    data["recent"] = _recent_payload()
    return jsonify(data)


@bp.route("/api/overview")
def api_overview():
    data = _public()
    data["root"] = data["root"] or current_root()
    data["xml_path"] = xml_store.XML_PATH if xml_store.has_gamelist() else None
    return jsonify(data)


@bp.route("/api/overview/stop", methods=["POST"])
def api_overview_stop():
    with _state_lock:
        if _job["stop"] is not None:
            _job["stop"].set()
    return jsonify(_public())


@bp.route("/api/overview/systems")
def api_overview_systems():
    root = current_root()
    systems = list_systems(root) if root else []
    return jsonify({"root": root, "systems": systems,
                    "xml_path": xml_store.XML_PATH if xml_store.has_gamelist() else None})


@bp.route("/api/overview/recent")
def api_overview_recent():
    return jsonify({"recent": _recent_payload()})


@bp.route("/api/overview/recent/forget", methods=["POST"])
def api_overview_recent_forget():
    body = request.get_json(silent=True) or {}
    recent.forget_root(str(body.get("path") or ""))
    return jsonify({"recent": _recent_payload()})
