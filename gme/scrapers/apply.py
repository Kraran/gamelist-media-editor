"""Apply a scrape result to one game: shared by ScreenScraper, Arcade Database and Steam.

Body of every ``/api/<source>/apply/<index>`` route::

    {"proposed": {...from the scrape...}, "fields": ["desc", "image", ...]}
    {"proposed": {...}, "preset": "missing"}     # or "all": no dialog needed

``fields`` is what the user ticked in the scrape dialog. ``preset`` selects
the fields on the server (see ``compare.fields_for_preset``), which is what a
batch scrape will use. Only the selected fields change: a field the source
has no value for is never erased, and nothing is applied behind the user's
back (thumbnail, bezel and Pad2Key are rows of the dialog like the others).
"""

from flask import jsonify, request
from lxml import etree

from gme import history, xml_store
from gme.fields import FieldError, clean_meta, set_desc, set_name
from gme.http import api_err
from gme.i18n import st
from gme.media import MAX_DOWNLOAD_BYTES, MediaRejected, discard_old_media, download_pad2key, download_remote_media, media_dest, pad2key_dest
from gme.scrapers.compare import compare_rows, current_from_game, fields_for_preset
from gme.xml_store import MEDIA_DIRS, get_base_name, get_game_elem, require_gamelist, save_xml


def _download_error(field, e):
    """User message for a failed media download, or None to skip silently."""
    if isinstance(e, MediaRejected):      # broken, tiny or one-colour image: not written
        return f"{field}: {st('server.' + e.code, **e.params)}"
    code = str(e)
    if code == "green_placeholder":       # ScreenScraper's empty boxback
        return None
    if code == "too_large":
        return f"{field}: {st('server.file_too_large', n=MAX_DOWNLOAD_BYTES // (1024 * 1024))}"
    if code == "url_not_allowed":
        return f"{field}: {st('server.url_not_http')}"
    return f"{field}: {e}"


def set_media_path(game, field, rel_path):
    """Point ``field`` at ``rel_path``; the previous file goes to the Recycle Bin
    if it was another one that no other tag uses."""
    discard_old_media(game, field, game.findtext(field, "") or "", rel_path)
    elem = game.find(field)
    if elem is None:
        elem = etree.SubElement(game, field)
    elem.text = rel_path


def apply_proposed(game, fields, proposed, headers=None, media_handlers=None, no_url_key="server.no_ss_url"):
    """Write the selected ``fields`` of ``proposed`` into ``game`` (not saved).

    ``media_handlers`` maps a media field to ``fn(game, field, info) -> rel_path``
    for sources that download differently (Steam videos). Returns
    ``(applied, errors)``.
    """
    applied, errors = [], []
    wanted = [f for f in dict.fromkeys(fields or []) if isinstance(f, str)]

    for field in wanted:
        if field in MEDIA_DIRS or field == "pad2key":
            continue
        value = str(proposed.get(field) or "").strip()
        if not value:
            if field == "name":
                errors.append(st("server.name_empty_ignored"))
            continue
        if field == "name":
            set_name(game, value)
        elif field == "desc":
            set_desc(game, value)
        else:
            try:
                cleaned = clean_meta({field: value})
            except FieldError as e:
                key = "server.rating_invalid_value" if e.code == "rating_invalid" else "server.rating_range_value"
                errors.append(st(key, value=value))
                continue
            if field not in cleaned:
                continue                    # not a gamelist field
            elem = game.find(field)
            if elem is None:
                elem = etree.SubElement(game, field)
            elem.text = cleaned[field]
        applied.append(field)

    medias = proposed.get("medias") or {}
    base_name = get_base_name(game)
    handlers = media_handlers or {}
    supported = xml_store.media_fields()
    for field in wanted:
        if field not in MEDIA_DIRS or field not in supported:     # ES-DE: no wheel, map, bezel…
            continue
        info = medias.get(field) or {}
        url = str(info.get("url") or "").strip()
        if not url:
            errors.append(f"{field}: {st(no_url_key)}")
            continue
        try:
            if field in handlers:
                rel_path = handlers[field](game, field, info)
            else:
                dest = {}

                def dest_for(ext, f=field, dest=dest):
                    full, dest["value"] = media_dest(game, f, ext)
                    return full
                download_remote_media(url, xml_store.BASE_DIR, base_name, field, headers=headers, timeout=40,
                                      check=True, filename_for=dest_for)
                rel_path = dest["value"]
        except ValueError as e:
            msg = _download_error(field, e)
            if msg:
                errors.append(msg)
            continue
        except Exception as e:
            errors.append(f"{field}: {e}")
            continue
        set_media_path(game, field, rel_path)
        applied.append(field)

    if "pad2key" in wanted and not xml_store.is_esde():
        url = str((medias.get("pad2key") or {}).get("url") or "").strip()
        if url:
            try:
                download_pad2key(url, pad2key_dest(game))
                applied.append("pad2key")
            except Exception as e:
                errors.append(f"pad2key: {e}")
    return applied, errors


def apply_route(index, source, headers=None, media_handlers=None, no_url_key="server.no_ss_url", body=None):
    """The whole ``/api/<source>/apply/<index>`` route."""
    err = require_gamelist()
    if err:
        return err
    body = (request.get_json(silent=True) or {}) if body is None else body
    proposed = body.get("proposed") or {}
    if not isinstance(proposed, dict):
        return api_err(st("server.no_fields"), 400, code="no_fields")
    try:
        tree, game = get_game_elem(index)
    except IndexError:
        return api_err(st("server.invalid_index"), 404, code="invalid_index")
    preset = body.get("preset")
    if preset:
        try:
            fields = fields_for_preset(compare_rows(proposed, current_from_game(game), previews=False), preset)
        except ValueError:
            return api_err("unknown preset", 400, code="unknown_preset")
    else:
        fields = body.get("fields") or []
        if not isinstance(fields, list) or not fields:
            return api_err(st("server.no_fields"), 400, code="no_fields")
    applied, errors = apply_proposed(
        game, fields, proposed, headers=headers, media_handlers=media_handlers, no_url_key=no_url_key
    )
    if applied:
        history.label("scrape", weak=True, source=source, game=history.game_name(game), n=len(applied))
        save_xml(tree)
    return jsonify({"success": True, "applied": applied, "errors": errors, "source": source})
