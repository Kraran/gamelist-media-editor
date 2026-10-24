"""Actions › Check media: report with thumbnails, clean-up, broken links."""
import pytest
from lxml import etree
from PIL import Image

from gme import mediacheck, thumbs

pytestmark = pytest.mark.e2e


@pytest.fixture
def media_folder(gamelist, monkeypatch, tmp_path):
    monkeypatch.setattr(thumbs, "CACHE_DIR", str(tmp_path / "thumb-cache"))
    trashed = []

    def fake_trash(full):
        trashed.append(full)
        import os
        os.remove(full)

    monkeypatch.setattr(mediacheck, "_trash", fake_trash)
    folder = gamelist.parent
    (folder / "images").mkdir()
    Image.new("RGB", (64, 48), (200, 60, 60)).save(folder / "images" / "alpha-image.png")
    Image.new("RGB", (64, 48), (60, 60, 200)).save(folder / "images" / "old.png")
    (folder / "images" / "older.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 2000)
    xml = gamelist.read_text(encoding="utf-8").replace(
        "<name>Alpha</name>", "<name>Alpha</name><image>./images/alpha-image.png</image>", 1).replace(
        "<name>Bravo</name>", "<name>Bravo</name><marquee>./images/gone.png</marquee>", 1)
    gamelist.write_text(xml, encoding="utf-8")
    return folder, trashed


def open_check(page):
    page.click("#btn-actions")
    page.click("#btn-media-check")
    page.wait_for_selector("#check-stats .rc-stat")


def test_clean_up(page, media_folder):
    folder, trashed = media_folder
    page.reload()                                          # the media were added after the page loaded
    page.wait_for_selector("#game-list .game-item")
    open_check(page)
    stats = page.eval_on_selector_all("#check-stats .rc-stat-n", "els => els.map(e => e.textContent)")
    assert stats[:3] == ["3", "3", "2"] and stats[4] == "1"   # games, files, unused, (size), broken
    assert page.locator("[data-kind='delete'] .rc-thumb img").count() == 2
    page.wait_for_function("[...document.querySelectorAll('[data-kind=delete] .rc-thumb img')].some(i => i.naturalWidth > 0)")
    assert page.inner_text("#check-apply-label") == "Nettoyer (3)"
    assert page.is_checked("[data-check-option='trash']")
    page.uncheck("[data-rc='delete'][value='./images/older.jpg']")
    page.click("#check-apply")
    page.wait_for_function("document.querySelectorAll('[data-rc]').length === 1")
    assert [p.split("/")[-1].split("\\")[-1] for p in trashed] == ["old.png"]
    assert (folder / "images" / "older.jpg").exists() and (folder / "images" / "alpha-image.png").exists()
    bravo = [g for g in etree.parse(str(folder / "gamelist.xml")).getroot() if g.findtext("name") == "Bravo"][0]
    assert bravo.find("marquee") is None
    assert "Corbeille" in page.inner_text("#toast")


def test_all_good(page, gamelist):
    open_check(page)
    page.wait_for_selector(".rc-all-good")
    assert "Chaque média est utilisé" in page.inner_text("#check-body")
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('check-modal').classList.contains('open')")
