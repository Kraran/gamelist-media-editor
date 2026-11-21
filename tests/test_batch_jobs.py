"""Checkpoints survive process loss, repeated requests and competing tabs."""
import pytest
from flask import jsonify

from gme import batch_jobs, xml_store
from gme.scrapers.compare import scrape_payload
from gme.scrapers import apply as scrape_apply
from conftest import LOCAL


@pytest.fixture
def source(monkeypatch):
    calls = []

    def scrape(index, body=None):
        _, game = xml_store.get_game_elem(index)
        calls.append(game.findtext("path"))
        proposed = {"developer": "Studio " + game.findtext("name"), "medias": {"image": {"url": "https://source.test/img?password=secret"}}}
        return jsonify({"proposed": proposed, **scrape_payload(game, proposed)})

    monkeypatch.setitem(batch_jobs.SOURCES, "screenscraper", scrape)
    return calls


def start(client, **patch):
    response = client.post("/api/batch", headers=LOCAL, json={
        "source": "screenscraper", "mode": "missing", "fields": ["developer"],
        "paths": ["./alpha.zip", "./bravo.zip", "./charlie.zip"], **patch})
    assert response.status_code == 200, response.get_json()
    return response.get_json()["job"]


def step(client, job, **patch):
    return client.post("/api/batch/step", headers=LOCAL,
                       json={"id": job["id"], "owner": job["owner"], "i": job["i"], **patch})


def saved(client):
    response = client.get("/api/batch", headers=LOCAL)
    assert response.status_code == 200
    return response.get_json()["job"]


def test_process_loss_replays_the_journal(gamelist, client, source, monkeypatch):
    job = start(client)
    assert step(client, job).status_code == 200
    monkeypatch.setattr(batch_jobs, "_cache", None)
    xml_store.set_gamelist_path(str(gamelist))
    checkpoint = saved(client)
    assert checkpoint["i"] == 1
    assert checkpoint["results"]["updated"][0]["path"] == "./alpha.zip"
    assert "owner" not in checkpoint
    response = client.post("/api/batch/claim", headers=LOCAL, json={"id": checkpoint["id"]})
    resumed = response.get_json()["job"]
    assert step(client, resumed).status_code == 200
    assert source == ["./alpha.zip", "./bravo.zip"]
    assert saved(client)["i"] == 2


def test_repeating_a_step_cannot_advance_the_next_game(gamelist, client, source):
    job = start(client)
    assert step(client, job).get_json()["i"] == 1
    assert step(client, job).get_json()["job"]["i"] == 1
    assert source == ["./alpha.zip"]


def test_another_tab_claims_exclusive_control(gamelist, client, source):
    job = start(client)
    claimed = client.post("/api/batch/claim", headers=LOCAL, json={"id": job["id"]}).get_json()["job"]
    assert step(client, job).status_code == 409
    assert source == []
    assert step(client, claimed).status_code == 200


def test_retry_does_not_discard_unprocessed_targets(gamelist, client, source):
    job = start(client)
    response = client.post("/api/batch/claim", headers=LOCAL, json={"id": job["id"], "retry": True})
    assert response.status_code == 400
    assert saved(client)["targets"] == job["targets"]
    assert step(client, job).get_json()["i"] == 1


def test_reordered_xml_uses_paths_not_saved_indexes(gamelist, client, source):
    job = start(client)
    tree = xml_store.load_xml()
    root = tree.getroot()
    first = root.find("game")
    root.remove(first)
    root.append(first)
    xml_store.save_xml(tree)
    assert step(client, job).status_code == 200
    assert source == ["./alpha.zip"]


def test_steps_append_results_without_rewriting_the_full_plan(gamelist, client, source):
    job = start(client)
    from pathlib import Path
    manifest = Path(batch_jobs._path()).read_bytes()
    assert step(client, job).status_code == 200
    assert Path(batch_jobs._path()).read_bytes() == manifest
    assert Path(batch_jobs._events_path(job)).stat().st_size > 0


def test_xml_write_failure_pauses_the_batch(gamelist, client, source, monkeypatch):
    job = start(client)
    before = gamelist.read_bytes()

    def locked(*args):
        raise PermissionError("XML locked")

    monkeypatch.setattr(xml_store, "atomic_write", locked)
    assert step(client, job).get_json()["halted"] == "XML locked"
    assert gamelist.read_bytes() == before
    assert step(client, {**job, "i": 1}).get_json()["job"]["i"] == 1
    assert source == ["./alpha.zip"]


def test_old_session_cannot_apply_to_another_gamelist(gamelist, client, tmp_path, source):
    job = start(client)
    session = xml_store.SESSION_ID
    other = tmp_path / "other.xml"
    other.write_bytes(gamelist.read_bytes())
    xml_store.set_gamelist_path(str(other))
    assert saved(client) is None
    response = client.post("/api/batch/step", headers={**LOCAL, "X-Gamelist-Session": session},
                           json={"id": job["id"], "owner": job["owner"], "i": 0})
    assert response.status_code == 409
    assert source == []


def test_partial_retry_preserves_successful_fields_and_hides_credentials(gamelist, client, source, monkeypatch, batch_state_dir):
    def failed(*args, **kwargs):
        raise OSError("Failed https://source.test/img?password=secret")

    monkeypatch.setattr(scrape_apply, "download_remote_media", failed)
    job = start(client, fields=["developer", "image"], paths=["./alpha.zip"], mode="all")
    result = step(client, job).get_json()["result"]
    assert result["kind"] == "updated"
    assert result["game"]["retry_fields"] == ["image"]
    assert "secret" not in result["game"]["warnings"][0]
    raw = "".join(p.read_text(encoding="utf-8") for p in batch_state_dir.iterdir())
    assert "secret" not in raw and "source.test" not in raw
    retry = client.post("/api/batch/claim", headers=LOCAL, json={"id": job["id"], "retry": True}).get_json()["job"]
    assert retry["targets"][0]["fields"] == ["image"]
    written = []
    original = scrape_apply.apply_proposed

    def record(game, fields, proposed, **kwargs):
        written.extend(fields)
        return original(game, fields, proposed, **kwargs)

    monkeypatch.setattr(scrape_apply, "apply_proposed", record)
    assert step(client, retry).status_code == 200
    assert written == ["image"]


def test_quota_halts_until_explicit_resume(gamelist, client, monkeypatch, source):
    original = batch_jobs.SOURCES["screenscraper"]
    monkeypatch.setitem(batch_jobs.SOURCES, "screenscraper", lambda index, body=None: (jsonify({"error": "Quota", "code": "source_blocked"}), 503))
    job = start(client)
    assert step(client, job).get_json()["halted"] == "Quota"
    assert step(client, {**job, "i": 1}).get_json()["job"]["i"] == 1
    monkeypatch.setitem(batch_jobs.SOURCES, "screenscraper", original)
    resumed = client.post("/api/batch/claim", headers=LOCAL, json={"id": job["id"]}).get_json()["job"]
    assert step(client, resumed).get_json()["i"] == 2
    assert source == ["./bravo.zip"]


@pytest.mark.parametrize("tail", [
    b'{"i":2,"kind":',
    b'{"i":2,"kind":"nothing","game":{"path":"./bravo.zip","name":"Bravo"},"halted":""}',
], ids=["truncated-json", "missing-newline"])
def test_truncated_final_checkpoint_is_repaired(gamelist, client, source, monkeypatch, tail):
    job = start(client)
    step(client, job)
    with open(batch_jobs._events_path(job), "ab") as stream:
        stream.write(tail)
    monkeypatch.setattr(batch_jobs, "_cache", None)
    assert saved(client)["i"] == 1
    resumed = client.post("/api/batch/claim", headers=LOCAL, json={"id": job["id"]}).get_json()["job"]
    assert step(client, resumed).get_json()["i"] == 2
    monkeypatch.setattr(batch_jobs, "_cache", None)
    assert saved(client)["i"] == 2


@pytest.mark.parametrize("patch", [{"source": []}, {"fields": ["path"]}, {"paths": []}, {"paths": [42]}, {"mode": "none"}])
def test_invalid_options_change_nothing(gamelist, client, patch):
    before = gamelist.read_bytes()
    response = client.post("/api/batch", headers=LOCAL, json={"source": "screenscraper", "mode": "missing", "fields": ["developer"], "paths": ["./alpha.zip"], **patch})
    assert response.status_code == 400
    assert saved(client) is None
    assert gamelist.read_bytes() == before
