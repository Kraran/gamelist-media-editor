"""Delete a game: its files go to the Recycle Bin, files another game uses stay."""
import pytest
from lxml import etree

from gme import fsutil, xml_store
from tests.conftest import LOCAL

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><image>./images/alpha-image.png</image>
    <thumbnail>./images/alpha-thumb.png</thumbnail><boxart>./images/shared-box.png</boxart></game>
  <game><path>./bravo.zip</path><name>Bravo</name><boxart>./images/shared-box.png</boxart></game>
  <game><path>./disc/Delta.m3u</path><name>Delta</name></game>
  <game><path>./kinst.zip</path><name>Killer Instinct</name></game>
  <game><path>./twin.zip</path><name>Twin</name></game>
  <game><path>./twin.zip</path><name>Twin (copy)</name></game>
</gameList>
"""


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "roms" / "psx"
    (root / "images").mkdir(parents=True)
    (root / "disc").mkdir()
    (root / "kinst").mkdir()
    (root / "gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    for rel in ("alpha.zip", "alpha.keys", "bravo.zip", "kinst.zip", "kinst/kinst.chd", "twin.zip",
                "disc/Delta (Disc 1).chd", "disc/Delta (Disc 2).chd",
                "images/alpha-image.png", "images/alpha-thumb.png", "images/shared-box.png"):
        (root / rel).write_bytes(b"x" * 10)
    (root / "disc" / "Delta.m3u").write_text("Delta (Disc 1).chd\nDelta (Disc 2).chd\n")
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    yield root
    xml_store.close_gamelist()


def preview(client, index, path):
    r = client.post(f"/api/delete-game/{index}/preview?path={path}", headers=LOCAL)
    assert r.status_code == 200
    return r.get_json()


def delete(client, index, path, **body):
    return client.post(f"/api/delete-game/{index}?path={path}", headers=LOCAL, json=body)


def names(folder):
    return [g.findtext("name") for g in etree.parse(str(folder / "gamelist.xml")).getroot()]


def test_preview_lists_what_goes_and_what_stays(folder, client):
    data = preview(client, 0, "./alpha.zip")
    assert [f["path"] for f in data["files"]] == ["./alpha.zip", "./alpha.keys"]
    assert sorted(m["path"] for m in data["media"]) == ["./images/alpha-image.png", "./images/alpha-thumb.png"]
    assert [k["path"] for k in data["kept"]] == ["./images/shared-box.png"]       # Bravo's box art too
    assert names(folder)[0] == "Alpha"                                            # a dry run


def test_delete_trashes_the_game_and_keeps_shared_files(folder, client, trashed):
    data = delete(client, 0, "./alpha.zip", backup=True).get_json()
    assert data["trash"] is True and data["failed_files"] == []
    assert data["kept_files"] == ["./images/shared-box.png"]
    assert len(trashed) == 4
    assert not (folder / "alpha.zip").exists() and not (folder / "images" / "alpha-thumb.png").exists()
    assert (folder / "images" / "shared-box.png").exists()
    assert names(folder)[:2] == ["Bravo", "Delta"]
    assert "Alpha" in (folder / "gamelist.xml.bak").read_text(encoding="utf-8")


def test_discs_of_a_playlist_go_with_it(folder, client):
    data = delete(client, 2, "./disc/Delta.m3u").get_json()
    assert sorted(data["deleted_files"]) == ["./disc/Delta (Disc 1).chd", "./disc/Delta (Disc 2).chd", "./disc/Delta.m3u"]
    assert (folder / "disc").is_dir()


def test_the_romset_folder_goes_with_the_rom(folder, client):
    assert [f["path"] for f in preview(client, 3, "./kinst.zip")["files"]] == ["./kinst.zip", "./kinst"]
    delete(client, 3, "./kinst.zip")
    assert not (folder / "kinst").exists()


def test_a_rom_listed_twice_is_kept(folder, client):
    data = delete(client, 4, "./twin.zip").get_json()
    assert data["kept_files"] == ["./twin.zip"] and data["deleted_files"] == []
    assert (folder / "twin.zip").exists()
    assert "Twin" not in names(folder) and "Twin (copy)" in names(folder)


def test_without_trash_files_are_deleted_for_good(folder, client, trashed):
    delete(client, 1, "./bravo.zip", trash=False)
    assert trashed == []
    assert not (folder / "bravo.zip").exists()
    assert (folder / "images" / "shared-box.png").exists()                       # Alpha still uses it


def test_rom_that_cannot_be_deleted_changes_nothing(folder, client, monkeypatch):
    def no_recycle_bin(path):
        raise OSError("no Recycle Bin on this drive")
    monkeypatch.setattr(fsutil, "trash", no_recycle_bin)
    r = delete(client, 0, "./alpha.zip")
    assert r.status_code == 409 and r.get_json()["code"] == "rom_not_deleted"
    assert "./alpha.zip" in r.get_json()["error"]
    assert (folder / "alpha.zip").exists() and (folder / "images" / "alpha-image.png").exists()
    assert names(folder)[0] == "Alpha"
