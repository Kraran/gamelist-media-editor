"""Delayed responses cannot hide edits or update a different selected game."""
import io

import pytest
from PIL import Image

from .test_editor_safety import select, game

pytestmark = pytest.mark.e2e


def delay_response(page, path):
    """Keep the real response pending in the browser while the user keeps working."""
    page.evaluate("""path => {
      const original = window.fetch;
      window.fetch = async (...args) => {
        const response = await original(...args);
        if (String(args[0]).startsWith(path)) {
          await new Promise(resolve => { window.releaseResponse = resolve; });
        }
        return response;
      };
    }""", path)


def test_typing_during_save_stays_unsaved(page, gamelist):
    select(page, "Alpha")
    page.wait_for_function("!document.getElementById('desc-textarea').readOnly")
    page.fill("#desc-textarea", "Sent to disk")
    delay_response(page, "/api/game/0?")
    page.click("#btn-save")
    page.wait_for_function("typeof window.releaseResponse === 'function'")
    page.fill("#desc-textarea", "Typed while saving")
    page.evaluate("window.releaseResponse()")
    page.wait_for_function("!_saving")
    assert game(gamelist, "Alpha")["desc"] == "Sent to disk"
    assert page.input_value("#desc-textarea") == "Typed while saving"
    assert page.is_visible("#save-bar")
    assert page.evaluate("changedFields()") == ["desc"]


def test_an_old_upload_updates_its_game_without_touching_the_new_selection(page, gamelist):
    select(page, "Alpha")
    delay_response(page, "/api/upload/")
    buf = io.BytesIO()
    Image.new("RGB", (16, 12), "red").save(buf, "PNG")
    page.evaluate("document.getElementById('media-file-input').dataset.field = 'image'")
    page.set_input_files("#media-file-input", {"name": "new.png", "mimeType": "image/png", "buffer": buf.getvalue()})
    page.wait_for_function("typeof window.releaseResponse === 'function'")
    select(page, "Bravo")
    page.evaluate("window.releaseResponse()")
    page.wait_for_function("games.find(g => g.name === 'Alpha').image")
    assert not page.evaluate("games.find(g => g.name === 'Bravo').image || ''")
    assert page.input_value("#game-name-input") == "Bravo"
    assert page.locator('.media-tile[data-field="image"]').count() == 0
    assert game(gamelist, "Alpha")["image"]
    assert "image" not in game(gamelist, "Bravo")


def test_returning_to_a_cached_game_unlocks_its_description(page):
    select(page, "Alpha")
    page.wait_for_function("!document.getElementById('desc-textarea').readOnly")
    delay_response(page, "/api/game/1?")
    select(page, "Bravo")
    page.wait_for_function("typeof window.releaseResponse === 'function'")
    select(page, "Alpha")
    assert page.evaluate("!document.getElementById('desc-textarea').readOnly")
    page.fill("#desc-textarea", "Still editing Alpha")
    page.evaluate("window.releaseResponse()")
    page.wait_for_function("games.find(g => g.name === 'Bravo')._detail")
    assert page.input_value("#desc-textarea") == "Still editing Alpha"
    assert page.is_visible("#save-bar")


def test_refresh_preserves_an_unsaved_description(page):
    select(page, "Alpha")
    page.wait_for_function("!document.getElementById('desc-textarea').readOnly")
    page.fill("#desc-textarea", "Unsaved draft")
    page.evaluate("loadGames()")
    page.wait_for_function("!document.getElementById('desc-textarea').readOnly")
    assert page.input_value("#desc-textarea") == "Unsaved draft"
    assert page.evaluate("changedFields()") == ["desc"]
