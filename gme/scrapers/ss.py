"""ScreenScraper scraper: API client, response parsing and routes."""

import os
import re
import json

import requests
from flask import Blueprint, jsonify, request
from lxml import etree

from gme import xml_store
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st
from gme.media import MAX_DOWNLOAD_BYTES, download_pad2key, download_remote_media, pad2key_dest, safe_delete_file
from gme.paths import APP_DIR
from gme.scrapers.common import throttle_api, clean_game_name, name_similarity, rom_identification
from gme.systems import detect_system_id
from gme.version import APP_UA, SS_SOFTNAME
from gme.xml_store import MEDIA_DIRS, P2K_TYPES, get_base_name, get_game_elem, require_gamelist, resolve_under_base, save_xml

bp = Blueprint("ss", __name__)


# --- ScreenScraper ------------------------------------------------------------
# Developer credentials are obfuscated (NOT secret): they identify *this app*
# on the SS API. End users may add their member login for a quota boost.
SS_API = "https://api.screenscraper.fr/api2"

SS_CONFIG_NAME = "screenscraper_config.json"


def _ss_unmask(blob: str) -> str:
    """De-obfuscate built-in developer credentials (XOR + base64).
    This is NOT real encryption — the key ships with the app. It only avoids
    leaving plaintext in the source for casual reading.
    """
    import base64
    key = b"GamelistMediaEditor/SS/v1"
    raw = base64.b64decode(blob.encode("ascii"))
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode("utf-8")


# Developer credentials identify *this software* (not end users).
_SS_DEV_ID = _ss_unmask("DBMMFw0H")
_SS_DEV_PASS = _ss_unmask("MhQnVQNdKjx7DFY=")

# ES field → ScreenScraper type. No fallback to another artwork kind if missing.
SS_MEDIA_PREF = {
    "image": ["ss"],
    "video": ["video-normalized"],
    "marquee": ["wheel-hd"],
    "manual": ["manuel"],
    "boxback": ["box-2D-back"],
    "boxart": ["box-3D"],
    "cartridge": ["support-2D"],
    "fanart": ["fanart"],
    "mix": ["mixrbv2"],
    "map": ["maps"],
    "thumbnail": ["box-2D"],
    "bezel": ["bezel-16-9"],
}
# User-configurable type (Outils → ScreenScraper). Only that type is requested.
SS_MEDIA_CHOICES = {
    "image": ("ss", "sstitle"),
    "boxart": ("box-2D", "box-3D"),
    "mix": ("mixrbv1", "mixrbv2"),
}
SS_MEDIA_DEFAULTS = {
    "image": "ss",
    "boxart": "box-3D",
    "mix": "mixrbv2",
}


def ss_config_path():
    """Config lives next to the .exe / app.py (writable), not next to the XML."""
    return os.path.join(APP_DIR, SS_CONFIG_NAME)


def normalize_ss_media_types(raw):
    """Keep only allowed image/boxart/mix types; fill defaults for missing keys."""
    out = dict(SS_MEDIA_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for field, allowed in SS_MEDIA_CHOICES.items():
        val = str(raw.get(field) or "").strip()
        for opt in allowed:
            if val.lower() == opt.lower():
                out[field] = opt
                break
    return out


def ss_media_pref(cfg=None):
    """Exact SS type per field. Configurable fields use only the saved choice."""
    cfg = cfg or load_ss_config()
    chosen = cfg.get("media_types") or SS_MEDIA_DEFAULTS
    prefs = {k: list(v) for k, v in SS_MEDIA_PREF.items()}
    for field, first in chosen.items():
        if field not in prefs or not first:
            continue
        prefs[field] = [first]
    return prefs


def load_ss_config():
    """User boost credentials + region + media type prefs (local file)."""
    path = ss_config_path()
    defaults = {
        "ssid": "",
        "sspassword": "",
        "prefer_region": "fr",
        "media_types": dict(SS_MEDIA_DEFAULTS),
    }
    if not os.path.isfile(path):
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return defaults
        for k in ("ssid", "sspassword", "prefer_region"):
            if k in data and data[k] is not None:
                defaults[k] = str(data[k]).strip()
        defaults["media_types"] = normalize_ss_media_types(data.get("media_types"))
        return defaults
    except Exception:
        return defaults


def save_ss_config(data):
    """Persist user boost, region and media type prefs (never write built-in dev password)."""
    cfg = load_ss_config()
    for k in ("ssid", "prefer_region"):
        if k in data and data[k] is not None:
            cfg[k] = str(data[k]).strip()
    if data.get("sspassword"):
        cfg["sspassword"] = str(data["sspassword"])
    if data.get("clear_sspassword"):
        cfg["sspassword"] = ""
    if "media_types" in data:
        cfg["media_types"] = normalize_ss_media_types(data.get("media_types"))
    cfg.pop("devid", None)
    cfg.pop("devpassword", None)
    path = ss_config_path()
    atomic_write(path, json.dumps(cfg, indent=2, ensure_ascii=False).encode("utf-8"))
    return cfg


def ss_public_config(cfg=None):
    """Config for the UI — no developer secrets."""
    cfg = cfg or load_ss_config()
    return {
        "ssid": cfg.get("ssid") or "",
        "sspassword_set": bool(cfg.get("sspassword")),
        "prefer_region": cfg.get("prefer_region") or "fr",
        "media_types": normalize_ss_media_types(cfg.get("media_types")),
        "softname": SS_SOFTNAME,
        "configured": True,
        "user_boost": bool(cfg.get("ssid") and cfg.get("sspassword")),
    }


def extract_ss_names(jeu):
    """All display names from a SS jeu object."""
    names = []
    noms = jeu.get("noms") or jeu.get("nom")
    if isinstance(noms, list):
        for n in noms:
            if isinstance(n, dict):
                t = (n.get("text") or n.get("nom") or "").strip()
                if t:
                    names.append(t)
            elif isinstance(n, str) and n.strip():
                names.append(n.strip())
    elif isinstance(noms, dict):
        t = (noms.get("text") or noms.get("nom") or "").strip()
        if t:
            names.append(t)
    elif isinstance(noms, str) and noms.strip():
        names.append(noms.strip())
    return names


def ss_candidate_summary(jeu, query_name=""):
    """Compact candidate for the UI picker."""
    names = extract_ss_names(jeu)
    best = names[0] if names else f"#{jeu.get('id')}"
    score = max((name_similarity(query_name, n) for n in names), default=0.0)
    systeme = jeu.get("systeme") or {}
    sys_name = ""
    if isinstance(systeme, dict):
        sys_name = (systeme.get("text") or systeme.get("nom") or "").strip()
    return {
        "ss_id": str(jeu.get("id") or ""),
        "name": best,
        "names": names[:6],
        "system": sys_name,
        "score": round(score, 3),
    }


def format_ss_error(raw, status=200):
    """Map ScreenScraper error text → localized message."""
    t = (raw or "").strip()
    low = t.lower()
    if not t and status == 429:
        return st("server.ss_429")
    if status == 503:
        return st("server.ss_503")
    if any(k in low for k in ("login", "identifiant", "password", "mot de passe", "bad ident")):
        return st("server.ss_login")
    if "api closed" in low or "api ferm" in low or "fermee" in low or "fermée" in low:
        return st("server.ss_api_closed")
    if any(
        k in low
        for k in (
            "quota", "overquota", "over quota", "trop de requ", "demande",
            "threads", "thread", "maxthreads", "limit", "limite",
            "exceed", "depass", "dépass",
        )
    ):
        return st("server.ss_quota")
    if status == 429 or "429" in low:
        return st("server.ss_too_many")
    if t.startswith("Erreur") or t.startswith("API"):
        return t[:400]
    if status != 200:
        return st("server.ss_http", status=status, detail=t[:250])
    return t[:400] if t else st("server.ss_error", status=status)


def ss_request(endpoint, extra_params=None, timeout=25):
    """
    Call ScreenScraper API2. Returns (ok, data_or_error_str, http_status).
    Built-in developer credentials + optional user ssid/sspassword for quota boost.
    Throttled to avoid burst / quota spikes.
    """
    cfg = load_ss_config()
    params = {
        "devid": _SS_DEV_ID,
        "devpassword": _SS_DEV_PASS,
        "softname": SS_SOFTNAME,
        "output": "json",
    }
    if cfg.get("ssid") and cfg.get("sspassword"):
        params["ssid"] = cfg["ssid"]
        params["sspassword"] = cfg["sspassword"]
    if extra_params:
        params.update({k: v for k, v in extra_params.items() if v is not None and v != ""})
    url = f"{SS_API}/{endpoint}"
    throttle_api("ss")
    try:
        r = requests.get(
            url,
            params=params,
            headers={"User-Agent": APP_UA},
            timeout=timeout,
        )
        body = r.text or ""
        if r.status_code == 429:
            return False, format_ss_error(body, 429), 429
        if r.status_code == 503:
            return False, format_ss_error(body, 503), 503
        if r.status_code != 200:
            return False, format_ss_error(body, r.status_code), r.status_code
        stripped = body.strip()
        if stripped.startswith("Erreur") or stripped.lower().startswith("api closed"):
            return False, format_ss_error(stripped, r.status_code), r.status_code
        try:
            data = r.json()
        except Exception:
            # Plain-text quota messages sometimes without "Erreur" prefix
            if any(k in stripped.lower() for k in ("quota", "thread", "limit")):
                return False, format_ss_error(stripped, r.status_code), r.status_code
            return False, f"Réponse non JSON: {stripped[:300]}", r.status_code
        header = data.get("header") or {}
        err = (header.get("error") or "").strip()
        if err and err not in ("OK", "0", "none", "null"):
            if header.get("success") not in ("true", True, "1", 1):
                return False, format_ss_error(err, r.status_code), r.status_code
        return True, data, r.status_code
    except requests.Timeout:
        return False, "Délai d'attente ScreenScraper dépassé — le serveur est peut-être surchargé.", 504
    except requests.RequestException as e:
        return False, f"Réseau ScreenScraper: {e}", 502


def _ss_pick_text(entries, prefer_region="fr", key_region="region", key_text="text"):
    """Pick best localized text from list of {region, text} or similar."""
    if not entries:
        return ""
    if isinstance(entries, str):
        return entries.strip()
    if isinstance(entries, dict):
        # single object
        return (entries.get(key_text) or entries.get("nom") or entries.get("synopsis") or "").strip()
    if not isinstance(entries, list):
        return str(entries).strip()
    prefer = [prefer_region, "fr", "eu", "wor", "us", "jp", "ss"]
    # dedupe prefer order
    seen = set()
    order = []
    for r in prefer:
        if r not in seen:
            order.append(r)
            seen.add(r)
    by_region = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        reg = (e.get(key_region) or e.get("langue") or "").lower()
        txt = (e.get(key_text) or e.get("nom") or e.get("synopsis") or "").strip()
        if txt:
            by_region[reg] = txt
    for r in order:
        if r in by_region:
            return by_region[r]
    # any
    for v in by_region.values():
        return v
    return ""


def _ss_pick_media(medias, preferred_types, prefer_region="fr"):
    """Return best media URL for preferred types."""
    if not medias:
        return None, None
    if not isinstance(medias, list):
        medias = [medias]
    prefer = [prefer_region, "wor", "eu", "us", "jp", "ss", ""]
    prefs_l = [t.strip().lower() for t in preferred_types]
    candidates = []
    for m in medias:
        if not isinstance(m, dict):
            continue
        mtype = (m.get("type") or "").strip().lower()
        url = m.get("url") or ""
        if not url:
            continue
        region = (m.get("region") or "").lower()
        try:
            type_rank = prefs_l.index(mtype)
        except ValueError:
            continue
        try:
            region_rank = prefer.index(region) if region in prefer else len(prefer)
        except ValueError:
            region_rank = len(prefer)
        candidates.append((type_rank, region_rank, url, mtype, region))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (x[0], x[1]))
    best = candidates[0]
    return best[2], best[3]


def parse_ss_game(jeu, prefer_region="fr", media_pref=None):
    """Map ScreenScraper jeu object → ES-oriented dict."""
    if not jeu or not isinstance(jeu, dict):
        return None
    noms = jeu.get("noms") or jeu.get("nom")
    name = _ss_pick_text(noms, prefer_region)
    if not name and isinstance(noms, list) and noms:
        name = _ss_pick_text(noms, prefer_region, key_text="text")
    synopsis = jeu.get("synopsis") or []
    desc = _ss_pick_text(synopsis, prefer_region, key_text="text")
    # rating: note is often /20
    note = jeu.get("note") or {}
    rating = ""
    try:
        raw = note.get("text") if isinstance(note, dict) else note
        if raw not in (None, ""):
            val = float(str(raw).replace(",", "."))
            # SS notes are typically 0–20
            if val > 1.0:
                val = val / 20.0
            rating = f"{max(0.0, min(1.0, val)):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        pass
    # dates
    dates = jeu.get("dates") or []
    releasedate = ""
    date_txt = _ss_pick_text(dates, prefer_region, key_text="text")
    if date_txt:
        digits = "".join(c for c in date_txt if c.isdigit())
        if len(digits) >= 8:
            releasedate = digits[:8] + "T000000"
        elif len(digits) == 4:
            releasedate = digits + "0101T000000"
    developer = ""
    dev = jeu.get("developpeur") or jeu.get("developer")
    if isinstance(dev, dict):
        developer = (dev.get("text") or dev.get("nom") or "").strip()
    elif isinstance(dev, str):
        developer = dev.strip()
    publisher = ""
    ed = jeu.get("editeur") or jeu.get("publisher")
    if isinstance(ed, dict):
        publisher = (ed.get("text") or ed.get("nom") or "").strip()
    elif isinstance(ed, str):
        publisher = ed.strip()
    # genre: first genre name
    genre = ""
    genres = jeu.get("genres") or []
    if isinstance(genres, list) and genres:
        g0 = genres[0]
        if isinstance(g0, dict):
            gn = g0.get("noms") or g0.get("nom")
            genre = _ss_pick_text(gn, prefer_region).upper()
    family = ""
    familles = jeu.get("familles") or jeu.get("famille") or []
    if isinstance(familles, dict):
        familles = [familles]
    if isinstance(familles, list) and familles:
        f0 = familles[0]
        if isinstance(f0, dict):
            family = _ss_pick_text(f0.get("noms") or f0.get("nom"), prefer_region)
        elif isinstance(f0, str):
            family = f0.strip()
    players = ""
    joueurs = jeu.get("joueurs") or {}
    if isinstance(joueurs, dict):
        players = (joueurs.get("text") or "").strip()
    elif isinstance(joueurs, str):
        players = joueurs.strip()
    lang = ""
    langues = jeu.get("langues") or {}
    if isinstance(langues, dict):
        lang = (langues.get("text") or "").strip().split(",")[0].strip().lower()
    elif isinstance(langues, str):
        lang = langues.split(",")[0].strip().lower()
    region = ""
    regions = jeu.get("regions") or jeu.get("region") or {}
    if isinstance(regions, dict):
        region = (regions.get("text") or "").strip().split(",")[0].strip().lower()
        if not region:
            inner = regions.get("region") or regions.get("regions") or []
            if isinstance(inner, list) and inner:
                r0 = inner[0]
                region = (r0.get("text") if isinstance(r0, dict) else str(r0)).strip().lower()
            elif isinstance(inner, dict):
                region = (inner.get("text") or "").strip().lower()
            elif isinstance(inner, str):
                region = inner.strip().lower()
    elif isinstance(regions, list) and regions:
        r0 = regions[0]
        region = (r0.get("text") if isinstance(r0, dict) else str(r0)).strip().lower()
    elif isinstance(regions, str):
        region = regions.split(",")[0].strip().lower()
    if "," in region:
        region = region.split(",")[0].strip()
    medias = jeu.get("medias") or []
    media_out = {}
    prefs_map = media_pref or ss_media_pref()
    for field, prefs in prefs_map.items():
        url, mtype = _ss_pick_media(medias, prefs, prefer_region)
        if url:
            media_out[field] = {"url": url, "type": mtype}
    p2k_url, p2k_type = _ss_pick_media(medias, P2K_TYPES, prefer_region)
    if p2k_url:
        media_out["pad2key"] = {"url": p2k_url, "type": p2k_type}
    return {
        "ss_id": str(jeu.get("id") or ""),
        "name": name,
        "desc": desc,
        "rating": rating,
        "releasedate": releasedate,
        "developer": developer,
        "publisher": publisher,
        "family": family,
        "genre": genre,
        "players": players,
        "lang": lang,
        "region": region,
        "arcadesystemname": "",
        "medias": media_out,
    }


@bp.route("/api/ss/config", methods=["GET", "POST"])
def api_ss_config():
    """Load or save user boost credentials (local file only, gitignored)."""
    if request.method == "GET":
        return jsonify(ss_public_config())
    try:
        body = request.get_json(silent=True) or {}
        current = load_ss_config()
        payload = {}
        if "ssid" in body:
            payload["ssid"] = (body.get("ssid") or "").strip()
        if "prefer_region" in body:
            payload["prefer_region"] = (body.get("prefer_region") or "fr").strip()
        if "media_types" in body:
            payload["media_types"] = body.get("media_types") or {}
        if body.get("sspassword"):
            payload["sspassword"] = body["sspassword"]
        if body.get("clear_sspassword"):
            payload["clear_sspassword"] = True
        merged = dict(current)
        merged.update(payload)
        cfg = save_ss_config(merged)
        return jsonify({"success": True, "config": ss_public_config(cfg)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/ss/test", methods=["POST"])
def api_ss_test():
    """Test API (built-in dev credentials + optional user boost)."""
    cfg = load_ss_config()
    # Prefer user info if user creds present
    if cfg.get("ssid") and cfg.get("sspassword"):
        ok, data, status = ss_request("ssuserInfos.php")
        if ok:
            user = (data.get("response") or {}).get("ssuser") or {}
            return jsonify({
                "success": True,
                "mode": "user",
                "id": user.get("id") or cfg.get("ssid"),
                "level": user.get("niveau") or user.get("level") or "",
                "maxthreads": user.get("maxthreads") or "",
                "requeststoday": user.get("requetesauj") or user.get("requeststoday") or "",
                "raw_keys": list(user.keys())[:20] if isinstance(user, dict) else [],
            })
        # fall through to infra test with error note
        user_err = data
    else:
        user_err = None
    ok, data, status = ss_request("ssinfraInfos.php")
    if ok:
        return jsonify({
            "success": True,
            "mode": "infra",
            "message": st("server.ss_dev_ok"),
            "user_error": user_err if user_err else None,
        })
    return jsonify({"error": str(data)}), 400


@bp.route("/api/ss/scrape/<int:index>", methods=["POST"])
def api_ss_scrape(index):
    """
    Look up a game on ScreenScraper.
    1) Prefer CRC/MD5 of the ROM (inner file if .zip)
    2) If ambiguous / not found → return ranked candidates for the user to pick
    Optional body: { "gameid": "12345" } to force a specific SS game.
    """
    err = require_gamelist()
    if err:
        return err
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    cfg = load_ss_config()
    body = request.get_json(silent=True) or {}
    force_id = str(body.get("gameid") or "").strip()

    path_rel = game.findtext("path", "") or ""
    rom_name = os.path.basename(path_rel) if path_rel else ""
    local_name = game.findtext("name", "") or os.path.splitext(rom_name)[0]
    system_id, system_folder = detect_system_id()
    prefer = cfg.get("prefer_region") or "fr"

    rom_full = resolve_under_base(path_rel) if path_rel else None
    hash_info = rom_identification(rom_full) if rom_full else None
    api_errors = []  # collect real SS messages (auth, not found, …)

    def full_from_jeu(jeu, match_method):
        parsed = parse_ss_game(jeu, prefer, ss_media_pref(cfg))
        if not parsed:
            return None
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
        return {
            "success": True,
            "match_method": match_method,
            "system_id": system_id,
            "system_folder": system_folder,
            "rom_name": rom_name,
            "hash": hash_info,
            "proposed": parsed,
            "current": current,
        }

    # --- Forced game id (user picked a candidate) ---
    if force_id:
        extra = {"gameid": force_id}
        if system_id:
            extra["systemeid"] = str(system_id)
        ok, data, _ = ss_request("jeuInfos.php", extra)
        if not ok:
            return api_err(st("server.ss_gameid_error", id=force_id, detail=data), 404, code="ss_gameid")
        jeu = (data.get("response") or {}).get("jeu")
        if isinstance(jeu, list):
            jeu = jeu[0] if jeu else None
        result = full_from_jeu(jeu, "gameid")
        if not result:
            return api_err(st("server.ss_empty_gameid"), 404, code="ss_empty")
        return jsonify(result)

    # --- 1) Hash / exact ROM identification (several variants) ---
    def try_jeu_infos(extra, method):
        ok, data, _ = ss_request("jeuInfos.php", extra)
        if not ok:
            api_errors.append(f"{method}: {data}")
            return None
        jeu = (data.get("response") or {}).get("jeu")
        if isinstance(jeu, list):
            jeu = jeu[0] if jeu else None
        return full_from_jeu(jeu, method)

    if hash_info and hash_info.get("crc"):
        id_romnom = hash_info.get("inner_name") or rom_name
        base_hash = {
            "romtype": "rom",
            "crc": hash_info["crc"],
            "md5": hash_info.get("md5") or "",
            "sha1": hash_info.get("sha1") or "",
            "romtaille": str(hash_info.get("size") or ""),
        }
        attempts = []
        # A) inner name + system
        if id_romnom and system_id:
            attempts.append(({**base_hash, "romnom": id_romnom, "systemeid": str(system_id)}, "hash"))
        # B) outer name + system
        if rom_name and system_id and rom_name != id_romnom:
            attempts.append(({**base_hash, "romnom": rom_name, "systemeid": str(system_id)}, "hash-zipname"))
        # C) CRC only + system (no romnom — SS can match on hash alone)
        if system_id:
            attempts.append(({**base_hash, "systemeid": str(system_id)}, "hash-nosystemname"))
        # D) inner name, no system (system map wrong?)
        if id_romnom:
            attempts.append(({**base_hash, "romnom": id_romnom}, "hash-nosystem"))
        # E) CRC only, no system
        attempts.append((dict(base_hash), "hash-crc-only"))

        seen = set()
        for extra, method in attempts:
            key = tuple(sorted((k, str(v)) for k, v in extra.items()))
            if key in seen:
                continue
            seen.add(key)
            result = try_jeu_infos(extra, method)
            if result:
                return jsonify(result)

    # --- 2) Search by cleaned name → candidates (never auto-pick a weak match) ---
    search_name = clean_game_name(local_name) or clean_game_name(rom_name) or local_name
    # Use a slightly cleaned display name for recherche (keep some structure)
    recherche = re.sub(r"[\\(\\[].*?[\\)\\]]", "", local_name or rom_name)
    recherche = re.sub(r"\\s+", " ", recherche).strip()
    if not recherche:
        recherche = local_name or rom_name

    def run_search(params):
        ok, data, _ = ss_request("jeuRecherche.php", params)
        found = []
        if not ok:
            api_errors.append(f"search: {data}")
            return found
        response = data.get("response") or {}
        jeux = response.get("jeux") or response.get("jeu") or []
        if isinstance(jeux, dict):
            jeux = [jeux]
        if not isinstance(jeux, list):
            return found
        for jeu in jeux:
            if not isinstance(jeu, dict) or not jeu.get("id"):
                continue
            found.append(ss_candidate_summary(jeu, local_name or rom_name))
        return found

    candidates = []
    if system_id:
        candidates = run_search({"recherche": recherche, "systemeid": str(system_id)})
    if not candidates:
        candidates = run_search({"recherche": recherche})
    # Also try cleaned name if different
    if not candidates and search_name and search_name != recherche.lower():
        if system_id:
            candidates = run_search({"recherche": search_name, "systemeid": str(system_id)})
        if not candidates:
            candidates = run_search({"recherche": search_name})
    # Deduplicate by ss_id, keep best score
    by_id = {}
    for c in candidates:
        sid = c.get("ss_id")
        if not sid:
            continue
        if sid not in by_id or c.get("score", 0) > by_id[sid].get("score", 0):
            by_id[sid] = c
    candidates = sorted(by_id.values(), key=lambda c: c.get("score", 0), reverse=True)

    # Strong unique match by name → auto-select only if score is very high and unique
    if len(candidates) == 1 and candidates[0].get("score", 0) >= 0.85:
        ok3, data3, _ = ss_request("jeuInfos.php", {
            "gameid": candidates[0]["ss_id"],
            "systemeid": str(system_id) if system_id else None,
        })
        if ok3:
            jeu = (data3.get("response") or {}).get("jeu")
            if isinstance(jeu, list):
                jeu = jeu[0] if jeu else None
            result = full_from_jeu(jeu, "name-unique")
            if result:
                return jsonify(result)

    if candidates:
        return jsonify({
            "success": True,
            "need_choice": True,
            "match_method": "search",
            "system_id": system_id,
            "system_folder": system_folder,
            "rom_name": rom_name,
            "local_name": local_name,
            "search": recherche,
            "hash": hash_info,
            "candidates": candidates[:15],
            "message": st("server.ss_candidates"),
        })

    # Prefer showing login/config errors over a generic "not found"
    login_err = next(
        (
            e for e in api_errors
            if any(
                k in e.lower()
                for k in (
                    "login", "identifiant", "manquants",
                    "quota", "thread", "limite", "limit", "429", "503",
                    "fermée", "fermee", "closed", "trop de requ",
                )
            )
        ),
        None,
    )
    if login_err:
        msg = login_err
    elif api_errors:
        msg = st("server.ss_not_found") + " — " + str(api_errors[-1])
    else:
        msg = st("server.ss_not_found")
    if system_id:
        msg += f" (SS id={system_id}, {system_folder})"
    else:
        msg += f" ({system_folder})"
    return jsonify({
        "error": msg,
        "api_errors": api_errors[-6:],
        "system_id": system_id,
        "system_folder": system_folder,
        "rom_name": rom_name,
        "local_name": local_name,
        "search": recherche,
        "hash": hash_info,
    }), 404


@bp.route("/api/ss/apply/<int:index>", methods=["POST"])
def api_ss_apply(index):
    """
    Apply selected ScreenScraper fields to the game.
    Body: { "fields": ["desc","image",...], "proposed": { ... from scrape ... } }
    Media fields: download from proposed.medias[field].url via existing upload logic.
    """
    err = require_gamelist()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    fields = body.get("fields") or []
    proposed = body.get("proposed") or {}
    if not fields:
        return api_err(st("server.no_fields"), 400, code="no_fields")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")

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

    # Text / meta fields
    for field in fields:
        if field in meta_map:
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

    # Media fields — download. Thumbnail is always applied when SS has box-2D.
    medias = proposed.get("medias") or {}
    base_name = get_base_name(game)
    media_fields = [f for f in fields if f in MEDIA_DIRS]
    if "thumbnail" not in media_fields:
        media_fields.append("thumbnail")
    if "bezel" not in media_fields:
        media_fields.append("bezel")
    for field in media_fields:
        info = medias.get(field) or {}
        url = (info.get("url") or "").strip()
        if not url:
            if field in ("thumbnail", "bezel"):
                continue
            errors.append(f"{field}: {st('server.no_ss_url')}")
            continue
        media_dir_name = MEDIA_DIRS[field]
        media_dir = os.path.join(xml_store.BASE_DIR, media_dir_name)
        os.makedirs(media_dir, exist_ok=True)
        try:
            new_filename = download_remote_media(
                url, media_dir, base_name, field, timeout=40
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

    p2k = (medias.get("pad2key") or {})
    p2k_url = (p2k.get("url") or "").strip()
    if p2k_url:
        try:
            dest = pad2key_dest(game)
            download_pad2key(p2k_url, dest)
            applied.append("pad2key")
        except Exception as e:
            errors.append(f"pad2key: {e}")

    if applied:
        save_xml(tree)

    return jsonify({
        "success": True,
        "applied": applied,
        "errors": errors,
    })
