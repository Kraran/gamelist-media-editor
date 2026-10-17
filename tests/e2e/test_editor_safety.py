"""Editing never loses data: untouched fields survive, unsaved changes are protected."""
import pytest
from lxml import etree

from .conftest import wait_until

pytestmark = pytest.mark.e2e


def game(xml, name):
    for g in etree.parse(str(xml)).getroot().findall("game"):
        if g.findtext("name") == name:
            return {c.tag: (c.text or "") for c in g}
    return None


def select(page, name):
    page.click(f"#game-list >> text={name}")
    page.wait_for_function(f"document.getElementById('game-name-input').value === {name!r}")


def confirm_dialog(page):
    page.wait_for_selector("#confirm-modal.open")
    return page.inner_text("#confirm-body")


# --- Genre and untouched fields -------------------------------------------------

def test_unknown_genre_is_shown_and_kept(page, gamelist):
    select(page, "Alpha")
    assert page.input_value("#meta-genre-main") == "Platform"
    page.fill("#meta-players", "1-4")
    page.click("#btn-save-meta")
    assert wait_until(lambda: game(gamelist, "Alpha").get("players") == "1-4")
    alpha = game(gamelist, "Alpha")
    assert alpha["genre"] == "Platform"          # was erased before the fix
    assert alpha["kidgame"] == "1"               # untouched: not rewritten as "" / "true"
    assert alpha["lang"] == "en,fr"


def test_known_genre_with_sub_genre_round_trips(page, gamelist):
    select(page, "Bravo")
    assert page.input_value("#meta-genre-main") == "ACTION"
    assert page.input_value("#meta-genre-sub") == "LABYRINTHE"
    page.fill("#meta-developer", "Studio B")
    page.click("#btn-save-meta")
    assert wait_until(lambda: game(gamelist, "Bravo").get("developer") == "Studio B")
    assert game(gamelist, "Bravo")["genre"] == "ACTION / LABYRINTHE"


def test_changing_the_genre_still_works(page, gamelist):
    select(page, "Alpha")
    page.select_option("#meta-genre-main", "COMBAT")
    page.click("#btn-save-meta")
    assert wait_until(lambda: game(gamelist, "Alpha").get("genre") == "COMBAT")


def test_save_with_nothing_changed_writes_nothing(page, gamelist):
    select(page, "Alpha")
    before = gamelist.read_bytes()
    page.click("#btn-save-meta")
    page.wait_for_selector("#toast.show, #toast.visible, #toast:not(:empty)")
    assert gamelist.read_bytes() == before


# --- Unsaved changes ---------------------------------------------------------------

def test_switching_game_asks_and_cancel_keeps_the_text(page, gamelist):
    select(page, "Alpha")
    page.fill("#desc-textarea", "My new text")
    page.click("#game-list >> text=Bravo")
    assert "Description" in confirm_dialog(page)
    page.click("#confirm-cancel")
    assert page.input_value("#game-name-input") == "Alpha"
    assert page.input_value("#desc-textarea") == "My new text"
    assert game(gamelist, "Alpha")["desc"] == "Alpha desc"


def test_dont_save_switches_and_writes_nothing(page, gamelist):
    select(page, "Alpha")
    page.fill("#desc-textarea", "Thrown away")
    page.click("#game-list >> text=Bravo")
    confirm_dialog(page)
    page.click("#confirm-extra")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Bravo'")
    assert game(gamelist, "Alpha")["desc"] == "Alpha desc"


def test_save_from_the_prompt_writes_then_switches(page, gamelist):
    select(page, "Alpha")
    page.fill("#desc-textarea", "Kept text")
    page.fill("#meta-players", "2")
    page.keyboard.press("Escape")  # leave the field; arrows now navigate the list
    page.click("#game-list >> text=Bravo")
    body = confirm_dialog(page)
    assert "Description" in body and "Joueurs" in body
    page.click("#confirm-ok")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Bravo'")
    alpha = game(gamelist, "Alpha")
    assert alpha["desc"] == "Kept text" and alpha["players"] == "2"


def test_ctrl_s_saves_every_changed_part(page, gamelist):
    select(page, "Charlie")
    page.fill("#game-name-input", "Charlie II")
    page.fill("#desc-textarea", "Charlie desc")
    page.click("#game-path")  # focus outside the fields
    page.keyboard.press("Control+s")
    assert wait_until(lambda: (game(gamelist, "Charlie II") or {}).get("desc") == "Charlie desc")


def test_save_button_shows_pending_changes(page):
    select(page, "Alpha")
    assert "has-changes" not in page.get_attribute("#btn-save-desc", "class")
    page.fill("#desc-textarea", "x")
    assert "has-changes" in page.get_attribute("#btn-save-desc", "class")
    assert "has-changes" not in page.get_attribute("#btn-save-meta", "class")


def test_reload_asks_when_changes_are_pending(page):
    select(page, "Alpha")
    page.fill("#meta-players", "9")
    page.click("#btn-reload")
    confirm_dialog(page)
    page.click("#confirm-cancel")
    assert page.input_value("#meta-players") == "9"


BEFORE_UNLOAD = "!window.dispatchEvent(new Event('beforeunload', {cancelable: true}))"


def test_closing_the_window_with_changes_is_blocked(page):
    select(page, "Alpha")
    assert page.evaluate(BEFORE_UNLOAD) is False      # nothing pending: closes freely
    page.fill("#desc-textarea", "unsaved")
    assert page.evaluate(BEFORE_UNLOAD) is True       # pending: the browser asks


def test_switching_without_changes_does_not_ask(page):
    select(page, "Alpha")
    page.click("#game-list >> text=Bravo")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Bravo'")
    assert not page.is_visible("#confirm-modal.open")


# --- Dialogs -----------------------------------------------------------------------

def test_escape_closes_the_open_gamelist_dialog(page):
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")
    page.keyboard.press("Escape")
    page.wait_for_selector("#open-gamelist-modal:not(.open)", state="attached")
    assert "open" not in page.get_attribute("#open-gamelist-modal", "class")
