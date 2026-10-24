"""Shared fixtures: a throw-away gamelist + Flask test client."""
import pytest

from gme import recent, xml_store
from gme.server import app

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name></game>
  <game><path>./bravo.zip</path><name>Bravo</name></game>
  <game><path>./charlie.zip</path><name>Charlie</name></game>
</gameList>
"""

LOCAL = {"Host": "127.0.0.1:5050", "Origin": "http://127.0.0.1:5050", "Sec-Fetch-Site": "same-origin"}


@pytest.fixture(autouse=True)
def recent_file(tmp_path, monkeypatch):
    """Recent gamelists go to a temporary file, never next to app.py."""
    path = tmp_path / "recent_gamelists.json"
    monkeypatch.setattr(recent, "RECENT_FILE", str(path))
    return path


@pytest.fixture
def gamelist(tmp_path):
    """gamelist.xml with 3 games (+ their ROM files) opened in the app."""
    xml = tmp_path / "gamelist.xml"
    xml.write_text(GAMELIST, encoding="utf-8")
    for rom in ("alpha.zip", "bravo.zip", "charlie.zip"):
        (tmp_path / rom).write_bytes(b"rom")
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def names(xml):
    """Game names in XML order."""
    from lxml import etree
    return [g.findtext("name") for g in etree.parse(str(xml)).getroot().findall("game")]
