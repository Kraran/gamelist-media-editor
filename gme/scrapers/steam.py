"""Steam trailer scraper: store search, video selection and routes."""

import os
import re
from urllib.parse import urlparse

import requests
from flask import Blueprint, jsonify, request

from gme import xml_store
from gme.http import api_err
from gme.i18n import st
from gme.media import MAX_DOWNLOAD_BYTES
from gme.scrapers.apply import apply_route
from gme.scrapers.common import throttle_api, clean_game_name, name_similarity
from gme.scrapers.compare import scrape_payload
from gme.systems import detect_system_id
from gme.version import APP_UA
from gme.xml_store import MEDIA_DIRS, get_base_name, get_game_elem, require_gamelist

bp = Blueprint("steam", __name__)


# --- Steam store trailers -----------------------------------------------------
# Unofficial store API + legacy progressive MP4 on the Steam CDN.
# movie_max.mp4 ≈ best quality (often 1080p); movie480.mp4 = 480p fallback.
STEAM_APPDETAILS = "https://store.steampowered.com/api/appdetails"
STEAM_STORESEARCH = "https://store.steampowered.com/api/storesearch/"
STEAM_SEARCHAPPS = "https://steamcommunity.com/actions/SearchApps/"
STEAM_UA = f"{APP_UA} (Steam trailer; +https://github.com/Kraran/gamelist-media-editor)"
STEAM_CDN_MP4 = "https://cdn.akamai.steamstatic.com/steam/apps/{mid}/{name}"


def _steam_https(url):
    url = (url or "").strip()
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url


def _steam_headers():
    return {"User-Agent": STEAM_UA, "Accept": "application/json"}


def parse_steam_appid(text):
    """Extract a Steam AppID from an URL, path, or bare number."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    m = re.search(r"(?:store\.steampowered\.com/app/|/app/)(\d{1,10})", s, re.I)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{1,10}", s):
        return s
    return None


def steam_probe(url, timeout=12):
    """HEAD a Steam CDN URL.

    Returns (exists, size_or_none).
    exists is False on 404/410/empty HTML error pages — never treat that as 'unknown size'.
    """
    url = _steam_https(url)
    if not url:
        return False, None
    try:
        r = requests.head(
            url,
            headers={"User-Agent": STEAM_UA},
            timeout=timeout,
            allow_redirects=True,
        )
        if r.status_code in (404, 410, 403):
            return False, None
        if r.status_code >= 400:
            return False, None
        ct = (r.headers.get("Content-Type") or "").lower()
        if "text/html" in ct:
            return False, None
        cl = r.headers.get("Content-Length")
        size = int(cl) if cl and str(cl).isdigit() else None
        if size is not None and size < 4096:
            return False, None
        return True, size
    except requests.RequestException:
        return False, None


def steam_cdn_mp4(movie_id, quality):
    name = "movie_max.mp4" if quality == "max" else "movie480.mp4"
    return STEAM_CDN_MP4.format(mid=movie_id, name=name)


def steam_pick_video(movie):
    """
    Choose a progressive MP4 for one Steam movie.
    Prefer max if it exists and size <= 50 MB, else 480p.
    Returns dict or None when this movie has no downloadable MP4.
    """
    if not isinstance(movie, dict):
        return None
    mid = movie.get("id")
    if mid in (None, ""):
        return None
    mp4 = movie.get("mp4") or {}
    if not isinstance(mp4, dict):
        mp4 = {}
    url_max = _steam_https(mp4.get("max") or "") or steam_cdn_mp4(mid, "max")
    url_480 = _steam_https(mp4.get("480") or "") or steam_cdn_mp4(mid, "480")

    exists_max, size_max = steam_probe(url_max)
    exists_480, size_480 = steam_probe(url_480)

    def usable(exists, size):
        if not exists:
            return False
        if size is None:
            return True
        return 0 < size <= MAX_DOWNLOAD_BYTES

    chosen = quality = size = None
    fallback = fallback_size = None

    if usable(exists_max, size_max):
        chosen, quality, size = url_max, "max", size_max
    elif usable(exists_480, size_480):
        chosen, quality, size = url_480, "480", size_480

    if chosen and quality == "max" and exists_480 and url_480 != chosen:
        fallback, fallback_size = url_480, size_480

    if not chosen:
        return None
    return {
        "url": chosen,
        "fallback_url": fallback or "",
        "type": f"steam-mp4-{quality}",
        "quality": quality,
        "bytes": size,
        "fallback_bytes": fallback_size,
        "movie_id": str(mid),
        "trailer": (movie.get("name") or "").strip(),
        "highlight": bool(movie.get("highlight")),
    }


_STEAM_FR_NAME = re.compile(
    r"(?:^|[\s\-_\(\[/])(fr|fra|french|fran[cç]ais|vf|vff|vofr|france)(?:$|[\s\-_\.\)\]])",
    re.I,
)


def steam_movie_is_french(name):
    """True when the trailer title looks localized in French."""
    return bool(_STEAM_FR_NAME.search(name or ""))


def steam_request_appdetails(appid, lang="french", cc="FR", timeout=25):
    """Return (ok, data_or_error, status). data is the inner app payload."""
    throttle_api("steam")
    try:
        r = requests.get(
            STEAM_APPDETAILS,
            params={"appids": str(appid), "l": lang, "cc": cc},
            headers=_steam_headers(),
            timeout=timeout,
        )
        if r.status_code != 200:
            return False, st("server.steam_http", status=r.status_code), r.status_code
        payload = r.json()
        block = payload.get(str(appid)) or payload.get(appid)
        if not isinstance(block, dict) or not block.get("success"):
            return False, st("server.steam_app_missing", id=appid), 404
        data = block.get("data") or {}
        if not isinstance(data, dict):
            return False, st("server.steam_app_missing", id=appid), 404
        return True, data, r.status_code
    except requests.Timeout:
        return False, st("server.steam_timeout"), 504
    except Exception as e:
        return False, st("server.steam_error", detail=e), 502


def steam_search(term, timeout=20):
    """Return list of {ss_id, name, score, system} candidates."""
    term = (term or "").strip()
    if not term:
        return []
    found = []
    throttle_api("steam")
    try:
        r = requests.get(
            STEAM_STORESEARCH,
            params={"term": term, "l": "french", "cc": "FR"},
            headers=_steam_headers(),
            timeout=timeout,
        )
        if r.status_code == 200:
            items = (r.json() or {}).get("items") or []
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    aid = it.get("id")
                    name = (it.get("name") or "").strip()
                    if not aid or not name:
                        continue
                    found.append({
                        "ss_id": str(aid),
                        "name": name,
                        "names": [name],
                        "system": "Steam",
                        "score": round(name_similarity(term, name), 3),
                        "appid": str(aid),
                    })
    except Exception:
        pass
    if found:
        return found
    # Fallback community search
    throttle_api("steam")
    try:
        from urllib.parse import quote
        r = requests.get(
            STEAM_SEARCHAPPS + quote(term),
            headers=_steam_headers(),
            timeout=timeout,
        )
        if r.status_code == 200:
            items = r.json() or []
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    aid = it.get("appid") or it.get("id")
                    name = (it.get("name") or "").strip()
                    if not aid or not name:
                        continue
                    found.append({
                        "ss_id": str(aid),
                        "name": name,
                        "names": [name],
                        "system": "Steam",
                        "score": round(name_similarity(term, name), 3),
                        "appid": str(aid),
                    })
    except Exception:
        pass
    return found


def parse_steam_game(data, video_info):
    """Map Steam appdetails + chosen trailer → SS-shaped proposed dict."""
    name = (data.get("name") or "").strip()
    desc = (data.get("short_description") or data.get("about_the_game") or "").strip()
    # strip simple HTML from about_the_game if used
    if desc and "<" in desc:
        desc = re.sub(r"<[^>]+>", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
    developers = data.get("developers") or []
    publishers = data.get("publishers") or []
    developer = ", ".join(developers) if isinstance(developers, list) else str(developers or "")
    publisher = ", ".join(publishers) if isinstance(publishers, list) else str(publishers or "")
    releasedate = ""
    rd = data.get("release_date") or {}
    date_txt = (rd.get("date") or "") if isinstance(rd, dict) else ""
    digits = "".join(c for c in date_txt if c.isdigit())
    if len(digits) >= 8:
        releasedate = digits[:8] + "T000000"
    elif len(digits) == 4:
        releasedate = digits + "0101T000000"
    genre = ""
    genres = data.get("genres") or []
    if isinstance(genres, list) and genres:
        g0 = genres[0]
        if isinstance(g0, dict):
            genre = (g0.get("description") or "").strip().upper()
    medias = {}
    if video_info and video_info.get("url"):
        medias["video"] = {
            "url": video_info["url"],
            "fallback_url": video_info.get("fallback_url") or "",
            "type": video_info.get("type") or "steam-mp4",
            "quality": video_info.get("quality") or "",
            "bytes": video_info.get("bytes"),
            "trailer": video_info.get("trailer") or "",
        }
    return {
        "ss_id": str(data.get("steam_appid") or ""),
        "steam_appid": str(data.get("steam_appid") or ""),
        "name": name,
        "desc": desc,
        "rating": "",
        "releasedate": releasedate,
        "developer": developer,
        "publisher": publisher,
        "genre": genre,
        "players": "",
        "lang": "fr",
        "medias": medias,
        "source": "steam",
        "trailer": (video_info or {}).get("trailer") or "",
        "video_quality": (video_info or {}).get("quality") or "",
        "video_bytes": (video_info or {}).get("bytes"),
    }


def steam_choose_movie(movies):
    """Prefer a French-titled trailer when one exists, else the newest."""
    if not isinstance(movies, list):
        return None, None
    usable = []
    for movie in movies:
        if not isinstance(movie, dict) or movie.get("id") is None:
            continue
        info = steam_pick_video(movie)
        if info:
            usable.append((movie, info))
    if not usable:
        return None, None
    french = [pair for pair in usable if steam_movie_is_french(pair[0].get("name"))]
    pool = french or usable
    pool.sort(key=lambda pair: int(pair[0].get("id") or 0), reverse=True)
    return pool[0]


def steam_load_app(appid):
    """French store page first; fall back to English movies if FR has none."""
    ok_fr, data_fr, status_fr = steam_request_appdetails(appid, lang="french", cc="FR")
    if not ok_fr:
        return steam_request_appdetails(appid, lang="english", cc="US")
    movies = data_fr.get("movies") or []
    if not movies:
        ok_en, data_en, _ = steam_request_appdetails(appid, lang="english", cc="US")
        if ok_en and isinstance(data_en, dict):
            data_fr["movies"] = data_en.get("movies") or []
    return True, data_fr, status_fr


@bp.route("/api/steam/scrape/<int:index>", methods=["POST"])
def api_steam_scrape(index):
    """
    Look up a Steam store trailer for the current game.
    Body optional: { "appid": "400" } or { "gameid": "400" } after a candidate pick.
    French store text when available. Newest French trailer if named as such,
    else newest trailer. movie_max.mp4 if <= 50 MB else movie480.mp4.
    """
    err = require_gamelist()
    if err:
        return err
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")

    body = request.get_json(silent=True) or {}
    force_id = str(body.get("appid") or body.get("gameid") or "").strip()
    path_rel = game.findtext("path", "") or ""
    rom_name = os.path.basename(path_rel) if path_rel else ""
    local_name = game.findtext("name", "") or os.path.splitext(rom_name)[0]
    _, system_folder = detect_system_id()

    appid = parse_steam_appid(force_id) or parse_steam_appid(local_name) or parse_steam_appid(path_rel)

    def finish(data, method):
        movies = data.get("movies") or []
        movie, video_info = steam_choose_movie(movies)
        if not video_info:
            return api_err(
                st("server.steam_no_movies", name=data.get("name") or appid or "?"),
                404,
                code="steam_no_movies",
            )
        parsed = parse_steam_game(data, video_info)
        return jsonify({
            "success": True,
            "match_method": method,
            "source": "steam",
            "system_folder": system_folder,
            "rom_name": rom_name,
            "local_name": local_name,
            "proposed": parsed,
            **scrape_payload(game, parsed),
            "steam_appid": parsed.get("steam_appid"),
            "trailer": video_info.get("trailer"),
            "video_quality": video_info.get("quality"),
            "video_bytes": video_info.get("bytes"),
        })

    if appid:
        ok, data, _ = steam_load_app(appid)
        if not ok:
            return api_err(str(data), 404, code="steam_app_missing")
        return finish(data, "appid")

    search_name = clean_game_name(local_name) or clean_game_name(rom_name) or local_name
    candidates = steam_search(search_name)
    if not candidates:
        return api_err(
            st("server.steam_not_found", name=local_name or rom_name or "?"),
            404,
            code="steam_not_found",
        )

    by_id = {}
    for c in candidates:
        sid = c.get("ss_id")
        if not sid:
            continue
        if sid not in by_id or c.get("score", 0) > by_id[sid].get("score", 0):
            by_id[sid] = c
    candidates = sorted(by_id.values(), key=lambda c: c.get("score", 0), reverse=True)

    if len(candidates) == 1 and candidates[0].get("score", 0) >= 0.85:
        ok, data, _ = steam_load_app(candidates[0]["ss_id"])
        if ok:
            return finish(data, "name-unique")

    if candidates[0].get("score", 0) >= 0.95 and (
        len(candidates) == 1 or candidates[0]["score"] > candidates[1].get("score", 0) + 0.15
    ):
        ok, data, _ = steam_load_app(candidates[0]["ss_id"])
        if ok:
            return finish(data, "name-unique")

    return jsonify({
        "success": True,
        "need_choice": True,
        "match_method": "search",
        "source": "steam",
        "system_folder": system_folder,
        "rom_name": rom_name,
        "local_name": local_name,
        "search": search_name,
        "candidates": candidates[:15],
        "message": st("server.steam_candidates"),
    })


def steam_download_video(game, field, info):
    """Steam trailer: best quality first, then the 480p fallback if over the limit."""
    urls = []
    for u in (info.get("url"), info.get("fallback_url")):
        if u and u not in urls:
            urls.append(u)
    media_dir_name = MEDIA_DIRS[field]
    media_dir = os.path.join(xml_store.BASE_DIR, media_dir_name)
    os.makedirs(media_dir, exist_ok=True)
    filename = f"{get_base_name(game)}-{field}.mp4"
    dest = os.path.join(media_dir, filename)
    last_err = None
    for url in urls:
        url = _steam_https(url)
        if urlparse(url).scheme not in ("http", "https"):
            last_err = st("server.url_not_http")
            continue
        tmp = dest + ".part"
        try:
            r = requests.get(url, headers={"User-Agent": STEAM_UA}, timeout=60, stream=True)
            r.raise_for_status()
            written = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(65536):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise ValueError("too_large")
                    f.write(chunk)
            os.replace(tmp, dest)
            return f"./{media_dir_name}/{filename}"
        except ValueError:
            last_err = st("server.file_too_large", n=MAX_DOWNLOAD_BYTES // (1024 * 1024))
        except Exception as e:
            last_err = str(e)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    raise RuntimeError(last_err or st("server.steam_too_large"))


@bp.route("/api/steam/apply/<int:index>", methods=["POST"])
def api_steam_apply(index):
    """Apply the selected Steam fields (contract: gme/scrapers/apply.py)."""
    return apply_route(
        index, "steam",
        headers={"User-Agent": STEAM_UA},
        media_handlers={"video": steam_download_video},
        no_url_key="server.no_steam_url",
    )
