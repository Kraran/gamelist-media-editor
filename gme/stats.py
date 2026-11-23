"""Statistics of the open gamelist (Actions › Statistics).

GET /api/stats?required=image,video   counts for the whole gamelist:
games, hidden / favorite / kids, games with a description, rated, dated,
"scraped" (a description or at least one media), genres, play counts and
time, and for every media tag: present (file found), broken (tag pointing
to a missing file) and missing (no tag). ``required`` is the system's list
of required media (Settings › Required media): ``complete`` counts the games
that have them all on disk.
"""

import os
from collections import Counter

from flask import Blueprint, jsonify, request

from gme import xml_store
from gme.xml_store import MEDIA_DIRS, load_xml, require_gamelist, resolve_under_base

bp = Blueprint("stats", __name__)
TOP_GENRES = 12


def _true(value):
    return (value or "").strip().lower() in ("true", "1", "yes")


def _int(value):
    try:
        return max(0, int(float((value or "0").strip() or 0)))
    except ValueError:
        return 0


def compute(tree, required=()):
    games = tree.getroot().findall("game")
    media = {f: {"present": 0, "broken": 0, "missing": 0} for f in xml_store.media_fields()}
    exists = {}                              # path → on disk (files shared by clones checked once)
    genres, out = Counter(), Counter()
    most = None
    for game in games:
        text = {child.tag: (child.text or "").strip() for child in reversed(game) if isinstance(child.tag, str)}
        out["hidden"] += _true(text.get("hidden"))
        out["favorite"] += _true(text.get("favorite"))
        out["kidgame"] += _true(text.get("kidgame"))
        out["with_desc"] += bool(text.get("desc"))
        out["rated"] += bool(text.get("rating"))
        out["dated"] += bool(text.get("releasedate"))
        main = text.get("genre", "").split("/")[0].strip()
        if main:
            genres[main.upper()] += 1
        else:
            out["no_genre"] += 1
        plays = _int(text.get("playcount"))
        if plays:
            out["played"] += 1
            out["playcount"] += plays
            if most is None or plays > most["playcount"]:
                most = {"name": text.get("name", ""), "playcount": plays}
        out["gametime"] += _int(text.get("gametime"))
        has_media, complete = False, True
        for field, counts in media.items():
            value = text.get(field, "")
            if not value:
                counts["missing"] += 1
                complete = complete and field not in required
                continue
            if value not in exists:
                full = resolve_under_base(value) if "://" not in value else None
                exists[value] = bool(full and os.path.isfile(full))
            if exists[value]:
                counts["present"] += 1
                has_media = True
            else:
                counts["broken"] += 1
                complete = complete and field not in required
        out["scraped"] += bool(text.get("desc")) or has_media
        out["complete"] += complete
    return {
        "games": len(games),
        **{k: out[k] for k in ("hidden", "favorite", "kidgame", "with_desc", "rated", "dated", "no_genre",
                               "scraped", "played", "playcount", "gametime", "complete")},
        "genres": [{"genre": g, "n": n} for g, n in genres.most_common(TOP_GENRES)],
        "genre_count": len(genres),
        "most_played": most,
        "media": [{"field": f, **c} for f, c in media.items()],
        "required": list(required),
    }


@bp.route("/api/stats")
def api_stats():
    err = require_gamelist()
    if err:
        return err
    required = [f for f in (request.args.get("required") or "").split(",") if f in MEDIA_DIRS]
    return jsonify(compute(load_xml(), required))
