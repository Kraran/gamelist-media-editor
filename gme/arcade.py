"""Arcade hardware names (<arcadesystemname>) from MAME drivers."""

import os
import json

from lxml import etree

from gme import xml_store
from gme.paths import APP_DIR, resource_path


_MAME_DRIVERS = None


def load_mame_drivers():
    """sourcefile stem → short board name (cps1 → CPS1). Cached."""
    global _MAME_DRIVERS
    if _MAME_DRIVERS is not None:
        return _MAME_DRIVERS
    path = resource_path("static", "mame_drivers.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        _MAME_DRIVERS = {str(k).lower(): str(v) for k, v in raw.items()}
    except Exception:
        _MAME_DRIVERS = {}
    return _MAME_DRIVERS


_DRIVER_PREFIXES = (
    ("segas16", "System 16"),
    ("sega16", "System 16"),
    ("segas32", "System 32"),
    ("sega32", "System 32"),
    ("gaelco", "Gaelco"),
    ("cps3", "CPS3"),
    ("cps2", "CPS2"),
    ("cps1", "CPS1"),
    ("neogeo", "Neo-Geo"),
    ("hng64", "Hyper Neo-Geo 64"),
    ("playch", "PlayChoice-10"),
    ("vsnes", "Vs. System"),
    ("decocass", "DECO Cassette"),
    ("konamigx", "Konami GX"),
    ("namcos", "Namco"),
    ("taito_type_x", "Taito Type X"),
    ("taitotx", "Taito Type X"),
    ("typex", "Taito Type X"),
    ("atomiswave", "Atomiswave"),
    ("lindbergh", "Lindbergh"),
    ("chihiro", "Chihiro"),
    ("triforce", "Triforce"),
    ("model3", "Model 3"),
    ("model2", "Model 2"),
    ("model1", "Model 1"),
    ("stv", "ST-V"),
    ("naomi2", "NAOMI 2"),
    ("naomi", "NAOMI"),
    ("cave", "Cave"),
    ("pgm", "PolyGame Master"),
    ("zn2", "ZN-2"),
    ("zn1", "ZN-1"),
    ("zn", "ZN"),
    ("taito_", "Taito"),
    ("taito", "Taito"),
    ("konami", "Konami"),
    ("mid", "Midway"),
    ("irem", "Irem"),
    ("sega", "Sega"),
    ("atari", "Atari"),
    ("namco", "Namco"),
)


def pretty_arcade_system(sourcefile, romset=""):
    """cps1.cpp → CPS1. Empty when the driver is named after this single game."""
    if not sourcefile:
        return ""
    path = str(sourcefile).replace("\\", "/").strip()
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    rom = os.path.splitext(os.path.basename(str(romset).replace("\\", "/")))[0].lower()
    if rom and stem == rom:
        return ""
    mapped = load_mame_drivers().get(stem)
    if mapped:
        return mapped
    for prefix, label in _DRIVER_PREFIXES:
        if stem.startswith(prefix):
            return label
    pretty = stem.replace("_", " ").replace("-", " ").strip()
    return pretty.title() if pretty else ""


def find_mame_listxml():
    """Look for a MAME -listxml dump near the gamelist or RetroBat tree."""
    candidates = []
    if xml_store.BASE_DIR:
        candidates.extend([
            os.path.join(xml_store.BASE_DIR, "mame.xml"),
            os.path.join(xml_store.BASE_DIR, "mame", "mame.xml"),
            os.path.join(os.path.dirname(xml_store.BASE_DIR), "mame.xml"),
        ])
        root = xml_store.BASE_DIR
        for _ in range(5):
            parent = os.path.dirname(root)
            if parent == root:
                break
            root = parent
            candidates.extend([
                os.path.join(root, "mame.xml"),
                os.path.join(root, "bios", "mame", "mame.xml"),
                os.path.join(root, "emulators", "mame", "mame.xml"),
                os.path.join(root, "emulators", "mame", "hash", "mame.xml"),
            ])
    candidates.append(os.path.join(APP_DIR, "mame.xml"))
    seen = set()
    for p in candidates:
        if not p or p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p) and os.path.getsize(p) > 1000:
            return p
    return None


def index_mame_listxml(path):
    """romset name → sourcefile from MAME -listxml (machine or game tags)."""
    idx, clones = {}, {}
    for _event, elem in etree.iterparse(path, events=("end",), tag=("machine", "game")):
        name = (elem.get("name") or "").strip()
        src = (elem.get("sourcefile") or "").strip()
        cloneof = (elem.get("cloneof") or "").strip()
        if name:
            if src:
                idx[name.lower()] = src
            if cloneof:
                clones[name.lower()] = cloneof.lower()
        elem.clear()
    for name, parent in clones.items():
        if name not in idx and parent in idx:
            idx[name] = idx[parent]
    return idx
