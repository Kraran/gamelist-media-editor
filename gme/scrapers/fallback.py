"""ScreenScraper first, then the fallback sources, field by field.

``scrape_game`` has the contract of ``ss.scrape_game`` (single game scrape,
batch scrape, multi-system batch all go through it). With no fallback turned
on it *is* ``ss.scrape_game``. Otherwise:

1. ScreenScraper is asked exactly as before (same requests, same
   ``ss_limits.GATE``: threads, requests per minute, quotas). When its quota is
   reached the gate refuses every request before it is sent, so the cached
   answers are still used and nothing more goes to ScreenScraper.
2. Every field takes the value of the first source of the chain (Settings ›
   Fallback sources, ScreenScraper first by default) that has it and is
   allowed to fill it. A fallback is only asked when one of its fields is still
   empty (in a batch: one of the batch fields the game is missing).
3. "Game not found" on ScreenScraper, or its quota reached ("continue" setting):
   the fallbacks alone. Nothing found anywhere is a plain "not found" (HTTP
   404), which never stops a batch. With "stop", a ScreenScraper quota stops
   it as before. A ScreenScraper candidate list (need_choice) is returned as is.

Each field of the result says where it comes from (``proposed.field_sources``
and ``compare[].source``), for the dialog's source chips.
"""

import copy

from flask import Blueprint, jsonify, request

from gme import remote_cache
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.scrapers import igdb, launchbox, sources, ss, ss_limits, tgdb
from gme.scrapers.common import rom_identification
from gme.scrapers.compare import META_KEYS, MEDIA_KEYS, current_from_game, _media_present, scrape_payload
from gme.systems import detect_system_id
from gme.xml_store import resolve_under_base

bp = Blueprint("sources", __name__)

LOOKUPS = {"launchbox": launchbox.lookup, "thegamesdb": tgdb.lookup, "igdb": igdb.lookup}


def _wanted(game, body):
    """Fields the caller wants filled (a batch: its fields, minus what the game has in "missing" mode)."""
    fields = body.get("fields")
    keys = set(META_KEYS) | set(MEDIA_KEYS)
    wanted = {f for f in fields if f in keys} if isinstance(fields, list) and fields else set(keys)
    if body.get("mode") == "missing":
        current = current_from_game(game)
        wanted = {f for f in wanted
                  if not (_media_present(f, current.get(f)) if f in MEDIA_KEYS else str(current.get(f) or "").strip())}
    return wanted


def _ss_values(proposed):
    out = {k: proposed.get(k) for k in META_KEYS if str(proposed.get(k) or "").strip()}
    for k, info in (proposed.get("medias") or {}).items():
        if isinstance(info, dict) and str(info.get("url") or "").strip():
            out[k] = info
    return out


def scrape_game(game, body=None, system=None):
    body = body or {}
    cfg = sources.load_config()
    chain = sources.active_fallbacks(cfg)
    if not chain or body.get("gameid"):
        return ss.scrape_game(game, body, system)
    system = system or detect_system_id()
    data, status = ss.scrape_game(game, body, system)
    if not isinstance(data, dict) or data.get("need_choice"):
        return data, status
    blocked = status == 503 or data.get("code") == "source_blocked" or bool(ss_limits.GATE.blocked())
    if status >= 400 and blocked and cfg.get("on_ss_quota") == "stop":
        return data, status
    ss_ok = status == 200 and isinstance(data.get("proposed"), dict)
    ss_state = "ok" if ss_ok else ("blocked" if blocked else "not_found")

    ss_cfg = ss.load_ss_config()
    disabled = set(ss.ss_disabled_media(ss_cfg))
    base = copy.deepcopy(data["proposed"]) if ss_ok else {"medias": {}, "disabled_media": sorted(disabled)}
    disabled |= set(base.get("disabled_media") or ())
    ss_vals = _ss_values(base) if ss_ok else {}
    dropped = []
    if ss_ok and ss_limits.GATE.blocked():
        # Quota reached during this lookup: its media could not be downloaded
        # (the gate refuses them), so the fallbacks may fill them instead.
        for k in [k for k in ss_vals if k in MEDIA_KEYS]:
            if remote_cache.get(ss_vals[k].get("url")) is None:
                dropped.append(k)
                del ss_vals[k]

    wanted = _wanted(game, body) - disabled
    hash_info = data.get("hash")
    if hash_info is None:
        path_rel = game.findtext("path", "") or ""
        full = resolve_under_base(path_rel) if path_rel else None
        hash_info = rom_identification(full) if full else None
    ctx = {"cfg": cfg, "names": sources.query_names(game, base.get("name") if ss_ok else ""),
           "hash": hash_info, "prefer": ss_cfg.get("prefer_region") or "fr", "refresh": bool(body.get("refresh"))}

    final = {}                              # field → (source, value)
    errors, matches = {}, {}
    for src in cfg["order"]:
        if src == "screenscraper":
            for k, v in ss_vals.items():
                if k in wanted and k not in final:
                    final[k] = (src, v)
            continue
        if src not in chain:
            continue
        allowed = set(cfg["fields"].get(src) or ()) & set(sources.SUPPORTED[src])
        needed = (allowed & wanted) - set(final)
        if not needed:
            continue
        try:
            partial, error = LOOKUPS[src](game, system[0], needed, ctx)
        except Exception as exc:              # one source failing never breaks the scrape
            log.warning("Fallback %s failed: %s", src, sources.redact(exc, cfg))
            partial, error = None, sources.redact(exc, cfg)
        if error:
            errors[src] = error
        if not partial:
            continue
        matches[src] = {"id": partial.get("source_id", ""), "name": partial.get("source_name", ""),
                        "match": partial.get("match", "")}
        for k in needed:
            if k in final:
                continue
            if k in MEDIA_KEYS:
                info = (partial.get("medias") or {}).get(k)
                if info and info.get("url"):
                    final[k] = (src, info)
            elif str(partial.get(k) or "").strip():
                final[k] = (src, partial[k])
    # Fields ScreenScraper has but nobody was asked for (outside the batch
    # fields, or a later source): keep ScreenScraper's value as before.
    for k, v in ss_vals.items():
        final.setdefault(k, ("screenscraper", v))

    proposed = base
    proposed["medias"] = {k: dict(v, source=s) for k, (s, v) in final.items() if k in MEDIA_KEYS}
    for k in META_KEYS:
        proposed[k] = final[k][1] if k in final else (proposed.get(k, "") if ss_ok else "")
    proposed["disabled_media"] = sorted(disabled)
    proposed["field_sources"] = {k: s for k, (s, _) in final.items()}
    used = [s for s in cfg["order"] if s in proposed["field_sources"].values()]
    proposed["sources_used"] = used
    info = {"ss": ss_state, "chain": chain, "used": used, "errors": errors, "matches": matches, "ss_media_dropped": dropped}

    if not ss_ok and not any(s != "screenscraper" for s in used):
        out = {"error": st("server.fallback_not_found"), "code": "not_found", "fallback": info,
               "ss_error": sources.redact(data.get("error") or ""), "system_id": system[0],
               "system_folder": system[1], "hash": hash_info}
        return out, 404
    if ss_ok:
        result = dict(data)
    else:
        path_rel = game.findtext("path", "") or ""
        result = {"success": True, "system_id": system[0], "system_folder": system[1],
                  "rom_name": path_rel.rsplit("/", 1)[-1], "hash": hash_info, "cache": data.get("cache")}
        result["match_method"] = "fallback-" + used[0] if used else "fallback"
    result["proposed"] = proposed
    result.update(scrape_payload(game, proposed))
    for row in result["compare"]:
        if row["status"] != "unavailable" and row["key"] in proposed["field_sources"]:
            row["source"] = proposed["field_sources"][row["key"]]
    result["fallback"] = info
    return result, 200


# --- settings routes ---------------------------------------------------------------------
def public_config(cfg=None):
    cfg = cfg or sources.load_config()
    return {
        "order": cfg["order"],
        "enabled": cfg["enabled"],
        "fields": cfg["fields"],
        "supported": {k: list(v) for k, v in sources.SUPPORTED.items()},
        "on_ss_quota": cfg["on_ss_quota"],
        "tgdb_apikey_set": bool(cfg.get("tgdb_apikey")),
        "igdb_client_id_set": bool(cfg.get("igdb_client_id")),
        "igdb_client_secret_set": bool(cfg.get("igdb_client_secret")),
        "configured": {s: sources.configured(s, cfg) for s in sources.FALLBACKS},
        "active": sources.active_fallbacks(cfg),
        "launchbox": launchbox.status(),
        "tgdb_allowance": tgdb.allowance(),
    }


@bp.route("/api/sources/config", methods=["GET", "POST"])
def api_sources_config():
    if request.method == "GET":
        return jsonify(public_config())
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return api_err(st("server.no_fields"), 400, code="bad_body")
    if body.get("igdb_client_id") or body.get("igdb_client_secret") or body.get("clear_igdb_client_secret"):
        igdb.forget_token()
    try:
        cfg = sources.save_config(body)
    except OSError as exc:
        return api_err(str(exc), 500, code="save_failed")
    return jsonify({"success": True, "config": public_config(cfg)})


@bp.route("/api/sources/test/<source>", methods=["POST"])
def api_sources_test(source):
    cfg = sources.load_config()
    try:
        if source == "thegamesdb":
            if not cfg.get("tgdb_apikey"):
                return api_err(st("server.source_key_missing", source="TheGamesDB"), 400, code="key_missing")
            return jsonify({"success": True, **tgdb.test(cfg)})
        if source == "igdb":
            if not (cfg.get("igdb_client_id") and cfg.get("igdb_client_secret")):
                return api_err(st("server.source_key_missing", source="IGDB"), 400, code="key_missing")
            return jsonify({"success": True, **igdb.test(cfg)})
    except (tgdb.TgdbError, igdb.IgdbError) as exc:
        return api_err(sources.redact(exc, cfg), 502, code="source_test_failed")
    return api_err("unknown source", 404, code="unknown_source")


@bp.route("/api/sources/launchbox", methods=["GET"])
def api_launchbox_status():
    return jsonify(launchbox.status())


@bp.route("/api/sources/launchbox/update", methods=["POST"])
def api_launchbox_update():
    started, reason = launchbox.start_update()
    if not started and reason == "recent":
        return api_err(st("server.launchbox_recent"), 409, code="launchbox_recent")
    return jsonify({"success": True, "started": started, **launchbox.status()})
