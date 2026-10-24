"""Keyboard shortcuts, "Next incomplete", the ⋯ menus and the Settings dialog."""
import json

import pytest

pytestmark = pytest.mark.e2e

MEDIA = ["image", "video", "marquee", "manual", "boxart", "boxback", "cartridge", "fanart", "mix", "map"]


def current_name(page):
    return page.input_value("#game-name-input")


def open_first(page):
    page.click("#game-list .game-item >> nth=0")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")


def test_j_k_navigate_but_not_while_typing(page):
    open_first(page)
    page.locator("#game-list").focus()
    page.keyboard.press("j")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Bravo'")
    page.keyboard.press("k")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")
    page.focus("#meta-developer")
    page.keyboard.type("jk")
    assert page.input_value("#meta-developer") == "jk"      # typed, not navigated
    assert current_name(page) == "Alpha"


def test_next_incomplete_skips_complete_games(page):
    open_first(page)
    # Bravo has every media: N goes from Alpha to Charlie
    page.evaluate("fields => { const g = games.find(x => x.name === 'Bravo');"
                  " fields.forEach(f => g[f] = './images/x.png'); }", MEDIA)
    page.locator("#game-list").focus()
    page.keyboard.press("n")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Charlie'")
    page.click("#btn-next-incomplete")                       # wraps around to Alpha
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")
    page.evaluate("fields => games.forEach(g => fields.forEach(f => g[f] = './images/x.png'))", MEDIA)
    page.click("#btn-next-incomplete")
    page.wait_for_selector("#toast.show")
    assert "Aucun autre jeu incomplet" in page.inner_text("#toast")
    assert current_name(page) == "Alpha"


def test_s_opens_the_scrape(page):
    answer = {"success": True, "source": "screenscraper", "match_method": "hash",
              "proposed": {"name": "Alpha", "medias": {}}, "current": {}, "compare": []}
    page.route("**/api/ss/scrape/**", lambda r: r.fulfill(status=200, content_type="application/json",
                                                          body=json.dumps(answer)))
    open_first(page)
    page.locator("#game-list").focus()
    page.keyboard.press("s")
    page.wait_for_selector("#ss-modal.open")
    page.keyboard.press("s")                                 # no second scrape behind the dialog
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')")


def test_question_mark_opens_shortcuts(page):
    page.locator("#game-list").focus()
    page.keyboard.press("?")
    page.wait_for_selector("#settings-modal.open")
    assert page.get_attribute("#tab-keys", "aria-selected") == "true"
    assert page.is_visible("#pane-keys") and page.is_hidden("#pane-general")
    page.keyboard.press("ArrowUp")                           # tabs: arrows move between panes
    assert page.get_attribute("#tab-sources", "aria-selected") == "true"
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('settings-modal').classList.contains('open')")


def test_settings_language_applies_at_once(page):
    page.click("#btn-settings")
    page.wait_for_selector("#settings-modal.open")
    page.select_option("#ui-lang", "en")
    page.wait_for_function("document.querySelector('#btn-settings .btn-label').textContent === 'Settings'")
    page.select_option("#ui-lang", "fr")
    page.wait_for_function("document.querySelector('#btn-settings .btn-label').textContent === 'Réglages'")


def test_settings_sources_reset(page):
    page.evaluate("localStorage.setItem('gme_scraper_by_system', JSON.stringify({snes: 'steam'}))")
    open_first(page)
    page.evaluate("updateScrapeButton()")
    assert page.inner_text("#scrape-source-name") == "Steam"
    page.click("#btn-settings")
    page.click("#tab-sources")
    assert "snes" in page.inner_text("#sources-list")
    page.click("#sources-list [data-reset-folder='snes']")
    assert "Aucun choix forcé" in page.inner_text("#sources-list")
    assert page.inner_text("#scrape-source-name") == "ScreenScraper"


def test_actions_menu_backup(page, gamelist):
    page.click("#btn-actions")
    assert page.get_attribute("#btn-actions", "aria-expanded") == "true"
    assert page.evaluate("document.activeElement.id") == "btn-manual-backup"
    page.keyboard.press("ArrowUp")                           # wraps to the last item
    assert page.evaluate("document.activeElement.id") == "btn-purge-regions"
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    page.wait_for_selector("#toast.show")
    assert (gamelist.parent / "gamelist.xml.bak").exists()
    assert page.is_hidden("#actions-menu")


def test_actions_menu_closes_on_outside_click(page):
    page.click("#btn-actions")
    page.click("#game-list .game-item >> nth=1")
    assert page.is_hidden("#actions-menu")
    assert page.get_attribute("#btn-actions", "aria-expanded") == "false"


def test_game_menu_copy_path_and_delete_asks(page, gamelist):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    open_first(page)
    page.click("#btn-game-menu")
    page.click("#btn-copy-path")
    page.wait_for_selector("#toast.show")
    assert page.evaluate("navigator.clipboard.readText()") == str(gamelist.parent / "alpha.zip")
    page.click("#btn-game-menu")
    page.click("#btn-delete-game")
    page.wait_for_selector("#confirm-modal.open")
    assert "Alpha" in page.inner_text("#confirm-title")
    assert page.evaluate("document.activeElement.id") == "confirm-ok"   # the dialog keeps the focus
    page.click("#confirm-cancel")
    assert (gamelist.parent / "alpha.zip").exists()
