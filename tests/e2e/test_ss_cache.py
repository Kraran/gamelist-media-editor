"""ScreenScraper answer cache in the browser: settings, cached scrape note, refresh."""
import json
import os

import pytest
import requests

from gme import remote_cache
from gme.scrapers import ss, ss_cache
from tests.test_ss_parallel import FakeSS

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")          # folder for documentation screenshots (optional)


@pytest.fixture
def fake_ss(monkeypatch, tmp_path, ss_config_file):
    server = FakeSS(maxthreads=2, delay=0.01)
    monkeypatch.setattr(requests, "get", server.get)
    monkeypatch.setattr(remote_cache, "CACHE_DIR", str(tmp_path / "remote-cache"))
    ss_config_file.write_text(json.dumps({"ssid": "member", "sspassword": "pw"}), encoding="utf-8")
    return server


def api_calls(server):
    return [c for c in server.calls if c[1] in ("jeuInfos.php", "jeuRecherche.php")]


def scrape_alpha(page):
    page.click("#game-list .game-item >> nth=0")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-modal.open")
    page.wait_for_selector("#ss-fields .ss-section, #ss-fields .ss-nothing")


def close_scrape(page):
    page.click("#ss-modal-cancel")
    page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')")


def test_second_scrape_comes_from_the_cache_and_can_be_refreshed(page, gamelist, fake_ss):
    scrape_alpha(page)
    assert page.is_hidden("#ss-cache-note")
    sent = len(api_calls(fake_ss))
    assert sent >= 1
    close_scrape(page)
    scrape_alpha(page)
    page.wait_for_selector("#ss-cache-note:not([hidden])")
    assert "aucune requête envoyée" in page.inner_text("#ss-cache-note")
    assert len(api_calls(fake_ss)) == sent
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "scrape-from-cache.png"))
    page.click("#ss-cache-refresh")
    page.wait_for_function("document.getElementById('ss-cache-note').hidden")
    assert len(api_calls(fake_ss)) == sent + 1


def test_settings_show_the_cache_and_empty_it(page, gamelist, fake_ss, ss_config_file):
    ss.ss_request("jeuInfos.php", {"romtype": "rom", "crc": "ABCD1234", "romnom": "alpha.zip"})
    ss.ss_request("jeuInfos.php", {"romtype": "rom", "crc": "ABCD1235", "romnom": "bravo.zip"})
    page.click("#btn-settings")
    page.wait_for_selector("#settings-modal.open")
    page.click("#tab-ss")
    page.wait_for_function("document.getElementById('ss-cache-stats').textContent.startsWith('2 ')")
    assert page.is_checked("#ss-cache-enabled")
    assert page.input_value("#ss-cache-days") == "30"
    if SHOTS:
        page.locator("#btn-ss-cache-clear").scroll_into_view_if_needed()
        page.screenshot(path=os.path.join(SHOTS, "settings-cache.png"))
    page.select_option("#ss-cache-days", "90")
    page.wait_for_function("document.getElementById('ss-cache-days').value === '90'")
    page.click("#btn-ss-cache-clear")
    page.wait_for_function("document.getElementById('ss-cache-stats').textContent.startsWith('0 ')")
    assert page.is_disabled("#btn-ss-cache-clear")
    assert ss_cache.stats()["entries"] == 0
    page.uncheck("#ss-cache-enabled")
    page.wait_for_function("document.getElementById('ss-cache-days').disabled")
    saved = json.loads(ss_config_file.read_text(encoding="utf-8"))
    assert saved["cache_enabled"] is False and saved["cache_days"] == 90
