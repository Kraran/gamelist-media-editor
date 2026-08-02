#!/usr/bin/env python3
"""Extract application icons from embedded JSON (base64).

Usage:
  python generate_icons.py

Looks for icons_data.json, or icons_png.json + icons_ico.json.
Called automatically by app.py when icons are missing.
"""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_payload() -> dict:
    """Merge available icon data files."""
    icons: dict = {}
    aliases: dict = {}
    for name in ("icons_data.json", "icons_png.json", "icons_ico.json"):
        path = ROOT / name
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        icons.update(payload.get("icons") or {})
        aliases.update(payload.get("aliases") or {})
    return {"icons": icons, "aliases": aliases}


def extract_icons(force: bool = False) -> list[str]:
    """Write icon files to disk. Returns list of written relative paths."""
    payload = _load_payload()
    icons = payload.get("icons") or {}
    aliases = payload.get("aliases") or {}
    if not icons:
        return []
    written: list[str] = []
    for rel, b64 in icons.items():
        dest = ROOT / rel
        if dest.exists() and not force:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(b64))
        written.append(rel)
    for dest_rel, src_rel in aliases.items():
        dest = ROOT / dest_rel
        src = ROOT / src_rel
        if dest.exists() and not force:
            continue
        if src.exists():
            shutil.copy2(src, dest)
            written.append(dest_rel)
    return written


if __name__ == "__main__":
    done = extract_icons(force=True)
    print(f"Extracted {len(done)} icon file(s):")
    for p in done:
        print(" ", p)
