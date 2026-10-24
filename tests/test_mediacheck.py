"""Media check: unused media files and links to missing files, then clean-up."""
import pytest
from lxml import etree

from gme import mediacheck, xml_store
from tests.conftest import LOCAL

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><image>./images/alpha-image.png</image>
    <video>./videos/alpha-video.mp4</video><titleshot>./images/alpha-title.png</titleshot></game>
  <game><path>./bravo.zip</path><name>Bravo</name><image>./images/bravo-image.png</image>
    <manual>./manuals/bravo-manual.pdf</manual></game>
  <game><path>./charlie.zip</path><name>Charlie</name><image>./images/alpha-image.png</image></game>
</gameList>
"""


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "roms" / "snes"
    for sub in ("images/boxart", "videos", "manuals"):
        (root / sub).mkdir(parents=True)
    (root / "gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    files = {
        "images/alpha-image.png": b"a" * 10,      # used twice
        "images/alpha-title.png": b"t",           # used by a Batocera tag
        "videos/alpha-video.mp4": b"v",
        "images/old-image.png": b"o" * 100,       # orphan
        "images/boxart/old-box.jpg": b"o" * 50,   # orphan in a sub-folder
        "videos/old-video.mp4": b"o" * 1000,      # orphan
        "images/notes.txt": b"not media",         # not a media file: ignored
        "images/.hidden.png": b"h",               # hidden: ignored
    }
    for rel, data in files.items():
        (root / rel).write_bytes(data)
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    yield root
    xml_store.close_gamelist()


@pytest.fixture
def no_trash(monkeypatch):
    """The test machine may have no Recycle Bin: record instead."""
    trashed = []

    def fake_trash(full):
        trashed.append(full)
        import os
        os.remove(full)

    monkeypatch.setattr(mediacheck, "_trash", fake_trash)
    return trashed


def report(client):
    r = client.get("/api/check-media", headers=LOCAL)
    assert r.status_code == 200
    return r.get_json()


def test_report(folder, client):
    data = report(client)
    assert data["files"] == 6
    assert sorted(o["path"] for o in data["orphans"]) == [
        "./images/boxart/old-box.jpg", "./images/old-image.png", "./videos/old-video.mp4"]
    assert data["orphan_bytes"] == 1150
    assert sorted((b["name"], b["tag"]) for b in data["broken"]) == [("Bravo", "image"), ("Bravo", "manual")]
    assert data["folders"] == ["images", "manuals", "videos"]


def test_delete_goes_to_trash_and_only_orphans(folder, client, no_trash):
    r = client.post("/api/check-media/apply", headers=LOCAL, json={
        "delete": ["./images/old-image.png", "./images/alpha-image.png", "./gamelist.xml"],
    })
    data = r.get_json()
    assert (data["deleted"], data["freed"], data["trash"]) == (1, 100, True)
    assert len(no_trash) == 1
    assert not (folder / "images" / "old-image.png").exists()
    assert (folder / "images" / "alpha-image.png").exists()       # used: never deleted
    assert (folder / "gamelist.xml").exists()
    assert len(data["report"]["orphans"]) == 2


def test_delete_without_trash(folder, client, no_trash):
    client.post("/api/check-media/apply", headers=LOCAL,
                json={"delete": ["./videos/old-video.mp4"], "trash": False})
    assert no_trash == []
    assert not (folder / "videos" / "old-video.mp4").exists()


def test_unlink_removes_only_the_broken_tags(folder, client):
    r = client.post("/api/check-media/apply", headers=LOCAL, json={
        "unlink": [{"path": "./bravo.zip", "tag": "image"}, {"path": "./alpha.zip", "tag": "image"}],
    })
    data = r.get_json()
    assert data["unlinked"] == 1
    games = {g.findtext("name"): g for g in etree.parse(str(folder / "gamelist.xml")).getroot()}
    assert games["Bravo"].find("image") is None
    assert games["Bravo"].findtext("manual") == "./manuals/bravo-manual.pdf"   # not asked
    assert games["Alpha"].findtext("image") == "./images/alpha-image.png"      # not broken
    assert (folder / "gamelist.xml.bak").exists()


def test_trash_failure_is_reported(folder, client, monkeypatch):
    def broken_trash(full):
        raise OSError("no recycle bin on this drive")
    monkeypatch.setattr(mediacheck, "_trash", broken_trash)
    data = client.post("/api/check-media/apply", headers=LOCAL,
                       json={"delete": ["./images/old-image.png"]}).get_json()
    assert data["deleted"] == 0 and data["failed"] == ["./images/old-image.png"]
    assert (folder / "images" / "old-image.png").exists()


def test_nothing_to_do_is_refused(folder, client):
    assert client.post("/api/check-media/apply", headers=LOCAL, json={}).status_code == 400
