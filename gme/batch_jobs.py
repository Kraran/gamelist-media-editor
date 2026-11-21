"""Durable, per-gamelist batch checkpoints. One request processes one game.

The current game finishes and checkpoints even if its browser disappears.
Only paths, options and results are saved, never scraper URLs or credentials.
Resuming claims the job for one browser; an older owner cannot advance it.
"""
import hashlib
import copy
import json
import os
import re
import uuid

from flask import Blueprint, current_app, jsonify, request

from gme import xml_store
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st
from gme.paths import APP_DIR
from gme.scrapers import adb, ss, steam
from gme.scrapers.apply import apply_route
from gme.scrapers.compare import MEDIA_KEYS, META_KEYS, fields_for_preset

bp = Blueprint("batch_jobs", __name__)
BATCH_DIR = os.path.join(APP_DIR, "state", "batches")
SOURCES = {"screenscraper": ss.api_ss_scrape, "arcadeitalia": adb.api_adb_scrape, "steam": steam.api_steam_scrape}
FIELDS = set(MEDIA_KEYS) | set(META_KEYS)
_cache = None
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _path():
    key = hashlib.sha256(os.path.normcase(xml_store.XML_PATH).encode("utf-8")).hexdigest()
    return os.path.join(BATCH_DIR, key + ".json")


def _events_path(job):
    return _path()[:-5] + "." + job["id"] + ".jsonl"


def _stamp(path):
    try:
        info = os.stat(path)
        return info.st_mtime_ns, info.st_size
    except FileNotFoundError:
        return None


def _remember(job):
    global _cache
    _cache = {"path": _path(), "stamp": _stamp(_path()),
              "events": _stamp(_events_path(job)), "job": job}


def _valid_fields(fields):
    return isinstance(fields, list) and all(isinstance(f, str) and f in FIELDS for f in fields)


def _valid_game(game):
    return (isinstance(game, dict) and isinstance(game.get("path"), str) and isinstance(game.get("name"), str)
            and all(k not in game or _valid_fields(game[k]) for k in ("fields", "retry_fields"))
            and ("warnings" not in game or isinstance(game["warnings"], list) and all(isinstance(w, str) for w in game["warnings"]))
            and ("message" not in game or isinstance(game["message"], str)))


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def load_job():
    global _cache
    try:
        if (_cache and _cache["path"] == _path() and _cache["stamp"] == _stamp(_path())
                and _cache["events"] == _stamp(_events_path(_cache["job"]))):
            return _cache["job"]
        with open(_path(), encoding="utf-8") as stream:
            job = json.load(stream)
        if (job.get("version") == 1 and isinstance(job.get("xmlPath"), str)
                and os.path.normcase(job["xmlPath"]) == os.path.normcase(xml_store.XML_PATH)
                and isinstance(job.get("id"), str) and _TOKEN.fullmatch(job["id"])
                and isinstance(job.get("owner"), str) and _TOKEN.fullmatch(job["owner"])
                and isinstance(job.get("source"), str)
                and job.get("source") in SOURCES and job.get("mode") in ("missing", "all")
                and _valid_fields(job.get("fields")) and isinstance(job.get("halted"), str)
                and isinstance(job.get("results"), dict)
                and all(isinstance(job["results"].get(k), list) and all(_valid_game(g) for g in job["results"][k])
                        for k in ("updated", "nothing", "uncertain", "errors"))
                and isinstance(job.get("targets"), list) and isinstance(job.get("i"), int)
                and all(_valid_game(g) for g in job["targets"])
                and 0 <= job["i"] <= len(job["targets"])):
            try:
                with open(_events_path(job), "rb") as stream:
                    for line in stream:
                        if not line.endswith(b"\n"):
                            break  # the newline commits a complete record
                        try:
                            event = json.loads(line)
                        except ValueError:
                            break  # a power cut can leave an incomplete final line
                        if event["i"] <= job["i"]:
                            continue  # already included in a resume manifest
                        if event["i"] != job["i"] + 1 or event["kind"] not in job["results"]:
                            raise ValueError("invalid checkpoint")
                        if not _valid_game(event["game"]) or not isinstance(event["halted"], str) or event["i"] > len(job["targets"]):
                            raise ValueError("invalid checkpoint")
                        job["results"][event["kind"]].append(event["game"])
                        job["i"] = event["i"]
                        job["halted"] = event["halted"]
            except FileNotFoundError:
                pass
            _remember(job)
            return job
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        pass
    _cache = None
    return None


def _save(job):
    global _cache
    previous = load_job()
    try:
        os.makedirs(BATCH_DIR, exist_ok=True)
        atomic_write(_path(), json.dumps(job, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        _remember(job)
    except OSError:
        _cache = None
        raise
    if previous and previous["id"] != job["id"]:
        try:
            os.remove(_events_path(previous))
        except OSError:
            pass


def _checkpoint(job, kind, game, halt):
    """Append only this result; avoid rewriting a 30,000-game plan per game."""
    global _cache
    event = {"i": job["i"] + 1, "kind": kind, "game": game,
             "halted": game["message"] if halt else ""}
    data = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    try:
        with open(_events_path(job), "a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell():
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    # Remove an interrupted append before writing a new record.
                    stream.seek(0)
                    content = stream.read()
                    stream.truncate(content.rfind(b"\n") + 1)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        job["results"][kind].append(game)
        job["i"] = event["i"]
        job["halted"] = event["halted"]
        _remember(job)
    except OSError:
        _cache = None
        raise


def _public(job, owner=False):
    if job is None:
        return None
    return {k: v for k, v in job.items() if owner or k != "owner"}


def _job():
    job = load_job()
    body = _body()
    if not job or body.get("id") != job["id"]:
        return None, api_err(st("batch.no_saved"), 409, code="batch_missing")
    return job, None


@bp.route("/api/batch")
def get_batch():
    err = xml_store.require_gamelist()
    if err:
        return err
    return jsonify({"job": _public(load_job())})


@bp.route("/api/batch", methods=["POST"])
def create_batch():
    err = xml_store.require_gamelist()
    if err:
        return err
    body = _body()
    source, mode = body.get("source"), body.get("mode")
    fields, paths = body.get("fields"), body.get("paths")
    if (not isinstance(source, str) or source not in SOURCES or mode not in ("missing", "all")
            or not isinstance(fields, list) or not fields
            or any(not isinstance(f, str) or f not in FIELDS for f in fields)
            or not isinstance(paths, list) or not 0 < len(paths) <= 100000
            or any(not isinstance(p, str) for p in paths)):
        return api_err(st("batch.invalid"), 400, code="invalid_batch")
    games = {}
    for game in xml_store.load_xml().getroot().findall("game"):
        games.setdefault(game.findtext("path", ""), []).append(game)
    targets = []
    for path in dict.fromkeys(paths):
        matches = games.get(path, [])
        if len(matches) != 1:
            return api_err(st("server.stale_game"), 409, code="stale_game")
        targets.append({"path": path, "name": matches[0].findtext("name", "") or path})
    job = {"version": 1, "id": uuid.uuid4().hex, "owner": uuid.uuid4().hex,
           "xmlPath": xml_store.XML_PATH, "source": source, "mode": mode,
           "fields": list(dict.fromkeys(fields)), "targets": targets, "i": 0, "halted": "",
           "fromSelection": bool(body.get("fromSelection")),
           "results": {"updated": [], "nothing": [], "uncertain": [], "errors": []}}
    try:
        if body.get("backup", True):
            xml_store.backup_xml()
        _save(job)
    except (OSError, ValueError) as exc:
        return api_err(str(exc), 500, code="batch_save_failed")
    return jsonify({"job": _public(job, owner=True)})


@bp.route("/api/batch/claim", methods=["POST"])
def claim_batch():
    err = xml_store.require_gamelist()
    if err:
        return err
    job, err = _job()
    if err:
        return err
    job = copy.deepcopy(job)
    body = _body()
    if body.get("retry"):
        if job["i"] < len(job["targets"]):
            return api_err(st("batch.invalid"), 400, code="batch_unfinished")
        # Retry only unsuccessful fields, even for a Replace-all batch.
        failed = job["results"]["errors"] + [g for g in job["results"]["updated"] if g.get("warnings")]
        retry = [{"path": g["path"], "name": g["name"], "fields": g.get("retry_fields", job["fields"])} for g in failed]
        if not retry:
            return api_err(st("batch.no_saved"), 400, code="nothing_to_retry")
        # Preserve the previous report until the retry has a durable new checkpoint.
        job = {**job, "id": uuid.uuid4().hex, "targets": retry, "i": 0,
               "results": {"updated": [], "nothing": [], "uncertain": [], "errors": []}}
    elif job["i"] >= len(job["targets"]):
        return api_err(st("batch.no_saved"), 400, code="batch_finished")
    job["owner"] = uuid.uuid4().hex
    job["halted"] = ""
    try:
        if body.get("retry"):
            xml_store.backup_xml()
        _save(job)
    except (OSError, ValueError) as exc:
        return api_err(str(exc), 500, code="batch_save_failed")
    return jsonify({"job": _public(job, owner=True)})


def _process(job, target):
    matches = xml_store.find_game_index_by_path(target["path"])
    if len(matches) != 1:
        raise ValueError(st("server.stale_game"))
    index = matches[0]
    # The existing source views share this request context (no forced candidate
    # is accepted from the step body). Their normal validation is reused.
    response = current_app.make_response(SOURCES[job["source"]](index, body={}))
    data = response.get_json() or {}
    if response.status_code >= 400:
        message = data.get("error") or st("errors.internal")
        blocked = data.get("code") == "source_blocked" or response.status_code in (429, 503) or any(
            word in message.lower() for word in ("quota", "429", "503", "too many", "trop de requ", "maintenance"))
        return "errors", {**target, "message": message}, blocked
    if data.get("need_choice"):
        return "uncertain", target, False
    wanted = set(target.get("fields", job["fields"]))
    todo = [f for f in fields_for_preset(data.get("compare", []), job["mode"]) if f in wanted]
    if not todo:
        return "nothing", target, False
    kwargs = {}
    if job["source"] == "steam":
        kwargs = {"headers": {"User-Agent": steam.STEAM_UA}, "media_handlers": {"video": steam.steam_download_video},
                  "no_url_key": "server.no_steam_url"}
    applied = current_app.make_response(apply_route(index, job["source"], body={"fields": todo, "proposed": data.get("proposed", {})}, **kwargs))
    result = applied.get_json() or {}
    if applied.status_code >= 400:
        raise ValueError(result.get("error") or st("errors.internal"))
    written, warnings = result.get("applied", []), result.get("errors", [])
    retry_fields = [f for f in todo if f not in written]
    if written:
        return "updated", {**target, "fields": written, "warnings": warnings, "retry_fields": retry_fields}, False
    if warnings:
        return "errors", {**target, "message": "; ".join(warnings), "retry_fields": retry_fields}, False
    return "nothing", target, False


@bp.route("/api/batch/step", methods=["POST"])
def step_batch():
    err = xml_store.require_gamelist()
    if err:
        return err
    job, err = _job()
    if err:
        return err
    body = _body()
    if body.get("owner") != job["owner"]:
        return api_err(st("batch.claimed"), 409, code="batch_claimed")
    # A repeated HTTP request cannot process the following game by accident.
    if body.get("i") != job["i"] or job["halted"] or job["i"] >= len(job["targets"]):
        return jsonify({"job": _public(job)})
    target = job["targets"][job["i"]]
    try:
        kind, result, halt = _process(job, target)
    except Exception as exc:
        xml_store.invalidate_cache()
        kind, result, halt = "errors", {**target, "message": str(exc)}, isinstance(exc, OSError)
    # Network exceptions can include authenticated scraper URLs. Reports need
    # their reason, not login parameters, in either the journal or the browser.
    if "message" in result:
        result["message"] = re.sub(r"https?://\S+", "[URL]", result["message"])
    if "warnings" in result:
        result["warnings"] = [re.sub(r"https?://\S+", "[URL]", w) for w in result["warnings"]]
    try:
        _checkpoint(job, kind, result, halt)
    except OSError as exc:
        return api_err(str(exc), 500, code="batch_save_failed")
    return jsonify({"i": job["i"], "halted": job["halted"], "result": {"kind": kind, "game": result}})
