"""Multi-level undo / redo of the open gamelist.xml.

Every write of the gamelist (``xml_store.save_xml``, ``backups.restore_snapshot``)
goes through :func:`before_write` / :func:`after_write`. The writes of one HTTP
request form one step (a bulk edit is one step, not one per game); the steps of
one batch scrape (one request per game) are merged into one step by their
``scope`` key. Each step keeps the file's bytes before and after, compressed
(zlib) and shared with the neighbouring steps, so 30 steps of a big gamelist
stay small in memory. The history lives in memory, one per gamelist path; the
dated snapshots of ``gme.backups`` stay the durable safety net.

Undo writes the "before" bytes back atomically, only when the file on disk is
still exactly the "after" of that step: a gamelist changed outside GME (another
tool, a sync, ES itself) resets the history instead of losing that change.
Redo is the mirror and a new edit drops the steps that were undone.

What the XML history cannot put back is recorded with the step and shown:
files moved to the Recycle Bin and media files written stay as they are. Image
edits are the exception: their originals are kept (``gme.imageedit``), so undo
restores them too (that step then cannot be redone).

Routes: ``GET /api/history``, ``POST /api/history/undo``, ``POST /api/history/redo``
(``{"expect": id}`` refuses when the step to undo is not that one, ``{"to": id}``
undoes / redoes up to that step).
"""

import hashlib
import os
import threading
import time
import uuid
import zlib
from collections import OrderedDict

from flask import Blueprint, g as flask_g, has_request_context, jsonify, request

from gme.i18n import st
from gme.http import api_err

bp = Blueprint("history", __name__)

MAX_STEPS = 30
MAX_BYTES = 160 * 1024 * 1024          # compressed, for one gamelist
MAX_PATHS = 8                          # gamelists remembered (most recent first)
BUSY_SECONDS = 20                      # a batch step this recent: a batch is running

_lock = threading.RLock()
_stores = OrderedDict()                # normcase(path) -> _Store
_local = threading.local()
_rev = [0]
_busy = {"batch": 0.0}


class HistoryError(Exception):
    def __init__(self, key, status=409, **params):
        super().__init__(key)
        self.key, self.status, self.params = key, status, params


def _sha(data):
    return hashlib.sha1(data).hexdigest()


class _State:
    """One version of the file: compressed bytes and their hash."""
    __slots__ = ("sha", "size", "blob")

    def __init__(self, data, sha=None):
        self.sha = sha or _sha(data)
        self.size = len(data)
        self.blob = zlib.compress(data, 6)

    def data(self):
        return zlib.decompress(self.blob)


class _Entry:
    def __init__(self, before, key, label):
        self.id = uuid.uuid4().hex[:12]
        self.before = before
        self.after = None
        self.pending = None            # raw bytes of the last write, compressed by seal()
        self.pending_sha = None
        self.key = key
        self.label = label
        self.created = time.time()
        self.merged = 1
        self.trashed = 0
        self.deleted = 0
        self.written = 0
        self.image_edits = []
        self.redo_blocked = False

    def set_after(self, data):
        self.pending, self.pending_sha, self.after = data, _sha(data), None

    def after_sha(self):
        return self.pending_sha if self.pending is not None else self.after.sha

    def seal(self):
        if self.pending is not None:
            if self.pending_sha == self.before.sha:
                self.after = self.before
            else:
                self.after = _State(self.pending, self.pending_sha)
            self.pending = self.pending_sha = None

    def changes_xml(self):
        return self.after_sha() != self.before.sha

    def public(self, done):
        return {"id": self.id, "label": self.label, "created": self.created, "done": done,
                "merged": self.merged, "trashed": self.trashed, "deleted": self.deleted, "written": self.written,
                "image_edit": bool(self.image_edits), "xml": self.changes_xml(),
                "redo_blocked": self.redo_blocked}


class _Store:
    def __init__(self):
        self.entries = []
        self.pos = 0                   # entries[:pos] are done, entries[pos:] can be redone

    def top(self):
        return self.entries[self.pos - 1] if self.pos else None

    def reset(self):
        self.entries, self.pos = [], 0

    def trim(self):
        for e in self.entries:
            if e is not self.top():
                e.seal()
        while len(self.entries) > MAX_STEPS:
            self._drop_oldest()
        while len(self.entries) > 1 and self._bytes() > MAX_BYTES:
            self._drop_oldest()

    def _drop_oldest(self):
        self.entries.pop(0)
        self.pos = max(0, self.pos - 1)

    def _bytes(self):
        seen, total = set(), 0
        for e in self.entries:
            for s in (e.before, e.after):
                if s is not None and id(s) not in seen:
                    seen.add(id(s))
                    total += len(s.blob)
            if e.pending is not None:
                total += len(e.pending) // 4
        return total


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _store(path, create=True):
    k = _key(path)
    with _lock:
        store = _stores.get(k)
        if store is None and create:
            store = _stores[k] = _Store()
            while len(_stores) > MAX_PATHS:
                _stores.popitem(last=False)
        if store is not None:
            _stores.move_to_end(k)
        return store


def _bump():
    _rev[0] += 1


def revision():
    return _rev[0]


def reset_all():
    """Forget every history (tests)."""
    with _lock:
        _stores.clear()
        _busy["batch"] = 0.0
        _bump()


# --- the current request / thread group -------------------------------------------

class _Group:
    __slots__ = ("entry", "path", "key", "label", "trashed", "deleted", "written", "image_edits", "before")

    def __init__(self):
        self.entry = self.path = self.key = self.label = self.before = None
        self.trashed = self.deleted = self.written = 0
        self.image_edits = []


def _group(create=True):
    if has_request_context():
        grp = flask_g.get("_gme_history")
        if grp is None and create:
            grp = flask_g._gme_history = _Group()
        return grp
    grp = getattr(_local, "group", None)
    if grp is None and create:
        grp = _local.group = _Group()
    return grp


def label(key, weak=False, **params):
    """Name the step of the current request: an ``history.*`` locale key and its
    parameters, translated by the page (``field`` is a field name). A ``weak``
    label does not replace one already set (a batch step names the batch)."""
    text = {"key": key, "params": params}
    grp = _group()
    if weak and grp.label is not None:
        return
    grp.label = text
    if grp.entry is not None:
        with _lock:
            grp.entry.label = text
            _bump()


def game_name(game):
    name = (game.findtext("name", "") or "").strip()
    return name or os.path.basename((game.findtext("path", "") or "").strip()) or "?"


def scope(key):
    """Merge the steps of consecutive requests with the same ``key`` (a batch)."""
    _group().key = key
    if str(key).startswith("batch:"):
        _busy["batch"] = time.time()


def note_trash(n=1):
    _group().trashed += n


def note_deleted(n=1):
    _group().deleted += n


def note_written(n=1):
    _group().written += n


def note_image_edit(edit_id):
    """An image edit (its originals are kept for undo) belongs to this step."""
    from gme import xml_store
    grp = _group()
    grp.image_edits.append(edit_id)
    if grp.entry is None and xml_store.XML_PATH:
        # Only media changed: a step whose XML did not change.
        with xml_store.operation_lock():
            data = _read(xml_store.XML_PATH)
            if data is not None:
                _open_entry(grp, xml_store.XML_PATH, data)
                grp.entry.set_after(data)
    _apply_group(grp)


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def before_write(path):
    """The gamelist ``path`` is about to be written (xml lock held)."""
    grp = _group()
    if grp.entry is not None and grp.path == _key(path):
        return
    grp.before = _read(path)


def after_write(path, data):
    """``data`` was written to ``path`` (xml lock held)."""
    grp = _group()
    if grp.entry is None or grp.path != _key(path):
        before = grp.before
        grp.before = None
        if before is None:             # no previous file: nothing to go back to
            return
        _open_entry(grp, path, before)
    with _lock:
        grp.entry.set_after(data)
        _apply_group(grp)
        _bump()
    if not has_request_context():
        finish()


def _open_entry(grp, path, before):
    with _lock:
        store = _store(path)
        sha = _sha(before)
        top = store.top()
        if (grp.key and top is not None and top.key == grp.key and store.pos == len(store.entries)
                and top.after_sha() == sha and not top.image_edits):
            top.merged += 1
            grp.entry, grp.path = top, _key(path)
            return
        del store.entries[store.pos:]                  # a new edit: no more redo
        state = None
        if top is not None:
            top.seal()
            if top.after.sha == sha:
                state = top.after                      # shared with the previous step
            else:
                store.reset()                          # changed outside GME meanwhile
        entry = _Entry(state or _State(before, sha), grp.key, grp.label or {"key": "change", "params": {}})
        store.entries.append(entry)
        store.pos = len(store.entries)
        store.trim()
        grp.entry, grp.path = entry, _key(path)
        _bump()


def _apply_group(grp):
    e = grp.entry
    if e is None:
        return
    if grp.label:
        e.label = grp.label
    # counts noted since the last time (a merged batch step adds up)
    e.trashed += grp.trashed
    e.deleted += grp.deleted
    e.written += grp.written
    grp.trashed = grp.deleted = grp.written = 0
    for edit_id in grp.image_edits:
        if edit_id not in e.image_edits:
            e.image_edits.append(edit_id)
    grp.image_edits = []


def finish(error=None):
    """End of the request (teardown) or of a write outside a request."""
    if has_request_context():
        grp = flask_g.pop("_gme_history", None)
    else:
        grp = getattr(_local, "group", None)
        _local.group = None
    if grp is None or grp.entry is None:
        return
    with _lock:
        _apply_group(grp)
        e = grp.entry
        store = _store(grp.path, create=False)
        if store is None or e not in store.entries:
            return
        if store.top() is e and not e.changes_xml() and not e.image_edits and e.merged == 1:
            store.entries.remove(e)                    # wrote the same bytes: no step
            store.pos -= 1
        _bump()


# --- undo / redo ------------------------------------------------------------------

def mark_batch_activity():
    _busy["batch"] = time.time()


def _busy_reason():
    if time.time() - _busy["batch"] < BUSY_SECONDS:
        try:
            from gme import batch_jobs
            job = batch_jobs.load_job()
            if job and not job.get("halted") and job.get("i", 0) < len(job.get("targets") or []):
                return "history.busy_batch"
        except Exception:
            pass
    try:
        from gme import multibatch
        if multibatch._public()["state"] == "running":
            return "history.busy_multibatch"
    except Exception:
        pass
    return None


def status(path):
    with _lock:
        store = _store(path, create=False) if path else None
        entries = store.entries if store else []
        pos = store.pos if store else 0
        out = [e.public(i < pos) for i, e in enumerate(entries)]
        nxt = entries[pos] if store and pos < len(entries) else None
        return {
            "entries": out[::-1],
            "pos": pos,
            "undo": out[pos - 1] if pos else None,
            "redo": out[pos] if nxt is not None and not nxt.redo_blocked else None,
            "max": MAX_STEPS,
            "rev": _rev[0],
        }


def _move(direction, expect=None, to=None):
    """Undo (-1) or redo (+1) one or several steps; returns a result dict."""
    from gme import fsutil, imageedit, network, xml_store
    path = xml_store.XML_PATH
    if not path:
        raise HistoryError("server.no_gamelist", 400)
    reason = _busy_reason()
    if reason:
        raise HistoryError(reason, 409)
    with xml_store.operation_lock(), _lock:
        store = _store(path, create=False)
        if store is None:
            raise HistoryError("history.nothing_undo" if direction < 0 else "history.nothing_redo", 409)
        for e in store.entries:
            e.seal()
        steps = []
        if direction < 0:
            if not store.pos:
                raise HistoryError("history.nothing_undo", 409)
            if expect and store.top().id != expect:
                raise HistoryError("history.moved", 409)
            ids = [e.id for e in store.entries[:store.pos]]
            count = (store.pos - ids.index(to)) if to in ids else 1
        else:
            if store.pos >= len(store.entries) or store.entries[store.pos].redo_blocked:
                raise HistoryError("history.nothing_redo", 409)
            ids = [e.id for e in store.entries[store.pos:]]
            count = (ids.index(to) + 1) if to in ids else 1
        current = _read(path)
        if current is None:
            raise HistoryError("server.xml_missing", 409, path=path)
        current_sha = _sha(current)
        trashed = deleted = written = restored = 0
        paths, warnings = [], []
        for _ in range(count):
            if direction < 0:
                if not store.pos:
                    break
                e = store.entries[store.pos - 1]
                expected, target = e.after, e.before
            else:
                if store.pos >= len(store.entries) or store.entries[store.pos].redo_blocked:
                    break
                e = store.entries[store.pos]
                expected, target = e.before, e.after
            if current_sha != expected.sha:
                store.reset()
                _bump()
                raise HistoryError("history.external", 409)
            if direction < 0 and e.image_edits:
                for edit_id in reversed(e.image_edits):
                    try:
                        n, done_paths = imageedit.restore_files(edit_id)
                        restored += n
                        paths.extend(done_paths)
                    except imageedit.EditError as exc:     # originals pruned
                        warnings.append(st(exc.key, **exc.params))
                    except OSError as exc:
                        warnings.append(str(exc))
                e.redo_blocked = True
            if target.sha != current_sha:
                fsutil.atomic_write(path, target.data())
                current_sha = target.sha
            trashed += e.trashed
            deleted += e.deleted
            written += e.written
            store.pos += direction
            steps.append(e.public(direction > 0))
        xml_store.set_gamelist_path(path)              # new session: open tabs reload
        network.after_save(path)
        _bump()
    return {"success": True, "steps": steps, "trashed": trashed, "deleted": deleted, "written": written,
            "restored": restored, "paths": paths, "warnings": warnings,
            "session_id": xml_store.SESSION_ID}


def undo(expect=None, to=None):
    return _move(-1, expect, to)


def redo(to=None):
    return _move(+1, None, to)


# --- routes -----------------------------------------------------------------------

def _body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _route(fn):
    from gme import xml_store
    err = xml_store.require_gamelist()
    if err:
        return err
    try:
        result = fn()
    except HistoryError as e:
        return api_err(st(e.key, **e.params), e.status, code=e.key.replace(".", "_"))
    except OSError as e:
        return api_err(str(e), 500, code="write_failed")
    result.update(status(xml_store.XML_PATH))
    return jsonify(result)


@bp.route("/api/history")
def api_history():
    from gme import xml_store
    return jsonify(status(xml_store.XML_PATH if xml_store.has_gamelist() else None))


@bp.route("/api/history/undo", methods=["POST"])
def api_history_undo():
    body = _body()
    expect = body.get("expect") if isinstance(body.get("expect"), str) else None
    to = body.get("to") if isinstance(body.get("to"), str) else None
    return _route(lambda: undo(expect, to))


@bp.route("/api/history/redo", methods=["POST"])
def api_history_redo():
    body = _body()
    to = body.get("to") if isinstance(body.get("to"), str) else None
    return _route(lambda: redo(to))


def add_revision_header(response):
    """``X-GME-History``: the page refreshes its Undo / Redo buttons when it changes."""
    response.headers["X-GME-History"] = str(_rev[0])
    grp = flask_g.get("_gme_history") if has_request_context() else None
    if grp is not None and grp.entry is not None:
        response.headers["X-GME-History-Step"] = grp.entry.id   # the toast's Undo targets it
    return response
