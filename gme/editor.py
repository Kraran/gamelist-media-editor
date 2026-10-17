"""Editor routes: game list, gamelist switching, media and metadata editing, tools."""

import os
import sys
import threading
import time

import requests
from flask import Blueprint, jsonify, render_template, request, send_from_directory
from lxml import etree

from gme import xml_store
from gme.arcade import find_mame_listxml, index_mame_listxml, pretty_arcade_system
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.media import MAX_DOWNLOAD_BYTES, MEDIA_EXTS, default_ext_for_field, download_remote_media, ext_from_magic, pad2key_dest, safe_delete_file
from gme.paths import resource_path
from gme.systems import get_system_info
from gme.version import APP_RELEASE_DATE, APP_VERSION
from gme.window import close_ui_window
from gme.xml_store import BOOL_META_FIELDS, MEDIA_DIRS, META_FIELDS, backup_xml, get_base_name, get_game_elem, get_games, has_gamelist, load_xml, require_gamelist, resolve_under_base, save_xml, set_gamelist_path

bp = Blueprint("editor", __name__)


# --- HTTP routes --------------------------------------------------------------
# JSON APIs return {ok:false, error, code?} on failure (see api_err).
# Mutating routes that need a loaded gamelist call require_gamelist() first.

@bp.route("/")
def index():
    return render_template("index.html", app_version=APP_VERSION,
                           app_release_date=APP_RELEASE_DATE)


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
            })
        return jsonify({
            "games": get_games(load_xml()),
            "system": get_system_info(),
            "xml_path": xml_store.XML_PATH,
            "base_dir": xml_store.BASE_DIR,
            "loaded": True,
        })
    except Exception as e:
        log.exception("api_games failed")
        return api_err(st("server.xml_read", detail=e), 500, code="xml_read")


@bp.route("/api/session")
def api_session():
    """Current gamelist path + system badge info (no full game list)."""
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

    return jsonify({
        "path": target,
        "parent": parent if has_parent else None,
        "dirs": dirs,
        "files": xmls,
        "drives": drives,
    })


@bp.route("/api/open-gamelist", methods=["POST"])
def api_open_gamelist():
    """
    Switch the editor to another gamelist.xml without restarting the server.
    Body: { "path": "C:\\RetroBat\\roms\\snes\\gamelist.xml" }
    Local-only tool (bound to 127.0.0.1) — absolute paths are intentional.
    """
    body = request.get_json(silent=True) or {}
    raw = body.get("path") or body.get("xml") or ""
    try:
        info = set_gamelist_path(raw)
        games = get_games(load_xml())
        return jsonify({
            "success": True,
            "xml_path": info["xml_path"],
            "base_dir": info["base_dir"],
            "system": get_system_info(),
            "games": games,
            "count": len(games),
        })
    except FileNotFoundError as e:
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
    if field not in MEDIA_DIRS:
        return api_err(st("server.invalid_field"), 400, code="invalid_field")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    try:
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(xml_store.BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        base_name = get_base_name(game)
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
            new_filename = f"{base_name}-{field}{ext}"
            file.save(os.path.join(media_dir, new_filename))
            rel_path = f"./{media_dir_name}/{new_filename}"
        elif url:
            try:
                new_filename = download_remote_media(
                    url, media_dir, base_name, field, timeout=20
                )
                rel_path = f"./{media_dir_name}/{new_filename}"
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

        # Remove previous media file if path changes (e.g. .png → .jpg)
        old_rel = game.findtext(field, "") or ""
        if old_rel and resolve_under_base(old_rel) != resolve_under_base(rel_path):
            safe_delete_file(old_rel)

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
    Use delete-game to remove files from disk.
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
        elem = game.find(field)
        if elem is not None:
            game.remove(elem)
            save_xml(tree)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/desc/<int:index>", methods=["POST"])
def update_desc(index):
    err = require_gamelist()
    if err:
        return err
    try:
        data = request.get_json(silent=True) or {}
        new_desc = data.get("desc", "") or ""
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return api_err(st("server.invalid_index"), 404, code="invalid_index")
        elem = game.find("desc")
        if elem is None:
            name_elem = game.find("name")
            if name_elem is not None:
                elem = etree.Element("desc")
                name_elem.addnext(elem)
            else:
                elem = etree.SubElement(game, "desc")
        elem.text = new_desc
        save_xml(tree)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/name/<int:index>", methods=["POST"])
def update_name(index):
    err = require_gamelist()
    if err:
        return err
    try:
        data = request.get_json(silent=True) or {}
        new_name = (data.get("name") or "").strip()
        if not new_name:
            return api_err(st("server.empty_name"), 400, code="empty_name")
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return api_err(st("server.invalid_index"), 404, code="invalid_index")
        elem = game.find("name")
        if elem is None:
            elem = etree.Element("name")
            game.insert(0, elem)
        elem.text = new_name
        save_xml(tree)
        return jsonify({"success": True, "name": new_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/meta/<int:index>", methods=["POST"])
def update_meta(index):
    err = require_gamelist()
    if err:
        return err
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            return api_err(st("server.no_data"), 400, code="no_data")
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return api_err(st("server.invalid_index"), 404, code="invalid_index")
        updated = {}
        for field, value in data.items():
            if field not in META_FIELDS:
                continue
            value = (value or "").strip()
            if field == "rating" and value:
                try:
                    fval = float(value)
                    if not (0.0 <= fval <= 1.0):
                        return api_err(st("server.rating_range"), 400, code="rating_range")
                    value = f"{fval:.2f}".rstrip("0").rstrip(".") if fval != 0 else "0"
                except ValueError:
                    return api_err(st("server.rating_invalid"), 400, code="rating_invalid")
            if field == "lang" and value:
                value = value.lower()
            if field in BOOL_META_FIELDS:
                value = "true" if value.lower() in ("true", "1", "yes", "on") else ""
            elem = game.find(field)
            if value == "":
                if elem is not None:
                    game.remove(elem)
            else:
                if elem is None:
                    elem = etree.SubElement(game, field)
                elem.text = value
            updated[field] = value
        save_xml(tree)
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@bp.route("/api/purge-regions", methods=["POST"])
def purge_regions():
    err = require_gamelist()
    if err:
        return err
    try:
        body = request.get_json(silent=True) or {}
        do_backup = bool(body.get("backup", False))
        backup_path = None
        if do_backup:
            backup_path = backup_xml()

        tree = load_xml()
        root = tree.getroot()
        count = 0
        for game in root.findall("game"):
            for region_elem in list(game.findall("region")):
                game.remove(region_elem)
                count += 1
        save_xml(tree)
        return jsonify({
            "success": True,
            "removed": count,
            "backup": backup_path,
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


@bp.route("/api/delete-game/<int:index>", methods=["POST"])
def delete_game(index):
    """Delete ROM + media files on disk + XML entry for the game."""
    err = require_gamelist()
    if err:
        return err
    try:
        body = request.get_json(silent=True) or {}
        do_backup = bool(body.get("backup", False))
        backup_path = None
        if do_backup:
            backup_path = backup_xml()

        tree = load_xml()
        root = tree.getroot()
        games = root.findall("game")
        if not (0 <= index < len(games)):
            return api_err(st("server.invalid_index"), 404, code="invalid_index")
        game = games[index]
        name = game.findtext("name", "") or st("server.game_fallback", index=index)
        media_tags = [
            "path", "image", "video", "marquee", "manual", "boxback",
            "thumbnail", "fanart", "map", "boxfront", "boxart", "cartridge", "mix",
            "bezel",
        ]
        deleted_files, failed_files = [], []
        for tag in media_tags:
            rel = game.findtext(tag, "") or ""
            if not rel:
                continue
            if safe_delete_file(rel):
                deleted_files.append(rel)
            else:
                full = resolve_under_base(rel)
                if full and os.path.exists(full):
                    failed_files.append(rel)
        keys_path = pad2key_dest(game)
        if keys_path and os.path.isfile(keys_path):
            try:
                os.remove(keys_path)
                deleted_files.append(os.path.relpath(keys_path, xml_store.BASE_DIR))
            except OSError:
                failed_files.append(keys_path)
        root.remove(game)
        save_xml(tree)
        return jsonify({
            "success": True, "name": name,
            "deleted_files": deleted_files, "failed_files": failed_files,
            "backup": backup_path,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/media/<path:filepath>")
def serve_media(filepath):
    """Serve a media file only if it resolves under BASE_DIR."""
    full = resolve_under_base(filepath)
    if not full or not os.path.isfile(full):
        return st("server.file_not_found"), 404
    return send_from_directory(os.path.dirname(full), os.path.basename(full))


@bp.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Stop the Flask server (exit 0 so Lancer.bat can close without pause)."""
    def _stop():
        time.sleep(0.35)
        close_ui_window()
        os._exit(0)

    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"success": True, "message": st("server.shutdown")})
