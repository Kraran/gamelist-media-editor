"""What a scrape would change: current value vs proposed value, field by field.

Every scraper returns a ``proposed`` dict (same shape for ScreenScraper,
Arcade Database and Steam). ``compare_rows`` lines it up with the game as it
is in the gamelist and gives each field a status:

- ``new``          the game has nothing there, the source has something
- ``different``    both have a value and they differ (text fields)
- ``replace``      both have a media file (files cannot be compared cheaply)
- ``same``         nothing would change
- ``unavailable``  the source has nothing for this field

The scrape dialog checks ``new`` rows by default (fill the gaps, never
overwrite without asking). ``fields_for_preset`` turns a preset into a field
list on the server too, so a future batch scrape can apply "missing" to many
games without a dialog.
"""

import os
import re

from gme import remote_cache
from gme.media import pad2key_dest
from gme.xml_store import resolve_under_base

META_KEYS = (
    "name", "desc", "rating", "releasedate", "developer", "publisher", "genre",
    "players", "lang", "region", "family", "kidgame", "arcadesystemname",
)
MEDIA_KEYS = (
    "image", "thumbnail", "marquee", "boxart", "boxback", "cartridge", "fanart",
    "mix", "map", "bezel", "video", "manual", "pad2key",
)
NOT_IMAGES = {"video", "manual", "pad2key"}       # shown as text, not previewed
PRESETS = {
    "missing": {"new"},
    "all": {"new", "different", "replace"},
    "none": set(),
}
_CASE_INSENSITIVE = {"lang", "region", "genre"}
_SPACES = re.compile(r"\s+")


def current_from_game(game):
    """The game's values for every field a scraper can fill (media: relative paths)."""
    cur = {k: (game.findtext(k, "") or "") for k in META_KEYS}
    for k in MEDIA_KEYS:
        if k == "pad2key":
            dest = pad2key_dest(game)
            cur[k] = os.path.basename(dest) if dest and os.path.isfile(dest) else ""
        else:
            cur[k] = game.findtext(k, "") or ""
    return cur


def _media_present(key, rel):
    if not rel:
        return False
    if key == "pad2key":
        return True                       # current_from_game only fills it when the file exists
    full = resolve_under_base(rel)
    return bool(full and os.path.isfile(full))


def _norm(key, value):
    v = _SPACES.sub(" ", str(value or "")).strip()
    if key in _CASE_INSENSITIVE:
        v = v.lower()
    return v


def _same_meta(key, cur, new):
    if key == "rating":
        try:
            return abs(float(cur) - float(new)) < 0.005
        except ValueError:
            pass
    if key == "releasedate":
        dc, dn = re.sub(r"\D", "", cur)[:8], re.sub(r"\D", "", new)[:8]
        if dc and dn:
            return dc == dn
    if key == "kidgame":
        return (cur.lower() == "true") == (new.lower() == "true")
    return _norm(key, cur) == _norm(key, new)


def compare_rows(proposed, current, headers=None, previews=True):
    """One row per field, in display order. Registers image previews (``previews``)."""
    proposed = proposed or {}
    medias = proposed.get("medias") or {}
    rows = []
    for key in META_KEYS:
        new = str(proposed.get(key) or "").strip()
        cur = str(current.get(key) or "")
        if not new:
            status = "unavailable"
        elif not cur.strip():
            status = "new"
        elif _same_meta(key, cur, new):
            status = "same"
        else:
            status = "different"
        rows.append({"key": key, "kind": "meta", "status": status, "current": cur, "proposed": new})
    for key in MEDIA_KEYS:
        info = medias.get(key) or {}
        url = (info.get("url") or "").strip()
        cur = str(current.get(key) or "")
        present = _media_present(key, cur)
        if not url:
            status = "unavailable"
        elif present:
            status = "replace"
        else:
            status = "new"
        row = {
            "key": key, "kind": "media", "status": status,
            "current": cur if present else "",
            "media_type": info.get("type") or "",
        }
        for extra in ("quality", "bytes", "trailer"):
            if info.get(extra):
                row[extra] = info[extra]
        if previews and url and key not in NOT_IMAGES:
            row["preview"] = "/api/scrape/preview/" + remote_cache.register(url, headers)
        rows.append(row)
    return rows


def fields_for_preset(rows, preset):
    """Field keys a preset selects ("missing", "all", "none")."""
    wanted = PRESETS.get(preset)
    if wanted is None:
        raise ValueError("unknown_preset")
    return [r["key"] for r in rows if r["status"] in wanted]


def scrape_payload(game, proposed, headers=None):
    """The ``current`` and ``compare`` parts every scrape response carries."""
    current = current_from_game(game)
    return {"current": current, "compare": compare_rows(proposed, current, headers)}
