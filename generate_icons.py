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

def read_b64(name: str) -> bytes:
    """Read a .b64 file, or join .b64.part0 + .part1 + ... if split."""
    whole = DATA / name
    if whole.is_file():
        return base64.b64decode(whole.read_text(encoding="ascii"))
    parts = sorted(DATA.glob(name + ".part*"))
    if not parts:
        raise FileNotFoundError(name)
    text = "".join(p.read_text(encoding="ascii") for p in parts)
    return base64.b64decode(text)

MAP = {
    "static/favicon-16.png": "favicon-16.png.b64",
    "static/favicon-32.png": "favicon-32.png.b64",
    "static/favicon.ico": "favicon.ico.b64",
    "static/app-icon.png": "app-icon.png.b64",
    "icon.ico": "favicon.ico.b64",
    "icon.png": "app-icon.png.b64",
}


def main() -> None:
    for dest_rel, data_name in MAP.items():
        try:
            data = read_b64(data_name)
        except FileNotFoundError:
            print(f"  missing {data_name}")
            continue
        dest = ROOT / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"  wrote {dest_rel} ({len(data)} bytes)")
    print("Done.")


if __name__ == "__main__":
    main()
