"""Check the gamelist against the media files of its folder, and clean up.

GET  /api/check-media         report: media files no game uses (orphans), and
                              media tags pointing to a file that is gone
POST /api/check-media/apply   {"delete": [relative paths], "unlink": [{"path": game path,
                               "tag": tag}], "trash": true, "backup": true}

Only the media folders of the gamelist (images/, videos/, manuals/, and their
sub-folders) are scanned, and only media files (images, videos, PDF). A file
counts as used when any tag of any game points to it, whatever the tag
(Batocera's <titleshot>, <wheel>… included). The apply step re-scans and only
deletes files the scan confirms are orphans; with "trash" they go to the
Recycle Bin (recoverable).
"""

import os

from flask import Blueprint, jsonify, request

from gme import xml_store
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.media import MEDIA_EXTS
from gme.xml_store import MEDIA_DIRS, backup_xml, load_xml, require_gamelist, save_xml

bp = Blueprint("mediacheck", __name__)

MEDIA_FOLDERS = sorted(set(MEDIA_DIRS.values()))        # images, manuals, videos
# Tags that hold media in EmulationStation forks (RetroBat, Batocera, ES-DE…)
MEDIA_TAGS = set(MEDIA_DIRS) | {"titleshot", "wheel", "boxfront", "screenshot", "magazine", "music"}
NOT_FILES = {"path", "name", "desc", "rating", "releasedate", "developer", "publisher", "genre",
             "players", "lang", "region", "family", "favorite", "hidden", "kidgame", "playcount",
             "lastplayed", "arcadesystemname", "genreid", "sortname", "md5", "crc32", "cheevosid"}


def _key(full):
    return os.path.normcase(os.path.normpath(full))


def _full(value):
    """Absolute path of a media value, or None when it is not a file path."""
    value = (value or "").strip()
    if not value or "://" in value:
        return None
    if os.path.isabs(value):
        return os.path.normpath(value)
    clean = value.replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return os.path.normpath(os.path.join(xml_store.BASE_DIR, clean))


def _rel(full):
    return "./" + os.path.relpath(full, xml_store.BASE_DIR).replace(os.sep, "/")


def scan(tree=None):
    tree = tree if tree is not None else load_xml()
    games = tree.getroot().findall("game")
    used, broken = set(), []
    for i, game in enumerate(games):
        for child in game:
            if child.tag in NOT_FILES or not isinstance(child.tag, str):
                continue
            full = _full(child.text)
            if not full:
                continue
            used.add(_key(full))
            if child.tag in MEDIA_TAGS and not os.path.exists(full):
                broken.append({
                    "index": i,
                    "path": game.findtext("path", "") or "",
                    "name": game.findtext("name", "") or "",
                    "tag": child.tag,
                    "value": (child.text or "").strip(),
                })

    files, orphans, orphan_bytes = 0, [], 0
    for folder in MEDIA_FOLDERS:
        top = os.path.join(xml_store.BASE_DIR, folder)
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames, key=str.lower):
                if name.startswith(".") or os.path.splitext(name)[1].lower() not in MEDIA_EXTS:
                    continue
                files += 1
                full = os.path.join(dirpath, name)
                if _key(full) in used:
                    continue
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                orphan_bytes += size
                orphans.append({"path": _rel(full), "folder": folder, "size": size})
    return {
        "base_dir": xml_store.BASE_DIR,
        "games": len(games),
        "folders": [f for f in MEDIA_FOLDERS if os.path.isdir(os.path.join(xml_store.BASE_DIR, f))],
        "files": files,
        "orphans": orphans,
        "orphan_bytes": orphan_bytes,
        "broken": broken,
    }


def _trash(full):
    from send2trash import send2trash
    send2trash(full)


@bp.route("/api/check-media")
def api_check_media():
    err = require_gamelist()
    if err:
        return err
    return jsonify(scan())


@bp.route("/api/check-media/apply", methods=["POST"])
def api_check_media_apply():
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    want_delete = {p for p in body.get("delete") or [] if isinstance(p, str)}
    want_unlink = {(u.get("path"), u.get("tag")) for u in body.get("unlink") or []
                   if isinstance(u, dict) and isinstance(u.get("tag"), str)}
    if not (want_delete or want_unlink):
        return api_err(st("server.no_fields"), 400, code="nothing_to_do")
    use_trash = bool(body.get("trash", True))

    tree = load_xml()
    report = scan(tree)
    games = tree.getroot().findall("game")

    # Broken links: remove the tag (the file is already gone)
    unlinked = 0
    for b in report["broken"]:
        if (b["path"], b["tag"]) not in want_unlink:
            continue
        game = games[b["index"]]
        for child in game.findall(b["tag"]):
            if (child.text or "").strip() == b["value"]:
                game.remove(child)
                unlinked += 1
    backup = None
    if unlinked:
        if body.get("backup", True):
            try:
                backup = backup_xml()
            except Exception as e:
                return api_err(str(e), 500, code="backup_failed")
        save_xml(tree)

    # Orphans: only files the scan confirms no game uses
    deleted, freed, failed = 0, 0, []
    for o in report["orphans"]:
        if o["path"] not in want_delete:
            continue
        full = _full(o["path"])
        try:
            if use_trash:
                _trash(full)
            else:
                os.remove(full)
            deleted += 1
            freed += o["size"]
        except Exception as e:  # trash unavailable (network drive…), locked file
            log.warning("Media check: could not delete %s (%s)", full, e)
            failed.append(o["path"])
    return jsonify({
        "success": True,
        "deleted": deleted,
        "freed": freed,
        "failed": failed,
        "unlinked": unlinked,
        "trash": use_trash,
        "backup": backup,
        "report": scan(),
    })
