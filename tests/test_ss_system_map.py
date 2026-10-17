"""Regression tests for the ScreenScraper system map (gme.systems.SS_SYSTEM_MAP)."""
import ast
from pathlib import Path

import pytest

from gme import systems, xml_store

SYSTEMS_PY = Path(__file__).resolve().parents[1] / "gme" / "systems.py"


def _ss_map_literal_keys():
    """Keys as written in the source: a dict literal silently drops duplicates."""
    tree = ast.parse(SYSTEMS_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SS_SYSTEM_MAP" for t in node.targets
        ):
            return [k.value for k in node.value.keys]
    raise AssertionError("SS_SYSTEM_MAP not found in gme/systems.py")


def test_no_duplicate_keys():
    keys = _ss_map_literal_keys()
    dups = sorted({k for k in keys if keys.count(k) > 1})
    assert not dups, f"duplicate SS_SYSTEM_MAP keys: {dups}"


def test_ids_are_positive_ints():
    bad = {k: v for k, v in systems.SS_SYSTEM_MAP.items() if not isinstance(v, int) or v <= 0}
    assert not bad


# Values checked against RetroBat/Batocera EmulationStation and ES-DE tables.
# Former wrong values in comments: they pointed at other ScreenScraper systems.
@pytest.mark.parametrize("folder, expected", [
    ("naomi", 56),        # was 142 (Neo-Geo)
    ("atomiswave", 53),   # was 148 (Irem)
    ("model2", 54),       # was 149 (Seta)
    ("model3", 55),       # was 150 (Midway)
    ("neogeo", 142),
    ("vic20", 73),        # was 118 (MSX Turbo R)
    ("c20", 73),
    ("msxturbor", 118),
    ("msx2", 116),
    ("pet", 240),         # was 120 (V.Smile)
    ("plus4", 99),
    ("pc88", 221),        # was 121 (Game.com)
    ("pc98", 208),        # was 122 (N64DD)
    ("pico8", 234),       # was 211 (Pokémon Mini)
    ("pokemini", 211),
    ("wasm4", 262),       # was 0
    ("cps1", 6),
    ("arcade", 75),
    ("megadrive", 1),
])
def test_known_system_ids(folder, expected):
    assert systems.SS_SYSTEM_MAP[folder] == expected


def test_detect_system_id_from_gamelist_folder(tmp_path, monkeypatch):
    folder = tmp_path / "Naomi"
    folder.mkdir()
    monkeypatch.setattr(xml_store, "BASE_DIR", str(folder))
    assert systems.detect_system_id() == (56, "naomi")
