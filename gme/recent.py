"""Recently opened gamelists, kept on disk next to the .exe / app.py.

They used to live in the browser's localStorage, which the app window can
lose: Quit stops the window process before it has written its storage to
disk. ``recent_gamelists.json`` is written by the server each time a
gamelist is opened, whatever the browser.
"""

import json
import os
import threading

from flask import Blueprint, jsonify, request

from gme.fsutil import atomic_write
from gme.log import log
from gme.paths import APP_DIR

bp = Blueprint("recent", __name__)

RECENT_FILE = os.path.join(APP_DIR, "recent_gamelists.json")
RECENT_MAX = 12          # the dialog shows the 10 most recent other than the open one
_lock = threading.Lock()


def _key(path):
    """Same file whatever the case or slashes on Windows."""
    return os.path.normcase(os.path.normpath(path))


def _read():
    try:
        with open(RECENT_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [p for p in data if isinstance(p, str) and p] if isinstance(data, list) else []


def _write(paths):
    try:
        atomic_write(RECENT_FILE, json.dumps(paths[:RECENT_MAX], ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError as e:
        log.warning("Could not save the recent gamelists (%s)", e)


def recent_paths():
    with _lock:
        return _read()


def remember(path, at_end=False):
    """Put ``path`` first (or last, for imported entries) without duplicates."""
    if not path:
        return
    path = os.path.abspath(path)
    with _lock:
        paths = _read()
        if at_end:
            if not any(_key(p) == _key(path) for p in paths):
                _write(paths + [path])
            return
        _write([path] + [p for p in paths if _key(p) != _key(path)])


def forget(path):
    with _lock:
        paths = _read()
        kept = [p for p in paths if _key(p) != _key(path)]
        if len(kept) != len(paths):
            _write(kept)


@bp.route("/api/recent")
def api_recent():
    return jsonify({"recent": [{"path": p, "exists": os.path.isfile(p)} for p in recent_paths()]})


@bp.route("/api/recent/forget", methods=["POST"])
def api_recent_forget():
    body = request.get_json(silent=True) or {}
    forget(str(body.get("path") or ""))
    return api_recent()


@bp.route("/api/recent/import", methods=["POST"])
def api_recent_import():
    """One-time move of the list the browser kept (oldest versions) to the file."""
    body = request.get_json(silent=True) or {}
    paths = body.get("paths")
    if isinstance(paths, list):
        for p in paths[:RECENT_MAX]:
            if isinstance(p, str) and p.strip():
                remember(p.strip(), at_end=True)
    return api_recent()
