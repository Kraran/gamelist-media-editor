#!/usr/bin/env python3
"""Extract application icons from icons_data.json (base64).

Usage:
  python generate_icons.py

Called automatically by app.py when icons are missing.
"""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def extract_icons(force: bool = False) -> list[str]:
    data_path = ROOT / "icons_data.json"
    if not data_path.is_file():
        return []
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    icons = payload.get("icons") or {}
    aliases = payload.get("aliases") or {}
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
