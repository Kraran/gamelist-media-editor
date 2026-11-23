"""Fallback sources in the browser: settings tab, LaunchBox download, source chips."""
import json
import os

import pytest

from gme.scrapers import launchbox, sources, ss
from tests.test_fallback_sources import METADATA

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")          # folder for documentation screenshots (optional)
SNES_METADATA = METADATA.replace("Nintendo Entertainment System", "Super Nintendo Entertainment System") \
    .replace("<Name>Bravo Quest</Name>", "<Name>Charlie</Name>")


def snes_zip():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Metadata.xml", SNES_METADATA)
    return buf.getvalue()


@pytest.fixture
def lb_ready(tmp_path):
    archive = tmp_path / "Metadata.zip"
    archive.write_bytes(snes_zip())
    os.makedirs(launchbox.LB_DIR, exist_ok=True)
    launchbox.build_index(str(archive), launchbox.db_path())
    sources.save_config({"enabled": {"launchbox": True}})


def open_fallback(page):
    page.click("#btn-settings")
    page.wait_for_selector("#settings-modal.open")
    page.click("#tab-fallback")
    page.wait_for_selector("#fb-order .fb-row[data-src='launchbox']")


def test_settings_order_keys_and_fields(page, tmp_path):
    open_fallback(page)
    rows = page.locator("#fb-order .fb-row")
    assert rows.count() == 4
    assert page.get_attribute("#fb-order .fb-row >> nth=0", "data-src") == "screenscraper"
    assert page.get_attribute(".fb-row[data-src='launchbox']", "data-state") == "off"
    page.check("[data-fb-enable='launchbox']")
    page.wait_for_selector(".fb-row[data-src='launchbox'][data-state='setup']")   # no base yet
    page.click(".fb-row[data-src='igdb'] [data-fb-move='-1']")
    page.wait_for_function("document.querySelectorAll('#fb-order .fb-row')[2].dataset.src === 'igdb'")
    page.fill("#fb-tgdb-key", "MY-TGDB-KEY-42")
    page.press("#fb-tgdb-key", "Tab")
    page.wait_for_function("document.getElementById('fb-tgdb-key').placeholder !== ''")
    assert page.input_value("#fb-tgdb-key") == ""
    assert "MY-TGDB-KEY-42" not in page.content()
    page.uncheck("[data-fb-field='desc'][data-src='launchbox']")
    page.wait_for_function("!fbConfig.fields.launchbox.includes('desc')")      # saved
    page.uncheck("#fb-continue")
    page.wait_for_function("fbConfig.on_ss_quota === 'stop'")
    saved = json.loads((tmp_path / "sources_config.json").read_text(encoding="utf-8"))
    assert saved["enabled"]["launchbox"] is True
    assert saved["order"] == ["screenscraper", "launchbox", "igdb", "thegamesdb"]
    assert saved["tgdb_apikey"] == "MY-TGDB-KEY-42"
    assert "desc" not in saved["fields"]["launchbox"]
    assert saved["on_ss_quota"] == "stop"


def test_launchbox_download_from_the_settings(page, monkeypatch):
    payload = snes_zip()

    class Resp:
        headers = {"content-length": str(len(payload))}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_content(self, n): yield payload

    monkeypatch.setattr(launchbox.requests, "get", lambda url, **k: Resp())
    sources.save_config({"enabled": {"launchbox": True}})
    open_fallback(page)
    assert "pas encore" in page.inner_text("#lb-status")
    page.click("#btn-lb-update")
    page.wait_for_selector(".fb-row[data-src='launchbox'][data-state='on']", timeout=10000)
    page.wait_for_function("document.getElementById('lb-status').textContent.includes('3 jeux')")
    assert page.is_disabled("#btn-lb-update")                    # once a day
    assert "Mettre à jour" in page.inner_text("#btn-lb-update")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "settings-fallback.png"))
        page.locator("#fb-fields").scroll_into_view_if_needed()
        page.screenshot(path=os.path.join(SHOTS, "settings-fallback-fields.png"))


def test_scrape_dialog_shows_where_fields_come_from(page, fake_sources, lb_ready):
    page.click("#game-list .game-item >> nth=0")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-modal.open")
    page.wait_for_selector("#ss-fields .ss-section")
    assert "complété par LaunchBox" in page.inner_text("#ss-modal-info")
    chips = page.locator("#ss-fields .ss-src[data-src='launchbox']")
    assert chips.count() >= 3                                     # publisher, date, box…
    assert page.locator(".ss-meta-row:has([data-ss-field='publisher']) .ss-src").inner_text() == "LaunchBox"
    assert page.locator(".ss-meta-row:has([data-ss-field='developer']) .ss-src").count() == 0   # ScreenScraper's
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "scrape-fallback-chips.png"))
    page.click("#ss-modal-cancel")


def test_game_missing_on_screenscraper_found_on_launchbox(page, fake_sources, lb_ready, monkeypatch):
    monkeypatch.setattr(ss, "ss_request", lambda *a, **k: (False, "Erreur : Jeu non trouvée !", 404))
    page.click("#game-list .game-item >> nth=2")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Charlie'")
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-modal.open")
    page.wait_for_selector("#ss-fields .ss-section")
    info = page.inner_text("#ss-modal-info")
    assert "LaunchBox" in info and "absent de ScreenScraper" in info
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "scrape-fallback-only.png"))
    page.click("#ss-modal-apply")
    page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')", timeout=10000)
    from lxml import etree
    from gme import xml_store
    charlie = etree.parse(xml_store.XML_PATH).getroot().findall("game")[2]
    assert charlie.findtext("desc") == "Bravo from LaunchBox."
    assert charlie.findtext("thumbnail") is None or charlie.findtext("thumbnail") == ""   # Charlie has no box in the base
