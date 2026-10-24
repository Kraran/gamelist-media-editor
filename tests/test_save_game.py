"""POST /api/game/<index>: several fields saved in one validated write."""
from lxml import etree

from gme import xml_store
from conftest import LOCAL


def game(xml, i=0):
    g = etree.parse(str(xml)).getroot().findall("game")[i]
    return {c.tag: c.text or "" for c in g}, [c.tag for c in g]


def save(client, i, path, body):
    return client.post(f"/api/game/{i}?path={path}", json=body, headers=LOCAL)


def test_name_desc_and_metadata_in_one_write(gamelist, client, monkeypatch):
    writes = []
    real = xml_store.save_xml
    monkeypatch.setattr("gme.editor.save_xml", lambda tree: (writes.append(1), real(tree)))
    r = save(client, 0, "./alpha.zip", {"name": " Alpha II ", "desc": "New", "players": "1-4", "rating": "0.7", "favorite": "true"})
    assert r.status_code == 200
    assert len(writes) == 1
    values, order = game(gamelist)
    assert values["name"] == "Alpha II" and values["desc"] == "New"
    assert values["players"] == "1-4" and values["rating"] == "0.7" and values["favorite"] == "true"
    assert order[:3] == ["path", "name", "desc"]          # desc inserted right after the name
    assert r.get_json()["updated"]["name"] == "Alpha II"


def test_invalid_value_changes_nothing(gamelist, client):
    before = gamelist.read_bytes()
    r = save(client, 0, "./alpha.zip", {"players": "2", "rating": "7"})
    assert r.status_code == 400 and r.get_json()["code"] == "rating_range"
    assert gamelist.read_bytes() == before
    # the cached tree was not touched either: a later save does not carry "players"
    save(client, 0, "./alpha.zip", {"developer": "Studio"})
    assert "players" not in game(gamelist)[0]


def test_empty_name_is_refused(gamelist, client):
    r = save(client, 0, "./alpha.zip", {"name": "   "})
    assert r.status_code == 400 and r.get_json()["code"] == "empty_name"


def test_clearing_a_field_removes_its_tag(gamelist, client):
    save(client, 1, "./bravo.zip", {"developer": "X"})
    assert "developer" in game(gamelist, 1)[0]
    save(client, 1, "./bravo.zip", {"developer": ""})
    assert "developer" not in game(gamelist, 1)[0]


def test_unknown_fields_are_ignored(gamelist, client):
    before = game(gamelist)[0]
    r = save(client, 0, "./alpha.zip", {"path": "../../evil", "image": "x.png", "players": "2"})
    assert r.status_code == 200
    after = game(gamelist)[0]
    assert after["path"] == before["path"] and "image" not in after and after["players"] == "2"


def test_follows_a_game_that_moved(gamelist, client):
    text = gamelist.read_text(encoding="utf-8").replace("<game><path>./alpha.zip</path><name>Alpha</name></game>", "")
    gamelist.write_text(text, encoding="utf-8")
    xml_store._xml_cache.update(mtime=None, tree=None)
    r = save(client, 1, "./bravo.zip", {"players": "3"})       # Bravo is now index 0
    assert r.status_code == 200 and r.headers["X-Game-Reindexed"] == "0"
    assert game(gamelist, 0)[0]["players"] == "3"


def test_empty_body_is_refused(gamelist, client):
    assert save(client, 0, "./alpha.zip", {}).status_code == 400
