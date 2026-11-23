"""TheGamesDB (api.thegamesdb.net), with the user's own API key.

A key is asked for on the TheGamesDB forum ("API Requests"); public keys
have a small monthly allowance, given back in every answer
(``remaining_monthly_allowance`` + ``extra_allowance``). GME reads it, stops
asking when it reaches zero (until ``allowance_refresh_timer``), sends one
request at a time, one per second at most, and caches every answer
(``sources.cache_get``) so a game is never asked twice. The key travels in the
query string as the API wants, so URLs are never logged or shown (``redact``).

Per game: the ROM CRC first (``/v1/Games/ByGameHash``), else the name
(``/v1.1/Games/ByGameName``), both on the system's platform(s); then the
images (``/v1/Games/Images``) only when a media is still missing. Genre,
developer and publisher ids are turned into names with their lists, fetched
once and cached.
"""

import difflib
import threading
import time

import requests

from gme.i18n import st
from gme.scrapers import platforms, sources
from gme.version import APP_UA

API = "https://api.thegamesdb.net"
IMAGES_FALLBACK_BASE = "https://cdn.thegamesdb.net/images/original/"
_throttle = sources.Throttle(1.0)
_allowance_lock = threading.Lock()
_allowance = {"remaining": None, "until": 0.0}

# gamelist field: (TheGamesDB image type, boxart side)
MEDIA = {
    "thumbnail": ("boxart", "front"),
    "boxback": ("boxart", "back"),
    "image": ("screenshot", None),
    "titleshot": ("titlescreen", None),
    "marquee": ("clearlogo", None),
    "wheel": ("clearlogo", None),
    "fanart": ("fanart", None),
}
LISTS = {"genre": ("Genres", "genres", "genres"), "developer": ("Developers", "developers", "developers"),
         "publisher": ("Publishers", "publishers", "publishers")}


class TgdbError(Exception):
    pass


def allowance():
    with _allowance_lock:
        return dict(_allowance)


def _note_allowance(data):
    try:
        remaining = int(data.get("remaining_monthly_allowance") or 0) + int(data.get("extra_allowance") or 0)
    except (TypeError, ValueError):
        return
    timer = data.get("allowance_refresh_timer")
    with _allowance_lock:
        _allowance["remaining"] = remaining
        if remaining <= 0 and timer:
            try:
                _allowance["until"] = time.time() + float(timer)
            except (TypeError, ValueError):
                _allowance["until"] = time.time() + 3600
        elif remaining > 0:
            _allowance["until"] = 0.0


def _exhausted():
    with _allowance_lock:
        return _allowance["until"] and time.time() < _allowance["until"]


def _get(path, params, cfg, cache_key=None, refresh=False, count_allowance=True):
    """One API call (cached when ``cache_key``). Raises TgdbError."""
    if cache_key is not None:
        cached = sources.cache_get("thegamesdb", [path, cache_key], refresh)
        if cached is not None:
            return cached
    if count_allowance and _exhausted():
        raise TgdbError(st("server.tgdb_allowance"))
    query = dict(params, apikey=cfg["tgdb_apikey"])
    try:
        with _throttle:
            r = requests.get(API + path, params=query, headers={"User-Agent": APP_UA}, timeout=25)
    except requests.Timeout:
        raise TgdbError(st("server.source_timeout", source="TheGamesDB"))
    except requests.RequestException as exc:
        raise TgdbError(st("server.source_network", source="TheGamesDB", detail=sources.redact(exc, cfg)))
    if r.status_code == 403:
        raise TgdbError(st("server.tgdb_forbidden"))
    if r.status_code != 200:
        raise TgdbError(st("server.source_bad_answer", source="TheGamesDB", detail=f"HTTP {r.status_code}"))
    try:
        data = r.json()
    except ValueError:
        raise TgdbError(st("server.source_bad_answer", source="TheGamesDB", detail="JSON"))
    if not isinstance(data, dict):
        raise TgdbError(st("server.source_bad_answer", source="TheGamesDB", detail="JSON"))
    _note_allowance(data)
    if cache_key is not None:
        clean = {k: v for k, v in data.items() if k in ("data", "include")}
        sources.cache_put("thegamesdb", [path, cache_key], clean, empty="/Games/By" in path and not _games(clean))
    return data


def _games(data):
    games = ((data or {}).get("data") or {}).get("games") or []
    return [g for g in games if isinstance(g, dict)] if isinstance(games, list) else []


def test(cfg):
    """``/v1/API/Limit`` (costs no allowance) → the allowance left."""
    data = _get("/v1/API/Limit", {}, cfg, count_allowance=False)
    return {"remaining": data.get("remaining_monthly_allowance"), "extra": data.get("extra_allowance"),
            "refresh_in": data.get("allowance_refresh_timer")}


def _pick(games, names):
    """The game whose title matches one of ``names``, or None."""
    by_norm = [(sources.norm_title(g.get("game_title")), g) for g in games]
    for norm, _ in names:
        for n, g in by_norm:
            if n == norm:
                return g, "name"
    for norm, _ in names:
        close = difflib.get_close_matches(norm, [n for n, _ in by_norm], n=1, cutoff=0.9)
        if close:
            return next(g for n, g in by_norm if n == close[0]), "fuzzy-name"
    return None, ""


def _names_for(kind, ids, cfg, refresh):
    path, data_key, _ = LISTS[kind]
    data = _get("/v1/" + path, {}, cfg, cache_key=["list"], refresh=False)
    table = ((data.get("data") or {}).get(data_key)) or {}
    out = []
    for i in ids or []:
        entry = table.get(str(i)) or {}
        if entry.get("name"):
            out.append(entry["name"])
    return out


def lookup(game, system_id, needed, ctx):
    cfg = ctx["cfg"]
    plat = platforms.for_source("thegamesdb", system_id)
    if not plat:
        return None, None
    refresh = ctx.get("refresh", False)
    fields = "players,publishers,genres,overview,rating"
    try:
        found, method = None, ""
        crc = ((ctx.get("hash") or {}).get("crc") or "").lower()
        if crc:
            data = _get("/v1/Games/ByGameHash", {"hash": crc, "filter[type]": "crc", "filter[platform]": plat,
                                                  "fields": fields}, cfg,
                        cache_key=["crc", crc, plat], refresh=refresh)
            games = _games(data)
            if games:
                found, method = games[0], "crc"
        if not found:
            for _, title in ctx["names"][:2]:
                data = _get("/v1.1/Games/ByGameName", {"name": title, "filter[platform]": plat, "fields": fields},
                            cfg, cache_key=["name", sources.norm_title(title), plat], refresh=refresh)
                found, method = _pick(_games(data), ctx["names"])
                if found:
                    break
        if not found:
            return None, None
        out = {"medias": {}, "match": method, "source_id": str(found.get("id")),
               "source_name": found.get("game_title") or ""}
        values = {
            "name": found.get("game_title") or "",
            "desc": (found.get("overview") or "").strip(),
            "releasedate": sources.iso_to_es(found.get("release_date")),
            "players": str(found.get("players") or "") if found.get("players") else "",
        }
        for kind in LISTS:
            if kind in needed and found.get(LISTS[kind][2]):
                values[kind] = ", ".join(_names_for(kind, found.get(LISTS[kind][2]), cfg, refresh))
        for key, value in values.items():
            if key in needed and value:
                out[key] = value
        wanted = [f for f in MEDIA if f in needed]
        if wanted and found.get("id"):
            types = sorted({kind for kind, _ in MEDIA.values()})     # always the same: one cache entry
            data = _get("/v1/Games/Images", {"games_id": str(found["id"]), "filter[type]": ",".join(types)}, cfg,
                        cache_key=["images", str(found["id"]), types], refresh=refresh)
            body = data.get("data") or {}
            base = ((body.get("base_url") or {}).get("original")) or IMAGES_FALLBACK_BASE
            images = ((body.get("images") or {}).get(str(found["id"]))) or []
            for field in wanted:
                kind, side = MEDIA[field]
                pool = [im for im in images if isinstance(im, dict) and im.get("type") == kind
                        and (side is None or (im.get("side") or "front") == side) and im.get("filename")]
                if pool:
                    pool.sort(key=lambda im: int(im.get("id") or 0))
                    label = kind + (f" ({side})" if side else "")
                    out["medias"][field] = {"url": base + str(pool[0]["filename"]).lstrip("/"), "type": label}
        return out, None
    except TgdbError as exc:
        return None, str(exc)
