"""Recent gamelists in the "Open gamelist" dialog: one click opens, kept by the server."""
import pytest

from gme import recent

pytestmark = pytest.mark.e2e

OTHER = """<?xml version="1.0"?>
<gameList>
  <game><path>./zelda.zip</path><name>Zelda</name></game>
</gameList>
"""


@pytest.fixture
def other_gamelist(gamelist):
    xml = gamelist.parent.parent / "nes" / "gamelist.xml"
    xml.parent.mkdir()
    xml.write_text(OTHER, encoding="utf-8")
    return xml


def open_dialog(page):
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")


def open_path(page, path):
    open_dialog(page)
    page.fill("#open-gl-path", str(path))
    page.click("#open-gl-apply")
    page.wait_for_function("!document.getElementById('open-gamelist-modal').classList.contains('open')")


def recent_items(page):
    return page.locator("#open-gl-recent .open-gl-recent-item")


def test_recent_opens_in_one_click(page, gamelist, other_gamelist):
    open_path(page, gamelist)
    open_path(page, other_gamelist)
    page.wait_for_function("document.getElementById('system-name').textContent === 'nes'")
    assert recent.recent_paths()[0] == str(other_gamelist)    # kept by the server
    open_dialog(page)
    page.wait_for_selector("#open-gl-recent .open-gl-recent-item")
    assert recent_items(page).count() == 1                    # the open file is not listed
    assert recent_items(page).first.locator(".open-gl-recent-name").inner_text() == "snes"
    assert recent_items(page).first.get_attribute("title") == str(gamelist)
    recent_items(page).first.click()                          # one click: opened
    page.wait_for_function("document.getElementById('system-name').textContent === 'snes'")
    assert not page.evaluate("document.getElementById('open-gamelist-modal').classList.contains('open')")
    assert page.locator("#game-list .game-item").count() == 3


def test_ten_recent_files_are_shown(page, gamelist, tmp_path):
    for i in range(12):
        xml = tmp_path / "many" / f"sys{i:02}" / "gamelist.xml"
        xml.parent.mkdir(parents=True)
        xml.write_text(OTHER, encoding="utf-8")
        recent.remember(str(xml))
    open_dialog(page)
    page.wait_for_selector("#open-gl-recent .open-gl-recent-item")
    assert recent_items(page).count() == 10
    assert recent_items(page).first.locator(".open-gl-recent-name").inner_text() == "sys11"


def test_missing_recent_is_dropped(page, gamelist, other_gamelist):
    open_path(page, other_gamelist)
    open_path(page, gamelist)
    other_gamelist.unlink()
    open_dialog(page)
    page.wait_for_selector("#open-gl-recent .open-gl-recent-row.is-missing")
    page.click("#open-gl-recent .open-gl-recent-item")
    # The "opened" toast of the previous step may still be up: wait for the list itself
    page.wait_for_function("document.querySelectorAll('#open-gl-recent .open-gl-recent-item').length === 0")
    page.wait_for_selector("#toast.show.error")
    assert page.evaluate("document.getElementById('open-gamelist-modal').classList.contains('open')")
    assert str(other_gamelist) not in recent.recent_paths()


def test_recent_can_be_removed(page, gamelist, other_gamelist):
    open_path(page, other_gamelist)
    open_path(page, gamelist)
    open_dialog(page)
    page.click("#open-gl-recent .open-gl-recent-forget")
    page.wait_for_selector("#open-gl-recent .open-gl-recent-empty")
    assert str(other_gamelist) not in recent.recent_paths()


def test_browser_list_of_older_versions_is_imported(page, gamelist, other_gamelist):
    page.evaluate("p => localStorage.setItem('gme_recent_gamelists', JSON.stringify([p]))", str(other_gamelist))
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    page.wait_for_function("localStorage.getItem('gme_recent_gamelists') === null")
    assert str(other_gamelist) in recent.recent_paths()
