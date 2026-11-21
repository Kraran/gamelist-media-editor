"""An in-flight operation and an old tab cannot overwrite another gamelist."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from gme import xml_store
from gme.server import app
from conftest import LOCAL


def other_gamelist(tmp_path):
    other = tmp_path / "other.xml"
    # Same ROM path: game identity alone cannot distinguish these two lists.
    other.write_text('<gameList><game><path>./alpha.zip</path><name>Other</name></game></gameList>', encoding="utf-8")
    return other


def test_old_tree_cannot_be_saved_into_another_file(gamelist, tmp_path):
    tree = xml_store.load_xml()
    tree.find("game/name").text = "Edited Alpha"
    other = other_gamelist(tmp_path)
    before = other.read_bytes()
    xml_store.set_gamelist_path(str(other))
    with pytest.raises(ValueError):
        xml_store.save_xml(tree)
    assert other.read_bytes() == before


def test_old_tab_is_refused_even_when_the_rom_path_matches(gamelist, client, tmp_path):
    session = client.get("/api/games").get_json()["session_id"]
    other = other_gamelist(tmp_path)
    opened = client.post("/api/open-gamelist", json={"path": str(other)}, headers=LOCAL)
    assert opened.status_code == 200
    assert opened.get_json()["session_id"] != session
    before = other.read_bytes()
    response = client.post("/api/game/0?path=./alpha.zip", json={"name": "Wrong list"},
                           headers={**LOCAL, "X-Gamelist-Session": session})
    assert response.status_code == 409
    assert response.get_json()["code"] == "stale_gamelist"
    assert other.read_bytes() == before
    # The rejected request must release its lock as well.
    assert client.get("/api/games").status_code == 200


def test_reopening_the_same_path_invalidates_an_old_session(gamelist, client):
    session = xml_store.SESSION_ID
    xml_store.set_gamelist_path(str(gamelist))
    response = client.post("/api/backup", headers={**LOCAL, "X-Gamelist-Session": session})
    assert response.status_code == 409
    assert not gamelist.with_suffix(".xml.bak").exists()


def test_reload_can_recover_from_an_old_session(gamelist, client):
    session = xml_store.SESSION_ID
    xml_store.set_gamelist_path(str(gamelist))
    response = client.get("/api/games", headers={**LOCAL, "X-Gamelist-Session": session})
    assert response.status_code == 200
    assert response.get_json()["session_id"] == xml_store.SESSION_ID


def test_xml_paths_with_spaces_accents_and_percent_can_be_saved(tmp_path):
    path = tmp_path / "Jeux à 100%.xml"
    path.write_text('<gameList><game><name>Alpha</name></game></gameList>', encoding="utf-8")
    try:
        xml_store.set_gamelist_path(str(path))
        tree = xml_store.load_xml()
        tree.find("game/name").text = "Edited Alpha"
        xml_store.save_xml(tree)
        assert b"Edited Alpha" in path.read_bytes()
    finally:
        xml_store.close_gamelist()


def test_switch_waits_until_the_running_operation_is_saved(gamelist, tmp_path, monkeypatch):
    other = other_gamelist(tmp_path)
    before = other.read_bytes()
    saving, release, switching = threading.Event(), threading.Event(), threading.Event()
    real_save = xml_store.save_xml

    def delayed_save(tree):
        saving.set()
        assert release.wait(5)
        real_save(tree)

    monkeypatch.setattr("gme.editor.save_xml", delayed_save)

    def edit():
        with app.test_client() as client:
            return client.post("/api/game/0?path=./alpha.zip", json={"name": "Edited Alpha"}, headers=LOCAL).status_code

    def switch():
        switching.set()
        with app.test_client() as client:
            return client.post("/api/open-gamelist", json={"path": str(other)}, headers=LOCAL).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        editing = executor.submit(edit)
        try:
            assert saving.wait(5)
            opening = executor.submit(switch)
            assert switching.wait(5)
            assert xml_store.XML_PATH == str(gamelist)
            assert not opening.done()
        finally:
            release.set()
        assert editing.result(timeout=5) == 200
        assert opening.result(timeout=5) == 200
    assert b"Edited Alpha" in gamelist.read_bytes()
    assert other.read_bytes() == before
