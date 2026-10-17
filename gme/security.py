"""Request guards: local-only access (CSRF, DNS rebinding) and game identity (stale XML index)."""

from urllib.parse import urlparse

from flask import g as flask_g
from flask import request

from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.xml_store import find_game_index_by_path, has_gamelist, load_xml


# --- Local-only request guard (CSRF + DNS rebinding) --------------------------
# Binding to 127.0.0.1 is not enough: any web page open in the user's browser
# can still send "simple" POSTs to http://127.0.0.1:5050 (no CORS preflight),
# and get_json(silent=True) turns their empty body into {} — so routes such as
# /api/delete-game would run. A DNS-rebinding page could even read responses.
#   * Host must be a loopback name → blocks DNS rebinding (attacker hostname).
#   * State-changing methods must come from this very origin: Origin (sent by
#     browsers on every POST) must equal our own host, and Sec-Fetch-Site must
#     not be cross-site / same-site. Requests without these headers (curl,
#     scripts) are not browser CSRF and stay allowed.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hostname(netloc):
    """'127.0.0.1:5050' / '[::1]:5050' / 'localhost' → bare lowercase host."""
    netloc = (netloc or "").strip().lower()
    if netloc.startswith("["):
        return netloc[1:].split("]", 1)[0]
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc


def guard_local_requests():
    host = request.host or ""
    if _hostname(host) not in _LOOPBACK_HOSTS:
        log.warning("Rejected request with non-local Host %r: %s %s",
                    host, request.method, request.path)
        return api_err("Forbidden host", 403, code="forbidden_host")

    if request.method in _SAFE_METHODS:
        return None

    fetch_site = (request.headers.get("Sec-Fetch-Site") or "").lower()
    if fetch_site in ("cross-site", "same-site"):
        log.warning("Rejected %s request (Sec-Fetch-Site=%s): %s",
                    request.method, fetch_site, request.path)
        return api_err("Forbidden origin", 403, code="forbidden_origin")

    origin = request.headers.get("Origin")
    if origin is not None:
        parsed = urlparse(origin)
        if parsed.scheme != "http" or parsed.netloc.lower() != host.lower():
            log.warning("Rejected %s request from Origin %r: %s",
                        request.method, origin, request.path)
            return api_err("Forbidden origin", 403, code="forbidden_origin")
    return None


def check_game_identity():
    view_args = request.view_args or {}
    if "index" not in view_args or request.method != "POST":
        return None
    expected = request.args.get("path")
    if not expected or not has_gamelist():
        return None
    index = view_args["index"]
    games = load_xml().getroot().findall("game")
    if 0 <= index < len(games) and (games[index].findtext("path", "") or "") == expected:
        return None
    matches = find_game_index_by_path(expected)
    if len(matches) != 1:
        log.warning("Stale game reference: index %s, path %r (%d match)",
                    index, expected, len(matches))
        return api_err(st("server.stale_game"), 409, code="stale_game",
                       path=expected, matches=len(matches))
    log.info("Game %r moved in gamelist.xml: index %s -> %s", expected, index, matches[0])
    view_args["index"] = matches[0]
    flask_g.game_reindexed = matches[0]
    return None


def flag_reindexed(response):
    new_index = flask_g.get("game_reindexed")
    if new_index is not None:
        response.headers["X-Game-Reindexed"] = str(new_index)
    return response
