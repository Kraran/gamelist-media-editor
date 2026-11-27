"""Multi-level undo / redo of the gamelist (gme/history.py, /api/history*)."""
import os
import time

from lxml import etree

from gme import history, xml_store
from tests.conftest import LOCAL, names


def save_name(client, index, path, name):
    r = client.post(f"/api/game/{index}?path={path}", json={"name": name}, headers=LOCAL)
    assert r.status_code == 200, r.get_json()
    return r


def state(client):
    return client.get("/api/history", headers=LOCAL).get_json()


def test_steps_undo_redo_in_order(client, gamelist):
    original = gamelist.read_bytes()
    save_name(client, 0, "./alpha.zip", "Alpha 1")
    save_name(client, 0, "./alpha.zip", "Alpha 2")
    save_name(client, 1, "./bravo.zip", "Bravo 1")
    h = state(client)
    assert [e["label"]["key"] for e in h["entries"]] == ["save", "save", "save"]
    assert h["undo"]["label"]["params"]["game"] == "Bravo 1"
    assert h["redo"] is None

    r = client.post("/api/history/undo", headers=LOCAL)
    assert r.status_code == 200
    assert names(gamelist) == ["Alpha 2", "Bravo", "Charlie"]
    assert r.get_json()["redo"]["label"]["params"]["game"] == "Bravo 1"
    client.post("/api/history/undo", headers=LOCAL)
    client.post("/api/history/undo", headers=LOCAL)
    assert gamelist.read_bytes() == original           # byte for byte
    r = client.post("/api/history/undo", headers=LOCAL)
    assert r.status_code == 409 and r.get_json()["code"] == "history_nothing_undo"

    client.post("/api/history/redo", headers=LOCAL)
    client.post("/api/history/redo", headers=LOCAL)
    assert names(gamelist) == ["Alpha 2", "Bravo", "Charlie"]
    client.post("/api/history/redo", headers=LOCAL)
    assert names(gamelist) == ["Alpha 2", "Bravo 1", "Charlie"]
    assert client.post("/api/history/redo", headers=LOCAL).status_code == 409


def test_new_edit_clears_redo(client, gamelist):
    save_name(client, 0, "./alpha.zip", "A1")
    save_name(client, 0, "./alpha.zip", "A2")
    client.post("/api/history/undo", headers=LOCAL)
    assert state(client)["redo"] is not None
    save_name(client, 1, "./bravo.zip", "B1")
    h = state(client)
    assert h["redo"] is None
    assert len(h["entries"]) == 2 and all(e["done"] for e in h["entries"])
    assert client.post("/api/history/redo", headers=LOCAL).status_code == 409
    client.post("/api/history/undo", headers=LOCAL)
    assert names(gamelist) == ["A1", "Bravo", "Charlie"]


def test_undo_opens_a_new_session_and_reloads(client, gamelist):
    save_name(client, 0, "./alpha.zip", "A1")
    before = xml_store.SESSION_ID
    d = client.post("/api/history/undo", headers=LOCAL).get_json()
    assert d["session_id"] == xml_store.SESSION_ID != before
    games = client.get("/api/games", headers=LOCAL).get_json()["games"]
    assert games[0]["name"] == "Alpha"                   # the cache follows the file


def test_outside_change_resets_instead_of_overwriting(client, gamelist):
    save_name(client, 0, "./alpha.zip", "A1")
    text = gamelist.read_text(encoding="utf-8").replace("Charlie", "Charlie (edited elsewhere)")
    gamelist.write_text(text, encoding="utf-8")
    r = client.post("/api/history/undo", headers=LOCAL)
    assert r.status_code == 409 and r.get_json()["code"] == "history_external"
    assert "Charlie (edited elsewhere)" in gamelist.read_text(encoding="utf-8")
    assert "A1" in gamelist.read_text(encoding="utf-8")
    assert state(client)["entries"] == []


def test_a_request_is_one_step(client, gamelist):
    r = client.post("/api/bulk", json={"paths": ["./alpha.zip", "./bravo.zip", "./charlie.zip"],
                                       "op": {"kind": "set", "field": "genre", "value": "Action"}}, headers=LOCAL)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["changed"] == 3
    h = state(client)
    assert len(h["entries"]) == 1
    e = h["entries"][0]
    assert e["label"]["key"] == "bulk" and e["label"]["params"] == {"n": 3, "games": 3, "field": "genre"}
    assert r.headers["X-GME-History-Step"] == e["id"]
    client.post("/api/history/undo", json={"expect": e["id"]}, headers=LOCAL)
    assert "<genre>" not in gamelist.read_text(encoding="utf-8")


def test_expect_refuses_another_step(client, gamelist):
    first = save_name(client, 0, "./alpha.zip", "A1").headers["X-GME-History-Step"]
    save_name(client, 1, "./bravo.zip", "B1")
    r = client.post("/api/history/undo", json={"expect": first}, headers=LOCAL)
    assert r.status_code == 409 and r.get_json()["code"] == "history_moved"
    assert names(gamelist) == ["A1", "B1", "Charlie"]


def test_to_undoes_and_redoes_several_steps(client, gamelist):
    ids = [save_name(client, 0, "./alpha.zip", f"A{i}").headers["X-GME-History-Step"] for i in range(4)]
    d = client.post("/api/history/undo", json={"to": ids[1]}, headers=LOCAL).get_json()
    assert len(d["steps"]) == 3
    assert names(gamelist)[0] == "A0"
    d = client.post("/api/history/redo", json={"to": ids[2]}, headers=LOCAL).get_json()
    assert len(d["steps"]) == 2
    assert names(gamelist)[0] == "A2"


def test_same_bytes_make_no_step(client, gamelist):
    save_name(client, 0, "./alpha.zip", "Alpha")          # no change at all
    save_name(client, 0, "./alpha.zip", "Alpha")
    entries = state(client)["entries"]
    assert len(entries) <= 1


def test_limit_keeps_the_last_steps(client, gamelist, monkeypatch):
    monkeypatch.setattr(history, "MAX_STEPS", 5)
    for i in range(8):
        save_name(client, 0, "./alpha.zip", f"A{i}")
    h = state(client)
    assert len(h["entries"]) == 5
    for _ in range(5):
        assert client.post("/api/history/undo", headers=LOCAL).status_code == 200
    assert names(gamelist)[0] == "A2"
    assert client.post("/api/history/undo", headers=LOCAL).status_code == 409


def test_states_are_compressed_and_shared(gamelist):
    tree = xml_store.load_xml()
    for i in range(3):
        tree.getroot().findall("game")[0].find("name").text = f"N{i}"
        xml_store.save_xml(tree)
    store = history._store(str(gamelist), create=False)
    assert len(store.entries) == 3
    for a, b in zip(store.entries, store.entries[1:]):
        assert a.after is b.before                      # one copy per version
    assert all(len(e.before.blob) < e.before.size or e.before.size < 200 for e in store.entries)


def test_backup_restore_is_a_step_and_backups_still_work(client, gamelist):
    _bak, oldest = xml_store.backup_xml_snapshot()       # the original, as a dated snapshot
    save_name(client, 0, "./alpha.zip", "A1")
    r = client.post("/api/backups/restore", json={"id": oldest}, headers=LOCAL)
    assert r.status_code == 200
    h = state(client)
    assert h["undo"]["label"]["key"] == "restore"
    assert names(gamelist)[0] == "Alpha"
    client.post("/api/history/undo", headers=LOCAL)
    assert names(gamelist)[0] == "A1"
    client.post("/api/history/redo", headers=LOCAL)
    assert names(gamelist)[0] == "Alpha"


def test_trash_is_reported_not_restored(client, gamelist, tmp_path, trashed):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.png").write_bytes(b"x")
    tree = etree.parse(str(gamelist))
    etree.SubElement(tree.getroot().findall("game")[0], "image").text = "./images/a.png"
    tree.write(str(gamelist), xml_declaration=True, encoding="UTF-8")
    xml_store.invalidate_cache()
    r = client.post("/api/bulk-delete", json={"paths": ["./alpha.zip"], "media": True}, headers=LOCAL)
    assert r.status_code == 200, r.get_json()
    e = state(client)["undo"]
    assert e["label"]["key"] == "bulk_delete" and e["trashed"] == 1
    d = client.post("/api/history/undo", headers=LOCAL).get_json()
    assert d["trashed"] == 1
    assert names(gamelist) == ["Alpha", "Bravo", "Charlie"]
    assert not (tmp_path / "images" / "a.png").exists()    # the XML only: the file is in the Bin


def test_batch_scrape_steps_merge_into_one(client, gamelist):
    # Two requests of the same batch scope: one step
    for name in ("A1", "A2"):
        with client.application.test_request_context("/api/x"):
            history.scope("batch:abc")
            history.label("batch", source="screenscraper")
            tree = xml_store.load_xml()
            tree.getroot().findall("game")[0].find("name").text = name
            xml_store.save_xml(tree)
            history.finish()
    h = state(client)
    assert len(h["entries"]) == 1 and h["entries"][0]["merged"] == 2
    history._busy["batch"] = 0.0
    client.post("/api/history/undo", headers=LOCAL)
    assert names(gamelist)[0] == "Alpha"


def test_busy_batch_refuses_undo(client, gamelist, monkeypatch):
    save_name(client, 0, "./alpha.zip", "A1")
    monkeypatch.setattr(history, "_busy_reason", lambda: "history.busy_batch")
    r = client.post("/api/history/undo", headers=LOCAL)
    assert r.status_code == 409 and r.get_json()["code"] == "history_busy_batch"
    assert names(gamelist)[0] == "A1"


def test_histories_are_per_gamelist(client, gamelist, tmp_path):
    save_name(client, 0, "./alpha.zip", "A1")
    other = tmp_path / "other" / "gamelist.xml"
    other.parent.mkdir()
    other.write_text('<?xml version="1.0"?>\n<gameList><game><path>./x.zip</path><name>X</name></game></gameList>\n')
    xml_store.set_gamelist_path(str(other))
    assert state(client)["entries"] == []
    xml_store.set_gamelist_path(str(gamelist))
    assert len(state(client)["entries"]) == 1


def test_save_outside_a_request_is_one_step_each(gamelist):
    tree = xml_store.load_xml()
    tree.getroot().findall("game")[1].find("name").text = "B"
    xml_store.save_xml(tree)
    tree.getroot().findall("game")[2].find("name").text = "C"
    xml_store.save_xml(tree)
    assert len(history.status(str(gamelist))["entries"]) == 2


def test_revision_header_moves_on_change(client, gamelist):
    r0 = client.get("/api/history", headers=LOCAL).headers["X-GME-History"]
    save_name(client, 0, "./alpha.zip", "A1")
    r1 = client.get("/api/history", headers=LOCAL).headers["X-GME-History"]
    assert int(r1) > int(r0)


def test_outside_change_then_a_new_save_starts_over(client, gamelist):
    save_name(client, 0, "./alpha.zip", "A1")
    gamelist.write_text(gamelist.read_text(encoding="utf-8").replace("Charlie", "Charlie X"), encoding="utf-8")
    xml_store.invalidate_cache()
    save_name(client, 1, "./bravo.zip", "B1")
    h = state(client)
    assert len(h["entries"]) == 1                      # the step before the outside change is gone
    client.post("/api/history/undo", headers=LOCAL)
    assert names(gamelist) == ["A1", "Bravo", "Charlie X"]   # the outside change is kept
