"""Actions on several systems: one system at a time, through the single-system routes."""
import os

import pytest
from lxml import etree

from gme import batch_jobs, multibatch, overview, remote_cache, xml_store
from gme.i18n import st
from gme.scrapers import ss_limits
from gme.scrapers.compare import scrape_payload
from tests.conftest import LOCAL, picture

SNES = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><genre>Platform</genre><image>./images/alpha.png</image></game>
  <game><path>./ghost.zip</path><name>Ghost</name><genre>Action</genre><marquee>./images/gone.png</marquee></game>
</gameList>
"""
NES = """<?xml version="1.0"?>
<gameList><game><path>./one.nes</path><name>One</name><genre>Puzzle</genre><developer>Dev</developer></game></gameList>
"""


def solid_png():
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (0, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def roms(tmp_path):
    root = tmp_path / "RetroBat" / "roms"
    snes = root / "snes"
    (snes / "images").mkdir(parents=True)
    (snes / "gamelist.xml").write_text(SNES, encoding="utf-8")
    for rom in ("alpha.zip", "extra.sfc"):
        (snes / rom).write_bytes(b"rom")
    (snes / "images" / "alpha.png").write_bytes(picture())
    (snes / "images" / "orphan.png").write_bytes(picture())
    nes = root / "nes"
    (nes / "images").mkdir(parents=True)
    (nes / "gamelist.xml").write_text(NES, encoding="utf-8")
    (nes / "one.nes").write_bytes(b"rom")
    (root / "broken").mkdir()
    (root / "broken" / "gamelist.xml").write_text("<gameList><game>", encoding="utf-8")
    overview.reset()
    multibatch.reset()
    overview.start(str(root))
    overview.wait(10)
    yield root
    multibatch.reset()
    overview.reset()
    xml_store.close_gamelist()


@pytest.fixture
def source(monkeypatch):
    calls = []

    def scrape(game, body=None, system=None):
        calls.append((xml_store.BASE_DIR, game.findtext("path")))
        proposed = {"developer": "Studio " + game.findtext("name")}
        return {"proposed": proposed, **scrape_payload(game, proposed)}, 200

    monkeypatch.setitem(batch_jobs.LOOKUPS, "screenscraper", scrape)
    monkeypatch.setattr(remote_cache, "fetch", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    ss_limits.GATE.reset()
    yield calls
    ss_limits.GATE.reset()


def xml_of(root, folder):
    return str(root / folder / "gamelist.xml")


def run(client, root, folders, ops, **extra):
    response = client.post("/api/multibatch", headers=LOCAL, json={
        "systems": [xml_of(root, f) for f in folders], "ops": ops, **extra})
    assert response.status_code == 200, response.get_json()
    assert multibatch.wait(20)
    return client.get("/api/multibatch", headers=LOCAL).get_json()


def games(path):
    return {g.findtext("path"): g for g in etree.parse(str(path)).getroot().findall("game")}


def steps(report, folder):
    s = next(s for s in report["systems"] if s["folder"] == folder)
    return {x["op"]: x for x in s["steps"]}


def test_rom_and_media_checks_run_on_each_system_with_a_backup(roms, client):
    report = run(client, roms, ["snes", "nes"], {"roms": {"add": True, "remove": True}, "media": {"unlink": True}})
    assert report["state"] == "done"
    snes = games(roms / "snes" / "gamelist.xml")
    assert set(snes) == {"./alpha.zip", "./extra.sfc"}         # ghost removed, extra added
    s = steps(report, "snes")
    assert s["roms"]["result"] == {"added": 1, "removed": 1, "media_deleted": 0, "backup": True}
    assert s["roms"]["state"] == "done"
    assert steps(report, "nes")["roms"]["result"] == {"nothing": True}
    assert os.path.isfile(roms / "snes" / "gamelist.xml.bak")      # dated snapshot + .bak, per system
    assert not os.path.exists(roms / "nes" / "gamelist.xml.bak")     # nothing changed there
    assert os.path.isfile(roms / "snes" / "images" / "orphan.png")   # no deletion asked
    assert os.path.isfile(roms / "snes" / "alpha.zip")


def test_clear_fields_and_original_gamelist_reopened(roms, client, gamelist):
    report = run(client, roms, ["snes", "nes"], {"clear": {"fields": ["genre"]}})
    assert report["state"] == "done"
    assert all(g.find("genre") is None for g in games(roms / "snes" / "gamelist.xml").values())
    assert all(g.find("genre") is None for g in games(roms / "nes" / "gamelist.xml").values())
    assert steps(report, "snes")["clear"]["result"] == {"changed": 2, "games": 2, "backup": True}
    assert xml_store.XML_PATH == str(gamelist) and report["reopened"] == str(gamelist)


def test_no_gamelist_open_before_means_none_after(roms, client):
    xml_store.close_gamelist()
    run(client, roms, ["nes"], {"clear": {"fields": ["genre"]}})
    assert not xml_store.has_gamelist()


def test_solid_images_keep_files_unless_opted_in(roms, client):
    (roms / "nes" / "images" / "black.png").write_bytes(solid_png())
    p = roms / "nes" / "gamelist.xml"
    p.write_text(NES.replace("<genre>", "<image>./images/black.png</image><genre>"), encoding="utf-8")
    report = run(client, roms, ["nes"], {"solid": {"fields": ["image"], "files": False}})
    assert steps(report, "nes")["solid"]["result"]["removed"] == 1
    assert games(p)["./one.nes"].find("image") is None
    assert os.path.isfile(roms / "nes" / "images" / "black.png")


@pytest.mark.parametrize("ops", [
    {"roms": {"remove": True, "delete_media": True}},
    {"media": {"delete": True}},
    {"solid": {"fields": ["image"], "files": True}},
])
def test_file_deletion_needs_the_confirmation(roms, client, ops):
    response = client.post("/api/multibatch", headers=LOCAL, json={"systems": [xml_of(roms, "snes")], "ops": ops})
    assert response.status_code == 400 and response.get_json()["code"] == "confirm_needed"
    assert os.path.isfile(roms / "snes" / "images" / "orphan.png")


def test_orphans_go_to_the_recycle_bin_when_confirmed(roms, client, trashed):
    report = run(client, roms, ["snes"], {"media": {"unlink": True, "delete": True}}, confirm_delete=True)
    assert steps(report, "snes")["media"]["result"]["deleted"] == 1
    assert not os.path.exists(roms / "snes" / "images" / "orphan.png")
    assert os.path.isfile(roms / "snes" / "images" / "alpha.png")
    assert trashed == [str(roms / "snes" / "images" / "orphan.png")]


@pytest.mark.parametrize("body", [
    {"systems": [], "ops": {"clear": {"fields": ["genre"]}}},
    {"systems": ["/elsewhere/gamelist.xml"], "ops": {"clear": {"fields": ["genre"]}}},
    {"systems": ["X"], "ops": {}},
    {"systems": ["X"], "ops": {"clear": {"fields": ["path"]}}},
    {"systems": ["X"], "ops": {"solid": {"fields": ["video"]}}},
    {"systems": ["X"], "ops": {"scrape": {"mode": "some", "fields": ["genre"]}}},
])
def test_bad_requests_are_refused(roms, client, body):
    body["systems"] = [xml_of(roms, "snes") if s == "X" else s for s in body["systems"]]
    response = client.post("/api/multibatch", headers=LOCAL, json=body)
    assert response.status_code == 400
    assert multibatch._public()["state"] == "idle"


def test_one_broken_system_does_not_stop_the_others(roms, client):
    report = run(client, roms, ["broken", "nes"], {"clear": {"fields": ["genre"]}})
    assert report["state"] == "done"
    states = {s["folder"]: s["state"] for s in report["systems"]}
    assert states == {"broken": "error", "nes": "done"}


def test_scrape_targets_only_games_missing_a_field(roms, client, source):
    report = run(client, roms, ["snes", "nes"], {"scrape": {"mode": "missing", "fields": ["developer"]}})
    assert report["state"] == "done"
    assert [p for _, p in source] == ["./alpha.zip", "./ghost.zip"]   # nes already has a developer
    assert steps(report, "snes")["scrape"]["result"]["updated"] == 2
    assert steps(report, "nes")["scrape"]["result"]["nothing"] is True
    assert games(roms / "snes" / "gamelist.xml")["./alpha.zip"].findtext("developer") == "Studio Alpha"


def test_quota_stops_the_whole_run(roms, client, source, monkeypatch):
    monkeypatch.setitem(batch_jobs.LOOKUPS, "screenscraper",
                        lambda game, body=None, system=None: ({"error": "Quota", "code": "source_blocked"}, 503))
    report = run(client, roms, ["nes", "snes"], {"scrape": {"mode": "all", "fields": ["developer"]},
                                                 "clear": {"fields": ["genre"]}})
    assert report["state"] == "halted" and report["halted"] == "Quota"
    states = {s["folder"]: s["state"] for s in report["systems"]}
    assert states == {"nes": "error", "snes": "skipped"}
    assert games(roms / "snes" / "gamelist.xml")["./alpha.zip"].findtext("genre") == "Platform"


def test_a_blocked_gate_halts_before_sending_anything(roms, client, source):
    ss_limits.GATE.note_status(430)
    report = run(client, roms, ["snes"], {"scrape": {"mode": "all", "fields": ["developer"]}})
    assert report["state"] == "halted" and report["halted"] == st("server.ss_quota_day")
    assert source == []


def test_a_saved_unfinished_batch_is_never_replaced(roms, client, source):
    xml_store.set_gamelist_path(xml_of(roms, "snes"))
    job = client.post("/api/batch", headers=LOCAL, json={
        "source": "screenscraper", "mode": "all", "fields": ["developer"],
        "paths": ["./alpha.zip", "./ghost.zip"]}).get_json()["job"]
    report = run(client, roms, ["snes"], {"scrape": {"mode": "all", "fields": ["developer"]}})
    assert steps(report, "snes")["scrape"]["result"]["skipped"] == "saved_batch"
    assert source == []
    assert client.get("/api/batch", headers=LOCAL).get_json()["job"]["id"] == job["id"]


def test_stop_ends_after_the_step_in_progress(roms, client, source, monkeypatch):
    import threading
    gate = threading.Event()
    original = batch_jobs.LOOKUPS["screenscraper"]

    def slow(game, body=None, system=None):
        gate.wait(5)
        return original(game, body, system)

    monkeypatch.setitem(batch_jobs.LOOKUPS, "screenscraper", slow)
    try:
        response = client.post("/api/multibatch", headers=LOCAL, json={
            "systems": [xml_of(roms, "snes"), xml_of(roms, "nes")],
            "ops": {"scrape": {"mode": "all", "fields": ["developer"]}}})
        assert response.status_code == 200
        again = client.post("/api/multibatch", headers=LOCAL, json={
            "systems": [xml_of(roms, "nes")], "ops": {"clear": {"fields": ["genre"]}}})
        assert again.status_code == 409
        client.post("/api/multibatch/stop", headers=LOCAL)
    finally:
        gate.set()
    assert multibatch.wait(20)
    report = client.get("/api/multibatch", headers=LOCAL).get_json()
    assert report["state"] == "stopped"
    assert {s["folder"]: s["state"] for s in report["systems"]}["nes"] == "skipped"
    assert len(source) <= 2


def test_mostly_missing_roms_are_never_removed(roms, client):
    snes = roms / "snes"
    lines = "".join(f"<game><path>./gone{i}.zip</path><name>Gone {i}</name></game>" for i in range(8))
    (snes / "gamelist.xml").write_text(SNES.replace("</gameList>", lines + "</gameList>"), encoding="utf-8")
    report = run(client, roms, ["snes"], {"roms": {"add": False, "remove": True}})
    assert steps(report, "snes")["roms"]["result"] == {"nothing": True, "suspicious": 9}
    assert len(games(snes / "gamelist.xml")) == 10
