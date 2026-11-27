"""Images of a single colour (Actions › Edit in bulk › Solid images).

POST /api/solid-images/preview  {"paths": [...], "fields": ["image", …], "files": false}
POST /api/solid-images/scan     same body: the preview as a background job
                                (progress, Stop: gme.jobs) → {"job": {...}}
POST /api/solid-images          same body: removes the tags (one backup, one write);
                                ``"job": id`` reuses that finished scan when the
                                gamelist and the images did not change since,
                                else answers 409 ``scan_stale`` (scan again)

A media is "solid" when ``gme.media.uniform_colour`` says so: on a 64 px copy
(averaging removes JPEG noise) the picture is fully transparent, or every
channel, alpha included, varies by at most ``UNIFORM_MAX_RANGE`` (10 / 255).
It is the rule the scrapes use to refuse a flat placeholder.

The tags go from gamelist.xml after a dated snapshot (Actions › Backups,
*Undo*). With ``"files": true`` the files also go to the Recycle Bin, but only
a file inside the gamelist folder that no other tag of any game points to
(another game, another media of the same game, a ``<path>``): such files are
kept and listed. ROMs are never deleted. Undo restores the gamelist, not the
files: they are recovered from the Recycle Bin.
"""

import copy
import os
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, jsonify, request

from gme import fsutil, history, jobs, xml_store
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.media import NOT_FILE_TAGS, file_key, uniform_colour
from gme.xml_store import MEDIA_DIRS, load_xml, require_gamelist, resolve_under_base, save_xml

bp = Blueprint("solidimages", __name__)

IMAGE_FIELDS = tuple(f for f in MEDIA_DIRS if f not in ("video", "manual", "music"))
PREVIEW_ROWS = 300
WORKERS = 4
_CACHE_MAX = 20000
_cache = {}                       # (normcase path, mtime_ns, size) → (colour | None, width, height)
_cache_lock = threading.Lock()


class SolidError(ValueError):
    def __init__(self, key):
        super().__init__(key)
        self.key = key


def file_colour(full):
    """(colour, width, height) of an image file; colour is None when it is not
    one colour (or not a readable picture). Cached by path, date and size."""
    try:
        stat = os.stat(full)
    except OSError:
        return None, 0, 0
    key = (os.path.normcase(full), stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    from PIL import Image
    result = (None, 0, 0)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(full) as im:
                size = im.size
                im.draft("RGB", (128, 128))      # JPEG: decode at a reduced size, much faster
                result = (uniform_colour(im.convert("RGBA")), size[0], size[1])
    except Exception as e:                       # not an image (video named .png), corrupt, bomb
        log.info("Solid images: cannot read %s (%s)", full, e)
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()
        _cache[key] = result
    return result


def _body():
    body = request.get_json(silent=True) or {}
    paths = body.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise SolidError("bulk.no_games")
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields or any(f not in IMAGE_FIELDS for f in fields):
        raise SolidError("bulk.bad_field")
    # ES-DE has no media tag to remove: removing a solid image means removing its file
    with_files = bool(body.get("files")) or xml_store.is_esde()
    fields = [f for f in dict.fromkeys(fields) if f in xml_store.media_fields()]
    if not fields:
        raise SolidError("bulk.bad_field")
    return set(paths), fields, with_files


def scan(tree, paths, fields, progress=None):
    """Solid image tags of the games whose <path> is in ``paths``.

    Returns (hits, stats): hits are (game, elem, full, colour, w, h).
    ``progress(done, total, current)`` may raise ``jobs.Cancelled``."""
    entries, missing = [], 0
    for game in tree.getroot().findall("game"):
        if (game.findtext("path", "") or "") not in paths:
            continue
        for field in fields:
            for elem in game.findall(field):
                value = (elem.text or "").strip()
                if not value:
                    continue
                full = resolve_under_base(value)
                if not full or not os.path.isfile(full):
                    missing += 1
                    continue
                entries.append((game, elem, full))
    files = sorted({e[2] for e in entries})
    colours = {}
    if progress:
        progress(0, len(files), "")
    pool = ThreadPoolExecutor(max_workers=WORKERS)
    try:
        futures = {pool.submit(file_colour, f): f for f in files}
        for n, future in enumerate(as_completed(futures), 1):
            colours[futures[future]] = future.result()
            if progress:
                progress(n, len(files), os.path.basename(futures[future]))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    hits = []
    for game, elem, full in entries:
        colour, w, h = colours[full]
        if colour is not None:
            hits.append((game, elem, full, colour, w, h))
    return hits, {"checked": len(entries), "files_checked": len(files), "missing": missing}


def file_plan(tree, hits):
    """Files that may go: (delete, kept). A file stays when another tag (any
    game, any media, a <path>) still points to it, or when it is a ROM."""
    removed = {id(h[1]) for h in hits}
    refs, roms = {}, set()
    for game in tree.getroot().findall("game"):
        rom = file_key(game.findtext("path", "") or "")
        if rom:
            roms.add(rom)
        for child in game:
            if isinstance(child.tag, str) and child.tag not in NOT_FILE_TAGS and child.text:
                key = file_key(child.text)
                if key:
                    refs.setdefault(key, []).append(child)
    delete, kept, seen = [], [], set()
    for _game, elem, full, _c, _w, _h in hits:
        key = file_key(elem.text)
        if not key or key in seen:
            continue
        seen.add(key)
        entry = {"path": elem.text.strip(), "full": full, "size": os.path.getsize(full)}
        if key in roms:
            kept.append(dict(entry, reason="rom"))
        elif any(id(r) not in removed for r in refs.get(key, [])):
            kept.append(dict(entry, reason="used"))
        else:
            delete.append(entry)
    return delete, kept


def _row(game, elem, colour, w, h):
    return {"path": game.findtext("path", "") or "", "name": game.findtext("name", "") or "",
            "field": elem.tag, "file": (elem.text or "").strip(), "colour": colour, "width": w, "height": h}


def _public(entries):
    return [{k: e[k] for k in ("path", "size", "reason") if k in e} for e in entries[:PREVIEW_ROWS]]


def _error(e):
    return api_err(st(e.key), 400, code=e.key.replace(".", "_"))


def _preview(tree, hits, stats, with_files):
    out = dict(stats, total=len(hits), games=len({id(h[0]) for h in hits}),
               rows=[_row(g, e, c, w, h) for g, e, _f, c, w, h in hits[:PREVIEW_ROWS]])
    if with_files:
        delete, kept = file_plan(tree, hits)
        out.update(delete=_public(delete), delete_total=len(delete), delete_bytes=sum(e["size"] for e in delete),
                   kept=_public(kept), kept_total=len(kept))
    return out


def _stamp_file(full):
    try:
        st_ = os.stat(full)
        return st_.st_mtime_ns, st_.st_size
    except OSError:
        return None


def _locate(tree, hits):
    """Hits as positions (game index, tag, n-th tag, value, file, stamp, colour, w, h)."""
    games = tree.getroot().findall("game")
    where = {id(g): i for i, g in enumerate(games)}
    out = []
    for game, elem, full, colour, w, h in hits:
        same = game.findall(elem.tag)
        out.append((where[id(game)], elem.tag, same.index(elem), elem.text, full, _stamp_file(full), colour, w, h))
    return out


def _relocate(tree, located):
    """Hits back from ``_locate`` positions; None when anything changed."""
    games = tree.getroot().findall("game")
    hits = []
    for gi, tag, k, text, full, stamp, colour, w, h in located:
        if gi >= len(games):
            return None
        same = games[gi].findall(tag)
        if k >= len(same) or same[k].text != text or _stamp_file(full) != stamp:
            return None
        hits.append((games[gi], same[k], full, colour, w, h))
    return hits


@bp.route("/api/solid-images/preview", methods=["POST"])
def api_solid_preview():
    err = require_gamelist()
    if err:
        return err
    try:
        paths, fields, with_files = _body()
    except SolidError as e:
        return _error(e)
    tree = load_xml()
    hits, stats = scan(tree, paths, fields)
    return jsonify(_preview(tree, hits, stats, with_files))


@bp.route("/api/solid-images/scan", methods=["POST"])
def api_solid_scan():
    err = require_gamelist()
    if err:
        return err
    try:
        paths, fields, with_files = _body()
    except SolidError as e:
        return _error(e)
    tree = copy.deepcopy(load_xml())        # the editor may change the cached tree meanwhile
    params = {"paths": sorted(paths), "fields": fields, "files": with_files}

    def run(job):
        hits, stats = scan(tree, paths, fields, progress=lambda d, t, c: job.tick(d, t, c))
        job.located = _locate(tree, hits)
        return _preview(tree, hits, stats, with_files)

    return jsonify({"job": jobs.start("solid", run, params).public(with_result=True)})


@bp.route("/api/solid-images", methods=["POST"])
def api_solid_apply():
    err = require_gamelist()
    if err:
        return err
    try:
        paths, fields, with_files = _body()
    except SolidError as e:
        return _error(e)
    tree = load_xml()
    job_id = (request.get_json(silent=True) or {}).get("job")
    if job_id:
        params = {"paths": sorted(paths), "fields": fields, "files": with_files}
        job = jobs.get(job_id)
        hits = None
        if jobs.reusable(job_id, "solid", params) is not None:
            hits = _relocate(tree, getattr(job, "located", []))
        if hits is None:
            return api_err(st("jobs.stale"), 409, code="scan_stale")
    else:
        hits, _stats = scan(tree, paths, fields)            # scanned again: what is on disk now
    if not hits:
        return jsonify({"success": True, "removed": 0, "games": 0, "deleted_files": [], "failed_files": [],
                        "kept_files": [], "snapshot": None})
    delete, kept = file_plan(tree, hits) if with_files else ([], [])
    try:
        _bak, snapshot = xml_store.backup_xml_snapshot()
    except Exception as e:
        return api_err(str(e), 500, code="backup_failed")
    history.label("solid", n=len(hits))
    for game, elem, *_rest in hits:
        game.remove(elem)
    save_xml(tree)
    deleted, failed = [], []
    for entry in delete:
        try:
            fsutil.trash(entry["full"])
            deleted.append(entry["path"])
        except Exception as e:  # no Recycle Bin on this drive, locked file: the file stays
            log.warning("Solid images: could not move %s to the Recycle Bin (%s)", entry["full"], e)
            failed.append(entry["path"])
    return jsonify({"success": True, "removed": len(hits), "games": len({id(h[0]) for h in hits}),
                    "deleted_files": deleted, "failed_files": failed,
                    "kept_files": [e["path"] for e in kept], "snapshot": snapshot})
