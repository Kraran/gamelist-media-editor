"""Check the gamelist against the ROM files of its folder, and bring it up to date.

GET  /api/check-roms         report: ROMs not in the gamelist, entries whose
                             ROM is gone, entries listed twice
POST /api/check-roms/scan    the same report as a background job (progress,
                             Stop: gme.jobs) → {"job": {...}}
POST /api/check-roms/apply   {"add": [paths], "remove": [paths], "merge": [paths],
                              "backup": true, "delete_media": false}

What counts as a ROM: a file whose extension is a known ROM / disc / archive
extension or is already used by an entry of this gamelist. Media folders
(images, videos, manuals…) are skipped, and so are the files a .cue, .gdi or
.m3u points to (the tracks of a disc are not games). A folder whose name has a
ROM extension ("Game.ps3", "Game.pc") is one game, like in EmulationStation.

The apply step re-scans the folder and only acts on paths the scan confirms:
it adds files that really are missing from the gamelist, removes entries whose
ROM really is gone, and merges entries that really share a path. Entries are
identified by their <path>, never by position.
"""

import copy
import os
import re

from flask import Blueprint, jsonify, request
from lxml import etree

from gme import fsutil, history, jobs, xml_store
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.systems import ARCADE_DB_FOLDERS, detect_system_id
from gme.xml_store import MEDIA_DIRS, backup_xml, load_xml, require_gamelist, resolve_under_base, save_xml

bp = Blueprint("romcheck", __name__)

ROM_EXTS = {
    # archives, discs, generic
    "zip", "7z", "rar", "bin", "cue", "chd", "iso", "img", "mdf", "mds", "ccd", "gdi", "cdi", "m3u",
    "pbp", "cso", "ciso", "rvz", "wbfs", "wia", "gcm", "gcz", "nkit", "rom",
    # Nintendo
    "nes", "fds", "unf", "unif", "sfc", "smc", "fig", "swc", "bs", "st", "gb", "gbc", "sgb", "gba",
    "n64", "z64", "v64", "ndd", "nds", "dsi", "3ds", "cia", "cci", "cxi", "vb", "vboy", "min",
    "wad", "wud", "wux", "rpx", "xci", "nsp", "nro",
    # Sega, NEC, SNK, Atari…
    "md", "gen", "smd", "32x", "sms", "gg", "sg", "sc", "pce", "sgx", "ws", "wsc", "ngp", "ngc",
    "a26", "a52", "a78", "lnx", "jag", "j64", "col", "cv", "int", "vec", "o2", "chf",
    # Sony
    "pkg", "vpk", "elf",
    # computers
    "d64", "d71", "d81", "t64", "tap", "prg", "crt", "g64", "x64", "adf", "adz", "dms", "ipf", "hdf",
    "lha", "uae", "msa", "stx", "dsk", "cdt", "sna", "z80", "tzx", "trd", "scl", "mx1", "mx2", "cas",
    "do", "po", "2mg", "woz", "nib", "atr", "xex", "xfd", "dim", "d88", "hdm", "fdi", "hdi",
    # engines, ports, others
    "p8", "tic", "wasm", "love", "scummvm", "exe", "lnk", "url",
    "pc", "ps3", "game", "squashfs", "wsquashfs",
}
# In sub-folders (a folder per game, data of PC ports…) only these count, plus
# the extensions the gamelist already uses: "pak", "exe", "bin"… found there are data.
SUBFOLDER_EXTS = {"zip", "7z", "m3u", "cue", "chd", "iso", "gdi", "cdi", "pbp", "cso", "rvz", "wbfs"}
# Folders that hold media or emulator data, never games
SKIP_DIRS = {
    "images", "videos", "manuals", "media", "music", "downloaded_images", "downloaded_videos",
    "downloaded_media", "snap", "snaps", "screenshots", "titles", "wheel", "wheels", "marquees",
    "boxart", "covers", "thumbnails", "fanart", "maps", "bezels", "cache", "saves", "states",
}
MAX_DEPTH = 4
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:(//|[^\\/])", re.I)   # steam://…, but not C:\…
_CUE_FILE = re.compile(r'^\s*FILE\s+"?(.+?)"?\s+\S+\s*$', re.I | re.M)


def _key(full):
    return os.path.normcase(os.path.normpath(full))


def _ext(name):
    return os.path.splitext(name)[1][1:].lower()


def _rel(full):
    """Gamelist form of a path under the folder: ./sub/file.ext with forward slashes."""
    return "./" + os.path.relpath(full, xml_store.rom_dir()).replace(os.sep, "/")


def _entry_full(path):
    if not path or _SCHEME.match(path):
        return None
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(xml_store.rom_dir(), path))


def _tracks(full):
    """Files a .cue / .gdi / .m3u points to (they belong to that game)."""
    ext = _ext(full)
    if ext not in ("cue", "gdi", "m3u"):
        return []
    try:
        with open(full, encoding="utf-8", errors="replace") as f:
            text = f.read(256 * 1024)
    except OSError:
        return []
    folder = os.path.dirname(full)
    if ext == "cue":
        names = _CUE_FILE.findall(text)
    elif ext == "gdi":
        names = []
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5:
                m = re.search(r'"([^"]+)"', line)
                names.append(m.group(1) if m else parts[4])
    else:
        names = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    return [os.path.normpath(os.path.join(folder, n)) for n in names]


def is_arcade_folder(folder_name):
    folder_name = (folder_name or "").lower()
    return folder_name in ARCADE_DB_FOLDERS or folder_name.startswith("mame")


def find_roms(base, listed_keys=(), used_exts=(), folder_name="", nested=False, exts=None, xml_path=None,
              on_folder=None):
    """The ROM files (and one-game folders) under ``base``: ``(paths, arcade)``.

    ``listed_keys``: keys (``_key``) of the paths the gamelist already lists,
    always kept; ``used_exts``: extensions the gamelist already uses; ``exts``:
    an explicit extension set (new gamelist for a known system) that replaces
    the defaults, in sub-folders too. Nothing is opened but .cue/.gdi/.m3u.
    ``on_folder(path)`` is called for each folder read (progress, Stop).
    """
    listed_keys = set(listed_keys)
    used_exts = set(used_exts)
    # Arcade (MAME, FBNeo, Naomi…): a game is a romset at the top of the folder;
    # its CHD disks sit in a sub-folder named after it and are never games.
    arcade = is_arcade_folder(folder_name)
    if exts:
        root_exts = set(exts) | used_exts
        sub_exts = set(exts) | used_exts
    else:
        root_exts = ROM_EXTS | used_exts
        sub_exts = SUBFOLDER_EXTS | used_exts
    max_depth = MAX_DEPTH
    if arcade:
        root_exts = (root_exts - {"chd"}) | used_exts
        sub_exts = (sub_exts - {"chd"}) | used_exts
        if not nested:
            max_depth = 1
    found, parts = [], set()
    xml_key = _key(xml_path or "")

    def walk(folder, depth):
        exts_here = root_exts if depth == 1 else sub_exts
        if on_folder:
            on_folder(folder)
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError:
            return
        # A sub-folder named like a ROM next to it ("kinst/" beside "kinst.zip")
        # holds that game's data (MAME CHD disks, DLC…), not other games.
        rom_stems = {os.path.splitext(e.name)[0].lower() for e in entries
                     if _ext(e.name) in exts_here and not e.name.startswith(".")}
        for e in entries:
            if e.name.startswith("."):
                continue
            try:
                is_dir = e.is_dir()
            except OSError:
                continue
            if is_dir:
                if e.name.lower() in SKIP_DIRS:
                    continue
                if _ext(e.name) in exts_here or _key(e.path) in listed_keys:
                    found.append(e.path)             # a folder that is one game
                elif depth < max_depth and e.name.lower() not in rom_stems:
                    walk(e.path, depth + 1)
            elif _ext(e.name) in exts_here and _key(e.path) != xml_key and e.name.lower() not in ("gamelist.xml", "gamelist.xml.bak"):
                found.append(e.path)
                parts.update(_key(p) for p in _tracks(e.path))

    walk(base, 1)
    return [p for p in found if _key(p) not in parts or _key(p) in listed_keys], arcade


def scan(tree=None, progress=None):
    """Compare the open gamelist with its folder. Returns a report dict.

    ``progress(done, total, current, phase)`` may raise ``jobs.Cancelled``."""
    tree = tree if tree is not None else load_xml()
    base = xml_store.rom_dir()
    games = tree.getroot().findall("game")
    tick = progress or (lambda *a: None)
    tick(0, len(games), "", "games")

    used_exts = set()
    by_key = {}                                  # ROM key -> [(xml index, game)]
    missing, non_file = [], 0
    for i, game in enumerate(games):
        path = (game.findtext("path", "") or "").strip()
        if i % 20 == 0:
            tick(i, len(games), path)
        full = _entry_full(path)
        if full is None:
            non_file += 1
            continue
        if _ext(full):
            used_exts.add(_ext(full))
        by_key.setdefault(_key(full), []).append((i, game))
        if not os.path.exists(full):
            missing.append({
                "index": i,
                "path": path,
                "name": game.findtext("name", "") or os.path.basename(path),
                "media": sum(1 for f in MEDIA_DIRS if (game.findtext(f, "") or "").strip()),
            })

    _, folder_name = detect_system_id()
    nested = any("/" in (g.findtext("path", "") or "").strip().lstrip("./").replace("\\", "/") for g in games)
    tick(len(games), len(games), "", "games")
    found = [0]

    def on_folder(folder):
        found[0] += 1
        tick(found[0], 0, os.path.relpath(folder, base) if folder != base else "", "folders")

    roms, arcade = find_roms(base, set(by_key), used_exts, folder_name, nested, xml_path=xml_store.XML_PATH,
                             on_folder=on_folder if progress else None)
    unlisted = []
    for full in roms:
        if _key(full) in by_key:
            continue
        try:
            size = os.path.getsize(full) if os.path.isfile(full) else None
        except OSError:
            size = None
        unlisted.append({"path": _rel(full), "name": _default_name(full), "size": size})

    duplicates = []
    for entries in by_key.values():
        if len(entries) > 1:
            duplicates.append({
                "path": entries[0][1].findtext("path", ""),
                "entries": [{"index": i, "name": g.findtext("name", "") or "", "filled": _filled(g)}
                            for i, g in entries],
            })

    return {
        "base_dir": base,
        "games": len(games),
        "roms": len(roms),
        "unlisted": unlisted,
        "missing": missing,
        "duplicates": duplicates,
        "non_file": non_file,
        "arcade": arcade,
    }


def _default_name(full):
    """EmulationStation's name for a new entry: the file name without extension."""
    name = os.path.basename(full.rstrip("\\/"))
    stem, ext = os.path.splitext(name)
    return stem if ext else name


def _filled(game):
    return sum(1 for child in game if (child.text or "").strip())


def _merge_into(keeper, other):
    """Copy into ``keeper`` the fields it lacks."""
    have = {child.tag for child in keeper if (child.text or "").strip()}
    for child in other:
        if child.tag not in have and (child.text or "").strip():
            old = keeper.find(child.tag)
            if old is not None:
                keeper.remove(old)
            keeper.append(etree.fromstring(etree.tostring(child)))
            have.add(child.tag)


def _delete_media(game, still_used):
    deleted = 0
    for field in MEDIA_DIRS:
        rel = (game.findtext(field, "") or "").strip()
        if not rel:
            continue
        full = resolve_under_base(rel)
        if not full or _key(full) in still_used or not os.path.isfile(full):
            continue
        try:
            fsutil.trash(full)
            deleted += 1
        except Exception as e:  # no Recycle Bin on this drive: keep the file
            log.warning("ROM check: could not move %s to the Recycle Bin (%s)", full, e)
    return deleted


@bp.route("/api/check-roms")
def api_check_roms():
    err = require_gamelist()
    if err:
        return err
    return jsonify(scan())


@bp.route("/api/check-roms/scan", methods=["POST"])
def api_check_roms_scan():
    err = require_gamelist()
    if err:
        return err
    tree = copy.deepcopy(load_xml())        # the editor may change the cached tree meanwhile
    return jsonify({"job": jobs.start("romcheck", lambda job: scan(tree, progress=job.tick)).public(with_result=True)})


@bp.route("/api/check-roms/apply", methods=["POST"])
def api_check_roms_apply():
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    want_add = {str(p) for p in body.get("add") or [] if isinstance(p, str)}
    want_remove = {str(p) for p in body.get("remove") or [] if isinstance(p, str)}
    want_merge = {str(p) for p in body.get("merge") or [] if isinstance(p, str)}
    if not (want_add or want_remove or want_merge):
        return api_err(st("server.no_fields"), 400, code="nothing_to_do")

    tree = load_xml()
    root = tree.getroot()
    job_id = body.get("job")
    if job_id:                              # the report the user reviewed, if still true
        report = jobs.reusable(job_id, "romcheck")
        if report is None:
            return api_err(st("jobs.stale"), 409, code="scan_stale")
    else:
        report = scan(tree)
    games = root.findall("game")

    backup = None
    if body.get("backup", True):
        try:
            backup = backup_xml()
        except Exception as e:
            log.warning("ROM check: backup failed (%s)", e)
            return api_err(str(e), 500, code="backup_failed")

    # Merge duplicates: the most complete entry stays and gets the others' fields
    merged = 0
    for dup in report["duplicates"]:
        if dup["path"] not in want_merge:
            continue
        entries = [games[e["index"]] for e in dup["entries"]]
        keeper = max(entries, key=_filled)
        for other in entries:
            if other is not keeper:
                _merge_into(keeper, other)
                root.remove(other)
                merged += 1

    # Remove entries whose ROM is gone
    removed, media_deleted = [], 0
    for m in report["missing"]:
        if m["path"] not in want_remove:
            continue
        game = games[m["index"]]
        if game.getparent() is None:
            continue                               # already merged away
        removed.append(game)
        root.remove(game)
    if body.get("delete_media") and removed:
        still_used = set()
        for game in root.findall("game"):
            for field in MEDIA_DIRS:
                rel = (game.findtext(field, "") or "").strip()
                full = resolve_under_base(rel) if rel else None
                if full:
                    still_used.add(_key(full))
        for game in removed:
            media_deleted += _delete_media(game, still_used)

    # Add the ROMs missing from the gamelist
    added = 0
    for u in report["unlisted"]:
        if u["path"] not in want_add:
            continue
        game = etree.SubElement(root, "game")
        etree.SubElement(game, "path").text = u["path"]
        etree.SubElement(game, "name").text = u["name"]
        added += 1

    if added or removed or merged:
        history.label("romcheck", added=added, removed=len(removed), merged=merged)
        save_xml(tree)
    return jsonify({
        "success": True,
        "added": added,
        "removed": len(removed),
        "merged": merged,
        "media_deleted": media_deleted,
        "backup": backup,
        "report": None if job_id else scan(),     # with a job, the page scans again (progress)
    })
