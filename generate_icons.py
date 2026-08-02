#!/usr/bin/env python3
"""Write application icons from icon_data/*.b64 files.

Usage:
  python generate_icons.py
"""
from __future__ import annotations

import base64
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "icon_data"


def read_payload(filename: str) -> bytes:
    """Load icon bytes from an icon_data file.

    Supports:
      - plain base64:  foo.b64
      - gzip+base64:   foo.gz.b64
    """
    path = DATA / filename
    if not path.is_file():
        raise FileNotFoundError(filename)
    raw = base64.b64decode(path.read_text(encoding="ascii"))
    if filename.endswith(".gz.b64"):
        return gzip.decompress(raw)
    return raw


MAP = {
    "static/favicon-16.png": "favicon-16.png.b64",
    "static/favicon-32.png": "favicon-32.png.b64",
    "static/favicon.ico": "favicon.ico.gz.b64",
    "static/app-icon.png": "app-icon.png.b64",
    "icon.ico": "favicon.ico.gz.b64",
    "icon.png": "app-icon.png.b64",
}


def main() -> None:
    for dest_rel, data_name in MAP.items():
        try:
            data = read_payload(data_name)
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
