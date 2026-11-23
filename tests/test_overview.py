"""Multi-system overview: roms root, system folders, counts per system, cache, recent roots."""
import os

import pytest

from gme import overview, recent, xml_store
from tests.conftest import LOCAL, picture

SNES = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><desc>A</desc><genre>Platform</genre><image>./images/alpha.png</image></game>
  <game><path>./bravo.zip</path><name>Bravo</name><image>./images/gone.png</image><releasedate>19920101T000000</releasedate></game>
  <game><path>./ghost.zip</path><name>Ghost</name><video>./videos/ghost.mp4</video></game>
  <game><path>steam://rungameid/1</path><name>Url</name><hidden>true</hidden></game>
</gameList>
"""
NES = """<?xml version="1.0"?>
<gameList><game><path>./sub/one.nes</path><name>One</name><marquee>./images/one-marquee.png</marquee></game></gameList>
"""


@pytest.fixture
def roms(tmp_path):
    root = tmp_path / "RetroBat" / "roms"
    snes = root / "snes"
    (snes / "images").mkdir(parents=True)
    (snes / "videos").mkdir()
    (snes / "gamelist.xml").write_text(SNES, encoding="utf-8")
    for rom in ("alpha.zip", "bravo.zip", "extra.sfc"):
        (snes / rom).write_bytes(b"rom")
    (snes / "images" / "alpha.png").write_bytes(picture())
    nes = root / "nes"
    (nes / "sub").mkdir(parents=True)
    (nes / "images").mkdir()
    (nes / "gamelist.xml").write_text(NES, encoding="utf-8")
    (nes / "sub" / "one.nes").write_bytes(b"rom")
    (nes / "images" / "one-marquee.png").write_bytes(picture())
    (root / "gba").mkdir()
    (root / "gba" / "a.gba").write_bytes(b"rom")          # ROMs, no gamelist
    (root / "bios").mkdir()
    (root / "bios" / "scph1001.bin").write_bytes(b"bios")  # never a system
    (root / "empty").mkdir()                               # nothing: not a system
    (root / "broken").mkdir()
    (root / "broken" / "gamelist.xml").write_text("<gameList><game>", encoding="utf-8")
    overview.reset()
    yield root
    overview.reset()


def by_folder(systems):
    return {s["folder"]: s for s in systems}


def test_lists_the_system_folders_with_friendly_names(roms):
    systems = overview.list_systems(str(roms))
    assert [s["folder"] for s in systems] == ["broken", "gba", "nes", "snes"]
    s = by_folder(systems)
    assert s["snes"]["label"] == "Super Nintendo" and s["snes"]["xml"].endswith("gamelist.xml")
    assert s["gba"]["xml"] is None and s["gba"]["label"] == "Game Boy Advance"
    assert s["broken"]["label"] == "broken"                 # unknown folder: its own name


@pytest.mark.parametrize("pick", ["", "..", "snes", "snes/gamelist.xml"])
def test_the_root_is_found_from_the_roms_folder_its_parent_or_a_system(roms, pick):
    start = {"": roms, "..": roms.parent, "snes": roms / "snes", "snes/gamelist.xml": roms / "snes" / "gamelist.xml"}[pick]
    assert overview.resolve_root(str(start)) == str(roms)


def test_batocera_and_recalbox_layouts(tmp_path):
    for layout in (("userdata", "roms"), ("share", "roms")):
        base = tmp_path.joinpath(*layout[:-1]) if layout[0] != "userdata" else tmp_path / "batocera"
        roms = base / ("roms" if layout[0] == "share" else os.path.join("userdata", "roms"))
        (roms / "nes").mkdir(parents=True)
        (roms / "nes" / "gamelist.xml").write_text("<gameList/>", encoding="utf-8")
        top = base if layout[0] == "userdata" else base.parent
        assert overview.resolve_root(str(top)) == str(roms)


def test_a_folder_without_systems_is_refused(tmp_path):
    (tmp_path / "docs").mkdir()
    with pytest.raises(ValueError):
        overview.resolve_root(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        overview.resolve_root(str(tmp_path / "nope"))


def test_counts_of_one_system(roms):
    s = overview.scan_system(by_folder(overview.list_systems(str(roms)))["snes"])
    assert s["games"] == 4 and s["error"] is None
    assert s["roms_missing"] == 1                       # ghost.zip (the steam:// entry is not a file)
    assert s["roms"] == 3 and s["roms_unlisted"] == 1    # extra.sfc
    assert s["media"]["image"] == {"present": 1, "broken": 1, "missing": 2}
    assert s["media"]["video"] == {"present": 0, "broken": 1, "missing": 3}
    assert s["meta_missing"]["desc"] == 3 and s["meta_missing"]["genre"] == 3 and s["meta_missing"]["releasedate"] == 3
    assert s["scraped"] == 1 and s["hidden"] == 1


def test_nested_roms_roms_only_and_broken_gamelists(roms):
    systems = by_folder(overview.list_systems(str(roms)))
    nes = overview.scan_system(systems["nes"])
    assert nes["roms_missing"] == 0 and nes["roms_unlisted"] == 0 and nes["media"]["marquee"]["present"] == 1
    gba = overview.scan_system(systems["gba"])
    assert gba["games"] == 0 and gba["roms_unlisted"] == 1
    broken = overview.scan_system(systems["broken"])
    assert broken["error"] == "bad_xml"


def test_nothing_is_written_and_the_open_gamelist_is_untouched(roms, tmp_path):
    other = tmp_path / "other" / "gamelist.xml"
    other.parent.mkdir()
    other.write_text("<gameList/>", encoding="utf-8")
    xml_store.set_gamelist_path(str(other))
    try:
        before = {p: os.stat(p).st_mtime_ns for p in map(str, roms.rglob("*"))}
        overview.start(str(roms))
        assert overview.wait()
        assert {p: os.stat(p).st_mtime_ns for p in map(str, roms.rglob("*"))} == before
        assert xml_store.XML_PATH == str(other)
    finally:
        xml_store.close_gamelist()


def test_results_are_cached_until_the_gamelist_changes(roms, monkeypatch):
    calls = []
    real = overview.scan_system
    monkeypatch.setattr(overview, "scan_system", lambda s: calls.append(s["folder"]) or real(s))
    system = by_folder(overview.list_systems(str(roms)))["snes"]
    assert overview.cached_scan(system)["cached"] is False
    assert overview.cached_scan(system)["cached"] is True
    xml = roms / "snes" / "gamelist.xml"
    xml.write_text(SNES.replace("Alpha", "Alpha 2"), encoding="utf-8")
    os.utime(xml, ns=(1, 10 ** 18))
    assert overview.cached_scan(system)["cached"] is False
    assert overview.cached_scan(system, refresh=True)["cached"] is False
    assert calls == ["snes", "snes", "snes"]


def test_scan_api_progress_and_recent_roots(roms, client):
    r = client.post("/api/overview/scan", headers=LOCAL, json={"path": str(roms.parent)})
    assert r.status_code == 200
    data = r.get_json()
    assert data["root"] == str(roms) and data["total"] == 4
    assert data["recent"] == [{"path": str(roms), "exists": True}]
    assert overview.wait()
    data = client.get("/api/overview", headers=LOCAL).get_json()
    assert data["state"] == "done" and data["done"] == 4
    assert [s["folder"] for s in data["systems"]] == ["broken", "gba", "nes", "snes"]
    assert recent.recent_roots() == [str(roms)]
    quick = client.get("/api/overview/systems", headers=LOCAL).get_json()
    assert [s["folder"] for s in quick["systems"]] == ["broken", "gba", "nes", "snes"]


def test_scan_api_errors(tmp_path, roms, client):
    r = client.post("/api/overview/scan", headers=LOCAL, json={"path": str(tmp_path / "gone")})
    assert r.status_code == 404 and r.get_json()["code"] == "browse_not_dir"
    (tmp_path / "plain").mkdir()
    r = client.post("/api/overview/scan", headers=LOCAL, json={"path": str(tmp_path / "plain")})
    assert r.status_code == 400 and r.get_json()["code"] == "overview_no_systems"
    r = client.post("/api/overview/scan", headers=LOCAL, json={})
    assert r.status_code == 400


def test_recent_roots_keep_six_and_forget(tmp_path, client):
    paths = []
    for i in range(8):
        p = tmp_path / f"r{i}"
        p.mkdir()
        paths.append(str(p))
        recent.remember_root(str(p))
    assert recent.recent_roots() == list(reversed(paths))[:recent.ROOTS_MAX]
    os.rmdir(paths[-1])
    data = client.get("/api/overview/recent", headers=LOCAL).get_json()["recent"]
    assert data[0] == {"path": paths[-1], "exists": False}
    data = client.post("/api/overview/recent/forget", headers=LOCAL, json={"path": paths[-1]}).get_json()["recent"]
    assert paths[-1] not in [d["path"] for d in data]


def test_the_root_comes_back_when_a_system_of_a_recent_root_is_open(roms):
    recent.remember_root(str(roms))
    xml_store.set_gamelist_path(str(roms / "nes" / "gamelist.xml"))
    try:
        assert overview.current_root() == str(roms)
    finally:
        xml_store.close_gamelist()


def test_stop(roms, client, monkeypatch):
    import threading
    gate = threading.Event()
    real = overview.scan_system
    monkeypatch.setattr(overview, "WORKERS", 1)
    monkeypatch.setattr(overview, "scan_system", lambda s: gate.wait(5) and real(s))
    client.post("/api/overview/scan", headers=LOCAL, json={"path": str(roms)})
    client.post("/api/overview/stop", headers=LOCAL)
    gate.set()
    assert overview.wait()
    data = client.get("/api/overview", headers=LOCAL).get_json()
    assert data["state"] == "stopped" and data["done"] < 4
