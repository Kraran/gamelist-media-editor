"""A broken or one-colour image from the source is never written: the scrape and the batch report say so."""
import io

import pytest
from lxml import etree
from PIL import Image

from gme import remote_cache
from tests.e2e.conftest import png

pytestmark = pytest.mark.e2e


def flat_screenshot():
    buf = io.BytesIO()
    Image.new("RGB", (320, 224), (0, 0, 0)).save(buf, "PNG")       # a black placeholder
    return buf.getvalue()


@pytest.fixture
def bad_screenshot(fake_sources, monkeypatch):
    """The screenshot (media=ss) is one black rectangle; the wheel is a real picture."""
    def fake_fetch(url, headers=None, timeout=40, max_bytes=0):
        fake_sources["downloads"].append(url)
        return (flat_screenshot() if "media=ss" in url else png()), "image/png"
    monkeypatch.setattr(remote_cache, "fetch", fake_fetch)
    return fake_sources


def test_single_scrape_reports_the_rejected_image(page, gamelist, bad_screenshot):
    page.click("#game-list .game-item >> nth=2")                    # Charlie: no media at all
    page.wait_for_function("document.getElementById('game-name-input').value === 'Charlie'")
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-modal.open")
    page.click("#ss-modal-apply")
    page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')")
    page.wait_for_selector("#toast.show")
    toast = page.inner_text("#toast")
    assert "image d’une seule couleur ou vide, non enregistrée" in toast
    charlie = etree.parse(str(gamelist)).getroot().findall("game")[2]
    assert charlie.findtext("image") is None                          # never pointed at the bad file
    assert charlie.findtext("marquee")                                # the good wheel is written
    images = sorted(p.name for p in (gamelist.parent / "images").iterdir())
    assert images == ["charlie-marquee.png"]


def test_batch_report_lists_the_rejected_image(page, gamelist, bad_screenshot):
    page.click("#game-list .game-item >> nth=2 >> .gi-select input")  # Charlie
    page.click("#btn-batch-selection")
    page.wait_for_selector("#batch-modal.open")
    page.click("#batch-start")
    page.wait_for_selector("#batch-export:not([hidden])", timeout=30000)
    body = page.inner_text("#batch-body")
    assert "image d’une seule couleur ou vide, non enregistrée" in body
    charlie = etree.parse(str(gamelist)).getroot().findall("game")[2]
    assert charlie.findtext("image") is None
