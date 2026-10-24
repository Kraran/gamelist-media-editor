"""Recent gamelists in the "Open gamelist" dialog: one click opens, stale ones go away."""
import pytest

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


def test_recent_opens_in_one_click(page, gamelist, other_gamelist):
    open_path(page, other_gamelist)
    page.wait_for_function("document.getElementById('system-name').textContent === 'nes'")
    open_dialog(page)
    items = page.locator("#open-gl-recent .open-gl-recent-item")
    assert items.count() == 1                                # the open file is not listed
    assert items.first.locator(".open-gl-recent-name").inner_text() == "snes"
    assert items.first.get_attribute("title") == str(gamelist)
    items.first.click()                                      # one click: opened
    page.wait_for_function("document.getElementById('system-name').textContent === 'snes'")
    assert not page.evaluate("document.getElementById('open-gamelist-modal').classList.contains('open')")
    assert page.locator("#game-list .game-item").count() == 3


def test_missing_recent_is_dropped(page, gamelist, other_gamelist):
    open_path(page, other_gamelist)
    open_path(page, gamelist)
    other_gamelist.unlink()
    open_dialog(page)
    page.click("#open-gl-recent .open-gl-recent-item")
    # The "opened" toast of the previous step may still be up: wait for the list itself
    page.wait_for_function("document.querySelectorAll('#open-gl-recent .open-gl-recent-item').length === 0")
    page.wait_for_selector("#toast.show.error")
    assert page.evaluate("document.getElementById('open-gamelist-modal').classList.contains('open')")
    assert "/nes/" not in page.evaluate("localStorage.getItem('gme_recent_gamelists')")


def test_recent_can_be_removed(page, gamelist, other_gamelist):
    open_path(page, other_gamelist)
    open_path(page, gamelist)
    open_dialog(page)
    page.click("#open-gl-recent .open-gl-recent-forget")
    assert page.locator("#open-gl-recent .open-gl-recent-item").count() == 0
    assert page.is_visible("#open-gl-recent .open-gl-recent-empty")
