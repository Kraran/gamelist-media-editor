"""Shared fixtures: a throw-away gamelist + Flask test client."""
import io
import os
import shutil

import pytest

from gme import fsutil, history, jobs, recent, settings, xml_store
from gme import batch_jobs
from gme.server import app

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name></game>
  <game><path>./bravo.zip</path><name>Bravo</name></game>
  <game><path>./charlie.zip</path><name>Charlie</name></game>
</gameList>
"""

def picture(size=(64, 48), color=(40, 120, 200), fmt="PNG"):
    """A small real picture: ``color`` with a light band, so scrapes accept it
    (gme.media.check_image refuses one-colour and tiny images)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, color)
    w, h = size
    ImageDraw.Draw(im).rectangle([w // 4, h // 3, w * 3 // 4, h * 2 // 3], fill=(240, 230, 210))
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


LOCAL = {"Host": "127.0.0.1:5050", "Origin": "http://127.0.0.1:5050", "Sec-Fetch-Site": "same-origin"}


@pytest.fixture(autouse=True)
def batch_state_dir(tmp_path, monkeypatch):
    path = tmp_path / "batch-state"
    monkeypatch.setattr(batch_jobs, "BATCH_DIR", str(path))
    return path


@pytest.fixture(autouse=True)
def recent_file(tmp_path, monkeypatch):
    """Recent gamelists go to a temporary file, never next to app.py."""
    path = tmp_path / "recent_gamelists.json"
    monkeypatch.setattr(recent, "RECENT_FILE", str(path))
    monkeypatch.setattr(recent, "ROOTS_FILE", str(tmp_path / "recent_roms_roots.json"))
    return path


@pytest.fixture(autouse=True)
def network_files(tmp_path, monkeypatch):
    """Network favourites and sign-ins go to temporary files; no reload timer survives a test."""
    from gme import network
    monkeypatch.setattr(network, "PLACES_FILE", str(tmp_path / "network_places.json"))
    monkeypatch.setattr(network, "CREDENTIALS_FILE", str(tmp_path / "network_credentials.json"))
    monkeypatch.setattr(network, "_connected", set())
    network._reload["last"] = None
    yield
    timer = network._reload.get("timer")
    if timer is not None:
        timer.cancel()
    network._reload["timer"] = None


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    """Interface settings go to a temporary file, never next to app.py."""
    path = tmp_path / "ui_settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", str(path))
    return path


@pytest.fixture(autouse=True)
def ss_config_file(tmp_path, monkeypatch):
    """ScreenScraper settings saved from a test go to a temporary file."""
    from gme.scrapers import ss
    path = tmp_path / "screenscraper_config.json"
    monkeypatch.setattr(ss, "ss_config_path", lambda: str(path))
    return path


@pytest.fixture(autouse=True)
def screenscraper_offline(monkeypatch, tmp_path):
    """No test may reach the real ScreenScraper; limits start unknown and workers stop."""
    from gme.scrapers import ss, ss_cache, ss_limits
    monkeypatch.setattr(ss, "SS_API", "http://127.0.0.1:9/api2")
    monkeypatch.setattr(ss_cache, "CACHE_DIR", str(tmp_path / "ss-api-cache"))
    ss_limits.GATE.reset()
    yield
    batch_jobs.stop_all()
    ss_limits.GATE.reset()


@pytest.fixture(autouse=True)
def fallback_sources_offline(monkeypatch, tmp_path):
    """Fallback sources: settings and caches in tmp, no real API reachable, all off."""
    from gme.scrapers import igdb, launchbox, sources, tgdb
    monkeypatch.setattr(sources, "config_path", lambda: str(tmp_path / "sources_config.json"))
    monkeypatch.setattr(sources, "CACHE_DIR", str(tmp_path / "sources-api-cache"))
    monkeypatch.setattr(launchbox, "LB_DIR", str(tmp_path / "launchbox"))
    monkeypatch.setattr(launchbox, "METADATA_URL", "http://127.0.0.1:9/Metadata.zip")
    monkeypatch.setattr(tgdb, "API", "http://127.0.0.1:9/tgdb")
    monkeypatch.setattr(igdb, "API", "http://127.0.0.1:9/igdb")
    monkeypatch.setattr(igdb, "TOKEN_URL", "http://127.0.0.1:9/token")
    igdb.forget_token()
    tgdb._allowance.update(remaining=None, until=0.0)
    launchbox._fuzzy_cache.clear()
    yield


@pytest.fixture(autouse=True)
def fresh_history():
    """Each test starts with no undo history and no background scan."""
    history.reset_all()
    jobs.reset()
    yield
    jobs.reset()
    history.reset_all()


@pytest.fixture(autouse=True)
def trashed(monkeypatch):
    """Nothing goes to the real Recycle Bin: what would is recorded, then removed."""
    paths = []

    def fake_trash(path):
        if not os.path.exists(path):
            raise OSError(f"no such file: {path}")
        paths.append(str(path))
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        history.note_trash()                   # like fsutil.trash: the undo step says so

    monkeypatch.setattr(fsutil, "trash", fake_trash)
    return paths


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
