"""Actions on several systems of the overview, one system at a time.

``POST /api/multibatch`` starts a run on the ticked systems of the overview's
roms folder; ``GET /api/multibatch`` returns its progress and report;
``POST /api/multibatch/stop`` stops it after the step in progress.

Each system is opened like a click in the overview would, then the chosen
operations run through the very routes of the single-system tools (same
checks, same dated backup before every change, same Recycle Bin rules):

1. ``roms``   Check ROMs: add the ROMs missing from the gamelist, optionally
              remove the entries whose ROM is gone (and send their unused media
              to the Recycle Bin, opt-in). Like the single-system window, no
              entry is removed when more than half the ROMs look gone;
2. ``media``  Check media: remove the links to missing files, optionally send
              the unused media files to the Recycle Bin (opt-in), unless more
              than half the media look unused (shared folder?);
3. ``solid``  Solid images: remove the tags, optionally the unused files (opt-in);
4. ``clear``  Clear fields;
5. ``scrape`` the system's scraper (ScreenScraper unless arcade / Steam), as a
              batch of the games missing a chosen field (or every game in
              *replace* mode), stepped like the batch window does: the
              process-wide ``ss_limits.GATE`` keeps every request within the
              member's ``maxthreads``, requests per minute and daily quota. A
              quota, ban or blocked source stops the whole run, not only the
              system.

Every file deletion needs its option *and* ``confirm_delete`` (the dialog's
confirmation). When the run ends, the gamelist that was open before is opened
again. Only one run at a time.
"""

import os
import threading
import time

from flask import Blueprint, jsonify, request

from gme import overview, xml_store
from gme.bulk import CLEAR_FIELDS
from gme.http import api_err
from gme.i18n import get_request_locale, locale_scope, st
from gme.log import log
from gme.scrapers import sources, ss_limits
from gme.scrapers.compare import MEDIA_KEYS, META_KEYS
from gme.solidimages import IMAGE_FIELDS
from gme.systems import default_scraper

bp = Blueprint("multibatch", __name__)

ORDER = ("roms", "media", "solid", "clear", "scrape")
SCRAPE_FIELDS = set(MEDIA_KEYS) | set(META_KEYS)
_lock = threading.Lock()
_run = {"state": "idle", "id": 0, "systems": [], "ops": {}, "current": None, "halted": "",
        "started": 0.0, "finished": 0.0, "stop": None, "reopened": None}


def _public():
    with _lock:
        out = {k: v for k, v in _run.items() if k != "stop"}
        out["systems"] = [dict(s, steps=[dict(x) for x in s["steps"]]) for s in _run["systems"]]
        out["current"] = dict(_run["current"]) if _run["current"] else None
        return out


def options():
    return {"order": list(ORDER), "clear_fields": list(CLEAR_FIELDS), "image_fields": list(IMAGE_FIELDS),
            "scrape_fields": sorted(SCRAPE_FIELDS)}


# --- validation -----------------------------------------------------------------

def _bool(d, k):
    return bool(isinstance(d, dict) and d.get(k))


def parse_ops(raw):
    """Clean the requested operations; raises ValueError(key) on a bad request."""
    if not isinstance(raw, dict):
        raise ValueError("multibatch.no_ops")
    ops = {}
    r = raw.get("roms")
    if isinstance(r, dict) and (r.get("add") or r.get("remove")):
        ops["roms"] = {"add": _bool(r, "add"), "remove": _bool(r, "remove"),
                       "delete_media": _bool(r, "remove") and _bool(r, "delete_media")}
    m = raw.get("media")
    if isinstance(m, dict) and (m.get("unlink") or m.get("delete")):
        ops["media"] = {"unlink": _bool(m, "unlink"), "delete": _bool(m, "delete")}
    s = raw.get("solid")
    if isinstance(s, dict):
        fields = s.get("fields")
        if not isinstance(fields, list) or not fields or any(f not in IMAGE_FIELDS for f in fields):
            raise ValueError("bulk.bad_field")
        ops["solid"] = {"fields": list(dict.fromkeys(fields)), "files": _bool(s, "files")}
    c = raw.get("clear")
    if isinstance(c, dict):
        fields = c.get("fields")
        if not isinstance(fields, list) or not fields or any(f not in CLEAR_FIELDS for f in fields):
            raise ValueError("bulk.bad_field")
        ops["clear"] = {"fields": list(dict.fromkeys(fields))}
    sc = raw.get("scrape")
    if isinstance(sc, dict):
        fields = sc.get("fields")
        if (sc.get("mode") not in ("missing", "all") or not isinstance(fields, list) or not fields
                or any(f not in SCRAPE_FIELDS for f in fields)):
            raise ValueError("batch.invalid")
        ops["scrape"] = {"mode": sc["mode"], "fields": list(dict.fromkeys(fields)), "refresh": _bool(sc, "refresh")}
    if not ops:
        raise ValueError("multibatch.no_ops")
    return ops


def deletes_files(ops):
    return bool(ops.get("roms", {}).get("delete_media") or ops.get("media", {}).get("delete")
                or ops.get("solid", {}).get("files"))


# --- internal calls -------------------------------------------------------------

class _Client:
    """The app's own routes, called in-process (same checks, locks and backups)."""

    def __init__(self, locale):
        from gme.server import app
        self.client = app.test_client()
        self.headers = {"X-Locale": locale}

    def get(self, url):
        r = self.client.get(url, headers=self.headers)
        return r.status_code, r.get_json(silent=True) or {}

    def post(self, url, body):
        r = self.client.post(url, json=body, headers=self.headers)
        return r.status_code, r.get_json(silent=True) or {}


class _Halt(Exception):
    """Stop the whole run (quota, ban, blocked source)."""


def _err(data):
    return data.get("error") or st("errors.internal")


def _paths():
    return [g.findtext("path", "") or "" for g in xml_store.load_xml().getroot().findall("game")]


def _missing_any(game, fields):
    for f in fields:
        if f == "name":
            continue
        value = (game.findtext(f, "") or "").strip()
        if not value:
            return True
        if f in xml_store.MEDIA_DIRS and "://" not in value:
            full = xml_store.resolve_under_base(value)
            if not full or not os.path.isfile(full):
                return True
    return False


def mostly_missing(n, total, minimum):
    """Same rule as the single-system windows: nothing is ticked when more than
    half looks gone (unplugged drive, folder shared with another gamelist…)."""
    return n > minimum and n > total / 2


def _op_roms(c, opt):
    status, rep = c.get("/api/check-roms")
    if status >= 400:
        raise RuntimeError(_err(rep))
    suspicious = opt["remove"] and mostly_missing(len(rep["missing"]), rep["games"], 5)
    body = {"add": [u["path"] for u in rep["unlisted"]] if opt["add"] else [],
            "remove": [m["path"] for m in rep["missing"]] if opt["remove"] and not suspicious else [],
            "delete_media": opt["delete_media"], "backup": True}
    if not body["add"] and not body["remove"]:
        return {"nothing": True, "suspicious": len(rep["missing"])} if suspicious else {"nothing": True}
    status, data = c.post("/api/check-roms/apply", body)
    if status >= 400:
        raise RuntimeError(_err(data))
    return {**({"suspicious": len(rep["missing"])} if suspicious else {}),"added": data["added"], "removed": data["removed"], "media_deleted": data["media_deleted"],
            "backup": bool(data.get("backup"))}


def _op_media(c, opt):
    status, rep = c.get("/api/check-media")
    if status >= 400:
        raise RuntimeError(_err(rep))
    suspicious = opt["delete"] and mostly_missing(len(rep["orphans"]), rep["files"], 20)
    body = {"unlink": [{"path": b["path"], "tag": b["tag"]} for b in rep["broken"]] if opt["unlink"] else [],
            "delete": [o["path"] for o in rep["orphans"]] if opt["delete"] and not suspicious else [],
            "trash": True, "backup": True}
    extra = {"suspicious": len(rep["orphans"])} if suspicious else {}
    if not body["unlink"] and not body["delete"]:
        return {"nothing": True, **extra}
    status, data = c.post("/api/check-media/apply", body)
    if status >= 400:
        raise RuntimeError(_err(data))
    return {**extra,"unlinked": data["unlinked"], "deleted": data["deleted"], "failed": len(data["failed"]),
            "backup": bool(data.get("backup"))}


def _op_solid(c, opt):
    paths = _paths()
    if not paths:
        return {"nothing": True}
    status, data = c.post("/api/solid-images", {"paths": paths, "fields": opt["fields"], "files": opt["files"]})
    if status >= 400:
        raise RuntimeError(_err(data))
    if not data["removed"]:
        return {"nothing": True}
    return {"removed": data["removed"], "games": data["games"], "deleted": len(data["deleted_files"]),
            "kept": len(data["kept_files"]), "failed": len(data["failed_files"]), "backup": bool(data.get("snapshot"))}


def _op_clear(c, opt):
    paths = _paths()
    if not paths:
        return {"nothing": True}
    status, data = c.post("/api/bulk", {"paths": paths, "op": {"kind": "clear_fields", "fields": opt["fields"]}})
    if status >= 400:
        raise RuntimeError(_err(data))
    if not data["changed"]:
        return {"nothing": True}
    return {"changed": data["changed"], "games": data["games"], "backup": bool(data.get("snapshot"))}


def _blocked_halt(source):
    if source != "screenscraper":
        return None
    if sources.continue_on_ss_block():      # the fallback sources carry on alone
        return None
    reason = ss_limits.GATE.blocked()
    return st(reason[0]) if reason else None


def _op_scrape(c, opt, system, stop, progress):
    source = default_scraper(system["folder"])
    halt = _blocked_halt(source)
    if halt:
        raise _Halt(halt)
    status, saved = c.get("/api/batch")
    job = (saved or {}).get("job")
    if job and job.get("i", 0) < len(job.get("targets", [])):
        return {"skipped": "saved_batch", "source": source}   # never replace a batch left to resume
    games = xml_store.load_xml().getroot().findall("game")
    paths = list(dict.fromkeys(g.findtext("path", "") or "" for g in games
                               if opt["mode"] == "all" or _missing_any(g, opt["fields"])))
    paths = [p for p in paths if p]
    if not paths:
        return {"nothing": True, "source": source}
    status, data = c.post("/api/batch", {"source": source, "mode": opt["mode"], "fields": opt["fields"],
                                          "paths": paths, "backup": True, "refresh": opt["refresh"]})
    if status >= 400:
        raise RuntimeError(_err(data))
    job = data["job"]
    counts = {"updated": 0, "nothing": 0, "uncertain": 0, "errors": 0}
    i, total = job["i"], len(job["targets"])
    progress(0, total)
    try:
        while i < total:
            if stop.is_set():
                return dict(counts, source=source, total=total, done=i, stopped=True)
            status, step = c.post("/api/batch/step", {"id": job["id"], "owner": job["owner"], "i": i})
            if status >= 400:
                raise RuntimeError(_err(step))
            if "result" not in step:             # stopped between two games
                return dict(counts, source=source, total=total, done=i, stopped=True)
            counts[step["result"]["kind"]] = counts.get(step["result"]["kind"], 0) + 1
            i = step["i"]
            progress(i, total)
            if step.get("halted"):
                raise _Halt(step["halted"])
    finally:
        c.post("/api/batch/stop", {"id": job["id"], "owner": job["owner"]})
    return dict(counts, source=source, total=total, done=i)


OPS = {"roms": _op_roms, "media": _op_media, "solid": _op_solid, "clear": _op_clear}


# --- the run ----------------------------------------------------------------------

def _set_step(sys_i, op, **values):
    with _lock:
        for step in _run["systems"][sys_i]["steps"]:
            if step["op"] == op:
                step.update(values)


def _set_system(sys_i, **values):
    with _lock:
        _run["systems"][sys_i].update(values)


def _worker(run_id, locale, ops, stop, original):
    with locale_scope(locale):           # st() in the user's language
        _work(run_id, locale, ops, stop, original)


def _work(run_id, locale, ops, stop, original):
    c = _Client(locale)
    try:
        for n, system in enumerate(list(_run["systems"])):
            if stop.is_set():
                break
            with _lock:
                _run["current"] = {"index": n, "folder": system["folder"], "label": system["label"], "op": None,
                                   "done": 0, "total": 0}
            _set_system(n, state="running")
            status, data = c.post("/api/open-gamelist", {"path": system["xml"]})
            if status >= 400:
                _set_system(n, state="error", error=_err(data))
                continue
            c.headers["X-Gamelist-Session"] = data["session_id"]
            failed = False
            for op in ORDER:
                if op not in ops:
                    continue
                if stop.is_set():
                    break
                with _lock:
                    _run["current"].update(op=op, done=0, total=0)
                _set_step(n, op, state="running")

                def progress(done, total):
                    with _lock:
                        if _run["current"]:
                            _run["current"].update(done=done, total=total)
                try:
                    if op == "scrape":
                        result = _op_scrape(c, ops[op], system, stop, progress)
                    else:
                        result = OPS[op](c, ops[op])
                    _set_step(n, op, state="stopped" if result.get("stopped") else "done", result=result)
                except _Halt as h:
                    _set_step(n, op, state="error", error=str(h))
                    with _lock:
                        _run["halted"] = str(h)
                    stop.set()
                    _set_system(n, state="error")
                    return
                except Exception as e:                 # one system's failure never stops the others
                    log.exception("multi-system: %s on %s failed", op, system["path"])
                    _set_step(n, op, state="error", error=str(e)[:400])
                    failed = True
            _set_system(n, state="stopped" if stop.is_set() else ("error" if failed else "done"))
    finally:
        with _lock:
            for s in _run["systems"]:
                if s["state"] == "pending":
                    s["state"] = "skipped"
                for step in s["steps"]:
                    if step["state"] == "pending":
                        step["state"] = "skipped"
        # Back to the gamelist that was open before (or none).
        reopened = None
        try:
            if original and os.path.isfile(original):
                xml_store.set_gamelist_path(original)
                reopened = original
            else:
                xml_store.close_gamelist()
        except Exception as e:
            log.warning("multi-system: could not reopen %s (%s)", original, e)
        with _lock:
            if _run["id"] == run_id:
                _run["state"] = "halted" if _run["halted"] else ("stopped" if stop.is_set() else "done")
                _run["current"] = None
                _run["finished"] = time.time()
                _run["reopened"] = reopened


def start(xmls, ops, locale):
    root = overview.current_root()
    if not root:
        raise ValueError("multibatch.no_root")
    known = {overview._key(s["xml"]): s for s in overview.list_systems(root) if s["xml"]}
    systems = []
    for x in dict.fromkeys(xmls):
        s = known.get(overview._key(x)) if isinstance(x, str) else None
        if not s:
            raise ValueError("multibatch.bad_system")
        systems.append(s)
    if not systems:
        raise ValueError("multibatch.no_systems")
    stop = threading.Event()
    with _lock:
        if _run["state"] == "running":
            raise RuntimeError("multibatch.running")
        _run.update({
            "state": "running", "id": _run["id"] + 1, "ops": ops, "halted": "", "current": None,
            "started": time.time(), "finished": 0.0, "stop": stop, "root": root, "reopened": None,
            "systems": [{"folder": s["folder"], "label": s["label"], "xml": s["xml"], "path": s["path"],
                         "state": "pending", "error": None,
                         "steps": [{"op": op, "state": "pending", "result": None, "error": None}
                                   for op in ORDER if op in ops]} for s in systems],
        })
        run_id = _run["id"]
    original = xml_store.XML_PATH if xml_store.has_gamelist() else None
    threading.Thread(target=_worker, args=(run_id, locale, ops, stop, original), daemon=True,
                     name="gme-multibatch").start()
    return _public()


def wait(timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if _public()["state"] != "running":
            return True
        time.sleep(0.02)
    return False


def reset():
    with _lock:
        if _run["stop"] is not None:
            _run["stop"].set()
    wait(10)
    with _lock:
        _run.update({"state": "idle", "systems": [], "ops": {}, "current": None, "halted": "", "stop": None,
                     "reopened": None})


# --- routes -----------------------------------------------------------------------

@bp.route("/api/multibatch")
def api_multibatch():
    data = _public()
    data["options"] = options()
    return jsonify(data)


@bp.route("/api/multibatch", methods=["POST"])
def api_multibatch_start():
    body = request.get_json(silent=True) or {}
    try:
        ops = parse_ops(body.get("ops"))
        if deletes_files(ops) and body.get("confirm_delete") is not True:
            return api_err(st("multibatch.confirm_needed"), 400, code="confirm_needed")
        systems = body.get("systems")
        if not isinstance(systems, list):
            raise ValueError("multibatch.no_systems")
        return jsonify(start(systems, ops, get_request_locale()))
    except ValueError as e:
        return api_err(st(str(e)), 400, code=str(e).replace(".", "_"))
    except RuntimeError as e:
        return api_err(st(str(e)), 409, code="multibatch_running")


@bp.route("/api/multibatch/stop", methods=["POST"])
def api_multibatch_stop():
    with _lock:
        if _run["stop"] is not None and _run["state"] == "running":
            _run["stop"].set()
    return jsonify(_public())
