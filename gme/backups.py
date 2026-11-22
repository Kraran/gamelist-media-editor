"""Dated XML snapshots next to each gamelist, with reversible restoration."""
import io
import os
import re
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from lxml import etree

from gme import xml_store
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st

bp = Blueprint("backups", __name__)
MAX_BACKUPS = 30
_ID = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{8}(?:-(?P<reason>backup|restore|legacy))?\.bak$")


def backup_dir():
    directory = os.path.join(xml_store.BASE_DIR, ".gme-backups", os.path.basename(xml_store.XML_PATH))
    base, real = os.path.realpath(xml_store.BASE_DIR), os.path.realpath(directory)
    if os.path.commonpath([base, real]) != base:
        raise ValueError(st("backups.invalid"))
    return directory


def _snapshot_name(created, reason="backup"):
    return created.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8] + "-" + reason + ".bak"


def _initialize_history():
    """Preserve a pre-existing .bak when upgrading to dated snapshots."""
    directory = backup_dir()
    initialized = os.path.join(directory, ".initialized")
    if os.path.isfile(initialized):
        return directory
    os.makedirs(directory, exist_ok=True)
    legacy = xml_store.XML_PATH + ".bak"
    if os.path.isfile(legacy) and not os.path.islink(legacy):
        created = datetime.fromtimestamp(os.path.getmtime(legacy), timezone.utc)
        with open(legacy, "rb") as stream:
            data = stream.read()
        atomic_write(os.path.join(directory, _snapshot_name(created, "legacy")), data)
    atomic_write(initialized, b"1")
    return directory


def snapshots():
    directory = _initialize_history()
    entries = []
    for name in sorted(os.listdir(directory), reverse=True):
        match = _ID.fullmatch(name)
        if not match:
            continue
        path = os.path.join(directory, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            created = datetime.strptime(name.split("-")[0], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        entries.append({"id": name, "created": created.isoformat(), "size": os.path.getsize(path),
                        "reason": match.group("reason") or "backup"})
    return entries


def create_snapshot(reason="backup"):
    """Called under the XML operation lock, before a bulk edit or restoration."""
    directory = _initialize_history()
    name = _snapshot_name(datetime.now(timezone.utc), reason)
    with open(xml_store.XML_PATH, "rb") as stream:
        data = stream.read()
    atomic_write(os.path.join(directory, name), data)
    for old in snapshots()[MAX_BACKUPS:]:
        os.remove(os.path.join(directory, old["id"]))
    return name


def restore_snapshot(name):
    """Put snapshot ``name`` back as the gamelist (under the operation lock).

    Returns the id of the snapshot taken of the replaced gamelist, or None
    when ``name`` does not exist. Raises ValueError / XMLSyntaxError when it
    is not a gamelist, OSError when it cannot be written. Opens a new session.
    """
    directory = backup_dir()
    path = os.path.join(directory, name)
    if not _ID.fullmatch(name) or os.path.islink(path) or not os.path.isfile(path):
        return None
    with open(path, "rb") as stream:
        data = stream.read()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    tree = etree.parse(io.BytesIO(data), parser)
    if tree.getroot().tag != "gameList":
        raise ValueError(st("backups.invalid"))
    # Read the selected bytes first: pruning can remove the oldest snapshot.
    previous = create_snapshot("restore")
    atomic_write(xml_store.XML_PATH, data)
    xml_store.set_gamelist_path(xml_store.XML_PATH)
    return previous


@bp.route("/api/backups")
def list_backups():
    err = xml_store.require_gamelist()
    if err:
        return err
    try:
        return jsonify({"backups": snapshots(), "limit": MAX_BACKUPS, "session_id": xml_store.SESSION_ID})
    except (OSError, ValueError) as exc:
        return api_err(str(exc), 500, code="backup_failed")


@bp.route("/api/backups/restore", methods=["POST"])
def restore_backup():
    err = xml_store.require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    name = body.get("id")
    if not isinstance(name, str) or not _ID.fullmatch(name):
        return api_err(st("backups.invalid"), 400, code="invalid_backup")
    try:
        previous = restore_snapshot(name)
        if previous is None:
            return api_err(st("backups.invalid"), 404, code="backup_missing")
        return jsonify({"success": True, "previous": previous, "session_id": xml_store.SESSION_ID})
    except (ValueError, etree.XMLSyntaxError):
        return api_err(st("backups.invalid"), 422, code="invalid_backup")
    except OSError as exc:
        return api_err(str(exc), 500, code="restore_failed")
