#!/usr/bin/env python3
"""Write application icons from icon_data/*.b64 files.

Usage:
  python generate_icons.py
"""
from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "icon_data"

# destination relative path -> data file name
MAP = {
    "static/favicon-16.png": "favicon-16.png.b64",
    "static/favicon-32.png": "favicon-32.png.b64",
    "static/favicon.ico": "favicon.ico.b64",
    "static/app-icon.png": "app-icon.png.b64",
    "icon.ico": "favicon.ico.b64",   # same multi-size ICO for Windows shortcut
    "icon.png": "app-icon.png.b64",
}


def main() -> None:
    for dest_rel, data_name in MAP.items():
        src = DATA / data_name
        if not src.is_file():
            print(f"  missing {src}")
            continue
        data = base64.b64decode(src.read_text(encoding="ascii"))
        dest = ROOT / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"  wrote {dest_rel} ({len(data)} bytes)")
    print("Done.")


if __name__ == "__main__":
    main()
