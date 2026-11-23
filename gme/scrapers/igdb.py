"""IGDB (api.igdb.com, Twitch), with the user's own Twitch application.

IGDB is free for non-commercial use under the Twitch Developer Service
Agreement. The user registers an application in the Twitch developer console
(Twitch account with two-factor authentication) and gives GME its Client ID
and Client Secret. GME gets an app access token (client credentials) and
keeps it in memory only, until it expires. Limits: 4 requests per second and
8 open requests; GME sends one request at a time, 0.3 s apart, and caches the
answers (``sources.cache_get``).

Per game: one ``/v4/games`` query (name search on the system's platforms)
with every field it needs expanded, so one request fills metadata and media.
"""

import difflib
import threading
import time

import requests

from gme.i18n import st
from gme.scrapers import platforms, sources
from gme.version import APP_UA

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API = "https://api.igdb.com/v4"
IMAGE_URL = "https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg"
_throttle = sources.Throttle(0.3)
_token_lock = threading.Lock()
_token = {"value": "", "expires": 0.0, "client": ""}

FIELDS = ("name,summary,first_release_date,total_rating,rating,genres.name,"
          "involved_companies.developer,involved_companies.publisher,involved_companies.company.name,"
          "cover.image_id,screenshots.image_id,artworks.image_id")
MEDIA = {"thumbnail": ("cover", "cover_big_2x"), "image": ("screenshots", "1080p"),
         "fanart": ("artworks", "1080p")}


class IgdbError(Exception):
    pass


def forget_token():
    with _token_lock:
        _token.update(value="", expires=0.0, client="")


def _get_token(cfg, force=False):
    with _token_lock:
        if not force and _token["value"] and _token["client"] == cfg["igdb_client_id"] \
                and time.time() < _token["expires"] - 60:
            return _token["value"]
        try:
            r = requests.post(TOKEN_URL, params={"client_id": cfg["igdb_client_id"],
                                                 "client_secret": cfg["igdb_client_secret"],
                                                 "grant_type": "client_credentials"},
                              headers={"User-Agent": APP_UA}, timeout=20)
        except requests.RequestException as exc:
            raise IgdbError(st("server.source_network", source="Twitch", detail=sources.redact(exc, cfg)))
        if r.status_code in (400, 401, 403):
            raise IgdbError(st("server.igdb_login"))
        if r.status_code != 200:
            raise IgdbError(st("server.source_bad_answer", source="Twitch", detail=f"HTTP {r.status_code}"))
        try:
            data = r.json()
            value = str(data["access_token"])
            expires = time.time() + float(data.get("expires_in") or 3600)
        except (ValueError, KeyError, TypeError):
            raise IgdbError(st("server.source_bad_answer", source="Twitch", detail="JSON"))
        _token.update(value=value, expires=expires, client=cfg["igdb_client_id"])
        return value


def _post(endpoint, query, cfg, cache_key=None, refresh=False):
    if cache_key is not None:
        cached = sources.cache_get("igdb", [endpoint, cache_key], refresh)
        if cached is not None:
            return cached
    for attempt in range(2):
        token = _get_token(cfg, force=attempt > 0)
        try:
            with _throttle:
                r = requests.post(f"{API}/{endpoint}", data=query.encode("utf-8"),
                                  headers={"Client-ID": cfg["igdb_client_id"], "Authorization": "Bearer " + token,
                                           "Accept": "application/json", "User-Agent": APP_UA}, timeout=25)
        except requests.Timeout:
            raise IgdbError(st("server.source_timeout", source="IGDB"))
        except requests.RequestException as exc:
            raise IgdbError(st("server.source_network", source="IGDB", detail=sources.redact(exc, cfg)))
        if r.status_code == 401 and attempt == 0:
            continue                                  # expired token: one new token, once
        break
    if r.status_code == 429:
        raise IgdbError(st("server.igdb_rate"))
    if r.status_code in (401, 403):
        raise IgdbError(st("server.igdb_login"))
    if r.status_code != 200:
        raise IgdbError(st("server.source_bad_answer", source="IGDB", detail=f"HTTP {r.status_code}"))
    try:
        data = r.json()
    except ValueError:
        raise IgdbError(st("server.source_bad_answer", source="IGDB", detail="JSON"))
    if not isinstance(data, list):
        raise IgdbError(st("server.source_bad_answer", source="IGDB", detail="JSON"))
    if cache_key is not None:
        sources.cache_put("igdb", [endpoint, cache_key], data, empty=not data)
    return data


def test(cfg):
    forget_token()
    _get_token(cfg)
    return {"ok": True}


def _quote(text):
    return '"' + str(text).replace("\\", " ").replace('"', " ") + '"'


def _pick(games, names):
    by_norm = [(sources.norm_title(g.get("name")), g) for g in games if isinstance(g, dict)]
    for norm, _ in names:
        for n, g in by_norm:
            if n == norm:
                return g, "name"
    for norm, _ in names:
        close = difflib.get_close_matches(norm, [n for n, _ in by_norm], n=1, cutoff=0.9)
        if close:
            return next(g for n, g in by_norm if n == close[0]), "fuzzy-name"
    return None, ""


def _date(ts):
    try:
        return time.strftime("%Y%m%dT000000", time.gmtime(int(ts)))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def lookup(game, system_id, needed, ctx):
    cfg = ctx["cfg"]
    plats = platforms.for_source("igdb", system_id)
    if not plats:
        return None, None
    plat_list = ",".join(str(p) for p in plats)
    try:
        found, method = None, ""
        for _, title in ctx["names"][:2]:
            query = f"search {_quote(title)}; fields {FIELDS}; where platforms = ({plat_list}); limit 10;"
            games = _post("games", query, cfg, cache_key=[sources.norm_title(title), plat_list],
                          refresh=ctx.get("refresh", False))
            found, method = _pick(games, ctx["names"])
            if found:
                break
        if not found:
            return None, None
        out = {"medias": {}, "match": method, "source_id": str(found.get("id") or ""),
               "source_name": found.get("name") or ""}
        companies = [c for c in (found.get("involved_companies") or []) if isinstance(c, dict)]

        def company(role):
            return ", ".join(dict.fromkeys(((c.get("company") or {}).get("name") or "")
                                           for c in companies if c.get(role) and (c.get("company") or {}).get("name")))
        rating = found.get("total_rating") or found.get("rating")
        values = {
            "name": found.get("name") or "",
            "desc": (found.get("summary") or "").strip(),
            "releasedate": _date(found.get("first_release_date")),
            "genre": ", ".join(g.get("name") for g in (found.get("genres") or []) if isinstance(g, dict) and g.get("name")),
            "developer": company("developer"),
            "publisher": company("publisher"),
            "rating": f"{max(0.0, min(100.0, float(rating))) / 100:.2f}" if rating else "",
        }
        for key, value in values.items():
            if key in needed and value:
                out[key] = value
        for field, (key, size) in MEDIA.items():
            if field not in needed:
                continue
            item = found.get(key)
            if isinstance(item, list):
                item = item[0] if item else None
            if isinstance(item, dict) and item.get("image_id"):
                out["medias"][field] = {"url": IMAGE_URL.format(size=size, image_id=item["image_id"]),
                                        "type": f"{key} ({size})"}
        return out, None
    except IgdbError as exc:
        return None, str(exc)
