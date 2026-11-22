"""Actions › Export the list: the games shown, as a CSV Excel opens (UTF-8 BOM, ; or , separator)."""
import csv
import io

import pytest

from gme import xml_store
from tests.conftest import LOCAL

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./zelda.zip</path><name>Zelda</name><genre>Aventure / Action</genre><releasedate>19860221T000000</releasedate>
    <developer>Nintendo</developer><publisher>Nintendo</publisher><players>1</players><rating>0.9</rating>
    <favorite>true</favorite><image>./images/zelda.png</image><video>./videos/zelda.mp4</video><desc>Long text</desc></game>
  <game><path>./alpha.zip</path><name>Élan, "le jeu"</name><hidden>true</hidden><kidgame>1</kidgame><marquee>./images/a.png</marquee></game>
  <game><path>./evil.zip</path><name>=HYPERLINK("http://x.test")</name><developer>+cmd</developer><publisher>@SUM(A1)</publisher></game>
</gameList>
"""


@pytest.fixture
def gl(tmp_path):
    xml = tmp_path / "roms" / "snes" / "gamelist.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(GAMELIST, encoding="utf-8")
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


@pytest.fixture
def client(gl):
    from gme.server import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def export(client, body, headers=LOCAL):
    return client.post("/api/export-csv", json=body, headers=headers)


def rows(resp, sep=";"):
    raw = resp.get_data()
    assert raw.startswith(b"\xef\xbb\xbf")                     # BOM: Excel reads the accents
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=sep))


def test_columns_and_values(client):
    resp = export(client, {"paths": ["./zelda.zip"], "required": ["image", "video", "marquee", "boxart"]})
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert resp.headers["Content-Disposition"].startswith('attachment; filename="gamelist-snes-')
    head, zelda = rows(resp)
    assert head == ["path", "name", "genre", "releasedate", "developer", "publisher", "players", "rating",
                    "favorite", "hidden", "kidgame", "region", "lang", "media", "required_media", "missing_required"]
    assert dict(zip(head, zelda)) == {
        "path": "./zelda.zip", "name": "Zelda", "genre": "Aventure / Action", "releasedate": "1986-02-21",
        "developer": "Nintendo", "publisher": "Nintendo", "players": "1", "rating": "0.9",
        "favorite": "true", "hidden": "false", "kidgame": "false", "region": "", "lang": "",
        "media": "2", "required_media": "2/4", "missing_required": "marquee, boxart"}


def test_order_and_selection_follow_the_list(client):
    resp = export(client, {"paths": ["./evil.zip", "./alpha.zip", "./unknown.zip"]})
    names = [r[1] for r in rows(resp)[1:]]
    assert names == ["'=HYPERLINK(\"http://x.test\")", 'Élan, "le jeu"']
    assert resp.headers["X-Exported-Games"] == "2"


def test_everything_by_name_without_paths(client):
    names = [r[1] for r in rows(export(client, {}))[1:]]
    assert names == ["'=HYPERLINK(\"http://x.test\")", "Zelda", 'Élan, "le jeu"']


def test_formulas_are_neutralised(client):
    evil = rows(export(client, {"paths": ["./evil.zip"]}))[1]
    assert evil[1].startswith("'=") and evil[4] == "'+cmd" and evil[5] == "'@SUM(A1)"


def test_booleans_quotes_and_comma_separator(client):
    resp = export(client, {"paths": ["./alpha.zip"], "sep": ","})
    text = resp.get_data().decode("utf-8-sig")
    assert '"Élan, ""le jeu"""' in text                        # quoted, quotes doubled
    alpha = rows(resp, ",")[1]
    assert alpha[8:11] == ["false", "true", "true"]            # favorite, hidden, kidgame (1 → true)
    assert alpha[-3:] == ["1", "1/4", "image, video, boxart"]  # default required media


@pytest.mark.parametrize("body", [{"paths": "./a.zip"}, {"paths": [1]}, {"required": ["desc"]}, {"sep": "|"}])
def test_bad_requests(client, body):
    assert export(client, body).status_code == 400


def test_local_only(client):
    assert export(client, {}, {**LOCAL, "Origin": "http://evil.test"}).status_code == 403
    assert export(client, {}, {**LOCAL, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert export(client, {}, {**LOCAL, "Host": "evil.test"}).status_code == 403


def test_needs_a_gamelist(client):
    xml_store.close_gamelist()
    assert export(client, {}).status_code == 400
