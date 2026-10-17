"""JSON error payloads shared by every route."""

from flask import jsonify


def api_err(message, status=400, code=None, **extra):
    """Consistent JSON error payload for the frontend."""
    payload = {"error": str(message), "ok": False}
    if code:
        payload["code"] = code
    payload.update(extra)
    return jsonify(payload), status
