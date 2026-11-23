"""ES-DE layout: gamelists in ES-DE/gamelists, media found by name in downloaded_media,
ROMs in the ROMDirectory. Generated trees only (tests/esde_tree.py)."""
import io
import os

import pytest
from lxml import etree

from gme import esde, mediacheck, overview, remote_cache, romcheck, xml_store
from gme.scrapers.compare import compare_rows, current_from_game
from tests.conftest import LOCAL
from tests.esde_tree import make_esde, picture


@pytest.fixture
def tree(tmp_path):
    paths = make_esde(tmp_path)
    xml_store.set_gamelist_path(paths["snes_xml"])
    yield paths
    xml_store.close_gamelist()
    overview.reset()


def on_disk(paths, key="snes_xml"):
    return {g.findtext("path"): g for g in etree.parse(paths[key]).getroot().findall("game")}


def index_of(path):
    return xml_store.find_game_index_by_path(path)[0]


def upload(client, path, field, data, name="new.png"):
    r = client.post(f"/api/upload/{index_of(path)}/{field}?path={path}", headers=LOCAL,
                    data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


# --- detection ---------------------------------------------------------------------

def test_desktop_layout_from_settings(tree):
    layout = xml_store.PROFILE
    assert layout is not None and layout.system == "snes"
    assert layout.rom_dir == os.path.join(tree["roms"], "snes")             # ~/Games/ROMs/snes
    assert layout.media_dir == os.path.join(tree["home"], "downloaded_media", "snes")
    assert not layout.portable
    assert xml_store.rom_dir() == layout.rom_dir


def test_portable_layout_defaults(tmp_path):
    paths = make_esde(tmp_path, portable=True)
    layout = esde.layout_for_gamelist(paths["snes_xml"])
    assert layout.portable
    assert layout.home == os.path.join(str(tmp_path), "ES-DE", "ES-DE")
    assert layout.rom_dir == os.path.join(str(tmp_path), "ES-DE", "ROMs", "snes")  # empty setting: ~/ROMs
    assert layout.media_dir == os.path.join(layout.home, "downloaded_media", "snes")


def test_custom_media_directory_with_espath(tmp_path):
    paths = make_esde(tmp_path, media_setting="%ESPATH%/media/ES-DE")
    layout = esde.layout_for_gamelist(paths["snes_xml"])
    assert layout.media_dir == os.path.join(paths["parent"], "media", "ES-DE", "snes")
    assert os.path.isfile(os.path.join(layout.media_dir, "covers", "Alpha (Europe).png"))


def test_custom_systems_rom_path(tmp_path):
    paths = make_esde(tmp_path)
    other = os.path.join(str(tmp_path), "elsewhere", "snes")
    os.makedirs(other)
    os.makedirs(os.path.join(paths["home"], "custom_systems"))
    with open(os.path.join(paths["home"], "custom_systems", "es_systems.xml"), "w") as f:
        f.write(f"<systemList><system><name>snes</name><path>{other}</path></system></systemList>")
    assert esde.layout_for_gamelist(paths["snes_xml"]).rom_dir == os.path.normpath(other)


@pytest.mark.parametrize("given", ["home", "parent", "settings", "gamelists", "system", "xml"])
def test_find_home_from_any_entry_point(tmp_path, given):
    paths = make_esde(tmp_path, portable=True)
    home = paths["home"]
    path = {"home": home, "parent": paths["parent"], "settings": os.path.join(home, "settings", "es_settings.xml"),
            "gamelists": os.path.join(home, "gamelists"), "system": os.path.dirname(paths["snes_xml"]),
            "xml": paths["snes_xml"]}[given]
    assert esde.find_home(path) == home


def test_classic_layouts_are_not_esde(tmp_path):
    # RetroBat's legacy ES keeps gamelists in .emulationstation/gamelists, with media tags
    legacy = tmp_path / "emulationstation" / ".emulationstation" / "gamelists" / "snes"
    legacy.mkdir(parents=True)
    (legacy / "gamelist.xml").write_text("<gameList><game><path>./a.zip</path></game></gameList>")
    assert esde.layout_for_gamelist(str(legacy / "gamelist.xml")) is None
    roms = tmp_path / "roms" / "snes"
    roms.mkdir(parents=True)
    (roms / "gamelist.xml").write_text("<gameList><game><path>./a.zip</path><image>./images/a.png</image></game></gameList>")
    xml_store.set_gamelist_path(str(roms / "gamelist.xml"))
    try:
        assert xml_store.PROFILE is None and xml_store.rom_dir() == str(roms)
        assert xml_store.load_xml().getroot().find("game").findtext("image") == "./images/a.png"
        assert xml_store.media_fields() == tuple(xml_store.MEDIA_DIRS)
    finally:
        xml_store.close_gamelist()


def test_settings_file_without_root_element(tmp_path):
    path = tmp_path / "es_settings.xml"
    path.write_text('<?xml version="1.0"?>\n<string name="ROMDirectory" value="D:\\Games &amp; ROMs" />\n'
                    '<string name="MediaDirectory" value="" />\n')
    assert esde.read_settings(str(path)) == {"ROMDirectory": "D:\\Games & ROMs", "MediaDirectory": ""}


# --- media by name -----------------------------------------------------------------

def test_rom_stem_keeps_sub_folders_and_inner_dots(tree):
    layout = xml_store.PROFILE
    assert esde.rom_stem(layout, "./Multi/Bravo/Bravo.m3u") == "Multi/Bravo/Bravo"
    assert esde.rom_stem(layout, "./H.E.R.O..sfc") == "H.E.R.O."
    assert esde.rom_stem(layout, os.path.join(layout.rom_dir, "Charlie.zip")) == "Charlie"
    assert esde.rom_stem(layout, "../escape.zip") is None
    os.makedirs(os.path.join(layout.rom_dir, "dig.scummvm"))         # a directory interpreted as a file
    assert esde.rom_stem(layout, "./dig.scummvm") == "dig.scummvm"


def test_media_are_shown_from_downloaded_media(tree, client):
    data = client.get("/api/games", headers=LOCAL).get_json()
    games = {g["path"]: g for g in data["games"]}
    alpha = games["./Alpha (Europe).sfc"]
    assert alpha["thumbnail"] == "@media/covers/Alpha (Europe).png"
    assert alpha["image"] == "@media/screenshots/Alpha (Europe).jpg"
    assert alpha["marquee"] == "@media/marquees/Alpha (Europe).png"
    assert games["./Multi/Bravo/Bravo.m3u"]["video"] == "@media/videos/Multi/Bravo/Bravo.mp4"
    assert "image" not in games["./Multi/Bravo/Bravo.m3u"]       # its legacy <image> tag is ignored, as ES-DE does
    profile = data["system"]["profile"]
    assert profile["kind"] == "esde" and "wheel" not in profile["fields"]
    r = client.get("/media/@media/covers/Alpha%20(Europe).png", headers=LOCAL)
    assert r.status_code == 200 and r.data[:4] == b"\x89PNG"
    assert client.get("/api/thumb?path=@media/covers/Alpha%20(Europe).png", headers=LOCAL).status_code == 200
    assert client.get("/media/@media/../settings/es_settings.xml", headers=LOCAL).status_code == 404


def test_extension_order_follows_esde(tree):
    snes = tree["snes_media"]
    with open(os.path.join(snes, "covers", "Charlie.jpg"), "wb") as f:
        f.write(picture(fmt="JPEG"))
    with open(os.path.join(snes, "covers", "Charlie.png"), "wb") as f:
        f.write(picture())
    xml_store.invalidate_cache()
    game = xml_store.load_xml().getroot().findall("game")[2]
    assert game.findtext("thumbnail") == "@media/covers/Charlie.png"


def test_saving_never_writes_media_tags_and_keeps_unknown_ones(tree, client):
    i = index_of("./Alpha (Europe).sfc")
    r = client.post(f"/api/game/{i}?path=./Alpha%20(Europe).sfc", headers=LOCAL, json={"name": "Alpha Renamed"})
    assert r.status_code == 200, r.get_json()
    text = open(tree["snes_xml"], encoding="utf-8").read()
    assert "@media" not in text and "gme-legacy" not in text
    assert "<thumbnail>" not in text and "<marquee>" not in text
    games = on_disk(tree)
    alpha = games["./Alpha (Europe).sfc"]
    assert alpha.findtext("name") == "Alpha Renamed"
    assert alpha.findtext("altemulator") == "Snes9x - Current" and alpha.findtext("playcount") == "3"
    assert games["./Multi/Bravo/Bravo.m3u"].findtext("image") == "./images/bravo-legacy.png"
    assert etree.parse(tree["snes_xml"]).getroot().find("folder").findtext("name") == "Multi-disc"
    # the editor still sees the media after the save
    assert xml_store.load_xml().getroot().findall("game")[0].findtext("thumbnail") == "@media/covers/Alpha (Europe).png"


def test_upload_writes_the_file_esde_looks_for(tree, client, trashed):
    out = upload(client, "./Charlie.zip", "thumbnail", picture())
    assert out["path"] == "@media/covers/Charlie.png"
    assert os.path.isfile(os.path.join(tree["snes_media"], "covers", "Charlie.png"))
    assert "<thumbnail>" not in open(tree["snes_xml"], encoding="utf-8").read()
    # nested ROM: same sub-folders under the media type folder
    out = upload(client, "./Multi/Bravo/Bravo.m3u", "manual", b"%PDF-1.4 manual", name="m.pdf")
    assert out["path"] == "@media/manuals/Multi/Bravo/Bravo.pdf"
    assert os.path.isfile(os.path.join(tree["snes_media"], "manuals", "Multi", "Bravo", "Bravo.pdf"))
    assert trashed == []


def test_replacing_with_another_format_removes_the_old_file(tree, client, trashed):
    shot = os.path.join(tree["snes_media"], "screenshots", "Alpha (Europe).jpg")
    out = upload(client, "./Alpha (Europe).sfc", "image", picture())
    assert out["path"] == "@media/screenshots/Alpha (Europe).png"
    assert not os.path.exists(shot) and trashed == [shot]


def test_unsupported_media_are_refused(tree, client):
    i = index_of("./Charlie.zip")
    r = client.post(f"/api/upload/{i}/wheel?path=./Charlie.zip", headers=LOCAL,
                    data={"file": (io.BytesIO(picture()), "w.png")}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_removing_a_media_moves_its_file_to_the_recycle_bin(tree, client, trashed):
    cover = os.path.join(tree["snes_media"], "covers", "Alpha (Europe).png")
    i = index_of("./Alpha (Europe).sfc")
    r = client.post(f"/api/clear/{i}/thumbnail?path=./Alpha%20(Europe).sfc", headers=LOCAL)
    assert r.status_code == 200 and r.get_json()["trashed"] == 1
    assert trashed == [cover]
    xml_store.invalidate_cache()
    assert xml_store.load_xml().getroot().findall("game")[0].findtext("thumbnail") is None


def test_bulk_clear_media_removes_the_files(tree, client, trashed):
    r = client.post("/api/bulk", headers=LOCAL, json={"paths": ["./Alpha (Europe).sfc"],
                                                     "op": {"kind": "clear_media", "fields": ["marquee"]}})
    assert r.status_code == 200, r.get_json()
    assert trashed == [os.path.join(tree["snes_media"], "marquees", "Alpha (Europe).png")]


# --- scrapes -------------------------------------------------------------------------

def test_scrape_writes_media_by_name_and_skips_what_esde_has_not(tree, monkeypatch, client):
    monkeypatch.setattr(remote_cache, "get", lambda url: picture((1, 150, 99)))
    proposed = {"developer": "Studio", "medias": {f: {"url": f"https://x.test/{f}.png"} for f in
                                                 ("thumbnail", "boxart", "wheel", "map", "bezel", "fanart")}}
    current = current_from_game(xml_store.load_xml().getroot().findall("game")[2])
    keys = [r["key"] for r in compare_rows(proposed, current, previews=False)]
    assert "thumbnail" in keys and not {"wheel", "map", "bezel", "pad2key", "music"} & set(keys)
    i = index_of("./Charlie.zip")
    r = client.post(f"/api/ss/apply/{i}?path=./Charlie.zip", headers=LOCAL,
                    json={"proposed": proposed, "fields": ["developer", "thumbnail", "boxart", "wheel", "fanart"]})
    assert r.status_code == 200, r.get_json()
    assert sorted(r.get_json()["applied"]) == ["boxart", "developer", "fanart", "thumbnail"]
    for folder in ("covers", "3dboxes", "fanart"):
        assert os.path.isfile(os.path.join(tree["snes_media"], folder, "Charlie.png"))
    assert not os.path.exists(os.path.join(tree["snes_media"], "wheel"))
    charlie = on_disk(tree)["./Charlie.zip"]
    assert charlie.findtext("developer") == "Studio"
    assert [c.tag for c in charlie] == ["path", "name", "developer"]


def test_preset_missing_sees_existing_media(tree):
    game = xml_store.load_xml().getroot().findall("game")[0]          # Alpha has a cover
    proposed = {"medias": {"thumbnail": {"url": "https://x.test/c.png"}, "fanart": {"url": "https://x.test/f.png"}}}
    rows = {r["key"]: r["status"] for r in compare_rows(proposed, current_from_game(game), previews=False)}
    assert rows["thumbnail"] == "replace" and rows["fanart"] == "new"


def test_rom_path_resolves_in_the_rom_directory(tree):
    full = xml_store.resolve_under_base("./Alpha (Europe).sfc")
    assert full == os.path.join(tree["roms"], "snes", "Alpha (Europe).sfc") and os.path.isfile(full)


# --- checks and overview -------------------------------------------------------------------

def test_rom_check_uses_the_rom_directory(tree):
    report = romcheck.scan()
    assert report["missing"] == []
    assert [u["path"] for u in report["unlisted"]] == ["./Delta.sfc"]


def test_media_check_keeps_media_of_roms_esde_shows(tree):
    report = mediacheck.scan()
    orphans = [o["path"] for o in report["orphans"]]
    assert orphans == ["@media/covers/Ghost.png"]                 # Delta.png: its ROM exists; custom/ is ES-DE's
    assert report["broken"] == []


def test_media_check_deletes_a_confirmed_orphan(tree, client, trashed):
    r = client.post("/api/check-media/apply", headers=LOCAL, json={"delete": ["@media/covers/Ghost.png"]})
    assert r.status_code == 200 and r.get_json()["deleted"] == 1
    assert trashed == [os.path.join(tree["snes_media"], "covers", "Ghost.png")]


def test_stats_count_media_found_by_name(tree, client):
    data = client.get("/api/stats", headers=LOCAL).get_json()
    media = {m["field"]: m for m in data["media"]}
    assert "wheel" not in media
    assert media["thumbnail"]["present"] == 1 and media["thumbnail"]["missing"] == 2


@pytest.mark.parametrize("given", ["home", "settings", "gamelists"])
def test_overview_of_an_esde_installation(tmp_path, client, given):
    paths = make_esde(tmp_path)
    home = paths["home"]
    path = {"home": home, "settings": os.path.join(home, "settings", "es_settings.xml"),
            "gamelists": os.path.join(home, "gamelists")}[given]
    assert overview.resolve_root(path) == os.path.join(home, "gamelists")
    overview.reset()
    r = client.post("/api/overview/scan", headers=LOCAL, json={"path": path})
    assert r.status_code == 200, r.get_json()
    assert overview.wait(10)
    systems = {s["folder"]: s for s in client.get("/api/overview", headers=LOCAL).get_json()["systems"]}
    assert set(systems) == {"snes", "megadrive"}                   # not ES-DE's CLEANUP folder
    snes = systems["snes"]
    assert snes["profile"] == "esde" and snes["games"] == 3
    assert snes["roms_missing"] == 0 and snes["roms_unlisted"] == 1
    assert snes["media"]["thumbnail"] == {"present": 1, "broken": 0, "missing": 2}
    assert snes["media"]["video"]["present"] == 1 and "wheel" not in snes["media"]
    assert systems["megadrive"]["media"]["thumbnail"]["present"] == 1
    overview.reset()


def test_open_settings_file_says_where_the_gamelists_are(tmp_path, client):
    paths = make_esde(tmp_path)
    r = client.post("/api/open-gamelist", headers=LOCAL,
                    json={"path": os.path.join(paths["home"], "settings", "es_settings.xml")})
    assert r.status_code == 400 and r.get_json()["code"] == "esde_home"
    browse = client.get("/api/browse", headers=LOCAL, query_string={"path": paths["home"]}).get_json()
    assert browse["esde"]["home"] == paths["home"]
    r = client.post("/api/open-gamelist", headers=LOCAL, json={"path": paths["md_xml"]})
    assert r.status_code == 200 and r.get_json()["system"]["profile"]["kind"] == "esde"
    xml_store.close_gamelist()


def test_system_ids_of_esde_names():
    from gme.systems import SS_SYSTEM_MAP
    assert SS_SYSTEM_MAP["genesis"] == 1 and SS_SYSTEM_MAP["sg-1000"] == 109 and SS_SYSTEM_MAP["tg-cd"] == 114


def test_deleting_a_game_removes_its_rom_and_its_media(tree, client, trashed):
    i = index_of("./Alpha (Europe).sfc")
    plan = client.post(f"/api/delete-game/{i}/preview?path=./Alpha%20(Europe).sfc", headers=LOCAL, json={}).get_json()
    files = [f["path"] for f in plan["files"]]
    media = sorted(m["path"] for m in plan["media"])
    assert files == ["./Alpha (Europe).sfc"]
    assert media == ["@media/covers/Alpha (Europe).png", "@media/marquees/Alpha (Europe).png",
                     "@media/screenshots/Alpha (Europe).jpg"]


def test_image_edit_keeps_the_media_name(tree, client):
    i = index_of("./Alpha (Europe).sfc")
    shots = os.path.join(tree["snes_media"], "screenshots")
    original = open(os.path.join(shots, "Alpha (Europe).jpg"), "rb").read()
    # "new" would make a copy ES-DE never shows: the edit takes the media's place
    r = client.post(f"/api/image-edit/{i}/image?path=./Alpha%20(Europe).sfc", headers=LOCAL,
                    json={"ops": {"format": "png"}, "mode": "new"})
    assert r.status_code == 200, r.get_json()
    out = r.get_json()
    assert out["path"] == "@media/screenshots/Alpha (Europe).png"
    assert os.listdir(shots) == ["Alpha (Europe).png"]
    assert "@media" not in open(tree["snes_xml"], encoding="utf-8").read()
    r = client.post("/api/image-edit/undo", headers=LOCAL, json={"id": out["undo"]})
    assert r.status_code == 200, r.get_json()
    assert os.listdir(shots) == ["Alpha (Europe).jpg"]
    assert open(os.path.join(shots, "Alpha (Europe).jpg"), "rb").read() == original


def test_actions_on_several_esde_systems(tmp_path, client, monkeypatch):
    from gme import batch_jobs, multibatch
    from gme.scrapers import ss_limits
    from gme.scrapers.compare import scrape_payload
    paths = make_esde(tmp_path)
    overview.reset()
    multibatch.reset()
    overview.start(os.path.join(paths["home"], "gamelists"))
    assert overview.wait(10)
    calls = []

    def scrape(game, body=None, system=None):
        calls.append(game.findtext("path"))
        proposed = {"developer": "Studio", "medias": {"thumbnail": {"url": "https://x.test/c.png"},
                                                      "wheel": {"url": "https://x.test/w.png"}}}
        return {"proposed": proposed, **scrape_payload(game, proposed)}, 200

    monkeypatch.setitem(batch_jobs.LOOKUPS, "screenscraper", scrape)
    monkeypatch.setattr(remote_cache, "get", lambda url: picture((3, 140, 70)))
    ss_limits.GATE.reset()
    try:
        r = client.post("/api/multibatch", headers=LOCAL, json={
            "systems": [paths["snes_xml"], paths["md_xml"]],
            "ops": {"scrape": {"mode": "missing", "fields": ["thumbnail", "wheel"]}}})
        assert r.status_code == 200, r.get_json()
        assert multibatch.wait(20)
        report = client.get("/api/multibatch", headers=LOCAL).get_json()
        assert report["state"] == "done", report
        # Alpha and Sonic already have a cover; a wheel is not an ES-DE media
        assert sorted(calls) == ["./Charlie.zip", "./Multi/Bravo/Bravo.m3u"]
        assert os.path.isfile(os.path.join(paths["snes_media"], "covers", "Charlie.png"))
        assert os.path.isfile(os.path.join(paths["snes_media"], "covers", "Multi", "Bravo", "Bravo.png"))
        assert "@media" not in open(paths["snes_xml"], encoding="utf-8").read()
    finally:
        multibatch.reset()
        overview.reset()
        ss_limits.GATE.reset()
        xml_store.close_gamelist()
