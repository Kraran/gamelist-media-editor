#!/usr/bin/env python3
"""
Gamelist Media Editor — local Flask app for EmulationStation / RetroBat gamelist.xml.

Bound to 127.0.0.1 only. Edits media paths and metadata, with optional .bak backups.
"""
import os
import sys
import re
import shutil
import threading
import time
from urllib.parse import urlparse, unquote

from flask import Flask, render_template, request, jsonify, send_from_directory
from lxml import etree
import requests

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XML_PATH = os.path.join(BASE_DIR, "gamelist.xml")

# Max size for media downloaded from a URL (bytes)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

MEDIA_DIRS = {
    "image": "images", "video": "videos", "marquee": "images",
    "manual": "manuals", "boxback": "images", "thumbnail": "images",
    "fanart": "images", "map": "images",
}
META_FIELDS = {
    "rating", "releasedate", "developer", "publisher",
    "family", "players", "lang", "genre",
}

# --- XML cache + process lock ------------------------------------------------
_xml_cache = {"mtime": None, "tree": None}
_xml_io_lock = threading.Lock()  # serialize read-modify-write of the XML file


def load_xml():
    """Parse gamelist.xml; reuse cached tree if file mtime unchanged."""
    try:
        mtime = os.path.getmtime(XML_PATH)
    except OSError:
        mtime = None
    if _xml_cache["tree"] is not None and _xml_cache["mtime"] == mtime:
        return _xml_cache["tree"]
    tree = etree.parse(XML_PATH, etree.XMLParser(remove_blank_text=True))
    _xml_cache["tree"] = tree
    _xml_cache["mtime"] = mtime
    return tree


def save_xml(tree):
    """Write XML to disk and refresh cache (serialized)."""
    with _xml_io_lock:
        tree.write(XML_PATH, pretty_print=True, xml_declaration=True, encoding="UTF-8")
        try:
            _xml_cache["mtime"] = os.path.getmtime(XML_PATH)
            _xml_cache["tree"] = tree
        except OSError:
            _xml_cache["mtime"] = None
            _xml_cache["tree"] = None


def backup_xml():
    """Copy gamelist.xml → gamelist.xml.bak (same folder). Returns backup path."""
    with _xml_io_lock:
        if not os.path.isfile(XML_PATH):
            raise FileNotFoundError(f"XML introuvable : {XML_PATH}")
        bak_path = XML_PATH + ".bak"
        shutil.copy2(XML_PATH, bak_path)
        return bak_path


def get_game_elem(index):
    """
    Return (tree, game_elem) for the game at XML index.
    Raises IndexError if out of range.
    """
    tree = load_xml()
    games = tree.getroot().findall("game")
    if not (0 <= index < len(games)):
        raise IndexError("Index invalide")
    return tree, games[index]


def resolve_under_base(rel_path):
    """
    Resolve a relative media path under BASE_DIR.
    Returns absolute path, or None if empty / path traversal / outside base.
    """
    if not rel_path:
        return None
    # Normalize separators; strip only leading "./" (not "../")
    clean = str(rel_path).replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    clean = clean.lstrip("/")
    if not clean or ".." in clean.split("/"):
        return None
    full = os.path.normpath(os.path.join(BASE_DIR, clean))
    base = os.path.normpath(BASE_DIR)
    try:
        if os.path.commonpath([base, full]) != base:
            return None
    except ValueError:
        # Different drives on Windows
        return None
    return full


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name or "unknown"


def get_base_name(game_elem):
    path = game_elem.findtext("path", "") or ""
    if path:
        return sanitize_filename(os.path.splitext(os.path.basename(path))[0])
    return sanitize_filename(game_elem.findtext("name", "unknown") or "unknown")


def get_games(tree):
    """Build sorted game list for the UI. Each item keeps original XML index."""
    games = []
    for i, game in enumerate(tree.getroot().findall("game")):
        path = game.findtext("path", "") or ""
        name = game.findtext("name", "") or (os.path.basename(path) if path else f"Jeu {i}")
        games.append({
            "index": i, "path": path, "name": name,
            "desc": game.findtext("desc", "") or "",
            "image": game.findtext("image", "") or "",
            "video": game.findtext("video", "") or "",
            "marquee": game.findtext("marquee", "") or "",
            "manual": game.findtext("manual", "") or "",
            "boxback": game.findtext("boxback", "") or "",
            "rating": game.findtext("rating", "") or "",
            "releasedate": game.findtext("releasedate", "") or "",
            "developer": game.findtext("developer", "") or "",
            "publisher": game.findtext("publisher", "") or "",
            "family": game.findtext("family", "") or "",
            "players": game.findtext("players", "") or "",
            "lang": game.findtext("lang", "") or "",
            "genre": game.findtext("genre", "") or "",
        })
    games.sort(key=lambda g: g["name"].lower())
    return games


def safe_delete_file(rel_path):
    """Delete a media file under BASE_DIR. Returns True if deleted."""
    full = resolve_under_base(rel_path)
    if not full or not os.path.isfile(full):
        return False
    try:
        os.remove(full)
        return True
    except OSError:
        return False


def default_ext_for_field(field):
    if field == "video":
        return ".mp4"
    if field == "manual":
        return ".pdf"
    return ".png"


def ext_from_content_type(ct, field):
    ct = (ct or "").lower()
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    if "mp4" in ct:
        return ".mp4"
    if "webm" in ct:
        return ".webm"
    if "pdf" in ct:
        return ".pdf"
    return default_ext_for_field(field)


# --- Routes ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    """Browsers often request /favicon.ico at the site root."""
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    return send_from_directory(static_dir, "favicon.ico", mimetype="image/x-icon")


@app.route("/api/games")
def api_games():
    try:
        return jsonify(get_games(load_xml()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload/<int:index>/<field>", methods=["POST"])
def upload(index, field):
    if field not in MEDIA_DIRS:
        return jsonify({"error": "Champ invalide"}), 400
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return jsonify({"error": "Index invalide"}), 404
    try:
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(BASE_DIR, media_dir_name)
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
                return jsonify({
                    "error": f"Fichier trop volumineux (max {MAX_DOWNLOAD_BYTES // (1024*1024)} Mo)"
                }), 400
            ext = os.path.splitext(file.filename)[1].lower() or default_ext_for_field(field)
            new_filename = f"{base_name}-{field}{ext}"
            file.save(os.path.join(media_dir, new_filename))
            rel_path = f"./{media_dir_name}/{new_filename}"
        elif url:
            try:
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https"):
                    return jsonify({"error": "URL non autorisee (http/https uniquement)"}), 400
                ext = os.path.splitext(unquote(parsed.path))[1].lower()
                if not ext or len(ext) > 6:
                    ext = ""
                r = requests.get(
                    url,
                    headers={"User-Agent": "GamelistMediaEditor/1.0"},
                    timeout=20,
                    stream=True,
                )
                r.raise_for_status()
                if not ext:
                    ext = ext_from_content_type(r.headers.get("content-type"), field)
                cl = r.headers.get("content-length")
                if cl is not None:
                    try:
                        if int(cl) > MAX_DOWNLOAD_BYTES:
                            r.close()
                            return jsonify({
                                "error": f"Fichier trop volumineux (max {MAX_DOWNLOAD_BYTES // (1024*1024)} Mo)"
                            }), 400
                    except ValueError:
                        pass
                new_filename = f"{base_name}-{field}{ext}"
                dest = os.path.join(media_dir, new_filename)
                written = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(8192):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_DOWNLOAD_BYTES:
                            f.close()
                            try:
                                os.remove(dest)
                            except OSError:
                                pass
                            return jsonify({
                                "error": f"Fichier trop volumineux (max {MAX_DOWNLOAD_BYTES // (1024*1024)} Mo)"
                            }), 400
                        f.write(chunk)
                rel_path = f"./{media_dir_name}/{new_filename}"
            except requests.RequestException as e:
                return jsonify({"error": f"Telechargement echoue: {e}"}), 400
            except Exception as e:
                return jsonify({"error": f"Telechargement echoue: {e}"}), 400
        else:
            return jsonify({"error": "Aucun fichier ni URL"}), 400

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


@app.route("/api/clear/<int:index>/<field>", methods=["POST"])
def clear_field(index, field):
    """
    Remove the XML media tag only (file on disk is kept).
    Use delete-game to remove files from disk.
    """
    if field not in MEDIA_DIRS:
        return jsonify({"error": "Champ invalide"}), 400
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return jsonify({"error": "Index invalide"}), 404
    try:
        elem = game.find(field)
        if elem is not None:
            game.remove(elem)
            save_xml(tree)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/desc/<int:index>", methods=["POST"])
def update_desc(index):
    try:
        data = request.get_json(silent=True) or {}
        new_desc = data.get("desc", "") or ""
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return jsonify({"error": "Index invalide"}), 404
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


@app.route("/api/name/<int:index>", methods=["POST"])
def update_name(index):
    try:
        data = request.get_json(silent=True) or {}
        new_name = (data.get("name") or "").strip()
        if not new_name:
            return jsonify({"error": "Nom vide"}), 400
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return jsonify({"error": "Index invalide"}), 404
        elem = game.find("name")
        if elem is None:
            elem = etree.Element("name")
            game.insert(0, elem)
        elem.text = new_name
        save_xml(tree)
        return jsonify({"success": True, "name": new_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/meta/<int:index>", methods=["POST"])
def update_meta(index):
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({"error": "Aucune donnee"}), 400
        try:
            tree, game = get_game_elem(index)
        except IndexError:
            return jsonify({"error": "Index invalide"}), 404
        updated = {}
        for field, value in data.items():
            if field not in META_FIELDS:
                continue
            value = (value or "").strip()
            if field == "rating" and value:
                try:
                    fval = float(value)
                    if not (0.0 <= fval <= 1.0):
                        return jsonify({"error": "rating entre 0 et 1"}), 400
                    value = f"{fval:.2f}".rstrip("0").rstrip(".") if fval != 0 else "0"
                except ValueError:
                    return jsonify({"error": "rating invalide"}), 400
            if field == "lang" and value:
                value = value.lower()
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


@app.route("/api/backup", methods=["POST"])
def api_backup():
    """Manual backup of gamelist.xml → gamelist.xml.bak"""
    try:
        backup_path = backup_xml()
        return jsonify({
            "success": True,
            "backup": backup_path,
            "filename": os.path.basename(backup_path),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/purge-regions", methods=["POST"])
def purge_regions():
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


@app.route("/api/delete-game/<int:index>", methods=["POST"])
def delete_game(index):
    """Delete ROM + media files on disk + XML entry for the game."""
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
            return jsonify({"error": "Index invalide"}), 404
        game = games[index]
        name = game.findtext("name", "") or f"Jeu {index}"
        media_tags = [
            "path", "image", "video", "marquee", "manual", "boxback",
            "thumbnail", "fanart", "map", "boxfront", "cartridge", "mix",
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
        root.remove(game)
        save_xml(tree)
        return jsonify({
            "success": True, "name": name,
            "deleted_files": deleted_files, "failed_files": failed_files,
            "backup": backup_path,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/media/<path:filepath>")
def serve_media(filepath):
    """Serve a media file only if it resolves under BASE_DIR."""
    full = resolve_under_base(filepath)
    if not full or not os.path.isfile(full):
        return "Fichier introuvable", 404
    return send_from_directory(os.path.dirname(full), os.path.basename(full))


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Stop the Flask server (exit 0 so Lancer.bat can close without pause)."""
    def _stop():
        time.sleep(0.35)
        os._exit(0)

    threading.Thread(target=_stop, daemon=True).start()
    return jsonify({"success": True, "message": "Arret du serveur"})


if __name__ == "__main__":
    print("=" * 60)
    print("  Gamelist Media Editor")
    print("=" * 60)
    print()
    if len(sys.argv) > 1:
        xml_arg = sys.argv[1].strip().strip('"').strip("'")
    else:
        print("Indique le chemin complet vers ton fichier gamelist.xml")
        print("(tu peux glisser-deposer le fichier dans le terminal)")
        print()
        xml_arg = input("Chemin du gamelist.xml : ").strip().strip('"').strip("'")
    if not xml_arg:
        print("Aucun fichier indique. Arret.")
        sys.exit(1)
    xml_arg = os.path.abspath(xml_arg)
    if not os.path.isfile(xml_arg):
        print(f"\nErreur : fichier introuvable ->\n  {xml_arg}")
        sys.exit(1)
    XML_PATH = xml_arg
    BASE_DIR = os.path.dirname(xml_arg)
    _xml_cache["mtime"] = None
    _xml_cache["tree"] = None
    print()
    print(f"  XML            : {XML_PATH}")
    print(f"  Dossier medias : {BASE_DIR}")
    print()
    print("  Ouvre http://127.0.0.1:5050 dans ton navigateur")
    print("  (Ctrl+C pour arreter le serveur)")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5050, debug=False)
