"""Scrape comparison, presets, shared apply and the preview cache (no network)."""
import io
import os

import pytest
from lxml import etree

from gme import remote_cache, xml_store
from gme.scrapers import steam
from gme.scrapers.compare import compare_rows, current_from_game, fields_for_preset
from gme.systems import default_scraper
from tests.conftest import LOCAL

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def png(color=(200, 30, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_cache, "CACHE_DIR", str(tmp_path / "remote-cache"))
    remote_cache._registry.clear()


@pytest.fixture
def downloads(monkeypatch):
    """Fake network: every fetch returns a small PNG and is counted."""
    calls = []

    def fake_fetch(url, headers=None, timeout=40, max_bytes=0):
        calls.append(url)
        return png(), "image/png"

    monkeypatch.setattr(remote_cache, "fetch", fake_fetch)
    return calls


def rows_by_key(rows):
    return {r["key"]: r for r in rows}


PROPOSED = {
    "name": "Alpha",                   # same as the gamelist
    "desc": "A fine game.",            # new
    "rating": "0.80",
    "releasedate": "19920101T000000",
    "genre": "Action",
    "developer": "",                   # source has nothing
    "medias": {
        "image": {"url": "https://media.example/ss.png?ssid=me&sspassword=secret", "type": "ss"},
        "thumbnail": {"url": "https://media.example/box2d.png", "type": "box-2D"},
        "bezel": {"url": "https://media.example/bezel.png", "type": "bezel-16-9"},
        "video": {"url": "https://media.example/v.mp4", "type": "video"},
    },
}


def test_statuses():
    current = {"name": "Alpha", "rating": "0.8", "releasedate": "19920101", "genre": "ACTION ", "developer": "Old Dev"}
    rows = rows_by_key(compare_rows(PROPOSED, current, previews=False))
    assert rows["name"]["status"] == "same"
    assert rows["desc"]["status"] == "new"
    assert rows["rating"]["status"] == "same"          # 0.80 == 0.8
    assert rows["releasedate"]["status"] == "same"     # same day, other format
    assert rows["genre"]["status"] == "same"           # case and spaces ignored
    assert rows["developer"]["status"] == "unavailable"
    assert rows["publisher"]["status"] == "unavailable"
    assert rows["image"]["status"] == "new"
    assert rows["boxart"]["status"] == "unavailable"


def test_different_text_and_media_to_replace(gamelist):
    tree, game = xml_store.get_game_elem(0)
    (gamelist.parent / "images").mkdir()
    (gamelist.parent / "images" / "alpha-image.png").write_bytes(PNG)
    etree.SubElement(game, "image").text = "./images/alpha-image.png"
    etree.SubElement(game, "thumbnail").text = "./images/missing-on-disk.png"
    etree.SubElement(game, "genre").text = "Puzzle"
    rows = rows_by_key(compare_rows(PROPOSED, current_from_game(game), previews=False))
    assert rows["genre"]["status"] == "different"
    assert rows["image"]["status"] == "replace"
    assert rows["thumbnail"]["status"] == "new"        # path set but the file is gone


def test_presets():
    rows = compare_rows(PROPOSED, {"name": "Alpha", "genre": "Puzzle"}, previews=False)
    missing = fields_for_preset(rows, "missing")
    assert "desc" in missing and "image" in missing and "thumbnail" in missing
    assert "genre" not in missing and "name" not in missing
    assert "genre" in fields_for_preset(rows, "all")
    assert "name" not in fields_for_preset(rows, "all")  # identical: nothing to do
    assert fields_for_preset(rows, "none") == []
    with pytest.raises(ValueError):
        fields_for_preset(rows, "everything")


def test_preview_keys_hide_urls():
    rows = rows_by_key(compare_rows(PROPOSED, {}))
    assert rows["image"]["preview"].startswith("/api/scrape/preview/")
    assert "secret" not in rows["image"]["preview"] and "http" not in rows["image"]["preview"]
    assert "preview" not in rows["video"]                # videos are not previewed


def test_preview_downloads_once_and_apply_reuses_it(gamelist, client, downloads):
    preview = rows_by_key(compare_rows(PROPOSED, {}))["image"]["preview"]
    r = client.get(preview, headers=LOCAL)
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert client.get(preview, headers=LOCAL).status_code == 200
    assert len(downloads) == 1                           # second view: from the cache

    r = client.post("/api/ss/apply/0?path=./alpha.zip", headers=LOCAL,
                    json={"proposed": PROPOSED, "fields": ["image"]})
    assert r.get_json()["applied"] == ["image"]
    assert len(downloads) == 1                           # applying did not download again
    game = etree.parse(str(gamelist)).getroot().find("game")
    assert game.findtext("image") == "./images/alpha-image.png"
    assert (gamelist.parent / "images" / "alpha-image.png").read_bytes()[:8] == PNG[:8]


def test_preview_unknown_bad_and_not_image(client, monkeypatch):
    assert client.get("/api/scrape/preview/" + "0" * 40, headers=LOCAL).status_code == 404
    assert client.get("/api/scrape/preview/../../etc", headers=LOCAL).status_code in (400, 404)
    monkeypatch.setattr(remote_cache, "fetch", lambda *a, **k: (b"<html>quota</html>", "text/html"))
    key = remote_cache.register("https://media.example/error.php")
    assert client.get("/api/scrape/preview/" + key, headers=LOCAL).status_code == 415
    assert remote_cache.get(key=key) is None             # an error page is never kept


def test_preview_cache_expires(monkeypatch):
    remote_cache.put("https://media.example/a.png", PNG)
    assert remote_cache.get("https://media.example/a.png") == PNG
    path = os.path.join(remote_cache.CACHE_DIR, remote_cache.key_for("https://media.example/a.png"))
    old = os.path.getmtime(path) - remote_cache.CACHE_TTL - 10
    os.utime(path, (old, old))
    assert remote_cache.get("https://media.example/a.png") is None
    assert remote_cache.prune_cache() == 1


def test_only_selected_fields_are_applied(gamelist, client, downloads):
    """Thumbnail, bezel and Pad2Key used to be applied even when not selected."""
    r = client.post("/api/ss/apply/0?path=./alpha.zip", headers=LOCAL,
                    json={"proposed": PROPOSED, "fields": ["desc"]})
    assert r.get_json()["applied"] == ["desc"]
    game = etree.parse(str(gamelist)).getroot().find("game")
    assert game.findtext("thumbnail") is None and game.findtext("bezel") is None
    assert downloads == []


def test_preset_missing_fills_gaps_only(gamelist, client, downloads):
    tree, game = xml_store.get_game_elem(0)
    etree.SubElement(game, "genre").text = "Puzzle"
    xml_store.save_xml(tree)
    r = client.post("/api/adb/apply/0?path=./alpha.zip", headers=LOCAL,
                    json={"proposed": PROPOSED, "preset": "missing"})
    data = r.get_json()
    assert set(data["applied"]) == {"desc", "rating", "releasedate", "image", "thumbnail", "bezel", "video"}
    game = etree.parse(str(gamelist)).getroot().find("game")
    assert game.findtext("genre") == "Puzzle"            # existing value kept
    assert game.findtext("rating") == "0.8"              # normalized like a manual edit


def test_empty_proposed_value_never_erases(gamelist, client):
    tree, game = xml_store.get_game_elem(0)
    etree.SubElement(game, "developer").text = "Kept"
    xml_store.save_xml(tree)
    client.post("/api/ss/apply/0?path=./alpha.zip", headers=LOCAL,
                json={"proposed": PROPOSED, "fields": ["developer", "desc"]})
    game = etree.parse(str(gamelist)).getroot().find("game")
    assert game.findtext("developer") == "Kept"


def test_invalid_rating_reported_not_written(gamelist, client):
    r = client.post("/api/steam/apply/0?path=./alpha.zip", headers=LOCAL,
                    json={"proposed": {"rating": "7"}, "fields": ["rating"]})
    data = r.get_json()
    assert data["applied"] == [] and len(data["errors"]) == 1


def test_apply_needs_fields_or_preset(gamelist, client):
    r = client.post("/api/ss/apply/0?path=./alpha.zip", headers=LOCAL, json={"proposed": PROPOSED})
    assert r.status_code == 400
    r = client.post("/api/ss/apply/0?path=./alpha.zip", headers=LOCAL,
                    json={"proposed": PROPOSED, "preset": "bogus"})
    assert r.status_code == 400


class FakeResponse:
    def __init__(self, size):
        self.size = size

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        sent = 0
        while sent < self.size:
            step = min(n, self.size - sent)
            sent += step
            yield b"\x00" * step


def test_steam_video_falls_back_to_480p(gamelist, client, monkeypatch):
    monkeypatch.setattr(steam, "MAX_DOWNLOAD_BYTES", 1000)
    sizes = {"https://cdn.example/movie_max.mp4": 5000, "https://cdn.example/movie480.mp4": 600}
    monkeypatch.setattr(steam.requests, "get", lambda url, **k: FakeResponse(sizes[url]))
    proposed = {"medias": {"video": {"url": "https://cdn.example/movie_max.mp4",
                                     "fallback_url": "https://cdn.example/movie480.mp4"}}}
    r = client.post("/api/steam/apply/0?path=./alpha.zip", headers=LOCAL,
                    json={"proposed": proposed, "fields": ["video"]})
    assert r.get_json()["applied"] == ["video"]
    video = gamelist.parent / "videos" / "alpha-video.mp4"
    assert video.stat().st_size == 600
    assert not list((gamelist.parent / "videos").glob("*.part"))


def test_default_scraper_per_system(gamelist, client):
    assert default_scraper("mame") == "arcadeitalia"
    assert default_scraper("FBNeo") == "arcadeitalia"
    assert default_scraper("steam") == "steam"
    assert default_scraper("snes") == "screenscraper"
    assert default_scraper("") == "screenscraper"
    system = client.get("/api/games", headers=LOCAL).get_json()["system"]
    assert system["scraper"] in ("screenscraper", "arcadeitalia", "steam")
