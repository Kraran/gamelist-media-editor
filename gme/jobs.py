"""Background analyses with progress and Stop.

A long read-only scan (solid-colour images, ROM check, media check) runs in a
thread: the request that starts it answers at once with the job, the page polls
``GET /api/jobs/<id>`` for ``done`` / ``total`` / ``current`` and can call
``POST /api/jobs/<id>/stop``. A job never writes anything: its result is a
report, and the apply route that uses it checks the gamelist did not change
since (session and file stamp) before writing, all at once. Stopping a scan
therefore leaves every file as it was.

The routes of this blueprint take no gamelist lock: Stop never waits for the
scan, and polling stays instant.
"""

import logging
import os
import threading
import time
import uuid

from flask import Blueprint, jsonify

from gme import xml_store
from gme.http import api_err
from gme.i18n import get_request_locale, locale_scope, st

log = logging.getLogger("gme")
bp = Blueprint("jobs", __name__)

KEEP = 12                       # finished jobs remembered (their result is fetched once)
MAX_AGE = 15 * 60               # a result older than this is scanned again by apply

_lock = threading.Lock()
_jobs = {}


class Cancelled(Exception):
    """Raised by ``Job.tick`` once Stop was asked."""


def gamelist_stamp():
    """What must not change between a scan and the apply that reuses it."""
    path = xml_store.XML_PATH
    try:
        st_ = os.stat(path) if path else None
    except OSError:
        st_ = None
    return (xml_store.SESSION_ID, path, st_.st_mtime_ns if st_ else None, st_.st_size if st_ else None)


class Job:
    def __init__(self, kind, params):
        self.id = uuid.uuid4().hex[:16]
        self.kind = kind
        self.params = params
        self.state = "running"
        self.done = 0
        self.total = 0
        self.current = ""
        self.phase = ""
        self.result = None
        self.error = None
        self.started = time.time()
        self.finished = 0.0
        self.stamp = gamelist_stamp()
        self.bound = True       # tied to the open gamelist (an update download is not)
        self.unit = ""          # "MB": done / total are megabytes
        self.stop_event = threading.Event()

    def tick(self, done=None, total=None, current=None, phase=None):
        """Progress; raises ``Cancelled`` when Stop was asked."""
        if done is not None:
            self.done = done
        if total is not None:
            self.total = total
        if current is not None:
            self.current = str(current)
        if phase is not None:
            self.phase = phase
        if self.stop_event.is_set():
            raise Cancelled()

    def cancelled(self):
        return self.stop_event.is_set()

    def public(self, with_result=False):
        out = {"id": self.id, "kind": self.kind, "state": self.state, "done": self.done, "total": self.total,
               "current": self.current, "phase": self.phase, "error": self.error,
               "elapsed": round((self.finished or time.time()) - self.started, 2)}
        if self.unit:
            out["unit"] = self.unit
        if with_result and self.state == "done":
            out["result"] = self.result
        return out


def start(kind, fn, params=None, bound=True, unit=""):
    """Run ``fn(job)`` in a thread; its return value becomes ``job.result``.

    A running job of the same kind is stopped first (one scan of a kind at once).
    ``bound=False``: the result stays valid when another gamelist is opened.
    """
    job = Job(kind, params or {})
    job.bound, job.unit = bound, unit
    locale = get_request_locale()
    with _lock:
        for other in _jobs.values():
            if other.kind == kind and other.state == "running":
                other.stop_event.set()
        _jobs[job.id] = job
        done = sorted((j for j in _jobs.values() if j.state != "running"), key=lambda j: j.started)
        for old in done[:-KEEP] if len(done) > KEEP else []:
            _jobs.pop(old.id, None)

    def run():
        with locale_scope(locale):
            try:
                result = fn(job)
                if job.stop_event.is_set():
                    job.state = "stopped"
                elif job.bound and job.stamp[0] != xml_store.SESSION_ID:
                    job.state, job.error = "error", st("server.stale_gamelist")
                else:
                    job.result, job.state = result, "done"
            except Cancelled:
                job.state = "stopped"
            except Exception as e:  # shown to the user, logged
                log.exception("Job %s failed", kind)
                job.state, job.error = "error", str(e)
            finally:
                job.finished = time.time()

    threading.Thread(target=run, name="gme-job-" + kind, daemon=True).start()
    return job


def get(job_id):
    with _lock:
        return _jobs.get(job_id) if isinstance(job_id, str) else None


def reusable(job_id, kind, params=None):
    """The finished result of ``job_id`` when it still describes the gamelist on disk."""
    job = get(job_id)
    if (job is None or job.kind != kind or job.state != "done" or job.stamp != gamelist_stamp()
            or time.time() - job.finished > MAX_AGE or (params is not None and job.params != params)):
        return None
    return job.result


def wait(job_id, timeout=20.0):
    """Block until the job ends (tests)."""
    end = time.time() + timeout
    job = get(job_id)
    while job is not None and job.state == "running" and time.time() < end:
        time.sleep(0.01)
    return job


def reset():
    with _lock:
        for job in _jobs.values():
            job.stop_event.set()
        _jobs.clear()


@bp.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = get(job_id)
    if job is None:
        return api_err(st("jobs.missing"), 404, code="job_missing")
    return jsonify({"job": job.public(with_result=True)})


@bp.route("/api/jobs/<job_id>/stop", methods=["POST"])
def api_job_stop(job_id):
    job = get(job_id)
    if job is None:
        return api_err(st("jobs.missing"), 404, code="job_missing")
    job.stop_event.set()
    return jsonify({"job": job.public()})
