"""/api/games (light list) and /api/game/<index> (one game, description included)."""
from lxml import etree

from gme import xml_store

H = {"Host": "127.0.0.1:5050"}

XML = """<?xml version="1.0"?>
<gameList>
  <game><path>./b.zip</path><name>Bravo</name><desc>Long text</desc><image>./images/b.png</image><genre></genre></game>
  <!-- a comment between games -->
  <game><path>./a.zip</path><name>alpha</name><image>./images/a1.png</image><image>./images/a2.png</image><!-- c --><players>1-2</players></game>
  <game><path>./roms/c.zip</path></game>
</gameList>
"""


def open_xml(tmp_path, text=XML):
    x = tmp_path / "gamelist.xml"
    x.write_text(text, encoding="utf-8")
    xml_store.set_gamelist_path(str(x))
    return x


def test_list_is_sorted_light_and_without_description(tmp_path, client):
    open_xml(tmp_path)
    games = client.get("/api/games", headers=H).get_json()["games"]
    assert [g["name"] for g in games] == ["alpha", "Bravo", "c.zip"]       # case-insensitive sort, name fallback
    assert all("desc" not in g for g in games)
    bravo = games[1]
    assert bravo == {"index": 0, "path": "./b.zip", "name": "Bravo", "image": "./images/b.png"}  # empty <genre> omitted


def test_first_occurrence_wins_like_findtext(tmp_path, client):
    open_xml(tmp_path)
    alpha = client.get("/api/games", headers=H).get_json()["games"][0]
    assert alpha["image"] == "./images/a1.png" and alpha["players"] == "1-2" and alpha["index"] == 1


def test_same_values_as_findtext_on_every_field(tmp_path):
    x = open_xml(tmp_path)
    root = etree.parse(str(x)).getroot()
    for g in xml_store.get_games(etree.parse(str(x))):
        game = root.findall("game")[g["index"]]
        for field in xml_store.LIST_FIELDS - {"name"}:
            assert g.get(field, "") == (game.findtext(field, "") or ""), (g["index"], field)


def test_detail_includes_the_description(tmp_path, client):
    open_xml(tmp_path)
    r = client.get("/api/game/0?path=./b.zip", headers=H)
    assert r.status_code == 200
    assert r.get_json()["desc"] == "Long text"


def test_detail_follows_a_game_that_moved(tmp_path, client):
    x = open_xml(tmp_path)
    x.write_text(XML.replace('<game><path>./b.zip</path>', '<game><path>./new.zip</path></game><game><path>./b.zip</path>'), encoding="utf-8")
    xml_store._xml_cache.update(mtime=None, tree=None)
    data = client.get("/api/game/0?path=./b.zip", headers=H).get_json()
    assert data["index"] == 1 and data["desc"] == "Long text"


def test_detail_of_a_vanished_game_is_409(tmp_path, client):
    open_xml(tmp_path)
    assert client.get("/api/game/0?path=./gone.zip", headers=H).status_code == 409


def test_detail_invalid_index_is_404(tmp_path, client):
    open_xml(tmp_path)
    assert client.get("/api/game/99", headers=H).status_code == 404


def test_detail_without_gamelist(client):
    xml_store.close_gamelist()
    assert client.get("/api/game/0", headers=H).status_code == 400
