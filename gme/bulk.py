"""Operations on many games at once (Actions › Edit in bulk, selection bar).

POST /api/bulk/preview          {"paths": [...], "op": {...}}
POST /api/bulk                  same body: applies it, one backup, one write
POST /api/bulk-delete/preview   {"paths": [...], "media": false}
POST /api/bulk-delete           {"paths": [...], "media": false, "trash": true}

Games are designated by their <path> (every game with that path). ``op``:

- ``{"kind": "set", "field": "genre", "value": "Shoot'em up"}``: one value for
  every game; ``""`` (or ``false`` for favorite / hidden / kidgame) removes the tag.
  ``releasedate`` takes ``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``.
- ``{"kind": "replace", "fields": ["name", "desc"] | "all", "find": "…",
  "replace": "…", "regex": false, "case": false}``: plain text or a Python
  regular expression (``\\1`` in the replacement), case-insensitive by default.
- ``{"kind": "reset_name", "strip_tags": true}``: the name becomes the ROM
  file name without its extension; ``strip_tags`` also removes ``(…)`` and
  ``[…]`` groups such as ``(Europe)`` or ``[!]``.
- ``{"kind": "clear_media", "fields": ["video", …]}``: removes the tags; the
  files stay on disk (``/api/clear`` does the same for one game).

Every apply first makes a dated snapshot (Actions › Backups) and returns its
id, which the interface uses to undo with ``/api/backups/restore``. A preview
lists the changes (the first ``PREVIEW_ROWS``) and changes nothing.

Removing games takes their entries out of gamelist.xml. ROM files are never
deleted here. With ``"media": true`` the media files only they use go to the
Recycle Bin (``"trash": true``, the default); a file another game still
points to, a file outside the gamelist folder or a ROM is kept.
"""

import os
import re

from flask import Blueprint, jsonify, request

from gme import fsutil, xml_store
from gme.fields import FieldError, clean_meta, set_desc, set_meta, set_name
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.media import NOT_FILE_TAGS, file_key
from gme.xml_store import BOOL_META_FIELDS, MEDIA_DIRS, load_xml, require_gamelist, resolve_under_base, save_xml

bp = Blueprint("bulk", __name__)

PREVIEW_ROWS = 300
MAX_FIND = 1000
SET_FIELDS = ("genre", "developer", "publisher", "releasedate", "rating", "players", "lang", "region",
              "family", "arcadesystemname", "favorite", "hidden", "kidgame")
REPLACE_FIELDS = ("name", "desc", "genre", "developer", "publisher", "players", "lang", "region",
                  "family", "arcadesystemname")
_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_ES_DATE = re.compile(r"^\d{8}T\d{6}$")
_TAGS = re.compile(r"\s*[\(\[][^\(\)\[\]]*[\)\]]")
_SPACES = re.compile(r"\s+")


class BulkError(ValueError):
    """A refused operation: (message key, params)."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key, self.params = key, params


def _paths(body):
    paths = body.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise BulkError("bulk.no_games")
    return set(paths)


def _targets(tree, paths):
    return [g for g in tree.getroot().findall("game") if (g.findtext("path", "") or "") in paths]


# --- What each operation does to one game -------------------------------------

def _es_date(value):
    if value == "" or _ES_DATE.match(value):
        return value
    m = _DATE.match(value)
    if not m:
        raise BulkError("bulk.bad_date", value=value)
    year, month, day = m.group(1), m.group(2) or "01", m.group(3) or "01"
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        raise BulkError("bulk.bad_date", value=value)
    return f"{year}{month}{day}T000000"


def _set_op(op):
    field = op.get("field")
    if field not in SET_FIELDS:
        raise BulkError("bulk.bad_field")
    value = op.get("value")
    if field in BOOL_META_FIELDS:
        value = "true" if value is True or str(value).lower() in ("true", "1", "yes", "on") else ""
    else:
        value = str(value if value is not None else "").strip()
        if field == "releasedate":
            value = _es_date(value)
        else:
            try:
                value = clean_meta({field: value})[field]
            except FieldError as e:
                raise BulkError("server." + ("rating_invalid_value" if e.code == "rating_invalid"
                                             else "rating_range_value"), value=value)

    def change(game):
        before = game.findtext(field, "") or ""
        if field in BOOL_META_FIELDS:
            same = (before.strip().lower() in ("true", "1", "yes")) == (value == "true")
        else:
            same = before == value
        return [] if same else [(field, before, value)]

    def write(game, _field, after):
        set_meta(game, {field: after})
    return change, write


def _replace_op(op):
    fields = op.get("fields")
    if fields == "all":
        fields = list(REPLACE_FIELDS)
    if not isinstance(fields, list) or not fields or any(f not in REPLACE_FIELDS for f in fields):
        raise BulkError("bulk.bad_field")
    find = op.get("find")
    repl = op.get("replace")
    repl = "" if repl is None else str(repl)
    if not isinstance(find, str) or not find or len(find) > MAX_FIND:
        raise BulkError("bulk.no_find")
    flags = 0 if op.get("case") else re.IGNORECASE
    if op.get("regex"):
        try:
            pattern = re.compile(find, flags)
        except re.error as e:
            raise BulkError("bulk.bad_regex", detail=str(e))
        sub = lambda text: pattern.sub(repl, text)  # noqa: E731
    else:
        pattern = re.compile(re.escape(find), flags)
        sub = lambda text: pattern.sub(lambda _m: repl, text)  # noqa: E731

    def change(game):
        out = []
        for field in fields:
            before = game.findtext(field, "") or ""
            if not before or not pattern.search(before):
                continue
            try:
                after = sub(before)
            except (re.error, IndexError) as e:
                raise BulkError("bulk.bad_regex", detail=str(e))
            if field != "desc":
                after = after.strip()
            if after == before or (field == "name" and not after):
                continue                         # a game never loses its name
            out.append((field, before, after))
        return out

    def write(game, field, after):
        if field == "name":
            set_name(game, after)
        elif field == "desc":
            if after.strip():
                set_desc(game, after)
            elif game.find("desc") is not None:
                game.remove(game.find("desc"))
        else:
            if field == "lang":
                after = after.lower()
            set_meta(game, {field: after})
    return change, write


def clean_name(path, strip_tags=False):
    """The name a ROM file gives: its file name without extension (and tags)."""
    stem = os.path.splitext(os.path.basename((path or "").replace("\\", "/").rstrip("/")))[0].strip()
    if strip_tags:
        stripped = _SPACES.sub(" ", _TAGS.sub("", stem)).strip(" -_.")
        if stripped:
            return stripped
    return stem


def _reset_name_op(op):
    strip_tags = bool(op.get("strip_tags"))

    def change(game):
        before = game.findtext("name", "") or ""
        after = clean_name(game.findtext("path", "") or "", strip_tags)
        return [("name", before, after)] if after and after != before else []

    def write(game, _field, after):
        set_name(game, after)
    return change, write


def _clear_media_op(op):
    fields = op.get("fields")
    if not isinstance(fields, list) or not fields or any(f not in MEDIA_DIRS for f in fields):
        raise BulkError("bulk.bad_field")

    def change(game):
        return [(f, game.findtext(f, "") or "", "") for f in fields if (game.findtext(f, "") or "").strip()]

    def write(game, field, _after):
        for elem in game.findall(field):
            game.remove(elem)
    return change, write


OPS = {"set": _set_op, "replace": _replace_op, "reset_name": _reset_name_op, "clear_media": _clear_media_op}


def _operation(body):
    op = body.get("op")
    if not isinstance(op, dict) or op.get("kind") not in OPS:
        raise BulkError("bulk.bad_op")
    return OPS[op["kind"]](op)


def _plan(tree, body):
    paths = _paths(body)
    change, write = _operation(body)
    plan = []
    for game in _targets(tree, paths):
        for field, before, after in change(game):
            plan.append((game, field, before, after))
    return plan, write


def _row(game, field, before, after):
    return {"path": game.findtext("path", "") or "", "name": game.findtext("name", "") or "",
            "field": field, "before": before[:400], "after": after[:400]}


def _error(e):
    return api_err(st(e.key, **e.params), 400, code=e.key.replace(".", "_"))


@bp.route("/api/bulk/preview", methods=["POST"])
def api_bulk_preview():
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    try:
        plan, _write = _plan(load_xml(), body)
    except BulkError as e:
        return _error(e)
    return jsonify({
        "total": len(plan),
        "games": len({id(p[0]) for p in plan}),
        "changes": [_row(*p) for p in plan[:PREVIEW_ROWS]],
    })


@bp.route("/api/bulk", methods=["POST"])
def api_bulk_apply():
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    tree = load_xml()
    try:
        plan, write = _plan(tree, body)
    except BulkError as e:
        return _error(e)
    if not plan:
        return jsonify({"success": True, "changed": 0, "games": 0, "snapshot": None})
    try:
        _bak, snapshot = xml_store.backup_xml_snapshot()
    except Exception as e:
        return api_err(str(e), 500, code="backup_failed")
    for game, field, _before, after in plan:
        write(game, field, after)
    save_xml(tree)
    return jsonify({"success": True, "changed": len(plan), "games": len({id(p[0]) for p in plan}),
                    "snapshot": snapshot})


# --- Removing games -----------------------------------------------------------------

def _delete_plan(tree, paths, with_media):
    """Games to remove, and their media files: (games, media, kept)."""
    games = _targets(tree, paths)
    if not games:
        raise BulkError("bulk.no_games")
    removed = {id(g) for g in games}
    protected, kept_keys = set(), set()
    for game in tree.getroot().findall("game"):
        rom = file_key(game.findtext("path", "") or "")
        if rom:
            protected.add(rom)                     # a ROM is never deleted, whoever points to it
        if id(game) in removed:
            continue
        for child in game:
            if isinstance(child.tag, str) and child.tag not in NOT_FILE_TAGS and child.text:
                key = file_key(child.text)
                if key:
                    kept_keys.add(key)              # still used by a game that stays
    media, kept, seen = [], [], set()
    if with_media:
        for game in games:
            for child in game:
                if not isinstance(child.tag, str) or child.tag in NOT_FILE_TAGS or child.tag == "path" \
                        or not child.text:
                    continue
                key = file_key(child.text)
                if not key or key in seen:
                    continue
                seen.add(key)
                full = resolve_under_base(child.text.strip())
                if not full or not os.path.isfile(full):
                    continue
                entry = {"path": child.text.strip(), "full": full, "size": os.path.getsize(full)}
                (kept if key in kept_keys or key in protected else media).append(entry)
    return games, media, kept


def _public(entries):
    return [{"path": e["path"], "size": e["size"]} for e in entries]


@bp.route("/api/bulk-delete/preview", methods=["POST"])
def api_bulk_delete_preview():
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    try:
        games, media, kept = _delete_plan(load_xml(), _paths(body), bool(body.get("media")))
    except BulkError as e:
        return _error(e)
    return jsonify({
        "games": len(games),
        "names": [g.findtext("name", "") or g.findtext("path", "") or "" for g in games[:PREVIEW_ROWS]],
        "media": _public(media[:PREVIEW_ROWS]), "media_total": len(media),
        "media_bytes": sum(e["size"] for e in media),
        "kept": _public(kept[:PREVIEW_ROWS]), "kept_total": len(kept),
    })


@bp.route("/api/bulk-delete", methods=["POST"])
def api_bulk_delete():
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    use_trash = body.get("trash", True) is not False
    tree = load_xml()
    try:
        games, media, kept = _delete_plan(tree, _paths(body), bool(body.get("media")))
    except BulkError as e:
        return _error(e)
    try:
        _bak, snapshot = xml_store.backup_xml_snapshot()
    except Exception as e:
        return api_err(str(e), 500, code="backup_failed")
    deleted, failed = [], []
    for entry in media:
        try:
            if use_trash:
                fsutil.trash(entry["full"])
            else:
                os.remove(entry["full"])
            deleted.append(entry["path"])
        except Exception as e:  # no Recycle Bin on this drive, locked file: the file stays
            log.warning("Bulk delete: could not delete %s (%s)", entry["full"], e)
            failed.append(entry["path"])
    root = tree.getroot()
    for game in games:
        root.remove(game)
    save_xml(tree)
    return jsonify({"success": True, "removed": len(games), "deleted_files": deleted,
                    "failed_files": failed, "kept_files": [e["path"] for e in kept],
                    "trash": use_trash, "snapshot": snapshot})
