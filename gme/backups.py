"""Dated XML snapshots next to each gamelist (on this PC for a network share), with reversible restoration."""
import io
import os
import re
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from lxml import etree

from gme import history, network, xml_store
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st
from gme.paths import APP_DIR

bp = Blueprint("backups", __name__)
MAX_BACKUPS = 30
_ID = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{8}(?:-(?P<reason>backup|restore|legacy))?\.bak$")


def _safe(part):
    return re.sub(r"[^A-Za-z0-9._ -]", "_", part).strip(" .") or "_"


def network_backup_root():
    """Where the snapshots of the gamelists opened from a network share go."""
    return os.path.join(APP_DIR, ".gme-backups", "network")


def backup_dir():
    """Snapshots of a local gamelist: next to it, in ``.gme-backups/<xml name>``.

    A gamelist on a network share (Batocera, Recalbox…) keeps them on this PC,
    in ``.gme-backups/network/<host>/<share>/<folders>/<xml name>`` next to the
    app: a backup must survive the very thing it protects against (the machine
    going off the network, a full or reflashed SD card), restoring one must not
    depend on the network, and 30 snapshots would otherwise be written over
    Wi-Fi to the console's card and shown by its file manager.
    """
    loc = network.location(xml_store.XML_PATH)
    if loc:
        unc_path = network.unc_path_of(xml_store.XML_PATH) or xml_store.XML_PATH
        host, share, rest = network.split_unc(unc_path) if network.is_unc(unc_path) else (loc["host"], loc["share"], "")
        if not rest and loc.get("mount"):
            rest = os.path.relpath(xml_store.XML_PATH, loc["mount"])
        folders = [p for p in re.split(r"[\\/]+", rest)[:-1] if p and p not in (".", "..")]
        root = network_backup_root()
        directory = os.path.join(root, _safe(host.lower()), _safe(share.lower() or "_"),
                                 *[_safe(p) for p in folders], _safe(os.path.basename(xml_store.XML_PATH)))
        base, real = os.path.realpath(root), os.path.realpath(directory)
        if os.path.commonpath([base, real]) != base:
            raise ValueError(st("backups.invalid"))
        return directory
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
    xml_store._history_hook("before_write", xml_store.XML_PATH)
    atomic_write(xml_store.XML_PATH, data)
    xml_store._history_hook("after_write", xml_store.XML_PATH, data)
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
        history.label("restore", date=name[:15])
        previous = restore_snapshot(name)
        if previous is None:
            return api_err(st("backups.invalid"), 404, code="backup_missing")
        return jsonify({"success": True, "previous": previous, "session_id": xml_store.SESSION_ID})
    except (ValueError, etree.XMLSyntaxError):
        return api_err(st("backups.invalid"), 422, code="invalid_backup")
    except OSError as exc:
        return api_err(str(exc), 500, code="restore_failed")
