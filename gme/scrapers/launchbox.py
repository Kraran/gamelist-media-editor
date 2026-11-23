"""LaunchBox Games Database, from its public daily metadata archive.

LaunchBox publishes its whole games database for any application to use as
one archive, ``Metadata.zip`` (about 110 MB, rebuilt every day). There is no
search API and no key: GME downloads the archive when the user asks (Settings ›
Fallback sources), at most once a day, turns it into a small SQLite index in
``cache/launchbox/`` (only the image kinds it uses, only the platforms GME
knows) and deletes the archive. Lookups are then local: no request per game.
Images are downloaded from ``images.launchbox-app.com`` like any other media
(one at a time).
"""

import difflib
import os
import sqlite3
import threading
import time
import zipfile
from contextlib import closing
from xml.etree import ElementTree as ET

import requests

from gme.log import log
from gme.paths import APP_DIR
from gme.scrapers import platforms, sources
from gme.version import APP_UA

METADATA_URL = "https://gamesdb.launchbox-app.com/Metadata.zip"
IMAGES_URL = "https://images.launchbox-app.com/"
LB_DIR = os.path.join(APP_DIR, "cache", "launchbox")
DB_NAME = "launchbox.sqlite"
MIN_AGE = 24 * 3600                  # the archive changes once a day
MAX_ARCHIVE = 600 * 1024 * 1024
SCHEMA = 1

# gamelist field: LaunchBox image types, best first
MEDIA_TYPES = {
    "image": ("Screenshot - Gameplay",),
    "titleshot": ("Screenshot - Game Title",),
    "thumbnail": ("Box - Front", "Box - Front - Reconstructed"),
    "boxart": ("Box - 3D",),
    "boxback": ("Box - Back", "Box - Back - Reconstructed"),
    "marquee": ("Clear Logo",),
    "wheel": ("Clear Logo",),
    "cartridge": ("Cart - Front", "Disc"),
    "fanart": ("Fanart - Background",),
}
KEPT_TYPES = tuple(dict.fromkeys(t for types in MEDIA_TYPES.values() for t in types))
_TYPE_CODE = {t: i for i, t in enumerate(KEPT_TYPES)}      # stored as a small number

_state_lock = threading.Lock()
_state = {"running": False, "phase": "", "done": 0, "total": 0, "error": "", "games": 0}
_fuzzy_cache = {}


def db_path():
    return os.path.join(LB_DIR, DB_NAME)


def _connect(path=None):
    conn = sqlite3.connect(path or db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _meta():
    path = db_path()
    if not os.path.isfile(path):
        return {}
    try:
        with closing(_connect(path)) as conn:
            return {r["k"]: r["v"] for r in conn.execute("SELECT k, v FROM meta")}
    except sqlite3.Error:
        return {}


def ready():
    meta = _meta()
    return meta.get("schema") == str(SCHEMA) and int(meta.get("games") or 0) > 0


def status():
    """The base for the interface: when, how many games, download progress."""
    meta = _meta()
    with _state_lock:
        st = dict(_state)
    downloaded = float(meta.get("downloaded") or 0)
    wait = max(0, int(MIN_AGE - (time.time() - downloaded))) if downloaded else 0
    return {
        "ready": meta.get("schema") == str(SCHEMA) and int(meta.get("games") or 0) > 0,
        "games": int(meta.get("games") or 0),
        "images": int(meta.get("images") or 0),
        "updated": meta.get("archive_date") or "",
        "downloaded": downloaded,
        "next_in": wait,
        **{k: st[k] for k in ("running", "phase", "done", "total", "error")},
    }


def _set(**kw):
    with _state_lock:
        _state.update(kw)


def start_update():
    """Download and index the archive in the background. ``(started, reason)``."""
    with _state_lock:
        if _state["running"]:
            return False, "running"
        info_age = time.time() - float(_meta().get("downloaded") or 0)
        if info_age < MIN_AGE:
            return False, "recent"
        _state.update(running=True, phase="download", done=0, total=0, error="", games=0)
    threading.Thread(target=_update, name="gme-launchbox", daemon=True).start()
    return True, ""


def _update():
    os.makedirs(LB_DIR, exist_ok=True)
    archive = os.path.join(LB_DIR, "Metadata.zip.part")
    try:
        archive_date = _download(archive)
        _set(phase="index", done=0, total=0)
        build_index(archive, db_path(), archive_date=archive_date)
        _set(running=False, phase="", error="")
    except Exception as exc:                          # reported in the settings
        log.warning("LaunchBox base not updated: %s", exc)
        _set(running=False, phase="", error=str(exc)[:300])
    finally:
        try:
            os.remove(archive)
        except OSError:
            pass


def _download(dest):
    with requests.get(METADATA_URL, headers={"User-Agent": APP_UA}, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        if total > MAX_ARCHIVE:
            raise ValueError("too_large")
        _set(total=total)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                done += len(chunk)
                if done > MAX_ARCHIVE:
                    raise ValueError("too_large")
                f.write(chunk)
                _set(done=done)
        return r.headers.get("last-modified") or ""


def _text(elem, tag):
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def build_index(archive, dest, archive_date=""):
    """``Metadata.zip`` → SQLite index at ``dest`` (written aside, then swapped)."""
    known = {name for entry in platforms.PLATFORMS.values() for name in entry[0]}
    tmp = dest + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = _connect(tmp)
    try:
        conn.executescript("""
            PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
            CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE games (id INTEGER PRIMARY KEY, platform TEXT, name TEXT, norm TEXT,
                overview TEXT, released TEXT, developer TEXT, publisher TEXT, genres TEXT,
                players TEXT, rating REAL);
            CREATE TABLE alts (id INTEGER, norm TEXT);
            CREATE TABLE images (id INTEGER, type INTEGER, region TEXT, file TEXT);
        """)
        games = alts = images = 0
        batch = {"games": [], "alts": [], "images": []}

        def flush():
            conn.executemany("INSERT OR REPLACE INTO games VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch["games"])
            conn.executemany("INSERT INTO alts VALUES (?,?)", batch["alts"])
            conn.executemany("INSERT INTO images VALUES (?,?,?,?)", batch["images"])
            for k in batch:
                batch[k] = []

        with zipfile.ZipFile(archive) as zf, zf.open("Metadata.xml") as xml:
            depth = 0
            root = None
            for event, elem in ET.iterparse(xml, events=("start", "end")):
                if event == "start":
                    if root is None:
                        root = elem
                    depth += 1
                    continue
                depth -= 1
                if depth != 1:              # only the children of the root element
                    continue
                tag = elem.tag
                if tag == "Game":
                    platform = _text(elem, "Platform")
                    gid = _text(elem, "DatabaseID")
                    if platform in known and gid.isdigit():
                        name = _text(elem, "Name")
                        try:
                            rating = float(_text(elem, "CommunityRating") or "")
                        except ValueError:
                            rating = None
                        batch["games"].append((
                            int(gid), platform, name, sources.norm_title(name), _text(elem, "Overview"),
                            _text(elem, "ReleaseDate")[:10] or _text(elem, "ReleaseYear"),
                            _text(elem, "Developer"), _text(elem, "Publisher"), _text(elem, "Genres"),
                            _text(elem, "MaxPlayers"), rating))
                        games += 1
                    elem.clear()
                elif tag == "GameAlternateName":
                    gid = _text(elem, "DatabaseID")
                    norm = sources.norm_title(_text(elem, "AlternateName"))
                    if gid.isdigit() and norm:
                        batch["alts"].append((int(gid), norm))
                        alts += 1
                    elem.clear()
                elif tag == "GameImage":
                    gid = _text(elem, "DatabaseID")
                    kind = _text(elem, "Type")
                    if gid.isdigit() and kind in _TYPE_CODE:
                        batch["images"].append((int(gid), _TYPE_CODE[kind], _text(elem, "Region"), _text(elem, "FileName")))
                        images += 1
                    elem.clear()
                root.clear()                # nothing kept in memory between games
                if len(batch["images"]) + len(batch["games"]) >= 20000:
                    flush()
                    _set(done=games)
            flush()
        conn.executescript("""
            DELETE FROM alts WHERE id NOT IN (SELECT id FROM games);
            DELETE FROM images WHERE id NOT IN (SELECT id FROM games);
            CREATE INDEX games_norm ON games (norm, platform);
            CREATE INDEX games_platform ON games (platform);
            CREATE INDEX alts_norm ON alts (norm);
            CREATE INDEX images_id ON images (id);
        """)
        count = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        n_images = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        if not count:
            raise ValueError("empty")
        conn.executemany("INSERT INTO meta VALUES (?,?)", [
            ("schema", str(SCHEMA)), ("games", str(count)), ("images", str(n_images)),
            ("downloaded", str(time.time())), ("archive_date", archive_date)])
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    os.replace(tmp, dest)
    _fuzzy_cache.clear()
    _set(games=count)
    return count


# --- lookups -------------------------------------------------------------------------
def _fuzzy(conn, norm, plats):
    key = tuple(plats)
    names = _fuzzy_cache.get(key)
    if names is None:
        marks = ",".join("?" * len(plats))
        names = {}
        for r in conn.execute(f"SELECT id, norm FROM games WHERE platform IN ({marks})", plats):
            names.setdefault(r["norm"], r["id"])
        _fuzzy_cache[key] = names
    close = difflib.get_close_matches(norm, list(names), n=1, cutoff=0.9)
    return names[close[0]] if close else None


def find_game(names, plats):
    """``(row, method)`` of the best LaunchBox game for these names, or ``(None, "")``."""
    if not plats or not ready():
        return None, ""
    plats = list(plats)
    marks = ",".join("?" * len(plats))
    with closing(_connect()) as conn:
        for norm, _ in names:
            row = conn.execute(f"SELECT * FROM games WHERE norm = ? AND platform IN ({marks}) "
                               "ORDER BY id LIMIT 1", [norm] + plats).fetchone()
            if row:
                return row, "name"
            row = conn.execute(f"SELECT g.* FROM alts a JOIN games g ON g.id = a.id WHERE a.norm = ? "
                               f"AND g.platform IN ({marks}) ORDER BY g.id LIMIT 1", [norm] + plats).fetchone()
            if row:
                return row, "alternate-name"
        for norm, _ in names:
            gid = _fuzzy(conn, norm, plats)
            if gid:
                return conn.execute("SELECT * FROM games WHERE id = ?", (gid,)).fetchone(), "fuzzy-name"
    return None, ""


def _images(gid):
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT type, region, file FROM images WHERE id = ?", (gid,))
        return [{"type": KEPT_TYPES[r["type"]] if 0 <= r["type"] < len(KEPT_TYPES) else "",
                 "region": r["region"], "file": r["file"]} for r in rows]


def lookup(game, system_id, needed, ctx):
    """Fill ``needed`` fields from the local base. ``(partial, error)``."""
    plats = platforms.for_source("launchbox", system_id)
    if not plats:
        return None, None
    row, method = find_game(ctx["names"], plats)
    if not row:
        return None, None
    out = {"medias": {}, "match": method, "source_id": str(row["id"]), "source_name": row["name"]}
    values = {
        "name": row["name"], "desc": row["overview"], "releasedate": sources.iso_to_es(row["released"]),
        "developer": row["developer"], "publisher": row["publisher"],
        "genre": ", ".join(g.strip() for g in (row["genres"] or "").split(";") if g.strip()),
        "players": row["players"] if row["players"] not in ("0", "") else "",
        "rating": f"{max(0.0, min(5.0, row['rating'])) / 5:.2f}" if row["rating"] else "",
    }
    for key, value in values.items():
        if key in needed and value:
            out[key] = value
    wanted_media = [f for f in MEDIA_TYPES if f in needed]
    if wanted_media:
        regions = sources.region_order(ctx.get("prefer"))
        rank = {r: i for i, r in enumerate(regions)}
        images = _images(row["id"])
        for field in wanted_media:
            for kind in MEDIA_TYPES[field]:
                pool = [im for im in images if im["type"] == kind and im["file"]]
                if pool:
                    pool.sort(key=lambda im: (rank.get(im["region"] or "", len(rank)), im["file"]))
                    best = pool[0]
                    label = kind + (f" ({best['region']})" if best["region"] else "")
                    out["medias"][field] = {"url": IMAGES_URL + best["file"].lstrip("/"), "type": label}
                    break
    return out, None
