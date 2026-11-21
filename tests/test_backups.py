"""Dated snapshots preserve exact XML bytes and make restoration reversible."""
import os

import pytest

from gme import backups, xml_store
from conftest import LOCAL


def history(client):
    response = client.get("/api/backups", headers=LOCAL)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["backups"]


def test_dated_backups_keep_the_compatible_bak(gamelist, client):
    before = gamelist.read_bytes()
    assert client.post("/api/backup", headers=LOCAL).status_code == 200
    first = history(client)
    assert len(first) == 1
    assert first[0]["size"] == len(before)
    assert first[0]["created"].endswith("+00:00")
    assert gamelist.with_suffix(".xml.bak").read_bytes() == before
    assert (gamelist.parent / ".gme-backups" / gamelist.name / first[0]["id"]).read_bytes() == before
    client.post("/api/backup", headers=LOCAL)
    assert len(history(client)) == 2


def test_restoration_can_itself_be_undone(gamelist, client):
    original = gamelist.read_bytes()
    client.post("/api/backup", headers=LOCAL)
    selected = history(client)[0]["id"]
    client.post("/api/game/0", headers=LOCAL, json={"name": "Edited Alpha"})
    edited = gamelist.read_bytes()
    session = xml_store.SESSION_ID
    response = client.post("/api/backups/restore", headers=LOCAL, json={"id": selected})
    assert response.status_code == 200
    assert response.get_json()["session_id"] != session
    assert gamelist.read_bytes() == original
    assert xml_store.load_xml().findtext("game/name") == "Alpha"
    previous = response.get_json()["previous"]
    assert history(client)[0]["reason"] == "restore"
    assert (gamelist.parent / ".gme-backups" / gamelist.name / previous).read_bytes() == edited
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": previous}).status_code == 200
    assert gamelist.read_bytes() == edited


def test_two_xml_files_have_separate_history(gamelist, client):
    client.post("/api/backup", headers=LOCAL)
    selected = history(client)[0]["id"]
    other = gamelist.with_name("other.xml")
    other.write_text("<gameList/>", encoding="utf-8")
    xml_store.set_gamelist_path(str(other))
    assert history(client) == []
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": selected}).status_code == 404
    assert other.read_text(encoding="utf-8") == "<gameList/>"


def test_legacy_bak_is_preserved_when_upgrading(gamelist, client):
    legacy = b"<gameList><game><name>Legacy</name></game></gameList>"
    gamelist.with_suffix(".xml.bak").write_bytes(legacy)
    entries = history(client)
    assert len(entries) == 1
    assert entries[0]["reason"] == "legacy"
    assert client.post("/api/backup", headers=LOCAL).status_code == 200
    assert len(history(client)) == 2
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": entries[0]["id"]}).status_code == 200
    assert gamelist.read_bytes() == legacy


@pytest.mark.parametrize("name", ["../gamelist.xml", "../../outside.xml", "C:\\outside.xml", "bad", None])
def test_restore_refuses_paths(gamelist, client, name):
    before = gamelist.read_bytes()
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": name}).status_code == 400
    assert gamelist.read_bytes() == before


def test_invalid_backup_changes_nothing(gamelist, client):
    client.post("/api/backup", headers=LOCAL)
    entry = history(client)[0]
    with open(os.path.join(backups.backup_dir(), entry["id"]), "wb") as stream:
        stream.write(b"<not-a-gamelist/>")
    before = gamelist.read_bytes()
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": entry["id"]}).status_code == 422
    assert gamelist.read_bytes() == before
    assert len(history(client)) == 1


def test_locked_restore_keeps_the_original(gamelist, client, monkeypatch):
    client.post("/api/backup", headers=LOCAL)
    entry = history(client)[0]
    client.post("/api/game/0", headers=LOCAL, json={"name": "Newer Alpha"})
    before = gamelist.read_bytes()
    real = backups.atomic_write

    def locked(path, data):
        if os.path.normcase(str(path)) == os.path.normcase(str(gamelist)):
            raise PermissionError("locked")
        real(path, data)

    monkeypatch.setattr(backups, "atomic_write", locked)
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": entry["id"]}).status_code == 500
    assert gamelist.read_bytes() == before


def test_retention_and_restoring_the_oldest_entry(gamelist, client, monkeypatch):
    monkeypatch.setattr(backups, "MAX_BACKUPS", 3)
    for index in range(5):
        client.post("/api/game/0", headers=LOCAL, json={"name": str(index)})
        assert client.post("/api/backup", headers=LOCAL).status_code == 200
    entries = history(client)
    assert len(entries) == 3
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": entries[-1]["id"]}).status_code == 200
    assert xml_store.load_xml().findtext("game/name") == "2"
    assert len(history(client)) == 3
