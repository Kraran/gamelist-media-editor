"""Interface settings, kept on disk next to the .exe / app.py (``ui_settings.json``).

GET  /api/settings   {"locale", "theme", "list_width", "search_all_fields",
                     "scrapers": {folder: source},
                     "required_media": {folder: [fields]}}
POST /api/settings   the same keys, each optional: ``locale`` and ``theme`` (dark, light,
                     system) replace the value; ``list_width`` is the width of the game
                     list in pixels (dragged by the user), ``null`` for the default;
                     ``search_all_fields`` (bool) makes the list search look in every
                     field (genre, developer…) instead of the name and ROM path only;
                     ``scrapers`` / ``required_media`` update one system folder at a time,
                     a ``null`` value going back to the automatic choice.

These used to live in the browser's localStorage, which the app window can
lose (see recent.py). Unknown values are refused, so a bad file or request
can never break the interface.
"""

import json
import os
import re
import threading

from flask import Blueprint, jsonify, request

from gme.fsutil import atomic_write
from gme.http import api_err
from gme.log import log
from gme.paths import APP_DIR
from gme.xml_store import MEDIA_DIRS

bp = Blueprint("settings", __name__)

SETTINGS_FILE = os.path.join(APP_DIR, "ui_settings.json")
SCRAPERS = ("screenscraper", "arcadeitalia", "steam")
THEMES = ("dark", "light", "system")
LIST_WIDTH_MIN, LIST_WIDTH_MAX = 260, 4000     # px; the page also keeps room for the editor
MEDIA_FIELDS = tuple(MEDIA_DIRS)
_LOCALE = re.compile(r"^[a-z]{2}$")
_FOLDER = re.compile(r"^[^\\/\x00-\x1f]{1,80}$")       # a system folder name, never a path
_lock = threading.Lock()


def _clean(data):
    """Only the known settings, with valid values."""
    data = data if isinstance(data, dict) else {}
    out = {"locale": None, "theme": "dark", "list_width": None, "search_all_fields": False,
           "scrapers": {}, "required_media": {}}
    if isinstance(data.get("locale"), str) and _LOCALE.match(data["locale"]):
        out["locale"] = data["locale"]
    if data.get("theme") in THEMES:
        out["theme"] = data["theme"]
    if _valid_list_width(data.get("list_width")):
        out["list_width"] = data["list_width"]
    if isinstance(data.get("search_all_fields"), bool):
        out["search_all_fields"] = data["search_all_fields"]
    for folder, source in (data.get("scrapers") or {}).items():
        if isinstance(folder, str) and _FOLDER.match(folder) and source in SCRAPERS:
            out["scrapers"][folder] = source
    for folder, fields in (data.get("required_media") or {}).items():
        if isinstance(folder, str) and _FOLDER.match(folder) and isinstance(fields, list):
            out["required_media"][folder] = [f for f in MEDIA_FIELDS if f in fields]
    return out


def _valid_list_width(value):
    return isinstance(value, int) and not isinstance(value, bool) and LIST_WIDTH_MIN <= value <= LIST_WIDTH_MAX


def load():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return _clean(json.load(f))
    except (OSError, ValueError):
        return _clean({})


def update(patch):
    """Apply ``patch`` (see the module doc) and save. Raises ValueError on a bad value."""
    if not isinstance(patch, dict):
        raise ValueError("settings must be an object")
    with _lock:
        cur = load()
        if "locale" in patch:
            if not (isinstance(patch["locale"], str) and _LOCALE.match(patch["locale"])):
                raise ValueError("locale")
            cur["locale"] = patch["locale"]
        if "theme" in patch:
            if patch["theme"] not in THEMES:
                raise ValueError("theme")
            cur["theme"] = patch["theme"]
        if "list_width" in patch:
            if not (patch["list_width"] is None or _valid_list_width(patch["list_width"])):
                raise ValueError("list_width")
            cur["list_width"] = patch["list_width"]
        if "search_all_fields" in patch:
            if not isinstance(patch["search_all_fields"], bool):
                raise ValueError("search_all_fields")
            cur["search_all_fields"] = patch["search_all_fields"]
        for key, valid in (("scrapers", lambda v: v in SCRAPERS),
                           ("required_media", lambda v: isinstance(v, list) and all(f in MEDIA_FIELDS for f in v))):
            changes = patch.get(key)
            if changes is None:
                continue
            if not isinstance(changes, dict):
                raise ValueError(key)
            for folder, value in changes.items():
                if not (isinstance(folder, str) and _FOLDER.match(folder)):
                    raise ValueError(key)
                if value is None:
                    cur[key].pop(folder, None)
                elif valid(value):
                    cur[key][folder] = value if key == "scrapers" else [f for f in MEDIA_FIELDS if f in value]
                else:
                    raise ValueError(key)
        try:
            atomic_write(SETTINGS_FILE, json.dumps(cur, ensure_ascii=False, indent=1).encode("utf-8"))
        except OSError as e:
            log.warning("Could not save the settings (%s)", e)
        return cur


@bp.route("/api/settings")
def api_get_settings():
    return jsonify(load())


@bp.route("/api/settings", methods=["POST"])
def api_set_settings():
    try:
        return jsonify(update(request.get_json(silent=True)))
    except ValueError as e:
        return api_err(f"invalid setting: {e}", 400, code="invalid_setting")
