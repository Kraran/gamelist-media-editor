"""Check the gamelist against the media files of its folder, and clean up.

GET  /api/check-media         report: media files no game uses (orphans), and
                              media tags pointing to a file that is gone
POST /api/check-media/scan    the same report as a background job (progress,
                              Stop: gme.jobs) → {"job": {...}}
POST /api/check-media/apply   {"delete": [relative paths], "unlink": [{"path": game path,
                               "tag": tag}], "trash": true, "backup": true}

Only the media folders of the gamelist (images/, videos/, manuals/, music/ and
their sub-folders) are scanned, and only media files (images, videos, PDF, audio). A file
counts as used when any tag of any game points to it, whatever the tag
(Batocera's <titleshot>, <wheel>… included). The apply step re-scans and only
deletes files the scan confirms are orphans; with "trash" they go to the
Recycle Bin (recoverable).
"""

import copy
import os

from flask import Blueprint, jsonify, request

from gme import esde, fsutil, history, jobs, xml_store
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.media import MEDIA_EXTS, file_path
from gme.xml_store import MEDIA_DIRS, backup_xml, load_xml, require_gamelist, save_xml

bp = Blueprint("mediacheck", __name__)

MEDIA_FOLDERS = sorted(set(MEDIA_DIRS.values()))        # images, manuals, music, videos
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
    if xml_store.PROFILE is not None:
        return file_path(value)
    if os.path.isabs(value):
        return os.path.normpath(value)
    clean = value.replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return os.path.normpath(os.path.join(xml_store.BASE_DIR, clean))


def _rel(full):
    return xml_store.gamelist_value(full)


def _folders():
    """(name, absolute path) of the media folders to scan."""
    if xml_store.PROFILE is not None:
        media_dir = xml_store.PROFILE.media_dir
        return [(f, os.path.join(media_dir, f)) for f in sorted(set(esde.FOLDERS.values()))]
    return [(f, os.path.join(xml_store.BASE_DIR, f)) for f in MEDIA_FOLDERS]


def _esde_rom_stems():
    """ES-DE shows every ROM of the folder, listed in the gamelist or not: the
    media of a ROM the gamelist does not list are not orphans."""
    layout = xml_store.PROFILE
    stems = set()
    top = layout.rom_dir
    for dirpath, dirnames, filenames in os.walk(top):
        rel_dir = os.path.relpath(dirpath, top).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        for name in dirnames:
            stems.add(os.path.normcase(rel_dir + name))
        for name in filenames:
            stems.add(os.path.normcase(rel_dir + os.path.splitext(name)[0]))
    return stems


def scan(tree=None, progress=None):
    """``progress(done, total, current, phase)`` may raise ``jobs.Cancelled``."""
    tree = tree if tree is not None else load_xml()
    games = tree.getroot().findall("game")
    tick = progress or (lambda *a: None)
    used, broken = set(), []
    for i, game in enumerate(games):
        if i % 20 == 0:
            tick(i, len(games), game.findtext("path", "") or "", "games")
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
    rom_stems = _esde_rom_stems() if xml_store.PROFILE is not None else None
    folders = _folders()
    for n, (folder, top) in enumerate(folders):
        tick(n, len(folders), folder, "folders")
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            tick(n, len(folders), os.path.relpath(dirpath, os.path.dirname(top)), "folders")
            for name in sorted(filenames, key=str.lower):
                if name.startswith(".") or os.path.splitext(name)[1].lower() not in MEDIA_EXTS:
                    continue
                files += 1
                full = os.path.join(dirpath, name)
                if _key(full) in used:
                    continue
                if rom_stems is not None:
                    stem = os.path.splitext(os.path.relpath(full, top))[0].replace(os.sep, "/")
                    if os.path.normcase(stem) in rom_stems:
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
        "folders": [f for f, top in _folders() if os.path.isdir(top)],
        "files": files,
        "orphans": orphans,
        "orphan_bytes": orphan_bytes,
        "broken": broken,
    }


def _trash(full):
    fsutil.trash(full)


@bp.route("/api/check-media")
def api_check_media():
    err = require_gamelist()
    if err:
        return err
    return jsonify(scan())


@bp.route("/api/check-media/scan", methods=["POST"])
def api_check_media_scan():
    err = require_gamelist()
    if err:
        return err
    tree = copy.deepcopy(load_xml())        # the editor may change the cached tree meanwhile
    return jsonify({"job": jobs.start("mediacheck", lambda job: scan(tree, progress=job.tick)).public(with_result=True)})


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
    job_id = body.get("job")
    if job_id:                              # the report the user reviewed, if still true
        report = jobs.reusable(job_id, "mediacheck")
        if report is None:
            return api_err(st("jobs.stale"), 409, code="scan_stale")
    else:
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
        history.label("mediacheck", n=unlinked)
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
                history.note_deleted()
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
        "report": None if job_id else scan(),     # with a job, the page scans again (progress)
    })
