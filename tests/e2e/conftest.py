"""Browser tests: the real UI (templates + app.js) against a live local server.

Run with:  python -m pytest -m e2e
Needs:     pip install -r requirements-dev.txt && python -m playwright install chromium
"""
import os
import threading
import time

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server  # noqa: E402

from gme import xml_store  # noqa: E402
from gme.server import app  # noqa: E402

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><desc>Alpha desc</desc><genre>Platform</genre><players>1</players><kidgame>1</kidgame><lang>en,fr</lang></game>
  <game><path>./bravo.zip</path><name>Bravo</name><desc>Bravo desc</desc><genre>ACTION / LABYRINTHE</genre></game>
  <game><path>./charlie.zip</path><name>Charlie</name></game>
</gameList>
"""


@pytest.fixture(scope="session")
def server():
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(scope="session")
def browser():
    with playwright_api.sync_playwright() as p:
        exe = os.environ.get("GME_CHROMIUM")  # optional: a specific Chromium binary
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def gamelist(tmp_path):
    xml = tmp_path / "roms" / "snes" / "gamelist.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(GAMELIST, encoding="utf-8")
    for rom in ("alpha", "bravo", "charlie"):
        (xml.parent / f"{rom}.zip").write_bytes(b"rom")
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


@pytest.fixture
def page(browser, server, gamelist):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.route("https://flagcdn.com/**", lambda r: r.abort())  # no network in tests
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(server + "/")
    pg.wait_for_selector("#game-list >> text=Charlie")
    pg.wait_for_function("document.getElementById('meta-genre-main').options.length > 1")  # genres.json loaded
    pg.evaluate("localStorage.setItem('gme_locale', 'fr')")
    yield pg
    ctx.close()
    assert not errors, f"JavaScript errors: {errors}"


def wait_until(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()
