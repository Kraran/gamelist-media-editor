"""Fallback scrape sources: LaunchBox, TheGamesDB and IGDB after ScreenScraper.

No test reaches a real API: requests are replaced by fakes (conftest also
points every source at a closed local port)."""
import io
import json
import time
import zipfile

import pytest
from lxml import etree

from gme import batch_jobs, multibatch, remote_cache
from gme.scrapers import fallback, igdb, launchbox, platforms, sources, ss, ss_limits, tgdb
from gme.systems import SS_SYSTEM_MAP
from conftest import LOCAL

NES = (3, "nes")

METADATA = """<?xml version="1.0" standalone="yes"?>
<LaunchBox>
  <Platform><Name>Nintendo Entertainment System</Name></Platform>
  <Game>
    <Name>Alpha</Name><DatabaseID>11</DatabaseID><Platform>Nintendo Entertainment System</Platform>
    <Overview>Alpha from LaunchBox.</Overview><ReleaseDate>1990-05-04T00:00:00-07:00</ReleaseDate>
    <Developer>Alpha Dev</Developer><Publisher>Alpha Pub</Publisher><Genres>Action; Platform</Genres>
    <MaxPlayers>2</MaxPlayers><CommunityRating>4</CommunityRating>
  </Game>
  <Game>
    <Name>Bravo Quest</Name><DatabaseID>12</DatabaseID><Platform>Nintendo Entertainment System</Platform>
    <Overview>Bravo from LaunchBox.</Overview><ReleaseYear>1991</ReleaseYear>
  </Game>
  <Game>
    <Name>Alpha</Name><DatabaseID>13</DatabaseID><Platform>Sega Genesis</Platform>
    <Overview>The other Alpha.</Overview>
  </Game>
  <Game>
    <Name>Not Mapped</Name><DatabaseID>14</DatabaseID><Platform>Some Unknown Platform</Platform>
  </Game>
  <GameAlternateName><AlternateName>Bravo</AlternateName><DatabaseID>12</DatabaseID></GameAlternateName>
  <GameImage><DatabaseID>11</DatabaseID><FileName>a-front-us.jpg</FileName><Type>Box - Front</Type><Region>North America</Region></GameImage>
  <GameImage><DatabaseID>11</DatabaseID><FileName>a-front-eu.jpg</FileName><Type>Box - Front</Type><Region>Europe</Region></GameImage>
  <GameImage><DatabaseID>11</DatabaseID><FileName>a-shot.png</FileName><Type>Screenshot - Gameplay</Type><Region></Region></GameImage>
  <GameImage><DatabaseID>11</DatabaseID><FileName>a-logo.png</FileName><Type>Clear Logo</Type><Region>World</Region></GameImage>
  <GameImage><DatabaseID>11</DatabaseID><FileName>a-banner.png</FileName><Type>Banner</Type><Region></Region></GameImage>
  <GameImage><DatabaseID>14</DatabaseID><FileName>x.png</FileName><Type>Box - Front</Type><Region></Region></GameImage>
</LaunchBox>
"""


def metadata_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Metadata.xml", METADATA)
        zf.writestr("Platforms.xml", "<LaunchBox/>")
    return buf.getvalue()


@pytest.fixture
def lb_base(tmp_path):
    archive = tmp_path / "Metadata.zip"
    archive.write_bytes(metadata_zip())
    import os
    os.makedirs(launchbox.LB_DIR, exist_ok=True)
    assert launchbox.build_index(str(archive), launchbox.db_path(), archive_date="today") == 3
    return launchbox.db_path()


def enable(**patch):
    body = {"enabled": {"launchbox": True}}
    body.update(patch)
    return sources.save_config(body)


def game(path="./alpha.zip", name="Alpha"):
    return etree.fromstring(f"<game><path>{path}</path><name>{name}</name></game>")


def ss_not_found(monkeypatch):
    calls = []

    def fake(endpoint, extra=None, timeout=25):
        calls.append(endpoint)
        return False, "Erreur : Jeu non trouvée !", 404
    monkeypatch.setattr(ss, "ss_request", fake)
    return calls


def ss_finds(monkeypatch, proposed):
    def fake(g, body=None, system=None):
        from gme.scrapers.compare import scrape_payload
        p = {"medias": {}, "disabled_media": ["titleshot", "wheel"], "ss_id": "77", **proposed}
        return {"success": True, "match_method": "hash", "proposed": p, "hash": {"crc": "ABCD1234"},
                **scrape_payload(g, p)}, 200
    monkeypatch.setattr(ss, "scrape_game", fake)


# --- settings ----------------------------------------------------------------------------
def test_everything_is_off_by_default_and_ss_alone_answers(gamelist, monkeypatch):
    seen = []
    monkeypatch.setattr(ss, "scrape_game", lambda g, body=None, system=None: seen.append(1) or ({"x": 1}, 200))
    assert sources.active_fallbacks() == []
    assert fallback.scrape_game(game(), {}, NES) == ({"x": 1}, 200)
    assert seen == [1]


def test_keys_are_saved_but_never_sent_back(client, tmp_path):
    r = client.post("/api/sources/config", headers=LOCAL, json={
        "tgdb_apikey": "TGDBKEY123456", "igdb_client_id": "CLIENTID99", "igdb_client_secret": "SECRET7777777",
        "enabled": {"thegamesdb": True}, "order": ["igdb", "screenscraper", "bogus"]})
    assert r.status_code == 200
    text = r.get_data(as_text=True) + client.get("/api/sources/config", headers=LOCAL).get_data(as_text=True)
    for secret in ("TGDBKEY123456", "CLIENTID99", "SECRET7777777"):
        assert secret not in text
    cfg = r.get_json()["config"]
    assert cfg["tgdb_apikey_set"] and cfg["igdb_client_id_set"] and cfg["igdb_client_secret_set"]
    assert cfg["order"] == ["igdb", "screenscraper", "launchbox", "thegamesdb"]
    assert cfg["active"] == ["thegamesdb"]
    saved = json.loads((tmp_path / "sources_config.json").read_text(encoding="utf-8"))
    assert saved["tgdb_apikey"] == "TGDBKEY123456"           # local file only (gitignored)
    client.post("/api/sources/config", headers=LOCAL, json={"clear_tgdb_apikey": True})
    assert not sources.load_config()["tgdb_apikey"]


def test_gitignore_keeps_the_settings_file_out_of_the_repo():
    from pathlib import Path
    assert "sources_config.json" in (Path(__file__).resolve().parents[1] / ".gitignore").read_text().split()


def test_redact_hides_keys_and_tokens():
    cfg = dict(sources.load_config(), tgdb_apikey="KEY-ABCDEFG", igdb_client_secret="S3CR3T-XYZ")
    text = "GET https://api.thegamesdb.net/v1/x?apikey=KEY-ABCDEFG&name=a Bearer tok.en-1 S3CR3T-XYZ client_secret=zz"
    out = sources.redact(text, cfg)
    assert "KEY-ABCDEFG" not in out and "S3CR3T-XYZ" not in out and "tok.en-1" not in out and "=zz" not in out


def test_fields_outside_a_source_are_refused():
    cfg = sources.save_config({"fields": {"igdb": ["desc", "boxback", "video"]}})
    assert cfg["fields"]["igdb"] == ["desc"]


# --- platforms -----------------------------------------------------------------------------
def test_platform_table_uses_known_screenscraper_ids():
    known = set(SS_SYSTEM_MAP.values())
    assert set(platforms.PLATFORMS) <= known
    for sid, (lb, tg, ig) in platforms.PLATFORMS.items():
        assert isinstance(lb, tuple) and all(isinstance(n, str) and n for n in lb)
        assert tg is None or all(p.isdigit() for p in tg.split(","))
        assert ig is None or all(isinstance(p, int) for p in ig)
    assert platforms.for_source("igdb", 3) == (18, 99)
    assert platforms.for_source("launchbox", None) is None


def test_titles_are_compared_without_tags_articles_or_accents():
    assert sources.norm_title("Legend of Zelda, The - A Link (USA) [!].zip", rom=True) == "legend of zelda a link"
    assert sources.norm_title("The Legend of Zelda: A Link") == "legend of zelda a link"
    assert sources.norm_title("Pokémon Rouge & Bleu") == "pokemon rouge and bleu"
    assert sources.iso_to_es("1990-05-04T00:00:00") == "19900504T000000"
    assert sources.iso_to_es("1991") == "19910101T000000"


def test_throttle_spaces_requests():
    th = sources.Throttle(0.05)
    t0 = time.monotonic()
    for _ in range(3):
        with th:
            pass
    assert time.monotonic() - t0 >= 0.1


# --- LaunchBox ----------------------------------------------------------------------------
def test_launchbox_index_keeps_known_platforms_and_used_images(lb_base):
    import sqlite3
    conn = sqlite3.connect(lb_base)
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 3          # unknown platform dropped
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 4         # banner and orphan dropped
    assert launchbox.ready()
    assert launchbox.status()["games"] == 3


def test_launchbox_matches_name_platform_alternate_name_and_region(lb_base):
    ctx = {"names": sources.query_names(game()), "prefer": "fr"}
    out, err = launchbox.lookup(game(), 3, set(sources.SUPPORTED["launchbox"]), ctx)
    assert err is None and out["match"] == "name" and out["source_id"] == "11"
    assert out["desc"] == "Alpha from LaunchBox."
    assert out["releasedate"] == "19900504T000000"
    assert out["genre"] == "Action, Platform" and out["players"] == "2" and out["rating"] == "0.80"
    assert out["medias"]["thumbnail"]["url"] == launchbox.IMAGES_URL + "a-front-eu.jpg"   # Europe before US for fr
    assert out["medias"]["marquee"]["url"].endswith("a-logo.png")
    assert out["medias"]["image"]["url"].endswith("a-shot.png")
    other, _ = launchbox.lookup(game(), 1, {"desc"}, ctx)                    # same name, other system
    assert other["desc"] == "The other Alpha."
    bravo = game("./bravo.zip", "Bravo")
    out, _ = launchbox.lookup(bravo, 3, {"desc", "releasedate"}, {"names": sources.query_names(bravo)})
    assert out["match"] == "alternate-name" and out["releasedate"] == "19910101T000000"
    typo = game("./x.zip", "Bravo Quesst")
    out, _ = launchbox.lookup(typo, 3, {"desc"}, {"names": sources.query_names(typo)})
    assert out["match"] == "fuzzy-name"
    unknown = game("./zzz.zip", "Nothing Like It")
    assert launchbox.lookup(unknown, 3, {"desc"}, {"names": sources.query_names(unknown)}) == (None, None)


def test_launchbox_download_is_once_a_day(monkeypatch):
    payload = metadata_zip()

    class Resp:
        headers = {"content-length": str(len(payload)), "last-modified": "Mon, 23 Nov 2026 08:00:42 GMT"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_content(self, n): yield payload

    urls = []
    monkeypatch.setattr(launchbox.requests, "get", lambda url, **k: urls.append(url) or Resp())
    launchbox._set(running=True)
    launchbox._update()                                           # what the background thread runs
    st = launchbox.status()
    assert st["ready"] and not st["running"] and st["games"] == 3 and not st["error"]
    assert st["next_in"] > 23 * 3600
    assert urls == [launchbox.METADATA_URL]
    assert launchbox.start_update() == (False, "recent")
    import os
    assert not [f for f in os.listdir(launchbox.LB_DIR) if f.endswith((".zip", ".part", ".tmp"))]


def test_launchbox_update_route_refuses_a_second_download(client, lb_base):
    r = client.post("/api/sources/launchbox/update", headers=LOCAL)
    assert r.status_code == 409 and r.get_json()["code"] == "launchbox_recent"


# --- the chain ------------------------------------------------------------------------------
def test_not_on_screenscraper_launchbox_answers(gamelist, lb_base, monkeypatch):
    enable()
    calls = ss_not_found(monkeypatch)
    data, status = fallback.scrape_game(game(), {}, NES)
    assert status == 200 and calls                               # ScreenScraper was asked first
    assert data["match_method"] == "fallback-launchbox"
    assert data["fallback"]["ss"] == "not_found" and data["fallback"]["used"] == ["launchbox"]
    rows = {r["key"]: r for r in data["compare"]}
    assert rows["desc"]["status"] == "new" and rows["desc"]["source"] == "launchbox"
    assert rows["thumbnail"]["source"] == "launchbox" and rows["thumbnail"]["preview"]
    assert "name" not in data["proposed"]["field_sources"]        # the name is off by default
    assert "titleshot" not in rows and "wheel" not in rows        # media turned off for ScreenScraper stay off


def test_launchbox_only_fills_what_screenscraper_lacks(gamelist, lb_base, monkeypatch):
    enable()
    ss_finds(monkeypatch, {"name": "Alpha SS", "desc": "From SS",
                           "medias": {"image": {"url": "https://neoclone.screenscraper.fr/x.png", "type": "ss"}}})
    data, status = fallback.scrape_game(game(), {}, NES)
    assert status == 200 and data["match_method"] == "hash"
    p = data["proposed"]
    assert p["desc"] == "From SS" and p["field_sources"]["desc"] == "screenscraper"
    assert p["developer"] == "Alpha Dev" and p["field_sources"]["developer"] == "launchbox"
    assert p["medias"]["image"]["url"].endswith("x.png")
    assert p["medias"]["thumbnail"]["source"] == "launchbox"
    assert data["fallback"]["used"] == ["screenscraper", "launchbox"]


def test_chain_order_and_allowed_fields_decide(gamelist, lb_base, monkeypatch):
    enable(order=["launchbox", "screenscraper"], fields={"launchbox": ["desc"]})
    ss_finds(monkeypatch, {"desc": "From SS", "developer": "SS Dev"})
    p = fallback.scrape_game(game(), {}, NES)[0]["proposed"]
    assert p["desc"] == "Alpha from LaunchBox."                  # LaunchBox first for the description
    assert p["developer"] == "SS Dev"                            # not a LaunchBox field here
    assert "thumbnail" not in p["medias"]


def test_batch_body_limits_the_fields_asked(gamelist, lb_base, monkeypatch):
    enable()
    ss_not_found(monkeypatch)
    asked = []
    original = launchbox.lookup
    monkeypatch.setitem(fallback.LOOKUPS, "launchbox", lambda g, s, needed, ctx: asked.append(set(needed)) or original(g, s, needed, ctx))
    g = game()
    etree.SubElement(g, "developer").text = "Mine"
    fallback.scrape_game(g, {"fields": ["developer", "desc", "video"], "mode": "missing"}, NES)
    assert asked == [{"desc"}]                                   # developer already there, video not a LaunchBox media


def test_nothing_found_is_a_plain_not_found(gamelist, lb_base, monkeypatch):
    enable()
    ss_not_found(monkeypatch)
    data, status = fallback.scrape_game(game("./zzz.zip", "Nothing Like It"), {}, NES)
    assert status == 404 and data["code"] == "not_found"
    assert not batch_jobs._blocked(status, data)


def test_ss_quota_sends_nothing_more_and_fallback_answers(gamelist, lb_base, monkeypatch):
    enable()
    sent = []
    monkeypatch.setattr(ss.requests, "get", lambda *a, **k: sent.append(a) or (_ for _ in ()).throw(AssertionError("sent")))
    ss_limits.GATE.note_status(430)
    data, status = fallback.scrape_game(game(), {}, NES)
    assert sent == []
    assert status == 200 and data["fallback"]["ss"] == "blocked"
    assert data["proposed"]["desc"] == "Alpha from LaunchBox."


def test_ss_quota_with_stop_setting_stays_blocked(gamelist, lb_base, monkeypatch):
    enable(on_ss_quota="stop")
    monkeypatch.setattr(ss.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    ss_limits.GATE.note_status(430)
    data, status = fallback.scrape_game(game(), {}, NES)
    assert status == 503 and data["code"] == "source_blocked"
    assert not sources.continue_on_ss_block()


def test_ss_candidates_are_left_to_the_user(gamelist, lb_base, monkeypatch):
    enable()
    monkeypatch.setattr(ss, "scrape_game", lambda g, b=None, s=None: ({"need_choice": True, "candidates": [1]}, 200))
    assert fallback.scrape_game(game(), {}, NES)[0] == {"need_choice": True, "candidates": [1]}


def test_single_scrape_route_uses_the_chain(gamelist, client, lb_base, monkeypatch):
    enable()
    ss_not_found(monkeypatch)
    monkeypatch.setattr(fallback, "detect_system_id", lambda: NES)
    r = client.post("/api/ss/scrape/0?path=./alpha.zip", headers=LOCAL, json={})
    assert r.status_code == 200
    assert r.get_json()["fallback"]["used"] == ["launchbox"]


def test_batch_carries_on_with_launchbox_when_ss_quota_is_reached(gamelist, client, lb_base, monkeypatch):
    enable()
    monkeypatch.setattr(batch_jobs, "detect_system_id", lambda: NES)
    monkeypatch.setattr(ss.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    monkeypatch.setattr(remote_cache, "fetch", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    ss_limits.GATE.note_status(430)
    job = client.post("/api/batch", headers=LOCAL, json={
        "source": "screenscraper", "mode": "missing", "fields": ["developer", "desc"],
        "paths": ["./alpha.zip", "./bravo.zip", "./charlie.zip"]}).get_json()["job"]
    kinds = []
    for i in range(3):
        step = client.post("/api/batch/step", headers=LOCAL,
                           json={"id": job["id"], "owner": job["owner"], "i": i}).get_json()
        assert not step["halted"]
        kinds.append(step["result"]["kind"])
    assert kinds == ["updated", "updated", "errors"]               # charlie is nowhere
    xml = etree.parse(str(gamelist)).getroot()
    assert xml.find("game").findtext("developer") == "Alpha Dev"
    assert xml.findall("game")[1].findtext("desc") == "Bravo from LaunchBox."


def test_batch_without_fallback_still_stops_on_ss_quota(gamelist, client, monkeypatch):
    monkeypatch.setattr(ss.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    ss_limits.GATE.note_status(430)
    job = client.post("/api/batch", headers=LOCAL, json={
        "source": "screenscraper", "mode": "missing", "fields": ["developer"],
        "paths": ["./alpha.zip", "./bravo.zip"]}).get_json()["job"]
    step = client.post("/api/batch/step", headers=LOCAL, json={"id": job["id"], "owner": job["owner"], "i": 0}).get_json()
    assert step["halted"]


def test_multibatch_goes_on_when_fallbacks_carry_on(lb_base):
    ss_limits.GATE.note_status(430)
    assert multibatch._blocked_halt("screenscraper")            # nothing enabled: stop as before
    enable()
    assert multibatch._blocked_halt("screenscraper") is None
    enable(on_ss_quota="stop")
    assert multibatch._blocked_halt("screenscraper")


def test_a_failing_source_does_not_break_the_scrape(gamelist, lb_base, monkeypatch):
    enable()
    ss_not_found(monkeypatch)
    monkeypatch.setitem(fallback.LOOKUPS, "launchbox", lambda *a: 1 / 0)
    data, status = fallback.scrape_game(game(), {}, NES)
    assert status == 404 and "launchbox" in data["fallback"]["errors"]


# --- TheGamesDB ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def tgdb_answer(data, remaining=100):
    return {"code": 200, "status": "Success", "remaining_monthly_allowance": remaining, "extra_allowance": 0,
            "allowance_refresh_timer": 3600, "data": data}


@pytest.fixture
def tgdb_api(monkeypatch):
    calls = []
    answers = {
        "/v1/Games/ByGameHash": tgdb_answer({"count": 0, "games": []}),
        "/v1.1/Games/ByGameName": tgdb_answer({"count": 2, "games": [
            {"id": 5, "game_title": "Alpha Strike", "platform": 7},
            {"id": 6, "game_title": "Alpha", "platform": 7, "release_date": "1990-01-02", "players": 2,
             "overview": "Alpha from TGDB.", "developers": [9], "publishers": [4], "genres": [1, 2]}]}),
        "/v1/Games/Images": tgdb_answer({"count": 3, "base_url": {"original": "https://cdn.thegamesdb.net/images/original/"},
                                         "images": {"6": [
                                             {"id": 2, "type": "boxart", "side": "back", "filename": "boxart/back/6-1.jpg"},
                                             {"id": 1, "type": "boxart", "side": "front", "filename": "boxart/front/6-1.jpg"},
                                             {"id": 3, "type": "clearlogo", "filename": "clearlogo/6.png"}]}}),
        "/v1/Developers": tgdb_answer({"count": 1, "developers": {"9": {"id": 9, "name": "Dev Nine"}}}),
        "/v1/Publishers": tgdb_answer({"count": 1, "publishers": {"4": {"id": 4, "name": "Pub Four"}}}),
        "/v1/Genres": tgdb_answer({"count": 2, "genres": {"1": {"id": 1, "name": "Action"}, "2": {"id": 2, "name": "Shooter"}}}),
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        path = url.replace(tgdb.API, "")
        calls.append((path, dict(params or {})))
        return FakeResponse(200, answers[path])
    monkeypatch.setattr(tgdb.requests, "get", fake_get)
    monkeypatch.setattr(tgdb, "_throttle", sources.Throttle(0))
    return calls


def tgdb_ctx(g=None, hash_info=None):
    cfg = sources.save_config({"tgdb_apikey": "TGDB-SECRET-1", "enabled": {"thegamesdb": True}})
    return {"cfg": cfg, "names": sources.query_names(g if g is not None else game()), "hash": hash_info, "refresh": False}


def test_tgdb_crc_then_name_then_images(tgdb_api):
    ctx = tgdb_ctx(hash_info={"crc": "ABCD1234"})
    out, err = tgdb.lookup(game(), 3, {"desc", "developer", "publisher", "genre", "thumbnail", "boxback", "wheel", "releasedate", "players"}, ctx)
    assert err is None and out["match"] == "name" and out["source_id"] == "6"
    assert [c[0] for c in tgdb_api][:2] == ["/v1/Games/ByGameHash", "/v1.1/Games/ByGameName"]
    assert {c[0] for c in tgdb_api[2:5]} == {"/v1/Genres", "/v1/Developers", "/v1/Publishers"}
    hash_call = tgdb_api[0][1]
    assert hash_call["hash"] == "abcd1234" and hash_call["filter[type]"] == "crc" and hash_call["filter[platform]"] == "7"
    assert out["developer"] == "Dev Nine" and out["publisher"] == "Pub Four" and out["genre"] == "Action, Shooter"
    assert out["releasedate"] == "19900102T000000" and out["players"] == "2"
    assert out["medias"]["thumbnail"]["url"] == "https://cdn.thegamesdb.net/images/original/boxart/front/6-1.jpg"
    assert out["medias"]["boxback"]["url"].endswith("boxart/back/6-1.jpg")
    assert out["medias"]["wheel"]["url"].endswith("clearlogo/6.png")
    assert tgdb.allowance()["remaining"] == 100
    n = len(tgdb_api)
    tgdb.lookup(game(), 3, {"desc", "developer", "thumbnail"}, ctx)        # all cached now
    assert len(tgdb_api) == n


def test_tgdb_cache_files_hold_no_key(tgdb_api):
    import gzip
    import pathlib
    tgdb.lookup(game(), 3, {"desc", "thumbnail"}, tgdb_ctx())
    files = list(pathlib.Path(sources.CACHE_DIR).glob("*.json.gz"))
    assert files
    for f in files:
        assert "TGDB-SECRET-1" not in gzip.decompress(f.read_bytes()).decode("utf-8")


def test_tgdb_skips_images_when_no_media_is_needed(tgdb_api):
    tgdb.lookup(game(), 3, {"desc"}, tgdb_ctx())
    assert "/v1/Games/Images" not in [c[0] for c in tgdb_api]


def test_tgdb_stops_asking_when_the_allowance_is_used_up(tgdb_api, monkeypatch):
    tgdb._note_allowance({"remaining_monthly_allowance": 0, "extra_allowance": 0, "allowance_refresh_timer": 600})
    out, err = tgdb.lookup(game("./other.zip", "Other"), 3, {"desc"}, tgdb_ctx())
    assert out is None and err and tgdb_api == []


def test_tgdb_refused_key_is_reported_without_the_key(monkeypatch):
    monkeypatch.setattr(tgdb.requests, "get", lambda *a, **k: FakeResponse(403))
    monkeypatch.setattr(tgdb, "_throttle", sources.Throttle(0))
    out, err = tgdb.lookup(game(), 3, {"desc"}, tgdb_ctx())
    assert out is None and "TGDB-SECRET-1" not in err and "TheGamesDB" in err


def test_tgdb_network_error_hides_the_key(monkeypatch):
    def boom(url, params=None, **k):
        raise tgdb.requests.ConnectionError(f"failed {url}?apikey={params['apikey']}")
    monkeypatch.setattr(tgdb.requests, "get", boom)
    monkeypatch.setattr(tgdb, "_throttle", sources.Throttle(0))
    _, err = tgdb.lookup(game(), 3, {"desc"}, tgdb_ctx())
    assert err and "TGDB-SECRET-1" not in err


def test_tgdb_without_platform_asks_nothing(tgdb_api):
    assert tgdb.lookup(game(), 281, {"desc"}, tgdb_ctx()) == (None, None)       # VC 4000: no TGDB platform
    assert tgdb_api == []


def test_test_route_needs_a_key(client):
    r = client.post("/api/sources/test/thegamesdb", headers=LOCAL)
    assert r.status_code == 400 and r.get_json()["code"] == "key_missing"


# --- IGDB -------------------------------------------------------------------------------------
@pytest.fixture
def igdb_api(monkeypatch):
    calls = {"token": 0, "games": []}
    state = {"expire_next": False}

    def fake_post(url, params=None, data=None, headers=None, timeout=None):
        if url == igdb.TOKEN_URL:
            calls["token"] += 1
            assert params["client_secret"] == "IGDB-SECRET-9"
            return FakeResponse(200, {"access_token": f"tok{calls['token']}", "expires_in": 5000, "token_type": "bearer"})
        calls["games"].append((data.decode("utf-8"), headers))
        if state["expire_next"]:
            state["expire_next"] = False
            return FakeResponse(401, {"message": "expired"})
        return FakeResponse(200, [
            {"id": 1, "name": "Alpha Two"},
            {"id": 2, "name": "Alpha", "summary": "Alpha from IGDB.", "first_release_date": 641779200,
             "total_rating": 81.4, "genres": [{"name": "Platform"}, {"name": "Adventure"}],
             "involved_companies": [{"developer": True, "publisher": False, "company": {"name": "Dev Co"}},
                                    {"developer": False, "publisher": True, "company": {"name": "Pub Co"}}],
             "cover": {"image_id": "co123"}, "screenshots": [{"image_id": "sc1"}], "artworks": [{"image_id": "ar1"}]}])
    monkeypatch.setattr(igdb.requests, "post", fake_post)
    monkeypatch.setattr(igdb, "_throttle", sources.Throttle(0))
    return calls, state


def igdb_ctx(g=None):
    cfg = sources.save_config({"igdb_client_id": "IGDB-ID-1", "igdb_client_secret": "IGDB-SECRET-9"})
    return {"cfg": cfg, "names": sources.query_names(g if g is not None else game()), "refresh": True}


def test_igdb_one_query_fills_metadata_and_media(igdb_api):
    calls, _ = igdb_api
    out, err = igdb.lookup(game(), 3, set(sources.SUPPORTED["igdb"]), igdb_ctx())
    assert err is None and out["source_id"] == "2" and out["match"] == "name"
    query, headers = calls["games"][0]
    assert 'search "Alpha";' in query and "where platforms = (18,99);" in query
    assert headers["Client-ID"] == "IGDB-ID-1" and headers["Authorization"] == "Bearer tok1"
    assert out["desc"] == "Alpha from IGDB." and out["rating"] == "0.81"
    assert out["releasedate"] == "19900504T000000"
    assert out["developer"] == "Dev Co" and out["publisher"] == "Pub Co" and out["genre"] == "Platform, Adventure"
    assert out["medias"]["thumbnail"]["url"] == "https://images.igdb.com/igdb/image/upload/t_cover_big_2x/co123.jpg"
    assert out["medias"]["image"]["url"].endswith("t_1080p/sc1.jpg")
    assert out["medias"]["fanart"]["url"].endswith("t_1080p/ar1.jpg")


def test_igdb_token_is_reused_and_renewed_once_on_401(igdb_api):
    calls, state = igdb_api
    ctx = igdb_ctx()
    igdb.lookup(game(), 3, {"desc"}, ctx)
    igdb.lookup(game(), 3, {"desc"}, ctx)
    assert calls["token"] == 1
    state["expire_next"] = True
    out, err = igdb.lookup(game(), 3, {"desc"}, ctx)
    assert calls["token"] == 2 and out["desc"] == "Alpha from IGDB."


def test_igdb_quotes_cannot_break_the_query(igdb_api):
    calls, _ = igdb_api
    igdb.lookup(game("./q.zip", 'Al"pha; fields *'), 3, {"desc"}, igdb_ctx(game("./q.zip", 'Al"pha; fields *')))
    assert 'search "Al pha; fields *";' in calls["games"][0][0]


def test_igdb_refused_login_is_an_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(igdb.requests, "post", lambda *a, **k: FakeResponse(400, {"message": "invalid client secret"}))
    out, err = igdb.lookup(game(), 3, {"desc"}, igdb_ctx())
    assert out is None and "IGDB" in err and "IGDB-SECRET-9" not in err


def test_whole_chain_with_three_sources(gamelist, lb_base, tgdb_api, igdb_api, monkeypatch):
    sources.save_config({"enabled": {"launchbox": True, "thegamesdb": True, "igdb": True},
                         "tgdb_apikey": "TGDB-SECRET-1", "igdb_client_id": "IGDB-ID-1",
                         "igdb_client_secret": "IGDB-SECRET-9",
                         "fields": {"launchbox": ["desc"], "thegamesdb": ["boxback", "developer"],
                                    "igdb": ["fanart", "developer", "rating"]}})
    ss_not_found(monkeypatch)
    data, status = fallback.scrape_game(game(), {}, NES)
    fs = data["proposed"]["field_sources"]
    assert status == 200
    assert fs["desc"] == "launchbox" and fs["boxback"] == "thegamesdb" and fs["developer"] == "thegamesdb"
    assert fs["fanart"] == "igdb" and fs["rating"] == "igdb"
    assert data["fallback"]["used"] == ["launchbox", "thegamesdb", "igdb"]
    assert "TGDB-SECRET-1" not in json.dumps(data) and "IGDB-SECRET-9" not in json.dumps(data)
