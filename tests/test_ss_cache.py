"""ScreenScraper answer cache: a rescrape costs no quota, nothing secret is stored."""
import gzip
import json
import threading
import time
from pathlib import Path

import pytest
import requests

from gme.scrapers import ss, ss_cache, ss_limits
from conftest import LOCAL
from test_ss_parallel import (ROMS, FakeSS, Resp, big_gamelist, developers, fake_ss,  # noqa: F401 (fixtures)
                              run_all, start)

HASH = {"romtype": "rom", "crc": "ABCD1234", "romnom": "game0.zip", "romtaille": "9"}


def api_calls(server, endpoint="jeuInfos.php"):
    return [c for c in server.calls if c[1] == endpoint]


def cached_files():
    return sorted(Path(ss_cache.CACHE_DIR).glob("*.json.gz"))


def read_all_cache():
    return "".join(gzip.decompress(p.read_bytes()).decode("utf-8") for p in cached_files())


@pytest.fixture
def secret_config(ss_config_file):
    def write(**extra):
        ss_config_file.write_text(json.dumps({"ssid": "member", "sspassword": "pw-Secret-42", **extra}), encoding="utf-8")
    write()
    return write


def test_a_cached_answer_sends_nothing_and_costs_no_quota(fake_ss, secret_config):
    server = fake_ss(maxthreads=2)
    secret_config()
    ok, first, _ = ss.ss_request("jeuInfos.php", HASH)
    assert ok and len(api_calls(server)) == 1
    before = ss_limits.GATE.snapshot()
    with ss_cache.track() as info:
        ok, second, status = ss.ss_request("jeuInfos.php", dict(HASH))
    assert ok and status == 200 and info == {"hits": 1, "sent": 0, "oldest": info["oldest"]}
    assert len(api_calls(server)) == 1                                    # not sent
    after = ss_limits.GATE.snapshot()
    assert after["last_minute"] == before["last_minute"]                 # not in the per-minute limiter
    assert after["today"] == before["today"]                             # not in the daily count
    assert second["response"]["jeu"] == first["response"]["jeu"]


def test_nothing_secret_or_personal_is_stored(fake_ss, secret_config):
    fake_ss(maxthreads=2)
    secret_config()
    ss.ss_request("jeuInfos.php", HASH)
    text = read_all_cache()
    assert text and "game0.zip" not in [p.name for p in cached_files()]
    for secret in ("pw-Secret-42", "sspassword", "ssid", "devpassword", "devid", ss._SS_DEV_PASS, "ssuser", "maxthreads"):
        assert secret not in text, secret


def test_a_cached_answer_never_feeds_stale_limits(fake_ss, secret_config):
    fake_ss(maxthreads=4)
    secret_config()
    ss.ss_request("jeuInfos.php", HASH)
    ss_limits.GATE.reset()
    assert ss.ss_request("jeuInfos.php", HASH)[0]
    assert "maxthreads" not in ss_limits.GATE.limits                       # still unknown: 1 thread


def test_the_key_ignores_credentials_but_not_the_lookup():
    assert ss_cache.key_for("jeuInfos.php", {**HASH, "ssid": "a", "sspassword": "b"}) == \
        ss_cache.key_for("jeuInfos.php", {**HASH, "ssid": "c", "sspassword": "d", "devid": "x"})
    assert ss_cache.key_for("jeuInfos.php", HASH) != ss_cache.key_for("jeuInfos.php", {**HASH, "crc": "FFFF0000"})
    assert ss_cache.key_for("jeuInfos.php", HASH) != ss_cache.key_for("jeuRecherche.php", HASH)


@pytest.mark.parametrize("status", [429, 430, 431, 423, 426, 401, 500, 503])
def test_refusals_and_server_errors_are_never_cached(fake_ss, secret_config, monkeypatch, status):
    server = fake_ss(maxthreads=2)
    secret_config()
    monkeypatch.setattr(ss, "_RETRY_429", ())
    monkeypatch.setattr(server, "answer", lambda *a: Resp(status, text="Erreur"))
    ok, _, got = ss.ss_request("jeuInfos.php", HASH)
    assert not ok and got == status
    assert cached_files() == []


def test_network_errors_are_never_cached(fake_ss, secret_config, monkeypatch):
    fake_ss(maxthreads=2)
    secret_config()

    def down(*a, **k):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", down)
    assert not ss.ss_request("jeuInfos.php", HASH)[0]
    assert cached_files() == []


def test_member_info_and_other_calls_are_never_cached(fake_ss, secret_config):
    server = fake_ss(maxthreads=2)
    secret_config()
    ss.ss_request("ssuserInfos.php")
    ss.ss_request("ssuserInfos.php")
    assert len(api_calls(server, "ssuserInfos.php")) == 2
    assert cached_files() == []


def test_not_found_is_kept_one_day_and_answers_last_cache_days(fake_ss, secret_config, monkeypatch):
    server = fake_ss(maxthreads=2)
    secret_config(cache_days=30)
    missing = {"romtype": "rom", "crc": "00000000"}                        # no romnom: the fake says "not found"
    assert ss.ss_request("jeuInfos.php", missing)[2] == 404
    ok, message, status = ss.ss_request("jeuInfos.php", missing)
    assert (ok, status) == (False, 404) and "non trouv" in message
    assert len(api_calls(server)) == 1
    assert ss.ss_request("jeuInfos.php", HASH)[0]
    now = time.time()
    monkeypatch.setattr(ss_cache.time, "time", lambda: now + 2 * 86400)
    ss.ss_request("jeuInfos.php", missing)                                # expired after a day
    ss.ss_request("jeuInfos.php", HASH)                                   # still cached
    assert len(api_calls(server)) == 3
    monkeypatch.setattr(ss_cache.time, "time", lambda: now + 31 * 86400)
    ss.ss_request("jeuInfos.php", HASH)                                   # 30 days passed
    assert len(api_calls(server)) == 4


def test_empty_searches_are_kept_one_day_only(fake_ss, secret_config, monkeypatch):
    server = fake_ss(maxthreads=2)
    secret_config()
    monkeypatch.setattr(server, "answer", lambda *a: Resp(payload={"header": {"success": "true"}, "response": {"jeux": []}}))
    for _ in range(2):
        assert ss.ss_request("jeuRecherche.php", {"recherche": "nothing"})[0]
    assert len(api_calls(server, "jeuRecherche.php")) == 1
    now = time.time()
    monkeypatch.setattr(ss_cache.time, "time", lambda: now + 2 * 86400)
    ss.ss_request("jeuRecherche.php", {"recherche": "nothing"})
    assert len(api_calls(server, "jeuRecherche.php")) == 2


def test_disabled_cache_sends_every_time(fake_ss, secret_config):
    server = fake_ss(maxthreads=2)
    secret_config(cache_enabled=False)
    for _ in range(2):
        ss.ss_request("jeuInfos.php", HASH)
    assert len(api_calls(server)) == 2 and cached_files() == []


def test_single_scrape_reports_the_cache_and_refresh_asks_again(big_gamelist, client, fake_ss, secret_config):
    server = fake_ss(maxthreads=2)
    secret_config()
    url = "/api/ss/scrape/0?path=./game0.zip"
    first = client.post(url, headers=LOCAL, json={}).get_json()
    assert first["cache"]["hits"] == 0 and first["cache"]["sent"] >= 1
    sent = len(api_calls(server))
    second = client.post(url, headers=LOCAL, json={}).get_json()
    assert second["cache"]["hits"] >= 1 and second["cache"]["sent"] == 0 and second["cache"]["time"]
    assert second["proposed"] == first["proposed"] and len(api_calls(server)) == sent
    third = client.post(url, headers=LOCAL, json={"refresh": True}).get_json()
    assert third["cache"]["hits"] == 0 and len(api_calls(server)) == sent + 1
    assert third["proposed"]["developer"] == first["proposed"]["developer"]


def test_batch_rescrape_uses_the_cache_and_keeps_maxthreads(big_gamelist, client, fake_ss, secret_config):
    server = fake_ss(maxthreads=2, delay=0.05)
    secret_config()
    run_all(client, start(client, fields=["developer"]))
    first = len(api_calls(server))
    assert first == len(ROMS) and server.peak <= 2
    # Same games again (mode "all"): every answer from the cache, nothing sent.
    r = client.post("/api/batch", headers=LOCAL, json={"source": "screenscraper", "mode": "all", "fields": ["developer"],
                                                       "paths": [f"./{rom}" for rom in ROMS], "backup": False})
    run_all(client, r.get_json()["job"])
    assert len(api_calls(server)) == first
    # "Ignore the cache": every game asked again, still never more than maxthreads.
    r = client.post("/api/batch", headers=LOCAL, json={"source": "screenscraper", "mode": "all", "fields": ["developer"],
                                                       "paths": [f"./{rom}" for rom in ROMS], "backup": False, "refresh": True})
    run_all(client, r.get_json()["job"])
    assert len(api_calls(server)) == 2 * first and server.peak <= 2
    assert developers(big_gamelist).count(None) == 0


def test_concurrent_reads_and_writes_of_one_answer(tmp_path):
    data = {"header": {"success": "true"}, "response": {"jeu": {"id": "1", "noms": [{"text": "x" * 2000}]}}}
    errors = []

    def worker():
        try:
            for _ in range(30):
                ss_cache.put("jeuInfos.php", HASH, data)
                hit = ss_cache.get("jeuInfos.php", HASH, 30)
                assert hit is None or hit[1]["response"]["jeu"]["id"] == "1"
        except Exception as e:                     # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert not errors
    assert len(cached_files()) == 1


def test_settings_save_clamp_and_empty(client, fake_ss, secret_config):
    fake_ss(maxthreads=2)
    secret_config()
    cfg = client.post("/api/ss/config", headers=LOCAL, json={"cache_enabled": False, "cache_days": 999}).get_json()["config"]
    assert cfg["cache_enabled"] is False and cfg["cache_days"] == 30
    cfg = client.post("/api/ss/config", headers=LOCAL, json={"cache_enabled": True, "cache_days": 90}).get_json()["config"]
    assert cfg["cache_enabled"] is True and cfg["cache_days"] == 90
    assert "pw-Secret-42" not in json.dumps(cfg)
    ss.ss_request("jeuInfos.php", HASH)
    stats = client.get("/api/ss/cache", headers=LOCAL).get_json()
    assert stats["entries"] == 1 and stats["bytes"] > 0
    assert client.get("/api/ss/config", headers=LOCAL).get_json()["cache"]["entries"] == 1
    cleared = client.post("/api/ss/cache/clear", headers=LOCAL).get_json()
    assert cleared["removed"] == 1 and cleared["entries"] == 0 and cached_files() == []


def test_prune_removes_old_answers(fake_ss, secret_config, monkeypatch):
    import os
    fake_ss(maxthreads=2)
    secret_config()
    ss.ss_request("jeuInfos.php", HASH)
    path = cached_files()[0]
    old = time.time() - 40 * 86400
    os.utime(path, (old, old))
    assert ss_cache.prune(30) == 1 and cached_files() == []
