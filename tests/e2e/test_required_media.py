"""Required media per system, settings kept by the server, dialogs and the keyboard."""
import json

import pytest

pytestmark = pytest.mark.e2e


def open_game(page, n=0, name="Alpha"):
    page.click(f"#game-list .game-item >> nth={n}")
    page.wait_for_function(f"document.getElementById('game-name-input').value === '{name}'")


def counts(page):
    return page.eval_on_selector_all("#game-list .gi-count", "els => els.map(e => e.textContent)")


def test_required_media_drive_counter_filter_and_next(page, gamelist, settings_file):
    text = gamelist.read_text(encoding="utf-8").replace(
        "<name>Bravo</name>", "<name>Bravo</name><image>./i.png</image><video>./v.mp4</video>"
                              "<marquee>./m.png</marquee>", 1)
    gamelist.write_text(text, encoding="utf-8")
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    assert counts(page) == ["0/4", "3/4", "0/4"]               # snes: image, video, marquee, boxart
    open_game(page, 1, "Bravo")
    assert page.eval_on_selector_all("#missing-chips .missing-chip.is-required", "els => els.map(e => e.dataset.field)") == ["boxart"]
    assert "Facultatifs" in page.inner_text("#missing-chips")

    page.click("#btn-required-media")                          # from the missing media
    page.wait_for_selector("#settings-modal.open")
    assert page.get_attribute("#tab-required", "aria-selected") == "true"
    assert "snes" in page.inner_text("#required-box") and "par défaut" in page.inner_text("#required-box")
    page.uncheck("[data-required='boxart']")
    page.wait_for_function("SETTINGS.required_media.snes && SETTINGS.required_media.snes.length === 3")
    assert json.loads(settings_file.read_text(encoding="utf-8"))["required_media"] == {"snes": ["image", "video", "marquee"]}
    assert counts(page) == ["0/3", "3/3", "0/3"]
    assert page.locator("#missing-chips .missing-chip.is-required").count() == 0
    page.keyboard.press("Escape")

    page.select_option("#media-filter", "any")                # games missing a required media
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 2")
    page.select_option("#media-filter", "all")
    open_game(page)
    page.click("#btn-next-incomplete")                         # Bravo is complete now: Charlie
    page.wait_for_function("document.getElementById('game-name-input').value === 'Charlie'")

    page.click("#btn-settings")
    page.click("#tab-required")
    page.click("#required-box [data-required-reset='snes']")   # back to the default
    page.wait_for_function("!SETTINGS.required_media.snes")
    assert counts(page) == ["0/4", "3/4", "0/4"]


def test_thumbnail_and_bezel_have_their_tiles(page, gamelist):
    folder = gamelist.parent
    (folder / "images").mkdir()
    from PIL import Image
    Image.new("RGB", (40, 30)).save(folder / "images" / "alpha-thumb.png")
    text = gamelist.read_text(encoding="utf-8").replace(
        "<name>Alpha</name>", "<name>Alpha</name><thumbnail>./images/alpha-thumb.png</thumbnail>", 1)
    gamelist.write_text(text, encoding="utf-8")
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    open_game(page)
    assert page.locator(".media-tile[data-field='thumbnail']").count() == 1
    assert "Miniature" in page.inner_text(".media-tile[data-field='thumbnail'] .tile-title")
    assert page.locator(".missing-chip[data-field='bezel']").count() == 1
    assert "Sans bezel" in " ".join(page.locator("#media-filter option").all_inner_texts())


def test_language_is_kept_by_the_server(page, server, settings_file):
    page.click("#btn-settings")
    page.select_option("#ui-lang", "en")
    page.wait_for_function("document.querySelector('#btn-settings .btn-label').textContent === 'Settings'")
    page.wait_for_function("SETTINGS.locale === 'en'")
    assert json.loads(settings_file.read_text(encoding="utf-8"))["locale"] == "en"
    page.evaluate("localStorage.clear()")
    page.reload()
    page.wait_for_function("document.querySelector('#btn-settings .btn-label').textContent === 'Settings'")


def test_browser_settings_of_older_versions_move_to_the_server(page, settings_file):
    page.evaluate("localStorage.setItem('gme_locale', 'de');"
                  "localStorage.setItem('gme_scraper_by_system', JSON.stringify({snes: 'steam', x: 'nope'}))")
    page.reload()
    page.wait_for_function("document.querySelector('#btn-settings .btn-label').textContent === 'Einstellungen'")
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["locale"] == "de" and saved["scrapers"] == {"snes": "steam"}
    assert page.evaluate("localStorage.getItem('gme_locale') === null && localStorage.getItem('gme_scraper_by_system') === null")


def test_screenscraper_settings_save_as_they_change(page, ss_config_file):
    page.click("#btn-settings")
    page.click("#tab-ss")
    page.wait_for_function("document.querySelectorAll('#ss-region option').length > 20")
    assert page.locator("#ss-region option[value='de']").count() == 1
    assert "Allemagne" in page.inner_text("#ss-region option[value='de']")
    assert page.locator("#btn-ss-save").count() == 0
    page.select_option("#ss-region", "de")
    page.wait_for_selector("#toast.show")
    assert json.loads(ss_config_file.read_text(encoding="utf-8"))["prefer_region"] == "de"


def test_tab_stays_in_the_open_dialog(page):
    page.click("#btn-settings")
    page.wait_for_selector("#settings-modal.open")
    for _ in range(12):
        page.keyboard.press("Tab")
        assert page.evaluate("document.getElementById('settings-modal').contains(document.activeElement)")
    for _ in range(6):
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.getElementById('settings-modal').contains(document.activeElement)")
