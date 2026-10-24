"""Actions › Check ROMs: report, selection, update of the gamelist, export."""
import pytest
from lxml import etree

pytestmark = pytest.mark.e2e


@pytest.fixture
def changed_folder(gamelist):
    folder = gamelist.parent
    (folder / "delta.sfc").write_bytes(b"rom")             # not in the gamelist
    (folder / "echo.zip").write_bytes(b"rom")              # not in the gamelist
    (folder / "charlie.zip").unlink()                      # its entry has no ROM any more
    return folder


def open_check(page):
    page.click("#btn-actions")
    page.click("#btn-rom-check")
    page.wait_for_selector("#check-stats .rc-stat")


def stats(page):
    return page.eval_on_selector_all("#check-stats .rc-stat-n", "els => els.map(e => e.textContent)")


def test_report_and_update(page, changed_folder):
    open_check(page)
    assert stats(page) == ["3", "4", "2", "1", "0"]        # games, ROM files, to add, without ROM, duplicates
    assert page.inner_text("#check-apply-label") == "Mettre à jour le gamelist (3)"
    page.uncheck("[data-rc='add'][value='./echo.zip']")
    assert page.is_checked("[data-rc-all='add']") is False   # partly ticked
    assert page.inner_text("#check-apply-label") == "Mettre à jour le gamelist (2)"
    page.click("#check-apply")
    page.wait_for_function("document.querySelector('#check-stats .rc-stat-n').textContent === '3'"
                           " && document.querySelectorAll('[data-rc]').length === 1")
    root = etree.parse(str(changed_folder / "gamelist.xml")).getroot()
    paths = [g.findtext("path") for g in root.findall("game")]
    assert "./delta.sfc" in paths and "./charlie.zip" not in paths and "./echo.zip" not in paths
    assert (changed_folder / "gamelist.xml.bak").exists()
    assert page.locator("#game-list .game-item").count() == 3   # list reloaded: alpha, bravo, delta


def test_section_box_and_escape(page, changed_folder):
    open_check(page)
    page.uncheck("[data-rc-all='add']")
    page.uncheck("[data-rc-all='remove']")
    assert page.is_disabled("#check-apply")
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('check-modal').classList.contains('open')")


def test_all_good_and_export(page, gamelist):
    open_check(page)
    page.wait_for_selector(".rc-all-good")
    with page.expect_download() as dl:
        page.click("#check-export")
    text = open(dl.value.path(), encoding="utf-8-sig").read()
    assert "Vérifier les ROMs" in text and "ROMs absentes du gamelist (0)" in text
