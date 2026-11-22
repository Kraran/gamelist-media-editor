"""ScreenScraper media per type (type, region, on/off) and the wheel, titleshot and music media."""
import json
from pathlib import Path

import pytest
from lxml import etree

from gme import media, mediacheck, xml_store
from gme.scrapers import compare, ss, ss_limits
from conftest import LOCAL, picture
from test_ss_parallel import (ROMS, FakeSS, Resp, big_gamelist,  # noqa: F401 (fixture)
                              run_all, start)

MEDIA_URL = "https://neoclone.screenscraper.fr/api2/mediaJeu.php?media={type}&region={region}&game={rom}"
# What the game has on ScreenScraper: several types, several regions
AVAILABLE = [("ss", "wor"), ("sstitle", "wor"), ("box-2D", "eu"), ("box-2D", "us"), ("box-3D", "eu"),
             ("box-3D", "jp"), ("wheel", "wor"), ("wheel-hd", "wor"), ("wheel-hd", "jp"), ("wheel-carbon", "wor"),
             ("screenmarquee", "wor"), ("mixrbv1", "wor"), ("mixrbv2", "wor"), ("support-2D", "eu"),
             ("box-2D-back", "eu"), ("fanart", ""), ("maps", ""), ("bezel-16-9", "wor"), ("bezel-4-3", "wor"),
             ("video-normalized", ""), ("video", ""), ("manuel", "eu")]
# What earlier versions always asked for (nothing may change for existing users)
HISTORICAL = {"image": ["ss"], "video": ["video-normalized"], "marquee": ["wheel-hd"], "manual": ["manuel"],
              "boxback": ["box-2D-back"], "boxart": ["box-3D"], "cartridge": ["support-2D"],
              "fanart": ["fanart"], "mix": ["mixrbv2"], "map": ["maps"], "thumbnail": ["box-2D"],
              "bezel": ["bezel-16-9"]}


def jeu(rom="game0.zip"):
    return {"id": "1", "noms": [{"region": "wor", "text": rom[:-4].title()}],
            "developpeur": {"text": "Studio"},
            "medias": [{"type": t, "region": r, "url": MEDIA_URL.format(type=t, region=r, rom=rom)}
                       for t, r in AVAILABLE]}


def picked(parsed, field):
    info = parsed["medias"].get(field)
    if not info:
        return None
    query = dict(p.split("=") for p in info["url"].split("?", 1)[1].split("&"))
    return query["media"], query["region"]


class RichSS(FakeSS):
    """FakeSS whose games have every kind of media."""

    def answer(self, path, params, rom):
        if path.endswith("jeuInfos.php") and rom:
            user = {"id": "member", "maxthreads": str(self.maxthreads), "maxrequestspermin": "60000",
                    "requeststoday": "1", "maxrequestsperday": "20000"}
            return Resp(payload={"header": {"success": "true"}, "response": {"ssuser": user, "jeu": jeu(rom)}})
        return super().answer(path, params, rom)


@pytest.fixture
def rich_ss(monkeypatch, tmp_path, ss_config_file):
    from gme import remote_cache
    import requests

    def make(config=None, maxthreads=2):
        server = RichSS(maxthreads=maxthreads, delay=0.01)
        monkeypatch.setattr(requests, "get", server.get)
        monkeypatch.setattr(remote_cache, "CACHE_DIR", str(tmp_path / "remote-cache"))
        ss_config_file.write_text(json.dumps({"ssid": "member", "sspassword": "pw", **(config or {})}),
                                  encoding="utf-8")
        return server
    return make


@pytest.fixture
def gate_slots(monkeypatch):
    """Every request that takes a ScreenScraper slot (API and media downloads)."""
    taken = []
    original = ss_limits.GATE.slot

    def slot(*args, **kwargs):
        taken.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(ss_limits.GATE, "slot", slot)
    return taken


def tags(xml, rom="game0.zip"):
    for game in etree.parse(str(xml)).getroot().findall("game"):
        if game.findtext("path") == f"./{rom}":
            return {child.tag: child.text for child in game}
    raise KeyError(rom)


# --- Settings -----------------------------------------------------------------

def test_defaults_ask_for_exactly_what_earlier_versions_did(ss_config_file):
    cfg = ss.load_ss_config()
    assert ss.ss_media_pref(cfg) == HISTORICAL
    assert ss.ss_disabled_media(cfg) == ["titleshot", "wheel"]
    # An old config file with the three former choices keeps them
    ss_config_file.write_text(json.dumps({"media_types": {"image": "sstitle", "boxart": "box-2D", "mix": "mixrbv1"}}))
    old = ss.ss_media_pref(ss.load_ss_config())
    assert old == {**HISTORICAL, "image": ["sstitle"], "boxart": ["box-2D"], "mix": ["mixrbv1"]}


def test_every_choice_and_default_is_consistent():
    assert set(ss.SS_MEDIA_CHOICES) == set(ss.SS_MEDIA_DEFAULTS)
    assert set(ss.SS_MEDIA_CHOICES) <= set(xml_store.MEDIA_DIRS)
    for field, default in ss.SS_MEDIA_DEFAULTS.items():
        assert default in ss.SS_MEDIA_CHOICES[field], field
    assert set(ss.SS_MEDIA_CHOICES) <= set(compare.MEDIA_KEYS)


def test_settings_route_saves_merges_and_refuses_bad_values(client, ss_config_file):
    r = client.post("/api/ss/config", headers=LOCAL, json={
        "media_types": {"marquee": "screenmarquee", "wheel": "WHEEL-HD", "image": "nonsense", "path": "ss"},
        "media_enabled": {"wheel": True, "video": False, "boxart": "yes"},
        "media_regions": {"boxart": "JP", "image": "mars", "nosuch": "eu"}})
    assert r.status_code == 200
    cfg = client.get("/api/ss/config").get_json()
    assert cfg["media_types"]["marquee"] == "screenmarquee"
    assert cfg["media_types"]["wheel"] == "wheel-hd"
    assert cfg["media_types"]["image"] == "ss"                  # refused: default kept
    assert cfg["media_enabled"]["wheel"] is True and cfg["media_enabled"]["video"] is False
    assert cfg["media_enabled"]["boxart"] is True               # not a bool: unchanged
    assert cfg["media_regions"] == {"boxart": "jp"}
    assert cfg["media_choices"]["wheel"] == list(ss.SS_MEDIA_CHOICES["wheel"])
    assert "jp" in cfg["media_region_choices"]
    # A partial save keeps the rest; "" goes back to the preferred region
    client.post("/api/ss/config", headers=LOCAL, json={"media_types": {"bezel": "bezel-4-3"},
                                                       "media_regions": {"boxart": ""}})
    cfg = client.get("/api/ss/config").get_json()
    assert cfg["media_types"]["marquee"] == "screenmarquee" and cfg["media_types"]["bezel"] == "bezel-4-3"
    assert cfg["media_regions"] == {} and cfg["media_enabled"]["wheel"] is True
    saved = json.loads(ss_config_file.read_text(encoding="utf-8"))
    assert "devpassword" not in saved and saved["media_enabled"]["video"] is False


# --- What ScreenScraper proposes ------------------------------------------------

def test_the_chosen_type_and_region_are_picked():
    cfg = {"media_types": {"marquee": "screenmarquee", "wheel": "wheel-carbon", "boxart": "box-2D",
                           "bezel": "bezel-4-3", "video": "video"},
           "media_enabled": {"wheel": True, "titleshot": True},
           "media_regions": {"boxart": "us", "marquee": "jp"}}
    parsed = ss.parse_ss_game(jeu(), "fr", ss.ss_media_pref(cfg), ss.normalize_media_regions(cfg["media_regions"]),
                              ss.ss_disabled_media(cfg))
    assert picked(parsed, "marquee") == ("screenmarquee", "wor")    # no jp one: another region
    assert picked(parsed, "wheel") == ("wheel-carbon", "wor")
    assert picked(parsed, "titleshot") == ("sstitle", "wor")
    assert picked(parsed, "boxart") == ("box-2D", "us")             # region asked first
    assert picked(parsed, "thumbnail") == ("box-2D", "eu")          # preferred region order
    assert picked(parsed, "bezel") == ("bezel-4-3", "wor")
    assert picked(parsed, "video") == ("video", "")
    assert parsed["disabled_media"] == []


def test_no_fallback_to_another_kind_of_artwork():
    cfg = {"media_types": {"cartridge": "support-texture"}}
    parsed = ss.parse_ss_game(jeu(), "fr", ss.ss_media_pref(cfg))
    assert "cartridge" not in parsed["medias"]


def test_disabled_media_are_neither_proposed_nor_listed():
    cfg = {"media_enabled": {"video": False, "fanart": False}}
    parsed = ss.parse_ss_game(jeu(), "fr", ss.ss_media_pref(cfg), {}, ss.ss_disabled_media(cfg))
    assert "video" not in parsed["medias"] and "wheel" not in parsed["medias"]
    keys = [r["key"] for r in compare.compare_rows(parsed, {}, previews=False)]
    assert not {"video", "fanart", "wheel", "titleshot"} & set(keys)
    assert {"image", "marquee", "boxart"} <= set(keys)
    # Another source (no disabled list) still shows every row
    keys = [r["key"] for r in compare.compare_rows({"medias": {}}, {}, previews=False)]
    assert {"wheel", "titleshot", "video"} <= set(keys)


def test_scrape_and_apply_wheel_and_titleshot_through_the_gate(big_gamelist, client, rich_ss, gate_slots):
    server = rich_ss({"media_enabled": {"wheel": True, "titleshot": True}, "media_types": {"wheel": "wheel-hd"},
                      "media_regions": {"wheel": "jp"}})
    data = client.post("/api/ss/scrape/0?path=./game0.zip", headers=LOCAL, json={}).get_json()
    rows = {r["key"]: r for r in data["compare"]}
    assert rows["wheel"]["status"] == "new" and rows["wheel"]["media_type"] == "wheel-hd"
    assert rows["titleshot"]["status"] == "new" and rows["titleshot"]["media_type"] == "sstitle"
    assert "music" not in rows                                     # ScreenScraper has no game music
    r = client.post("/api/ss/apply/0?path=./game0.zip", headers=LOCAL,
                    json={"proposed": data["proposed"], "fields": ["wheel", "titleshot", "marquee"]}).get_json()
    assert sorted(r["applied"]) == ["marquee", "titleshot", "wheel"], r
    written = tags(big_gamelist)
    assert written["wheel"] == "./images/game0-wheel.png"
    assert written["titleshot"] == "./images/game0-titleshot.png"
    assert written["marquee"] == "./images/game0-marquee.png"
    folder = big_gamelist.parent
    assert (folder / "images" / "game0-wheel.png").is_file() and (folder / "images" / "game0-titleshot.png").is_file()
    assert "media=wheel-hd&region=jp" in data["proposed"]["medias"]["wheel"]["url"]
    assert len([c for c in server.calls if c[1] == "mediaJeu.php"]) == 3
    # Every request (lookup + each media download) took a ScreenScraper slot
    assert len(gate_slots) == len(server.calls) >= 1 + 3
    assert server.peak <= 2


def test_batch_fills_the_new_media_without_exceeding_maxthreads(big_gamelist, client, rich_ss):
    server = rich_ss({"media_enabled": {"wheel": True, "titleshot": True}}, maxthreads=2)
    run_all(client, start(client, fields=("wheel", "titleshot")))
    for rom in ROMS:
        written = tags(big_gamelist, rom)
        assert written["wheel"] == f"./images/{rom[:-4]}-wheel.png"
        assert written["titleshot"] == f"./images/{rom[:-4]}-titleshot.png"
    assert server.peak <= 2


def test_batch_with_defaults_writes_no_new_media(big_gamelist, client, rich_ss):
    rich_ss()
    run_all(client, start(client, fields=("wheel", "titleshot", "image")))
    written = tags(big_gamelist)
    assert "wheel" not in written and "titleshot" not in written and written["image"]


# --- Music and the new tags in the editor -----------------------------------------

MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 64
OGG = b"OggS\x00\x02" + b"\x00" * 64


@pytest.mark.parametrize("head, ext", [(MP3, ".mp3"), (b"\xff\xfb\x90\x00" + b"\x00" * 20, ".mp3"), (OGG, ".ogg"),
                                       (b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 20, ".wav"),
                                       (b"fLaC\x00\x00\x00\x22" + b"\x00" * 20, ".flac"),
                                       (picture(fmt="JPEG"), ".jpg"), (b"RIFF\x24\x00\x00\x00WEBPVP8 ", ".webp")])
def test_audio_files_are_recognised(head, ext):
    assert media.ext_from_magic(head[:64]) == ext


def test_music_is_never_checked_as_an_image():
    assert not media.must_check_image("music", MP3)
    assert media.must_check_image("wheel", picture())
    assert media.default_ext_for_field("music") == ".mp3"


def test_upload_music_writes_the_tag_in_music_folder_and_serves_audio(gamelist, client):
    r = client.post("/api/upload/0/music?path=./alpha.zip", headers=LOCAL,
                    data={"file": (__import__("io").BytesIO(OGG), "theme.bin")}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["path"] == "./music/alpha-music.ogg"
    assert (gamelist.parent / "music" / "alpha-music.ogg").read_bytes() == OGG
    game = etree.parse(str(gamelist)).getroot().find("game")
    assert game.findtext("music") == "./music/alpha-music.ogg"
    served = client.get("/media/music/alpha-music.ogg")
    assert served.status_code == 200 and served.mimetype == "audio/ogg"
    games = client.get("/api/games").get_json()["games"]
    assert games[0]["music"] == "./music/alpha-music.ogg"
    r = client.post("/api/clear/0/music?path=./alpha.zip", headers=LOCAL)
    assert r.status_code == 200
    assert etree.parse(str(gamelist)).getroot().find("game").find("music") is None


def test_wheel_titleshot_music_are_listed_and_checked(gamelist, client):
    folder = Path(gamelist).parent
    (folder / "images").mkdir()
    (folder / "music").mkdir()
    (folder / "images" / "alpha-wheel.png").write_bytes(picture())
    (folder / "music" / "alpha-music.mp3").write_bytes(MP3)
    (folder / "music" / "orphan.mp3").write_bytes(MP3)
    xml = gamelist.read_text(encoding="utf-8").replace(
        "<name>Alpha</name>", "<name>Alpha</name><wheel>./images/alpha-wheel.png</wheel>"
        "<titleshot>./images/gone.png</titleshot><music>./music/alpha-music.mp3</music>")
    gamelist.write_text(xml, encoding="utf-8")
    xml_store.invalidate_cache()
    alpha = client.get("/api/games").get_json()["games"][0]
    assert alpha["wheel"] == "./images/alpha-wheel.png" and alpha["titleshot"] == "./images/gone.png"
    report = mediacheck.scan()
    orphans = [o["path"] if isinstance(o, dict) else o for o in report["orphans"]]
    assert any(p.endswith("music/orphan.mp3") for p in orphans)
    assert not any(p.endswith("alpha-music.mp3") for p in orphans)
    assert [b["tag"] for b in report["broken"]] == ["titleshot"]
