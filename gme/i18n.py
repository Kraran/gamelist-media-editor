"""Server-side translations (static/locales/*.json) following the UI language."""

import os
import json

from flask import request

from gme.paths import resource_path


_LOCALE_DIR = resource_path("static", "locales")
_LOCALE_CACHE = {}


def load_locale_dict(code):
    """Load static/locales/{code}.json (cached). Falls back to fr."""
    code = (code or "fr")[:2].lower()
    if code in _LOCALE_CACHE:
        return _LOCALE_CACHE[code]
    path = os.path.join(_LOCALE_DIR, f"{code}.json")
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        if code != "fr":
            return load_locale_dict("fr")
    _LOCALE_CACHE[code] = data
    return data


def get_request_locale():
    """Prefer X-Locale (frontend), then Accept-Language, else fr."""
    try:
        h = (request.headers.get("X-Locale") or "").strip().lower()
        if len(h) >= 2 and h[:2].isalpha():
            return h[:2]
        al = (request.headers.get("Accept-Language") or "").lower()
        if al.startswith("en"):
            return "en"
    except RuntimeError:
        # Outside request context
        pass
    return "fr"


def st(key, **params):
    """Server-side translation. key e.g. 'server.invalid_field'."""
    data = load_locale_dict(get_request_locale())
    parts = str(key).split(".")
    cur = data
    found = True
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            found = False
            break
    if not found or not isinstance(cur, str):
        # fallback French
        cur = load_locale_dict("fr")
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return str(key)
        if not isinstance(cur, str):
            return str(key)
    for k, v in params.items():
        cur = cur.replace("{" + str(k) + "}", str(v))
    return cur
