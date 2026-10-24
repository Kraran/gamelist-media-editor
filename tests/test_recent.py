"""Recent gamelists are kept by the server in recent_gamelists.json."""
import json

from gme import recent
from tests.conftest import LOCAL


def make_gamelists(tmp_path, n):
    paths = []
    for i in range(n):
        xml = tmp_path / f"sys{i}" / "gamelist.xml"
        xml.parent.mkdir()
        xml.write_text("<gameList/>", encoding="utf-8")
        paths.append(str(xml))
    return paths


def test_opening_puts_the_file_first(tmp_path, client, recent_file):
    a, b = make_gamelists(tmp_path, 2)
    for path in (a, b, a):
        r = client.post("/api/open-gamelist", headers=LOCAL, json={"path": path})
        assert r.status_code == 200
    assert json.loads(recent_file.read_text(encoding="utf-8")) == [a, b]   # no duplicate


def test_keeps_the_last_twelve(tmp_path):
    paths = make_gamelists(tmp_path, 15)
    for p in paths:
        recent.remember(p)
    assert recent.recent_paths() == list(reversed(paths))[:recent.RECENT_MAX]


def test_list_marks_missing_files(tmp_path, client):
    a, b = make_gamelists(tmp_path, 2)
    recent.remember(a)
    recent.remember(b)
    (tmp_path / "sys0" / "gamelist.xml").unlink()
    data = client.get("/api/recent", headers=LOCAL).get_json()["recent"]
    assert data == [{"path": b, "exists": True}, {"path": a, "exists": False}]


def test_opening_a_missing_file_forgets_it(tmp_path, client):
    (a,) = make_gamelists(tmp_path, 1)
    recent.remember(a)
    (tmp_path / "sys0" / "gamelist.xml").unlink()
    r = client.post("/api/open-gamelist", headers=LOCAL, json={"path": a})
    assert r.status_code == 404
    assert recent.recent_paths() == []


def test_forget_and_import(tmp_path, client):
    a, b, c = make_gamelists(tmp_path, 3)
    recent.remember(a)
    data = client.post("/api/recent/import", headers=LOCAL, json={"paths": [b, a, c, 42, ""]}).get_json()
    assert [r["path"] for r in data["recent"]] == [a, b, c]                # imported after, no duplicate
    data = client.post("/api/recent/forget", headers=LOCAL, json={"path": b}).get_json()
    assert [r["path"] for r in data["recent"]] == [a, c]


def test_unreadable_file_is_an_empty_list(recent_file):
    recent_file.write_text("{not json", encoding="utf-8")
    assert recent.recent_paths() == []
    recent_file.write_text('{"a": 1}', encoding="utf-8")
    assert recent.recent_paths() == []
