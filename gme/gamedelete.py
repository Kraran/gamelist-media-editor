"""Delete a game: its ROM files, its media and its entry in gamelist.xml.

POST /api/delete-game/<index>/preview   what would go: {"files", "media", "kept"}
POST /api/delete-game/<index>           {"trash": true, "backup": true}

The game's files are its ROM, what the ROM points to (tracks of a .cue / .gdi,
discs of a .m3u), the folder named like the ROM next to it (MAME: kinst/ holds
the disk of kinst.zip) and its Pad2Key .keys file; then the files its tags
point to. A file or folder another game still uses is kept (a box art reused
by a clone, a ROM listed twice). With "trash" everything goes to the Recycle
Bin. If the ROM itself cannot be deleted, nothing changes.
"""

import os
import shutil

from flask import Blueprint, jsonify, request

from gme import esde, fsutil, xml_store
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.media import NOT_FILE_TAGS, file_path, files_used_by_others, pad2key_dest
from gme.romcheck import SKIP_DIRS, _entry_full, _tracks
from gme.xml_store import backup_xml, get_game_elem, require_gamelist, save_xml

bp = Blueprint("gamedelete", __name__)


def _key(full):
    return os.path.normcase(os.path.normpath(full))


def _rel(full):
    """Gamelist form (./images/x.png, ES-DE: @media/covers/x.png) for files under
    the folder, else the full path."""
    if xml_store.PROFILE is not None:
        value = esde.to_value(xml_store.PROFILE, full)
        if value:
            return value
    try:
        rel = os.path.relpath(full, xml_store.rom_dir())
    except ValueError:          # another drive (Windows)
        return full
    if rel == ".." or rel.startswith(".." + os.sep):
        return full
    return "./" + rel.replace(os.sep, "/")


def _size(full):
    if not os.path.isdir(full):
        try:
            return os.path.getsize(full)
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, names in os.walk(full):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def plan(game):
    """What deleting ``game`` removes: {"files": [...], "media": [...], "kept": [...]}.

    Each entry: {"path", "full", "dir", "size"}. ``files`` starts with the ROM.
    """
    used = files_used_by_others(game)
    bases = {_key(xml_store.rom_dir()), _key(xml_store.BASE_DIR)}
    if xml_store.PROFILE is not None:
        bases.add(_key(xml_store.PROFILE.media_dir))
    out = {"files": [], "media": [], "kept": []}
    seen = set()

    def add(bucket, full):
        if not full or not os.path.exists(full):
            return
        key = _key(full)
        if key in seen or any(key == base or base.startswith(key + os.sep) for base in bases):
            return                          # never the system folder or above
        seen.add(key)
        is_dir = os.path.isdir(full)
        shared = any(k == key or k.startswith(key + os.sep) for k in used) if is_dir else key in used
        out["kept" if shared else bucket].append(
            {"path": _rel(full), "full": full, "dir": is_dir, "size": _size(full)})

    rom = _entry_full((game.findtext("path", "") or "").strip())
    if rom:
        add("files", rom)
        if os.path.isfile(rom):
            for track in _tracks(rom):
                add("files", track)
            data_dir = os.path.splitext(rom)[0]
            if data_dir != rom and os.path.isdir(data_dir) \
                    and os.path.basename(data_dir).lower() not in SKIP_DIRS:
                add("files", data_dir)
    keys = pad2key_dest(game)
    if keys and os.path.isfile(keys):
        add("files", keys)
    for child in game:
        if not isinstance(child.tag, str) or child.tag in NOT_FILE_TAGS or child.tag == "path":
            continue
        full = file_path(child.text)
        if full and os.path.isfile(full):
            add("media", full)
    return out


def _public(entries):
    return [{"path": e["path"], "dir": e["dir"], "size": e["size"]} for e in entries]


def _remove(full, use_trash):
    if use_trash:
        fsutil.trash(full)
    elif os.path.isdir(full):
        shutil.rmtree(full)
    else:
        os.remove(full)


@bp.route("/api/delete-game/<int:index>/preview", methods=["POST"])
def api_delete_preview(index):
    err = require_gamelist()
    if err:
        return err
    try:
        _tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    p = plan(game)
    return jsonify({
        "name": game.findtext("name", "") or "",
        "files": _public(p["files"]),
        "media": _public(p["media"]),
        "kept": _public(p["kept"]),
    })


@bp.route("/api/delete-game/<int:index>", methods=["POST"])
def api_delete_game(index):
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    use_trash = bool(body.get("trash", True))
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    name = game.findtext("name", "") or st("server.game_fallback", index=index)
    backup = None
    if body.get("backup"):
        try:
            backup = backup_xml()
        except Exception as e:
            return api_err(str(e), 500, code="backup_failed")
    p = plan(game)
    rom = p["files"][0] if p["files"] else None
    deleted, failed = [], []
    for entry in p["files"] + p["media"]:
        try:
            _remove(entry["full"], use_trash)
            deleted.append(entry["path"])
        except Exception as e:  # no Recycle Bin on this drive, locked file
            log.warning("Delete game: could not delete %s (%s)", entry["full"], e)
            if entry is rom:            # the ROM stays: so does everything else
                return api_err(st("server.rom_not_deleted", path=entry["path"], detail=e),
                               409, code="rom_not_deleted")
            failed.append(entry["path"])
    tree.getroot().remove(game)
    save_xml(tree)
    return jsonify({
        "success": True,
        "name": name,
        "deleted_files": deleted,
        "failed_files": failed,
        "kept_files": [e["path"] for e in p["kept"]],
        "trash": use_trash,
        "backup": backup,
    })
