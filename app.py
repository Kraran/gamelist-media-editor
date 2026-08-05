#!/usr/bin/env python3
"""
Gamelist Media Editor
"""
import os, sys, re
from urllib.parse import urlparse, unquote
from flask import Flask, render_template, request, jsonify, send_from_directory
from lxml import etree
import requests

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
XML_PATH = os.path.join(BASE_DIR, "gamelist.xml")

MEDIA_DIRS = {
    "image": "images", "video": "videos", "marquee": "images",
    "manual": "manuals", "boxback": "images", "thumbnail": "images",
    "fanart": "images", "map": "images",
}
META_FIELDS = {"rating","releasedate","developer","publisher","family","players","lang","genre"}

def load_xml():
    return etree.parse(XML_PATH, etree.XMLParser(remove_blank_text=True))

def save_xml(tree):
    tree.write(XML_PATH, pretty_print=True, xml_declaration=True, encoding="UTF-8")

def backup_xml():
    """Copy gamelist.xml to gamelist.xml.bak next to it. Returns backup path."""
    import shutil
    if not os.path.isfile(XML_PATH):
        raise FileNotFoundError(f"XML introuvable : {XML_PATH}")
    bak_path = XML_PATH + ".bak"
    shutil.copy2(XML_PATH, bak_path)
    return bak_path

def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name or "unknown"

def get_base_name(game_elem):
    path = game_elem.findtext("path", "") or ""
    if path:
        return sanitize_filename(os.path.splitext(os.path.basename(path))[0])
    return sanitize_filename(game_elem.findtext("name", "unknown") or "unknown")

def get_games(tree):
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
    if not rel_path:
        return False
    clean = rel_path.replace("\\", "/").lstrip("./")
    if ".." in clean.split("/"):
        return False
    full = os.path.normpath(os.path.join(BASE_DIR, clean))
    if not full.startswith(os.path.normpath(BASE_DIR)):
        return False
    if os.path.isfile(full):
        try:
            os.remove(full)
            return True
        except OSError:
            return False
    return False

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    """Favicon a la racine (les navigateurs la demandent souvent ici)."""
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
        tree = load_xml()
        games = tree.getroot().findall("game")
        if not (0 <= index < len(games)):
            return jsonify({"error": "Index invalide"}), 404
        game = games[index]
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        base_name = get_base_name(game)
        file = request.files.get("file")
        url = (request.form.get("url") or "").strip()
        rel_path = new_filename = None

        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower() or (".mp4" if field=="video" else ".pdf" if field=="manual" else ".png")
            new_filename = f"{base_name}-{field}{ext}"
            file.save(os.path.join(media_dir, new_filename))
            rel_path = f"./{media_dir_name}/{new_filename}"
        elif url:
            try:
                parsed = urlparse(url)
                ext = os.path.splitext(unquote(parsed.path))[1].lower()
                if not ext or len(ext) > 6:
                    ext = ""
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20, stream=True)
                r.raise_for_status()
                ct = (r.headers.get("content-type") or "").lower()
                if not ext:
                    if "png" in ct: ext = ".png"
                    elif "jpeg" in ct or "jpg" in ct: ext = ".jpg"
                    elif "gif" in ct: ext = ".gif"
                    elif "webp" in ct: ext = ".webp"
                    elif "mp4" in ct: ext = ".mp4"
                    elif "webm" in ct: ext = ".webm"
                    elif "pdf" in ct: ext = ".pdf"
                    else: ext = ".mp4" if field=="video" else ".pdf" if field=="manual" else ".png"
                new_filename = f"{base_name}-{field}{ext}"
                with open(os.path.join(media_dir, new_filename), "wb") as f:
                    for chunk in r.iter_content(8192):
                        if chunk: f.write(chunk)
                rel_path = f"./{media_dir_name}/{new_filename}"
            except Exception as e:
                return jsonify({"error": f"Telechargement echoue: {e}"}), 400
        else:
            return jsonify({"error": "Aucun fichier ni URL"}), 400

        elem = game.find(field)
        if elem is None:
            elem = etree.SubElement(game, field)
        elem.text = rel_path
        save_xml(tree)
        return jsonify({"success": True, "path": rel_path, "filename": new_filename, "field": field})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/clear/<int:index>/<field>", methods=["POST"])
def clear_field(index, field):
    if field not in MEDIA_DIRS:
        return jsonify({"error": "Champ invalide"}), 400
    try:
        tree = load_xml()
        games = tree.getroot().findall("game")
        if not (0 <= index < len(games)):
            return jsonify({"error": "Index invalide"}), 404
        elem = games[index].find(field)
        if elem is not None:
            games[index].remove(elem)
            save_xml(tree)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/desc/<int:index>", methods=["POST"])
def update_desc(index):
    try:
        data = request.get_json(silent=True) or {}
        new_desc = data.get("desc", "") or ""
        tree = load_xml()
        games = tree.getroot().findall("game")
        if not (0 <= index < len(games)):
            return jsonify({"error": "Index invalide"}), 404
        game = games[index]
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
        tree = load_xml()
        games = tree.getroot().findall("game")
        if not (0 <= index < len(games)):
            return jsonify({"error": "Index invalide"}), 404
        game = games[index]
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
        tree = load_xml()
        games = tree.getroot().findall("game")
        if not (0 <= index < len(games)):
            return jsonify({"error": "Index invalide"}), 404
        game = games[index]
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
    """Supprime ROM + medias + entree XML du jeu."""
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
            if rel:
                if safe_delete_file(rel):
                    deleted_files.append(rel)
                else:
                    clean = rel.replace("\\", "/").lstrip("./")
                    full = os.path.normpath(os.path.join(BASE_DIR, clean))
                    if os.path.exists(full):
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
    filepath = filepath.replace("..", "").lstrip("/")
    full = os.path.join(BASE_DIR, filepath)
    if os.path.isfile(full):
        return send_from_directory(os.path.dirname(full), os.path.basename(full))
    return "Fichier introuvable", 404

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
    globals()["XML_PATH"] = XML_PATH
    globals()["BASE_DIR"] = BASE_DIR
    print()
    print(f"  XML            : {XML_PATH}")
    print(f"  Dossier medias : {BASE_DIR}")
    print()
    print("  Ouvre http://127.0.0.1:5050 dans ton navigateur")
    print("  (Ctrl+C pour arreter le serveur)")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5050, debug=False)
