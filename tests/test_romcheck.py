"""ROM check: the gamelist compared with the files of its folder, then updated."""
import pytest
from lxml import etree

from gme import xml_store
from tests.conftest import LOCAL

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><image>./images/alpha-image.png</image></game>
  <game><path>./gone.zip</path><name>Gone</name><image>./images/gone-image.png</image><desc>bye</desc></game>
  <game><path>./disc/Bravo.m3u</path><name>Bravo</name></game>
  <game><path>./twin.zip</path><name>Twin</name></game>
  <game><path>./Charlie.ps3</path><name>Charlie</name></game>
  <game><path>steam://rungameid/400</path><name>Portal</name></game>
</gameList>
"""


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "roms" / "psx"
    (root / "images").mkdir(parents=True)
    (root / "disc").mkdir()
    (root / "Charlie.ps3").mkdir()                      # a folder that is one game
    (root / "Charlie.ps3" / "EBOOT.BIN").write_bytes(b"x")
    (root / "gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    for name in ("alpha.zip", "twin.zip", "new game (USA).zip", "Delta.cue", "Delta (Track 1).bin",
                 "Delta (Track 2).bin", "readme.txt", "gamelist.xml.bak"):
        (root / name).write_bytes(b"rom")
    (root / "Delta.cue").write_text('FILE "Delta (Track 1).bin" BINARY\nFILE "Delta (Track 2).bin" BINARY\n')
    (root / "disc" / "Bravo.m3u").write_text("Bravo (Disc 1).chd\nBravo (Disc 2).chd\n")
    (root / "disc" / "Bravo (Disc 1).chd").write_bytes(b"d1")
    (root / "disc" / "Bravo (Disc 2).chd").write_bytes(b"d2")
    (root / "images" / "orphan.zip").write_bytes(b"not a rom")   # media folders are skipped
    (root / "images" / "gone-image.png").write_bytes(b"png")
    (root / "images" / "alpha-image.png").write_bytes(b"png")
    (root / "Port").mkdir()
    (root / "Port" / "pak0.pak").write_bytes(b"data")            # data in a sub-folder, not a game
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    yield root
    xml_store.close_gamelist()


def report(client):
    r = client.get("/api/check-roms", headers=LOCAL)
    assert r.status_code == 200
    return r.get_json()


def test_report(folder, client):
    data = report(client)
    assert sorted(u["path"] for u in data["unlisted"]) == ["./Delta.cue", "./new game (USA).zip"]
    assert {u["name"] for u in data["unlisted"]} == {"Delta", "new game (USA)"}
    assert [m["path"] for m in data["missing"]] == ["./gone.zip"]
    assert data["missing"][0]["media"] == 1
    assert data["duplicates"] == []
    assert data["non_file"] == 1                                  # steam:// is not a file
    assert data["games"] == 6


def test_apply_adds_removes_and_keeps_a_backup(folder, client):
    r = client.post("/api/check-roms/apply", headers=LOCAL, json={
        "add": ["./new game (USA).zip", "./readme.txt"],          # readme is not offered: ignored
        "remove": ["./gone.zip", "./alpha.zip"],                  # alpha exists: never removed
    })
    data = r.get_json()
    assert (data["added"], data["removed"]) == (1, 1)
    assert data["report"]["missing"] == []
    root = etree.parse(str(folder / "gamelist.xml")).getroot()
    paths = [g.findtext("path") for g in root.findall("game")]
    assert "./gone.zip" not in paths and "./alpha.zip" in paths
    new = root.findall("game")[-1]
    assert (new.findtext("path"), new.findtext("name")) == ("./new game (USA).zip", "new game (USA)")
    assert "./gone.zip" in (folder / "gamelist.xml.bak").read_text(encoding="utf-8")
    assert (folder / "images" / "gone-image.png").exists()        # media kept unless asked


def test_remove_can_delete_unused_media(folder, client):
    client.post("/api/check-roms/apply", headers=LOCAL,
                json={"remove": ["./gone.zip"], "delete_media": True})
    assert not (folder / "images" / "gone-image.png").exists()
    assert (folder / "images" / "alpha-image.png").exists()


def test_merge_duplicates_keeps_every_field(tmp_path, client):
    xml = tmp_path / "gamelist.xml"
    xml.write_text("""<gameList>
      <game><path>./a.zip</path><name>A</name></game>
      <game><path>./a.zip</path><name>A2</name><genre>Puzzle</genre><desc>long</desc></game>
    </gameList>""", encoding="utf-8")
    (tmp_path / "a.zip").write_bytes(b"x")
    xml_store.set_gamelist_path(str(xml))
    try:
        assert len(report(client)["duplicates"]) == 1
        data = client.post("/api/check-roms/apply", headers=LOCAL, json={"merge": ["./a.zip"]}).get_json()
        assert data["merged"] == 1
        games = etree.parse(str(xml)).getroot().findall("game")
        assert len(games) == 1
        assert (games[0].findtext("name"), games[0].findtext("genre")) == ("A2", "Puzzle")
    finally:
        xml_store.close_gamelist()


def test_nothing_to_do_is_refused(folder, client):
    r = client.post("/api/check-roms/apply", headers=LOCAL, json={})
    assert r.status_code == 400
