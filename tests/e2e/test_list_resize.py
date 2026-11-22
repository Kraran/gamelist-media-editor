"""Width of the game list: dragged with the mouse, arrows on the handle, double-click resets; saved by the server."""
import json

import pytest

pytestmark = pytest.mark.e2e


def width(page, selector):
    return page.evaluate(f"Math.round(document.querySelector('{selector}').getBoundingClientRect().width)")


def drag_handle(page, dx):
    box = page.locator("#list-resizer").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    for step in range(1, 11):                                       # several moves, like a real drag
        page.mouse.move(x + dx * step / 10, y)
    page.mouse.up()


def saved(settings_file):
    return json.loads(settings_file.read_text(encoding="utf-8"))["list_width"]


def test_drag_widens_the_list_and_shrinks_the_editor(page, settings_file):
    page.click("#gi-0")
    page.wait_for_selector("#editor:not([hidden])")
    list_w, stage_w = width(page, "#sidebar"), width(page, ".stage")
    with page.expect_response("**/api/settings"):
        drag_handle(page, 300)
    assert width(page, "#sidebar") == list_w + 300
    assert width(page, ".stage") == stage_w - 300
    assert saved(settings_file) == list_w + 300
    # The media tiles get a smaller minimum as the list grows
    assert page.evaluate("getComputedStyle(document.querySelector('.media-grid')).columnWidth") != "220px"

    page.reload()                                                   # written by the server: no jump on load
    page.wait_for_selector("#game-list .game-item")
    assert width(page, "#sidebar") == list_w + 300

    with page.expect_response("**/api/settings"):
        page.dblclick("#list-resizer")                              # back to the default
    page.wait_for_function(f"document.getElementById('sidebar').getBoundingClientRect().width < {list_w + 1}")
    assert width(page, "#sidebar") == list_w
    assert saved(settings_file) is None


def test_the_editor_keeps_its_minimum(page, settings_file):
    with page.expect_response("**/api/settings"):
        drag_handle(page, 3000)
    assert width(page, ".content") == 600                           # LIST_CONTENT_MIN
    with page.expect_response("**/api/settings"):
        drag_handle(page, -3000)
    assert width(page, "#sidebar") == 260                           # LIST_WIDTH_MIN


def test_keyboard_and_escape(page, settings_file):
    list_w = width(page, "#sidebar")
    page.focus("#list-resizer")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_function(f"document.getElementById('sidebar').getBoundingClientRect().width > {list_w + 79}")
    assert width(page, "#sidebar") == list_w + 16 + 64
    assert page.get_attribute("#list-resizer", "aria-valuenow") == str(list_w + 80)
    with page.expect_response("**/api/settings"):                   # saved shortly after the last key
        page.keyboard.press("ArrowLeft")
    assert saved(settings_file) == list_w + 64

    # Escape during a drag puts the width back
    box = page.locator("#list-resizer").bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + 200
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 200, y)
    page.wait_for_function(f"document.getElementById('sidebar').getBoundingClientRect().width > {list_w + 200}")
    page.keyboard.press("Escape")
    page.mouse.up()
    page.wait_for_function(f"Math.round(document.getElementById('sidebar').getBoundingClientRect().width) === {list_w + 64}")
    assert not page.evaluate("document.body.classList.contains('is-resizing-list')")
