"""Per-game routes: the ?path= guard against stale XML indexes."""
import os

import app
from conftest import LOCAL, names


def rename(client, index, path, new_name):
    url = f"/api/name/{index}" + (f"?path={path}" if path is not None else "")
    return client.post(url, json={"name": new_name}, headers=LOCAL)


def remove_first_game_on_disk(xml):
    """Simulate an edit outside the app: Alpha disappears, indexes shift."""
    text = xml.read_text(encoding="utf-8")
    text = text.replace("<game><path>./alpha.zip</path><name>Alpha</name></game>", "")
    xml.write_text(text, encoding="utf-8")
    st = os.stat(xml)
    os.utime(xml, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))  # bust mtime cache


def test_matching_path_uses_index(gamelist, client):
    r = rename(client, 1, "./bravo.zip", "Bravo II")
    assert r.status_code == 200
    assert "X-Game-Reindexed" not in r.headers
    assert names(gamelist) == ["Alpha", "Bravo II", "Charlie"]


def test_moved_game_is_retargeted_by_path(gamelist, client):
    remove_first_game_on_disk(gamelist)        # Bravo: index 1 -> 0, Charlie: 2 -> 1
    r = rename(client, 1, "./bravo.zip", "Bravo II")  # UI still thinks Bravo is #1
    assert r.status_code == 200
    assert r.headers["X-Game-Reindexed"] == "0"
    assert names(gamelist) == ["Bravo II", "Charlie"]   # Charlie untouched


def test_delete_never_hits_the_wrong_game(gamelist, client):
    remove_first_game_on_disk(gamelist)
    r = client.post("/api/delete-game/1?path=./bravo.zip", json={}, headers=LOCAL)
    assert r.status_code == 200
    assert names(gamelist) == ["Charlie"]
    assert not (gamelist.parent / "bravo.zip").exists()
    assert (gamelist.parent / "charlie.zip").exists()


def test_vanished_game_returns_409(gamelist, client):
    remove_first_game_on_disk(gamelist)
    r = client.post("/api/delete-game/0?path=./alpha.zip", json={}, headers=LOCAL)
    assert r.status_code == 409
    assert r.get_json()["code"] == "stale_game"
    assert names(gamelist) == ["Bravo", "Charlie"]
    assert (gamelist.parent / "bravo.zip").exists()


def test_ambiguous_duplicate_path_returns_409(gamelist, client):
    text = gamelist.read_text(encoding="utf-8").replace("./charlie.zip", "./bravo.zip")
    gamelist.write_text(text, encoding="utf-8")
    app._xml_cache.update(mtime=None, tree=None)
    r = rename(client, 0, "./bravo.zip", "X")   # index 0 is Alpha, 2 games own the path
    assert r.status_code == 409


def test_without_path_param_keeps_index_behaviour(gamelist, client):
    r = rename(client, 2, None, "Charlie II")
    assert r.status_code == 200
    assert names(gamelist)[2] == "Charlie II"


def test_stale_message_is_localized(gamelist, client):
    remove_first_game_on_disk(gamelist)
    r = client.post("/api/delete-game/0?path=./alpha.zip", json={},
                    headers={**LOCAL, "X-Locale": "en"})
    assert "gamelist.xml" in r.get_json()["error"]
    assert r.get_json()["error"] != "server.stale_game"
