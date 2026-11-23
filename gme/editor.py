"""Editor routes: game list, gamelist switching, media and metadata editing, whole-gamelist actions."""

import os
import re
import sys
import threading
import time

import requests
from flask import Blueprint, Response, jsonify, render_template, request, send_from_directory
from lxml import etree

from gme import csv_export, esde, recent, settings, xml_store
from gme.arcade import find_mame_listxml, index_mame_listxml, pretty_arcade_system
from gme.fields import FieldError, clean_meta, set_desc, set_meta, set_name
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.media import MAX_DOWNLOAD_BYTES, MEDIA_EXTS, default_ext_for_field, discard_old_media, download_remote_media, ext_from_magic, media_dest, remove_media
from gme.paths import resource_path
from gme.systems import get_system_info
from gme.version import APP_RELEASE_DATE, APP_VERSION
from gme.window import close_ui_window
from gme.xml_store import MEDIA_DIRS, backup_xml, get_base_name, get_game_elem, find_game_index_by_path, game_fields, get_games, has_gamelist, LIST_FIELDS, load_xml, require_gamelist, resolve_under_base, save_xml, set_gamelist_path

bp = Blueprint("editor", __name__)


# --- HTTP routes --------------------------------------------------------------
# JSON APIs return {ok:false, error, code?} on failure (see api_err).
# Mutating routes that need a loaded gamelist call require_gamelist() first.

@bp.route("/")
def index():
    prefs = settings.load()
    return render_template("index.html", app_version=APP_VERSION,
                           app_release_date=APP_RELEASE_DATE, theme=prefs["theme"],
                           list_width=prefs["list_width"])


@bp.route("/favicon.ico")
def favicon():
    """Browsers often request /favicon.ico at the site root."""
    static_dir = resource_path("static")
    return send_from_directory(static_dir, "favicon.ico", mimetype="image/x-icon")


@bp.route("/api/games")
def api_games():
    try:
        if not has_gamelist():
            return jsonify({
                "games": [],
                "system": None,
                "xml_path": None,
                "base_dir": None,
                "loaded": False,
                "session_id": xml_store.SESSION_ID,
            })
        return jsonify({
            "games": get_games(load_xml()),
            "system": get_system_info(),
            "xml_path": xml_store.XML_PATH,
            "base_dir": xml_store.BASE_DIR,
            "loaded": True,
            "session_id": xml_store.SESSION_ID,
        })
    except Exception as e:
        log.exception("api_games failed")
        return api_err(st("server.xml_read", detail=e), 500, code="xml_read")


@bp.route("/api/game/<int:index>")
def api_game(index):
    """Everything about one game, description included (not sent with the list).

    ``?path=`` identifies the game: if gamelist.xml changed and the game moved,
    the right one is returned (with its new index); if it is gone, 409.
    """
    err = require_gamelist()
    if err:
        return err
    games = load_xml().getroot().findall("game")
    expected = request.args.get("path")
    if expected is not None and not (0 <= index < len(games) and (games[index].findtext("path", "") or "") == expected):
        matches = find_game_index_by_path(expected)
        if len(matches) != 1:
            return api_err(st("server.stale_game"), 409, code="stale_game", path=expected)
        index = matches[0]
    if not (0 <= index < len(games)):
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    return jsonify(game_fields(games[index], index, LIST_FIELDS | {"desc"}))


@bp.route("/api/session")
def api_session():
    """Diagnostics: open gamelist, system, version, exe or source (used by the CI exe smoke test)."""
    loaded = has_gamelist()
    return jsonify({
        "xml_path": xml_store.XML_PATH if loaded else None,
        "base_dir": xml_store.BASE_DIR if loaded else None,
        "system": get_system_info() if loaded else None,
        "version": APP_VERSION,
        "loaded": loaded,
        "frozen": bool(getattr(sys, "frozen", False)),
    })


@bp.route("/api/browse")
def api_browse():
    """
    List folders + .xml files for the in-app file picker.
    Query: ?path=  (optional). Default = parent of current gamelist.xml.
    Local-only tool — directory listing is intentional.
    """
    raw = (request.args.get("path") or "").strip().strip('"').strip("'")
    if raw:
        target = os.path.abspath(raw)
    else:
        # Default: parent of current gamelist, else common RetroBat/ES folders, else home
        if has_gamelist():
            start = xml_store.BASE_DIR if os.path.isdir(xml_store.BASE_DIR) else os.path.dirname(xml_store.XML_PATH)
            parent = os.path.dirname(start)
            target = parent if parent and os.path.isdir(parent) else start
        else:
            candidates = []
            home = os.path.expanduser("~")
            for p in (
                os.path.join(home, "RetroBat", "roms"),
                os.path.join(home, "emulationstation", "roms"),
                "C:\\RetroBat\\roms",
                "D:\\RetroBat\\roms",
                "E:\\RetroBat\\roms",
                home,
            ):
                if p and os.path.isdir(p):
                    candidates.append(p)
            target = candidates[0] if candidates else (home if os.path.isdir(home) else os.getcwd())

    if os.path.isfile(target):
        target = os.path.dirname(target)

    if not os.path.isdir(target):
        return api_err(st("server.browse_not_dir", path=target), 404, code="browse_not_dir")

    try:
        names = os.listdir(target)
    except OSError as e:
        return api_err(st("server.browse_denied", path=target, detail=e), 403, code="browse_denied")

    dirs = []
    xmls = []
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(target, name)
        try:
            if os.path.isdir(full):
                dirs.append({"name": name, "path": full})
            elif os.path.isfile(full) and name.lower().endswith(".xml"):
                xmls.append({
                    "name": name,
                    "path": full,
                    "is_gamelist": name.lower() == "gamelist.xml",
                })
        except OSError:
            continue

    dirs.sort(key=lambda d: d["name"].lower())
    xmls.sort(key=lambda f: (not f["is_gamelist"], f["name"].lower()))

    parent = os.path.dirname(target)
    # On Windows, dirname("C:\\") == "C:\\" — treat as no parent
    has_parent = bool(parent) and parent != target and os.path.isdir(parent)

    # Drive roots on Windows (C:\, D:\, …)
    drives = []
    if os.name == "nt":
        import string
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.isdir(root):
                drives.append({"name": f"{letter}:", "path": root})

    home = esde.find_home(target)
    return jsonify({
        "path": target,
        "parent": parent if has_parent else None,
        "esde": {"home": home, "gamelists": os.path.join(home, "gamelists")} if home else None,
        "dirs": dirs,
        "files": xmls,
        "has_gamelist": os.path.isfile(os.path.join(target, "gamelist.xml")),
        "drives": drives,
    })


def _esde_open_hint(raw):
    """ES-DE's settings file or folder is not a gamelist: say where its gamelists are."""
    path = os.path.abspath(str(raw or "").strip().strip('"').strip("'")) if raw else ""
    if not path or (os.path.isfile(path) and os.path.basename(path).lower() != "es_settings.xml"):
        return None
    home = esde.find_home(path)
    if not home:
        return None
    return api_err(st("server.esde_open_hint", path=os.path.join(home, "gamelists")), 400,
                   code="esde_home", esde_home=home)


@bp.route("/api/open-gamelist", methods=["POST"])
def api_open_gamelist():
    """
    Switch the editor to another gamelist.xml without restarting the server.
    Body: { "path": "C:\\RetroBat\\roms\\snes\\gamelist.xml" }
    Local-only tool (bound to 127.0.0.1) — absolute paths are intentional.
    """
    body = request.get_json(silent=True) or {}
    raw = body.get("path") or body.get("xml") or ""
    hint = _esde_open_hint(raw)
    if hint:
        return hint
    try:
        info = set_gamelist_path(raw)
        recent.remember(info["xml_path"])
        games = get_games(load_xml())
        return jsonify({
            "success": True,
            "xml_path": info["xml_path"],
            "base_dir": info["base_dir"],
            "system": get_system_info(),
            "games": games,
            "count": len(games),
            "session_id": xml_store.SESSION_ID,
        })
    except FileNotFoundError as e:
        recent.forget(os.path.abspath(str(raw).strip().strip('"').strip("'")))
        return api_err(str(e), 404, code="open_not_found")
    except ValueError as e:
        return api_err(str(e), 400, code="open_invalid")
    except Exception as e:
        log.exception("open-gamelist failed")
        return api_err(st("server.open_failed", detail=e), 500, code="open_failed")


@bp.route("/api/upload/<int:index>/<field>", methods=["POST"])
def upload(index, field):
    err = require_gamelist()
    if err:
        return err
    if field not in xml_store.media_fields():
        return api_err(st("server.invalid_field"), 400, code="invalid_field")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    try:
        base_name = get_base_name(game)
        dest = {}

        def dest_for(ext):
            dest["full"], dest["value"] = media_dest(game, field, ext)
            return dest["full"]
        file = request.files.get("file")
        url = (request.form.get("url") or "").strip()
        rel_path = new_filename = None

        if file and file.filename:
            # Size limit (same as URL downloads)
            try:
                file.stream.seek(0, os.SEEK_END)
                size = file.stream.tell()
                file.stream.seek(0)
            except Exception:
                size = None
            if size is not None and size > MAX_DOWNLOAD_BYTES:
                return api_err(st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024)), 400, code="file_too_large")
            ext = os.path.splitext(file.filename)[1].lower()
            if ext == ".jpeg":
                ext = ".jpg"
            if ext not in MEDIA_EXTS:
                head = file.stream.read(64)
                file.stream.seek(0)
                ext = ext_from_magic(head) or default_ext_for_field(field)
            data = file.stream.read(MAX_DOWNLOAD_BYTES + 1)
            if len(data) > MAX_DOWNLOAD_BYTES:
                return api_err(st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024)), 400, code="file_too_large")
            atomic_write(dest_for(ext), data)
            new_filename, rel_path = os.path.basename(dest["full"]), dest["value"]
        elif url:
            try:
                download_remote_media(url, xml_store.BASE_DIR, base_name, field, timeout=20, filename_for=dest_for)
                new_filename, rel_path = os.path.basename(dest["full"]), dest["value"]
            except ValueError as e:
                if str(e) == "url_not_allowed":
                    return api_err(st("server.url_not_allowed"), 400, code="url_not_allowed")
                if str(e) == "too_large":
                    return api_err(st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024*1024)), 400, code="file_too_large")
                if str(e) == "green_placeholder":
                    return api_err(st("server.green_placeholder"), 400, code="green_placeholder")
                return api_err(st("server.download_failed", detail=e), 400, code="download_failed")
            except requests.RequestException as e:
                return api_err(st("server.download_failed", detail=e), 400, code="download_failed")
            except Exception as e:
                return api_err(st("server.download_failed", detail=e), 400, code="download_failed")
        else:
            return api_err(st("server.no_file_url"), 400, code="no_file_url")

        # The previous file (another name, e.g. .png → .jpg) goes to the Recycle
        # Bin, unless another game still uses it
        discard_old_media(game, field, game.findtext(field, "") or "", rel_path)

        elem = game.find(field)
        if elem is None:
            elem = etree.SubElement(game, field)
        elem.text = rel_path
        save_xml(tree)
        return jsonify({
            "success": True, "path": rel_path,
            "filename": new_filename, "field": field,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/clear/<int:index>/<field>", methods=["POST"])
def clear_field(index, field):
    """
    Remove the XML media tag only (file on disk is kept).
    Use delete-game to remove files from disk. ES-DE has no media tag: the
    file itself goes to the Recycle Bin.
    """
    err = require_gamelist()
    if err:
        return err
    if field not in MEDIA_DIRS:
        return api_err(st("server.invalid_field"), 400, code="invalid_field")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    try:
        trashed = remove_media(game, field)          # ES-DE: the media is its file
        elem = game.find(field)
        if elem is not None:
            game.remove(elem)
            save_xml(tree)
        return jsonify({"success": True, "trashed": len(trashed)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/game/<int:index>", methods=["POST"])
def save_game(index):
    """Save several parts of a game (name, desc, metadata) in ONE write.

    Body: only the fields that changed, e.g. {"name": "...", "desc": "...",
    "players": "1-2"}. Everything is validated before anything is written.
    """
    err = require_gamelist()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data:
        return api_err(st("server.no_data"), 400, code="no_data")
    name = None
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return api_err(st("server.empty_name"), 400, code="empty_name")
    try:
        cleaned = clean_meta(data)
    except FieldError as e:
        return api_err(st(e.key), 400, code=e.code)
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    updated = dict(cleaned)
    if name is not None:
        set_name(game, name)
        updated["name"] = name
    if "desc" in data:
        updated["desc"] = data.get("desc") or ""
        set_desc(game, updated["desc"])
    set_meta(game, cleaned)
    try:
        save_xml(tree)
    except Exception as e:
        log.exception("save failed")
        return api_err(str(e), 500, code="save_failed")
    return jsonify({"success": True, "updated": updated})


@bp.route("/api/backup", methods=["POST"])
def api_backup():
    """Manual backup of gamelist.xml → gamelist.xml.bak"""
    err = require_gamelist()
    if err:
        return err
    try:
        backup_path = backup_xml()
        return jsonify({
            "success": True,
            "backup": backup_path,
            "filename": os.path.basename(backup_path),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/fill-arcadesystem", methods=["POST"])
def fill_arcadesystem():
    """Fill <arcadesystemname> from a MAME -listxml dump (mame.xml)."""
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    xml_path = (body.get("xml_path") or "").strip() or find_mame_listxml()
    if not xml_path or not os.path.isfile(xml_path):
        return api_err(st("server.mame_xml_missing"), 404, code="mame_xml_missing")
    try:
        idx = index_mame_listxml(xml_path)
    except Exception as e:
        return api_err(st("server.mame_xml_bad", detail=e), 400, code="mame_xml_bad")
    if not idx:
        return api_err(st("server.mame_xml_empty"), 400, code="mame_xml_empty")

    do_backup = bool(body.get("backup", False))
    backup_path = backup_xml() if do_backup else None
    overwrite = bool(body.get("overwrite", False))
    tree = load_xml()
    filled, skipped, missing = 0, 0, 0
    for game in tree.getroot().findall("game"):
        existing = (game.findtext("arcadesystemname") or "").strip()
        if existing and not overwrite:
            skipped += 1
            continue
        path = game.findtext("path", "") or ""
        romset = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0].lower()
        src = idx.get(romset)
        name = pretty_arcade_system(src, romset) if src else ""
        if not name:
            missing += 1
            continue
        elem = game.find("arcadesystemname")
        if elem is None:
            elem = etree.SubElement(game, "arcadesystemname")
        elem.text = name
        filled += 1
    if filled:
        save_xml(tree)
    return jsonify({
        "success": True,
        "filled": filled,
        "skipped": skipped,
        "missing": missing,
        "source": xml_path,
        "machines": len(idx),
        "backup": backup_path,
    })


@bp.route("/api/export-csv", methods=["POST"])
def api_export_csv():
    """The games shown in the list as a CSV file (Actions › Export the list).

    Body: ``{"paths": [...], "required": [...], "sep": ";"}``, all optional:
    ``paths`` is the list as displayed (filters applied, in that order; absent
    = every game), ``required`` the required media of the system (for the
    ``required_media`` / ``missing_required`` columns), ``sep`` one of , ; or tab.
    """
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    paths = body.get("paths")
    required = body.get("required")
    sep = body.get("sep", ";")
    if paths is not None and not (isinstance(paths, list) and all(isinstance(p, str) for p in paths)):
        return api_err("paths must be a list of strings", 400, code="bad_paths")
    if required is None:
        required = csv_export.DEFAULT_REQUIRED
    elif not (isinstance(required, list) and all(f in MEDIA_DIRS for f in required)):
        return api_err("unknown media field", 400, code="invalid_field")
    if sep not in csv_export.SEPARATORS:
        return api_err("bad separator", 400, code="bad_separator")
    games = csv_export.ordered_games(load_xml().getroot(), paths)
    folder = re.sub(r"[^A-Za-z0-9._-]", "_", (get_system_info() or {}).get("folder") or "") or "gamelist"
    filename = f"gamelist-{folder}-{time.strftime('%Y-%m-%d')}.csv"
    resp = Response(csv_export.build_csv(games, required, sep), mimetype="text/csv")
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["X-Exported-Games"] = str(len(games))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/media/<path:filepath>")
def serve_media(filepath):
    """Serve a media file only if it resolves under BASE_DIR."""
    full = resolve_under_base(filepath)
    if not full or not os.path.isfile(full):
        return st("server.file_not_found"), 404
    resp = send_from_directory(os.path.dirname(full), os.path.basename(full))
    # Revalidate every time (cheap 304): a replaced media keeps its name
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Stop the Flask server (exit 0 so Lancer.bat can close without pause)."""
    def _stop():
        time.sleep(0.35)
        close_ui_window()
        os._exit(0)

    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"success": True, "message": st("server.shutdown")})
