"""Theme: dark by default, light, or as the system; saved and applied before the page is drawn."""
import json

import pytest

pytestmark = pytest.mark.e2e


def theme(page):
    return page.evaluate("document.documentElement.dataset.theme")


def background(page):
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


def test_light_then_system(page, settings_file):
    assert theme(page) == "dark"
    dark_bg = background(page)
    page.click("#btn-settings")
    assert page.get_attribute("[data-theme-choice='dark']", "aria-pressed") == "true"
    page.click("[data-theme-choice='light']")
    assert theme(page) == "light" and background(page) != dark_bg
    page.wait_for_function("SETTINGS.theme === 'light'")
    assert json.loads(settings_file.read_text(encoding="utf-8"))["theme"] == "light"
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    assert theme(page) == "light"                                   # from the server, no flash

    page.emulate_media(color_scheme="dark")
    page.click("#btn-settings")
    page.click("[data-theme-choice='system']")
    assert theme(page) == "dark"
    page.emulate_media(color_scheme="light")                        # Windows switches: the app follows
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")
    page.reload()
    assert page.evaluate("document.documentElement.dataset.themePref") == "system"
    assert theme(page) == "light"
