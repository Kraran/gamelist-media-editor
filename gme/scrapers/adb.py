"""Arcade Database (Arcade Italia) scraper: API client, parsing and routes."""

import os
import re

import requests
from flask import Blueprint, jsonify, request
from lxml import etree

from gme import xml_store
from gme.arcade import pretty_arcade_system
from gme.http import api_err
from gme.i18n import st
from gme.media import MAX_DOWNLOAD_BYTES, download_remote_media, safe_delete_file
from gme.scrapers.common import throttle_api, name_similarity
from gme.systems import detect_system_id
from gme.version import APP_UA
from gme.xml_store import MEDIA_DIRS, get_base_name, get_game_elem, require_gamelist, resolve_under_base, save_xml

bp = Blueprint("adb", __name__)


def adb_fetch_driver(romset):
    """Read « Driver source: capcom/cps1.cpp » from the ADB game page."""
    if not romset:
        return ""
    try:
        throttle_api("adb")
        r = requests.get(
            "https://adb.arcadeitalia.net/dettaglio_mame.php",
            params={"game_name": romset},
            headers={"User-Agent": APP_UA},
            timeout=25,
        )
        r.raise_for_status()
        m = re.search(
            r"Driver source:.*?<span class=\"dettaglio\">\s*([^<]+?\.cpp)",
            r.text,
            re.I | re.S,
        )
        return (m.group(1).strip() if m else "")
    except Exception:
        return ""


def format_adb_error(raw, status=200):
    """Map Arcade Database error → localized message."""
    t = (raw or "").strip()
    low = t.lower()
    if status == 503 or "503" in low or "maintenance" in low:
        return st("server.adb_503")
    if status == 429 or any(k in low for k in ("rate", "limit", "quota", "too many", "trop")):
        return st("server.adb_rate")
    if status == 403:
        return st("server.adb_403")
    if t:
        return t[:400]
    return st("server.adb_error", status=status)


# --- Arcade Database (Arcade Italia) ------------------------------------------
# Best suited to MAME / FBNeo romset names. Same proposed/apply shape as SS.
ADB_API = "https://adb.arcadeitalia.net/service_scraper.php"
ADB_UA = f"{APP_UA} (ArcadeDB scraper; +https://github.com/Kraran/gamelist-media-editor)"


def adb_request(ajax, params, timeout=30):
    """Call Arcade Database scraper API. Returns (ok, data_or_error, status).
    Throttled (ADB recommends a single polite client per IP).
    """
    q = {"ajax": ajax}
    q.update({k: v for k, v in (params or {}).items() if v is not None and v != ""})
    throttle_api("adb")
    try:
        r = requests.get(
            ADB_API,
            params=q,
            headers={"User-Agent": ADB_UA, "Accept": "application/json"},
            timeout=timeout,
        )
        body = r.text or ""
        if r.status_code in (429, 503, 403):
            return False, format_adb_error(body, r.status_code), r.status_code
        if r.status_code != 200:
            return False, format_adb_error(body, r.status_code), r.status_code
        try:
            data = r.json()
        except Exception:
            low = body.lower()
            if any(k in low for k in ("limit", "quota", "maintenance", "503")):
                return False, format_adb_error(body, r.status_code), r.status_code
            return False, f"Réponse non JSON: {body[:300]}", r.status_code
        # Some error payloads still return 200 with empty/error flag
        if isinstance(data, dict):
            err = data.get("error") or data.get("message") or ""
            if err and not data.get("result"):
                return False, format_adb_error(str(err), r.status_code), r.status_code
        return True, data, r.status_code
    except requests.Timeout:
        return False, "Délai d'attente Arcade Database dépassé — serveur lent ou saturé.", 504
    except requests.RequestException as e:
        return False, f"Réseau Arcade Database: {e}", 502


def arcade_system_from_adb(item):
    """Map ADB romset → driver file → short board name (CPS1, Neo-Geo…)."""
    if not isinstance(item, dict):
        return ""
    romset = (item.get("game_name") or "").strip()
    src = (item.get("sourcefile") or item.get("source_file") or item.get("driver") or "").strip()
    if not src:
        src = adb_fetch_driver(romset)
    name = pretty_arcade_system(src, romset)
    if name:
        return name
    for key in ("hardware", "system"):
        val = (item.get(key) or "").strip()
        if val:
            return val
    return ""


def enrich_adb_item_media(item):
    """Merge QUERY_MAME_MEDIA URLs (pcb, decal, cabinet, flyer, …) into the item."""
    if not item or not isinstance(item, dict):
        return item
    gname = (item.get("game_name") or "").strip()
    if not gname:
        return item
    ok, data, _ = adb_request("query_mame_media", {"game_name": gname})
    if not ok or not isinstance(data, dict):
        return item
    results = data.get("result") or []
    if not results or not isinstance(results[0], dict):
        return item
    for k, v in results[0].items():
        if isinstance(k, str) and k.startswith("url_") and v:
            item[k] = v
    return item


def parse_adb_game(item):
    """Map one ADB result object → same proposed shape as ScreenScraper."""
    if not item or not isinstance(item, dict):
        return None
    title = (item.get("title") or item.get("short_title") or item.get("game_name") or "").strip()
    history = (item.get("history") or "").strip()
    # Strip excessive copyright footer if present at end — keep history text as-is
    manufacturer = (item.get("manufacturer") or "").strip()
    genre = (item.get("genre") or "").strip()
    if genre:
        genre = genre.upper()
    players = item.get("nplayers") or item.get("players") or ""
    if players is not None:
        players = str(players).strip()
    year = str(item.get("year") or "").strip()
    releasedate = ""
    digits = "".join(c for c in year if c.isdigit())
    if len(digits) >= 4:
        releasedate = digits[:4] + "0101T000000"
    rating = ""
    try:
        rate = item.get("rate")
        if rate not in (None, ""):
            val = float(rate)
            # ADB rate often 0–100
            if val > 1.0:
                val = val / 100.0
            rating = f"{max(0.0, min(1.0, val)):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        pass
    lang = ""
    languages = (item.get("languages") or "").strip()
    if languages:
        lang = languages.split(",")[0].split("/")[0].strip().lower()[:2]

    def pick_url(*keys):
        for k in keys:
            u = (item.get(k) or "").strip()
            if u and u.startswith("http"):
                return u, k
        return None, None

    medias = {}
    u, t = pick_url("url_image_ingame", "url_image_title", "url_image_select")
    if u:
        medias["image"] = {"url": u, "type": t}
    u, t = pick_url("url_video_shortplay_hd", "url_video_shortplay")
    if u:
        medias["video"] = {"url": u, "type": t}
    # Arcade mapping (MAME / FBNeo / NeoGeo / Atomiswave / …):
    # PCB → Support (cartridge), CABINET → Boxart, FLYER → Boxback, DECAL → Marquee
    u, t = pick_url("url_image_decal")
    if u:
        medias["marquee"] = {"url": u, "type": t}
    u, t = pick_url("url_manual")
    if u:
        medias["manual"] = {"url": u, "type": t}
    u, t = pick_url("url_image_cabinet")
    if u:
        medias["boxart"] = {"url": u, "type": t}
    u, t = pick_url("url_image_flyer")
    if u:
        medias["boxback"] = {"url": u, "type": t}
    u, t = pick_url("url_image_pcb")
    if u:
        medias["cartridge"] = {"url": u, "type": t}

    return {
        "ss_id": str(item.get("game_name") or ""),  # romset id used as key
        "adb_romset": str(item.get("game_name") or ""),
        "name": title,
        "desc": history,
        "rating": rating,
        "releasedate": releasedate,
        "developer": manufacturer,
        "publisher": manufacturer,
        "genre": genre,
        "players": players,
        "lang": lang,
        "medias": medias,
        "family": (item.get("serie") or "").strip(),
        "arcadesystemname": arcade_system_from_adb(item),
        "source": "arcadeitalia",
        "cloneof": (item.get("cloneof") or "").strip(),
        "status": (item.get("status") or "").strip(),
    }


def adb_current_from_game(game):
    current = {
        "name": game.findtext("name", "") or "",
        "desc": game.findtext("desc", "") or "",
        "rating": game.findtext("rating", "") or "",
        "releasedate": game.findtext("releasedate", "") or "",
        "developer": game.findtext("developer", "") or "",
        "publisher": game.findtext("publisher", "") or "",
        "genre": game.findtext("genre", "") or "",
        "players": game.findtext("players", "") or "",
        "lang": game.findtext("lang", "") or "",
    }
    for f in MEDIA_DIRS:
        current[f] = game.findtext(f, "") or ""
    return current


@bp.route("/api/adb/scrape/<int:index>", methods=["POST"])
def api_adb_scrape(index):
    """
    Look up a game on Arcade Database (MAME romset name).
    Optional body: { "romset": "mslug" } to force a specific set.
    """
    err = require_gamelist()
    if err:
        return err
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="bad_index")

    body = request.get_json(silent=True) or {}
    force_romset = str(body.get("romset") or body.get("gameid") or "").strip()

    path_rel = game.findtext("path", "") or ""
    rom_name = os.path.basename(path_rel) if path_rel else ""
    romset = force_romset or os.path.splitext(rom_name)[0]
    # Clean common extra suffixes in non-pure MAME names
    if not force_romset:
        romset = romset.strip()
    local_name = game.findtext("name", "") or romset
    system_id, system_folder = detect_system_id()

    if not romset:
        return api_err(
            st("server.adb_no_romset"),
            400,
            code="no_romset",
        )

    # 1) Exact query (with parent fallback for clones)
    ok, data, _ = adb_request("query_mame", {
        "game_name": romset,
        "use_parent": "1",
        "lang": "en",
    })
    results = []
    if ok:
        results = (data.get("result") or []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            results = []

    # 2) If forced romset but empty, fail
    if force_romset and not results:
        return api_err(
            st("server.adb_romset_missing", romset=force_romset),
            404,
            code="adb_not_found",
            romset=force_romset,
        )

    # 3) Fuzzy list if exact miss
    if not results:
        ok2, data2, _ = adb_request("query_mame_like", {"game_name": romset})
        if ok2:
            results = (data2.get("result") or []) if isinstance(data2, dict) else []
            if not isinstance(results, list):
                results = []
        elif not ok:
            return api_err(str(data), 502, code="adb_error")

    if not results:
        return api_err(
            st("server.adb_not_found", romset=romset, folder=system_folder),
            404,
            code="adb_not_found",
            romset=romset,
            system_folder=system_folder,
        )

    # Single exact-ish match → full proposal
    if len(results) == 1 or force_romset:
        item = results[0]
        # If we only had lightweight "like" results, re-fetch full data
        gname = (item.get("game_name") or "").strip()
        if gname and ("history" not in item or "url_image_ingame" not in item):
            ok3, data3, _ = adb_request("query_mame", {
                "game_name": gname,
                "use_parent": "1",
                "lang": "en",
            })
            if ok3:
                full = (data3.get("result") or []) if isinstance(data3, dict) else []
                if full:
                    item = full[0]
        item = enrich_adb_item_media(item)
        parsed = parse_adb_game(item)
        if not parsed:
            return api_err(st("server.adb_unusable"), 502)
        return jsonify({
            "success": True,
            "match_method": "romset" if force_romset or len(results) == 1 else "search",
            "source": "arcadeitalia",
            "system_id": system_id,
            "system_folder": system_folder,
            "rom_name": rom_name,
            "romset": romset,
            "proposed": parsed,
            "current": adb_current_from_game(game),
        })

    # Multiple candidates
    candidates = []
    for item in results[:15]:
        gname = (item.get("game_name") or "").strip()
        title = (item.get("title") or item.get("short_title") or gname).strip()
        score = name_similarity(romset, gname) if gname else 0.0
        score = max(score, name_similarity(local_name, title))
        candidates.append({
            "ss_id": gname,  # reused by UI as id key
            "name": title,
            "names": [title, gname] if gname and gname != title else [title],
            "system": (item.get("manufacturer") or "")[:40],
            "score": round(score, 3),
            "romset": gname,
        })
    candidates.sort(key=lambda c: c.get("score", 0), reverse=True)

    # Strong unique name match → fetch full record
    if candidates and candidates[0]["score"] >= 0.95 and (
        len(candidates) == 1 or candidates[0]["score"] > candidates[1]["score"] + 0.15
    ):
        gname = candidates[0]["ss_id"]
        ok3, data3, _ = adb_request("query_mame", {
            "game_name": gname,
            "use_parent": "1",
            "lang": "en",
        })
        if ok3:
            full = (data3.get("result") or []) if isinstance(data3, dict) else []
            if full:
                parsed = parse_adb_game(enrich_adb_item_media(full[0]))
                if parsed:
                    return jsonify({
                        "success": True,
                        "match_method": "name-unique",
                        "source": "arcadeitalia",
                        "system_id": system_id,
                        "system_folder": system_folder,
                        "rom_name": rom_name,
                        "romset": romset,
                        "proposed": parsed,
                        "current": adb_current_from_game(game),
                    })

    return jsonify({
        "success": True,
        "need_choice": True,
        "match_method": "search",
        "source": "arcadeitalia",
        "system_id": system_id,
        "system_folder": system_folder,
        "rom_name": rom_name,
        "romset": romset,
        "local_name": local_name,
        "search": romset,
        "candidates": candidates,
        "message": "Plusieurs romsets possibles sur Arcade Database — choisis le bon.",
    })


@bp.route("/api/adb/apply/<int:index>", methods=["POST"])
def api_adb_apply(index):
    """Apply selected Arcade Database fields — same contract as /api/ss/apply."""
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    fields = list(body.get("fields") or [])
    proposed = body.get("proposed") or {}
    if (proposed.get("arcadesystemname") or "").strip() and "arcadesystemname" not in fields:
        fields.append("arcadesystemname")
    if not fields:
        return api_err(st("server.no_fields"), 400, code="no_fields")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="bad_index")

    applied = []
    errors = []
    meta_map = {
        "name": "name", "desc": "desc", "rating": "rating",
        "releasedate": "releasedate", "developer": "developer",
        "publisher": "publisher", "genre": "genre",
        "players": "players", "lang": "lang", "region": "region",
        "family": "family", "kidgame": "kidgame",
        "arcadesystemname": "arcadesystemname",
    }

    for field in fields:
        if field not in meta_map:
            continue
        value = (proposed.get(field) or "").strip()
        if field == "name" and not value:
            errors.append(st("server.name_empty_ignored"))
            continue
        if field == "rating" and value:
            try:
                fval = float(value)
                if not (0.0 <= fval <= 1.0):
                    errors.append(st("server.rating_range_value", value=value))
                    continue
            except ValueError:
                errors.append(st("server.rating_invalid_value", value=value))
                continue
        if field == "lang" and value:
            value = value.lower()
        tag = meta_map[field]
        elem = game.find(tag)
        if value == "":
            if elem is not None:
                game.remove(elem)
        else:
            if elem is None:
                if tag == "name":
                    elem = etree.Element("name")
                    game.insert(0, elem)
                elif tag == "desc":
                    name_elem = game.find("name")
                    elem = etree.Element("desc")
                    if name_elem is not None:
                        name_elem.addnext(elem)
                    else:
                        game.append(elem)
                else:
                    elem = etree.SubElement(game, tag)
            elem.text = value
        applied.append(field)

    medias = proposed.get("medias") or {}
    base_name = get_base_name(game)
    for field in fields:
        if field not in MEDIA_DIRS:
            continue
        info = medias.get(field) or {}
        url = (info.get("url") or "").strip()
        if not url:
            errors.append(f"{field}: {st('server.no_adb_url')}")
            continue
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(xml_store.BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        try:
            new_filename = download_remote_media(
                url, media_dir, base_name, field,
                headers={"User-Agent": ADB_UA},
                timeout=40,
            )
            rel_path = f"./{media_dir_name}/{new_filename}"
            old_rel = game.findtext(field, "") or ""
            if old_rel and resolve_under_base(old_rel) != resolve_under_base(rel_path):
                safe_delete_file(old_rel)
            elem = game.find(field)
            if elem is None:
                elem = etree.SubElement(game, field)
            elem.text = rel_path
            applied.append(field)
        except ValueError as e:
            if str(e) == "too_large":
                errors.append(f"{field}: {st('server.file_too_large', n=MAX_DOWNLOAD_BYTES // (1024*1024))}")
            elif str(e) == "url_not_allowed":
                errors.append(f"{field}: {st('server.url_not_http')}")
            elif str(e) == "green_placeholder":
                continue
            else:
                errors.append(f"{field}: {e}")
        except Exception as e:
            errors.append(f"{field}: {e}")

    if applied:
        save_xml(tree)

    return jsonify({"success": True, "applied": applied, "errors": errors, "source": "arcadeitalia"})
