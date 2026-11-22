"""CSV export of the game list (Actions › Export the list): the games shown in the UI, in that order.

UTF-8 with a BOM, so Excel reads the accents; the separator follows the UI
language (``;`` where the decimal mark is a comma, as Excel expects there).
Column names are the gamelist tags: the same file works whatever the language.
"""

import csv
import io
import re

from gme.xml_store import BOOL_META_FIELDS, LIST_FIELDS, MEDIA_DIRS, game_fields

MEDIA_FIELDS = tuple(MEDIA_DIRS)
DEFAULT_REQUIRED = ("image", "video", "marquee", "boxart")
SEPARATORS = (",", ";", "\t")
META_COLUMNS = ("path", "name", "genre", "releasedate", "developer", "publisher", "players",
                "rating", "favorite", "hidden", "kidgame", "region", "lang")
COLUMNS = META_COLUMNS + ("media", "required_media", "missing_required")
_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})(T\d{6})?$")
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _cell(value):
    """A spreadsheet must not run a cell as a formula (=HYPERLINK… from a scraped name)."""
    value = str(value or "")
    return "'" + value if value.startswith(_FORMULA) else value


def _date(value):
    """19920315T000000 → 1992-03-15 (a date Excel recognises); anything else as stored."""
    m = _DATE.match(value or "")
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else (value or "")


def _bool(value):
    return "true" if str(value or "").strip().lower() in ("true", "1", "yes") else "false"


def ordered_games(root, paths=None):
    """List fields of the games, in the order of ``paths`` (the UI list), or all games by name.

    Unknown paths are skipped; a path listed twice in the gamelist is exported twice.
    """
    games = [game_fields(g, i, LIST_FIELDS) for i, g in enumerate(root.iterchildren("game"))]
    if paths is None:
        return sorted(games, key=lambda g: g["name"].lower())
    by_path = {}
    for g in games:
        by_path.setdefault(g["path"], []).append(g)
    out = []
    for p in paths:
        queue = by_path.get(p)
        if queue:
            out.append(queue.pop(0))
    return out


def build_csv(games, required=DEFAULT_REQUIRED, sep=";"):
    """CSV bytes (UTF-8 + BOM) for ``games`` (dicts of game_fields)."""
    required = [f for f in MEDIA_FIELDS if f in required]
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=sep, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(COLUMNS)
    for g in games:
        row = []
        for col in META_COLUMNS:
            value = g.get(col, "")
            if col in BOOL_META_FIELDS:
                value = _bool(value)
            elif col == "releasedate":
                value = _date(value)
            row.append(_cell(value))
        present = [f for f in MEDIA_FIELDS if str(g.get(f) or "").strip()]
        missing = [f for f in required if f not in present]
        row += [str(len(present)), f"{len(required) - len(missing)}/{len(required)}", ", ".join(missing)]
        writer.writerow(row)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")
