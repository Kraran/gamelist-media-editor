"""DAT tool (Actions › DAT tool): compare the system's ROM files with a DAT.

GET  /api/dat                  loaded DAT, running job, mame.xml found nearby
POST /api/dat/load             multipart ``file`` (a DAT the user picks) or
                               JSON {"path": "…"}; parsed in the background
POST /api/dat/compare          {"hash": "none" | "crc" | "sha1"} in the background
POST /api/dat/stop             stops the running job
GET  /api/dat/report           ?status=&hide_clones=1&hide_bios=1&offset=&limit=
                               (&format=csv for the whole filtered report)

A ROM file is matched by name first: its stem is a game name (``pacman.zip``,
``Tetris (World).zip``) or its file name is a ROM name (``Tetris (World).gb``).
Hashing is opt-in. With CRC32, a zip is checked through its index (the CRC of
each member is stored there, nothing is decompressed); other files are read in
full, in the background, with progress and Stop. SHA1 reads everything.

Statuses: ``ok`` (name and, when hashed, content match), ``renamed`` (content
matches a DAT game under another name), ``bad`` (content differs from the DAT,
or the DAT marks that dump as bad), ``incomplete`` (romset missing ROMs),
``unknown`` (not in the DAT) and ``missing`` (in the DAT, no file). Flags:
clone, BIOS, not playable, CHD missing, not checked (7z/rar, folders).

This tool only reads: ROM files are never renamed, moved or deleted. Display
names can be taken from the DAT through Edit in bulk › Names (backup + undo).
"""

import csv
import io
import os
import tempfile
import threading
import time
import zipfile
import zlib
import hashlib

from flask import Blueprint, Response, jsonify, request

from gme import arcade, xml_store
from gme.datfile import DatError, read_dat
from gme.http import api_err
from gme.i18n import get_request_locale, locale_scope, st
from gme.log import log
from gme.romcheck import _entry_full, _key, find_roms
from gme.systems import detect_system_id
from gme.xml_store import load_xml, require_gamelist

bp = Blueprint("dattool", __name__)

STATUSES = ("ok", "renamed", "bad", "incomplete", "unknown", "missing")
DAT_EXTS = (".dat", ".xml")
REPORT_ROWS = 500
CHUNK = 1 << 20

_lock = threading.Lock()
STATE = {
    "dat": None,          # datfile.Dat
    "job": None,          # {"id", "kind", "state", "done", "total", "unit", "current", "error"}
    "report": None,       # {"base_dir", "session", "hash", "rows": [...], "created"}
}
_stop = threading.Event()


# --- jobs ---------------------------------------------------------------------------

def _job_public():
    job = STATE["job"]
    return dict(job) if job else None


def _start_job(kind, target, *args):
    with _lock:
        job = STATE["job"]
        if job and job["state"] == "running":
            return None
        job = {"id": "%s-%d" % (kind, int(time.time() * 1000)), "kind": kind, "state": "running",
               "done": 0, "total": 0, "unit": "bytes", "error": None,
               "current": args[-1] if kind == "load" else ""}
        STATE["job"] = job
        _stop.clear()

    locale = get_request_locale()

    def run():
        with locale_scope(locale):
            try:
                target(job, *args)
                job["state"] = "stopped" if _stop.is_set() else "done"
            except DatError as e:
                if _stop.is_set():
                    job["state"] = "stopped"
                else:
                    job["state"], job["error"] = "error", st("dat.bad_file", detail=str(e))
            except Exception as e:  # pragma: no cover - logged, shown to the user
                log.exception("DAT %s failed", kind)
                job["state"], job["error"] = "error", str(e)

    threading.Thread(target=run, name="gme-dat-" + kind, daemon=True).start()
    return job


def _progress(job):
    def report(done, total):
        job["done"], job["total"] = done, total
        if _stop.is_set():
            raise DatError("stopped")
    return report


# --- loading ------------------------------------------------------------------------

def _load(job, path, temp, name):
    try:
        dat = read_dat(path, _progress(job))
    finally:
        if temp:
            try:
                os.remove(path)
            except OSError:
                pass
    if not dat.games:
        raise DatError(st("dat.no_games"))
    if temp:
        dat.source = name
    with _lock:
        STATE["dat"] = dat
        STATE["report"] = None
    log.info("DAT loaded: %s (%d games)", dat.title, len(dat.games))


@bp.route("/api/dat")
def api_dat_state():
    job = _job_public()                       # first: a job seen finished has stored its result
    dat = STATE["dat"]
    report = STATE["report"]
    mame = None
    if xml_store.has_gamelist():
        try:
            mame = arcade.find_mame_listxml()
        except OSError:
            mame = None
    fresh = bool(report and report["session"] == xml_store.SESSION_ID)
    return jsonify({
        "dat": dat.info() if dat else None,
        "job": job,
        "mame_xml": mame,
        "report": _summary(report) if fresh else None,
    })


@bp.route("/api/dat/load", methods=["POST"])
def api_dat_load():
    upload = request.files.get("file")
    if upload is not None and upload.filename:
        name = os.path.basename(upload.filename.replace("\\", "/"))
        if not name.lower().endswith(DAT_EXTS):
            return api_err(st("dat.bad_ext"), 400, code="dat_bad_ext")
        fd, path = tempfile.mkstemp(prefix="gme-dat-", suffix=os.path.splitext(name)[1])
        with os.fdopen(fd, "wb") as out:
            upload.save(out)
        temp = True
    else:
        body = request.get_json(silent=True) or {}
        raw = str(body.get("path") or "").strip().strip('"').strip("'")
        path = os.path.abspath(raw) if raw else ""
        name = os.path.basename(path)
        if not raw or not os.path.isfile(path):
            return api_err(st("dat.not_found", path=raw), 404, code="dat_not_found")
        if not path.lower().endswith(DAT_EXTS):
            return api_err(st("dat.bad_ext"), 400, code="dat_bad_ext")
        temp = False
    job = _start_job("load", _load, path, temp, name)
    if job is None:
        if temp:
            os.remove(path)
        return api_err(st("dat.busy"), 409, code="dat_busy")
    return jsonify({"success": True, "job": _job_public()})


@bp.route("/api/dat/stop", methods=["POST"])
def api_dat_stop():
    _stop.set()
    return jsonify({"success": True, "job": _job_public()})


# --- comparing ----------------------------------------------------------------------

def _crc_file(path, job, want_sha1):
    crc, sha = 0, hashlib.sha1() if want_sha1 else None
    with open(path, "rb") as f:
        while True:
            if _stop.is_set():
                return None, None
            data = f.read(CHUNK)
            if not data:
                break
            crc = zlib.crc32(data, crc)
            if sha is not None:
                sha.update(data)
            job["done"] += len(data)
    return "%08x" % (crc & 0xFFFFFFFF), (sha.hexdigest() if sha is not None else None)


def _zip_members(path, job, want_sha1):
    """[(name, size, crc, sha1)] from the zip index (+ SHA1 by reading members)."""
    out = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            sha = None
            if want_sha1:
                h = hashlib.sha1()
                with z.open(info) as member:
                    while True:
                        if _stop.is_set():
                            return None
                        data = member.read(CHUNK)
                        if not data:
                            break
                        h.update(data)
                        job["done"] += len(data)
                sha = h.hexdigest()
            out.append((os.path.basename(info.filename), info.file_size, "%08x" % info.CRC, sha))
    return out


def _rom_matches(rom, size, crc, sha1):
    if sha1 and rom.sha1:
        return sha1 == rom.sha1
    if crc and rom.crc:
        return crc == rom.crc and (rom.size is None or size is None or rom.size == size)
    return None


def _check_set(game, members):
    """Compare a romset's required ROMs with zip members: (status, detail)."""
    by_name = {m[0].lower(): m for m in members}
    by_crc = {}
    for m in members:
        by_crc.setdefault(m[2], m)
    bad, missing, baddump = [], [], False
    for rom in game.roms:
        if not rom.required:
            continue
        member = by_name.get(os.path.basename(rom.name).lower())
        if member is not None:
            ok = _rom_matches(rom, member[1], member[2], member[3])
            if ok is False:
                alt = by_crc.get(rom.crc) if rom.crc else None
                if alt is None:
                    bad.append(rom.name)
                    continue
        elif rom.crc and rom.crc in by_crc:
            pass                                   # present under another name inside the zip
        else:
            missing.append(rom.name)
            continue
        if rom.baddump:
            baddump = True
    if bad:
        return "bad", ", ".join(bad[:5])
    if missing:
        return "incomplete", ", ".join(missing[:5])
    if baddump:
        return "bad", "dat_baddump"
    return "ok", ""


def _single(game, name, size, crc, sha1):
    """A loose file (or a one-member archive) against its game: status, detail."""
    roms = [r for r in game.roms if r.required]
    if not roms:
        return "ok", ""
    rom = None
    for r in roms:
        if os.path.basename(r.name).lower() == name.lower():
            rom = r
            break
    if rom is None and len(roms) == 1:
        rom = roms[0]
    if rom is None:
        return "ok", ""
    ok = _rom_matches(rom, size, crc, sha1)
    if ok is False:
        # a multi-file game (disc tracks): the file may be another of its ROMs
        if any(_rom_matches(r, size, crc, sha1) for r in roms):
            return "ok", ""
        return "bad", ""
    if rom.baddump:
        return "bad", "dat_baddump"
    return "ok", ""


def _by_hash(dat, size, crc, sha1):
    """The one-ROM game whose ROM has this content (a whole romset needs _vote)."""
    hits = dat.by_sha1(sha1) if sha1 else []
    if not hits and crc:
        hits = [(g, r) for g, r in dat.by_crc(crc) if r.size is None or size is None or r.size == size]
    for game, rom in hits:
        if rom.required and sum(1 for r in game.roms if r.required) == 1:
            return game
    return None


def _vote(dat, members):
    """The game whose required ROMs are all among the zip members (by CRC)."""
    votes = {}
    for m in members:
        for game, _rom in dat.by_crc(m[2]):
            votes[game.name.lower()] = game
    best = None
    crcs = {m[2] for m in members}
    for game in votes.values():
        need = [r.crc for r in game.roms if r.required and r.crc]
        if need and all(c in crcs for c in need):
            if best is None or len(need) > len([r for r in best.roms if r.required]):
                best = game
    return best


def _compare(job, dat, files, base, mode, session):
    want_hash = mode in ("crc", "sha1")
    want_sha1 = mode == "sha1"
    job["unit"] = "bytes" if want_hash else "files"
    total = 0
    if want_hash:
        for f in files:
            if f["dir"] or f["ext"] in ("7z", "rar"):
                continue
            if f["ext"] == "zip" and not want_sha1:
                continue
            total += f["size"] or 0
    else:
        total = len(files)
    job["total"] = total
    rows, seen = [], set()
    for f in files:
        if _stop.is_set():
            return
        job["current"] = f["name"]
        game = dat.find(f["name"])
        status, detail, flags = "unknown", "", []
        hashed = False
        try:
            if want_hash and not f["dir"] and f["ext"] == "zip":
                members = _zip_members(f["full"], job, want_sha1)
                if members is None:
                    return
                hashed = True
                if game is None:
                    if len(members) == 1:
                        game = _by_hash(dat, members[0][1], members[0][2], members[0][3])
                    else:
                        game = _vote(dat, members)
                    if game is not None:
                        status = "renamed"
                if game is not None and status != "renamed":
                    if len(members) == 1 and len([r for r in game.roms if r.required]) == 1:
                        m = members[0]
                        status, detail = _single(game, m[0], m[1], m[2], m[3])
                    else:
                        status, detail = _check_set(game, members)
            elif want_hash and not f["dir"] and f["ext"] not in ("7z", "rar"):
                crc, sha1 = _crc_file(f["full"], job, want_sha1)
                if crc is None:
                    return
                hashed = True
                if game is None:
                    game = _by_hash(dat, f["size"], crc, sha1)
                    if game is not None:
                        status = "renamed"
                else:
                    status, detail = _single(game, f["name"], f["size"], crc, sha1)
            elif game is not None:
                status = "ok"
        except (OSError, zipfile.BadZipFile, RuntimeError) as e:
            status, detail = ("bad" if game is not None else "unknown"), str(e)[:200]
        if not want_hash:
            job["done"] += 1
        if want_hash and not hashed:
            flags.append("not_checked")
        if game is not None:
            seen.add(game.name.lower())
            if game.disks and not all(
                    os.path.isfile(os.path.join(os.path.dirname(f["full"]), game.name, d + ".chd"))
                    or os.path.isfile(os.path.join(os.path.dirname(f["full"]), game.name, d))
                    for d in game.disks):
                flags.append("chd_missing")
        rows.append(_row(f["rel"], f["name"], status, game, detail, flags, f["listed"]))
    for key, game in dat.games.items():
        if key not in seen:
            rows.append(_row("", "", "missing", game, "", [], False))
    with _lock:
        STATE["report"] = {"base_dir": base, "session": session, "hash": mode, "rows": rows,
                           "created": time.time(), "dat": dat.title}


def _row(rel, name, status, game, detail, flags, listed):
    flags = list(flags)
    if game is not None:
        if game.cloneof:
            flags.append("clone")
        if game.bios:
            flags.append("bios")
        if not game.playable:
            flags.append("not_playable")
    return {"path": rel, "file": name, "status": status, "dat": game.name if game else "",
            "desc": game.desc if game else "", "parent": game.cloneof if game else "",
            "flags": flags, "detail": detail, "listed": listed}


@bp.route("/api/dat/compare", methods=["POST"])
def api_dat_compare():
    err = require_gamelist()
    if err:
        return err
    dat = STATE["dat"]
    if dat is None:
        return api_err(st("dat.none_loaded"), 400, code="dat_none")
    body = request.get_json(silent=True) or {}
    mode = body.get("hash") if body.get("hash") in ("none", "crc", "sha1") else "none"
    tree = load_xml()
    base = xml_store.BASE_DIR
    listed, used_exts, nested = set(), set(), False
    for game in tree.getroot().findall("game"):
        path = (game.findtext("path", "") or "").strip()
        full = _entry_full(path)
        if full is None:
            continue
        listed.add(_key(full))
        ext = os.path.splitext(full)[1][1:].lower()
        if ext:
            used_exts.add(ext)
        if "/" in path.lstrip("./").replace("\\", "/"):
            nested = True
    _, folder = detect_system_id()
    paths, _arcade = find_roms(base, listed, used_exts, folder, nested, xml_path=xml_store.XML_PATH)
    files = []
    for full in paths:
        is_dir = os.path.isdir(full)
        try:
            size = None if is_dir else os.path.getsize(full)
        except OSError:
            size = None
        name = os.path.basename(full.rstrip("\\/"))
        files.append({"full": full, "rel": "./" + os.path.relpath(full, base).replace(os.sep, "/"),
                      "name": name, "ext": os.path.splitext(name)[1][1:].lower(), "dir": is_dir,
                      "size": size, "listed": _key(full) in listed})
    job = _start_job("compare", _compare, dat, files, base, mode, xml_store.SESSION_ID)
    if job is None:
        return api_err(st("dat.busy"), 409, code="dat_busy")
    return jsonify({"success": True, "job": _job_public(), "files": len(files)})


# --- report ---------------------------------------------------------------------------

def _visible(row, hide_clones, hide_bios):
    if hide_clones and "clone" in row["flags"]:
        return False
    if hide_bios and "bios" in row["flags"]:
        return False
    return True


def _summary(report, hide_clones=False, hide_bios=False):
    counts = {s: 0 for s in STATUSES}
    for row in report["rows"]:
        if _visible(row, hide_clones, hide_bios):
            counts[row["status"]] += 1
    return {"counts": counts, "hash": report["hash"], "dat": report.get("dat", ""),
            "chd_missing": sum(1 for r in report["rows"] if "chd_missing" in r["flags"])}


def matches():
    """Last report's ``{gamelist path: DAT game}`` for the open gamelist, else {}."""
    report = STATE["report"]
    dat = STATE["dat"]
    if not report or not dat or report["session"] != xml_store.SESSION_ID:
        return {}
    out = {}
    for row in report["rows"]:
        if row["path"] and row["dat"] and row["status"] != "unknown":
            game = dat.games.get(row["dat"].lower())
            if game is not None:
                out[row["path"]] = game
    return out


@bp.route("/api/dat/report")
def api_dat_report():
    report = STATE["report"]
    if not report or report["session"] != xml_store.SESSION_ID:
        return api_err(st("dat.no_report"), 404, code="dat_no_report")
    args = request.args
    hide_clones = args.get("hide_clones") in ("1", "true")
    hide_bios = args.get("hide_bios") in ("1", "true")
    status = args.get("status") or ""
    rows = [r for r in report["rows"] if _visible(r, hide_clones, hide_bios)
            and (not status or r["status"] == status)]
    if args.get("format") == "csv":
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        writer.writerow(["status", "file", "path", "dat_name", "description", "parent", "flags", "detail"])
        for r in rows:
            writer.writerow([r["status"], r["file"], r["path"], r["dat"], r["desc"], r["parent"],
                             " ".join(r["flags"]), r["detail"]])
        return Response("\ufeff" + out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=dat-report.csv"})
    try:
        offset = max(0, int(args.get("offset") or 0))
        limit = min(REPORT_ROWS, max(1, int(args.get("limit") or REPORT_ROWS)))
    except ValueError:
        offset, limit = 0, REPORT_ROWS
    out = _summary(report, hide_clones, hide_bios)
    out.update({"total": len(rows), "offset": offset, "rows": rows[offset:offset + limit]})
    return jsonify(out)
