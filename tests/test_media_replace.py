"""Replacing a media: a file another game (or tag) uses is never deleted nor overwritten."""
import io

import pytest
from lxml import etree
from PIL import Image

from gme import remote_cache, xml_store
from gme.scrapers.apply import apply_proposed
from tests.conftest import LOCAL

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><boxart>./images/shared-box.png</boxart>
    <image>./images/alpha-image.png</image><thumbnail>./images/alpha-image.png</thumbnail>
    <marquee>./images/alpha-marquee.png</marquee></game>
  <game><path>./bravo.zip</path><name>Bravo</name><boxart>./images/shared-box.png</boxart></game>
</gameList>
"""


def png(color=(0, 200, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def jpg():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "roms" / "snes"
    (root / "images").mkdir(parents=True)
    (root / "gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    for rel in ("alpha.zip", "bravo.zip", "images/shared-box.png", "images/alpha-image.png", "images/alpha-marquee.png"):
        (root / rel).write_bytes(png((1, 2, 3)))
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    yield root
    xml_store.close_gamelist()


def upload(client, index, path, field, data, name="new.png"):
    r = client.post(f"/api/upload/{index}/{field}?path={path}", headers=LOCAL,
                    data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    return r.get_json()["path"]


def tag(folder, name, field):
    games = {g.findtext("name"): g for g in etree.parse(str(folder / "gamelist.xml")).getroot()}
    return games[name].findtext(field)


def test_file_of_another_game_is_not_deleted(folder, client, trashed):
    assert upload(client, 1, "./bravo.zip", "boxart", png()) == "./images/bravo-boxart.png"
    assert (folder / "images" / "shared-box.png").exists()           # Alpha's box art
    assert tag(folder, "Alpha", "boxart") == "./images/shared-box.png"
    assert trashed == []


def test_file_of_another_tag_is_not_overwritten(folder, client, trashed):
    before = (folder / "images" / "alpha-image.png").read_bytes()
    assert upload(client, 0, "./alpha.zip", "image", png()) == "./images/alpha-image-2.png"
    assert (folder / "images" / "alpha-image.png").read_bytes() == before   # still the thumbnail
    assert tag(folder, "Alpha", "thumbnail") == "./images/alpha-image.png"
    assert trashed == []


def test_old_file_nobody_uses_goes_to_the_recycle_bin(folder, client, trashed):
    assert upload(client, 0, "./alpha.zip", "marquee", jpg(), name="logo.jpg") == "./images/alpha-marquee.jpg"
    assert [p.replace("\\", "/").rsplit("/", 1)[-1] for p in trashed] == ["alpha-marquee.png"]


def test_same_name_is_overwritten_when_only_this_tag_uses_it(folder, client, trashed):
    assert upload(client, 0, "./alpha.zip", "marquee", png((9, 9, 9))) == "./images/alpha-marquee.png"
    assert trashed == []


def test_scrape_follows_the_same_rules(folder, monkeypatch, trashed):
    monkeypatch.setattr(remote_cache, "get", lambda url: png((5, 5, 5)))
    tree = xml_store.load_xml()
    bravo = tree.getroot().findall("game")[1]
    applied, errors = apply_proposed(bravo, ["boxart"], {"medias": {"boxart": {"url": "https://x.test/b.png"}}})
    assert (applied, errors) == (["boxart"], [])
    assert bravo.findtext("boxart") == "./images/bravo-boxart.png"
    assert (folder / "images" / "shared-box.png").exists()
    assert trashed == []
