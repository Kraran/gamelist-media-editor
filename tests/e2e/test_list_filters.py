"""Genre and favorite/hidden/kids filters, search in every field, CSV export of the list, copy of the ticked paths."""
import csv
import io
import json

import pytest

from gme import xml_store

pytestmark = pytest.mark.e2e

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><genre>Plateforme</genre><developer>Studio Nord</developer><favorite>true</favorite></game>
  <game><path>./bravo.zip</path><name>Bravo</name><genre>ACTION / LABYRINTHE</genre><hidden>true</hidden><image>./images/b.png</image></game>
  <game><path>./charlie.zip</path><name>Charlie</name><genre>Action</genre><kidgame>true</kidgame><publisher>Nordic Games</publisher></game>
  <game><path>./delta.zip</path><name>Delta</name></game>
</gameList>
"""


@pytest.fixture
def gamelist(tmp_path):
    xml = tmp_path / "roms" / "snes" / "gamelist.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(GAMELIST, encoding="utf-8")
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


def names(page):
    return page.locator("#game-list .game-item .name").all_inner_texts()


def choose(page, select, value):
    page.select_option(select, value)
    page.wait_for_function(f"document.getElementById('{select[1:]}').value === {json.dumps(value)}")


def test_genre_filter_groups_by_main_genre(page):
    options = page.locator("#genre-filter option").all_inner_texts()
    assert options == ["Genres", "ACTION (2)", "Plateforme (1)", "Sans genre (1)"]
    choose(page, "#genre-filter", "g:ACTION")
    assert names(page) == ["Bravo", "Charlie"]
    assert page.inner_text("#game-count").startswith("2")
    assert "is-active" in page.get_attribute("label:has(#genre-filter)", "class")
    choose(page, "#genre-filter", "none")
    assert names(page) == ["Delta"]


def test_flag_filter_and_faceted_counts(page):
    options = page.locator("#flag-filter option").all_inner_texts()
    assert options == ["Tous", "Favoris (1)", "Cachés (1)", "Non cachés (3)", "Pour enfants (1)"]
    choose(page, "#flag-filter", "favorite")
    assert names(page) == ["Alpha"]
    choose(page, "#flag-filter", "visible")
    assert names(page) == ["Alpha", "Charlie", "Delta"]
    # The genre menu counts what the flag filter leaves
    assert "ACTION (1)" in page.locator("#genre-filter option").all_inner_texts()
    choose(page, "#genre-filter", "g:ACTION")
    assert names(page) == ["Charlie"]
    choose(page, "#flag-filter", "kidgame")
    assert names(page) == ["Charlie"]
    choose(page, "#flag-filter", "hidden")
    assert names(page) == ["Bravo"]
    choose(page, "#flag-filter", "favorite")                       # no favorite action game
    assert names(page) == []
    assert page.is_visible("#game-list .filter-empty")


def test_search_in_every_field_is_an_option_and_is_saved(page, settings_file):
    page.fill("#search", "nord")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 0")
    with page.expect_response("**/api/settings"):
        page.click("#btn-search-all")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 2")
    assert names(page) == ["Alpha", "Charlie"]                      # developer, publisher
    assert page.get_attribute("#btn-search-all", "aria-pressed") == "true"
    assert page.get_attribute("#search", "placeholder") == "Rechercher dans tous les champs…"
    assert json.loads(settings_file.read_text(encoding="utf-8"))["search_all_fields"] is True
    page.fill("#search", "labyrinthe")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 1")
    assert names(page) == ["Bravo"]
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    assert page.get_attribute("#btn-search-all", "aria-pressed") == "true"


def test_csv_export_of_the_filtered_list(page):
    choose(page, "#genre-filter", "g:ACTION")
    page.click("#btn-actions")
    with page.expect_download() as dl:
        page.click("#btn-export-csv")
    assert dl.value.suggested_filename.startswith("gamelist-snes-") and dl.value.suggested_filename.endswith(".csv")
    raw = open(dl.value.path(), "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:2] == ["path", "name"]
    assert [r[1] for r in rows[1:]] == ["Bravo", "Charlie"]
    assert rows[1][-2:] == ["1/4", "video, marquee, boxart"]
    page.wait_for_selector("#toast.show")
    assert "2" in page.inner_text("#toast")


def test_copy_paths_of_the_ticked_games(page, gamelist):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.click("#gi-2 .gi-select")                                 # Charlie
    page.click("#gi-0 .gi-select")                                 # Alpha
    assert page.is_visible("#btn-selection-copy")
    page.click("#btn-selection-copy")
    page.wait_for_selector("#toast.show")
    folder = gamelist.parent
    assert page.evaluate("navigator.clipboard.readText()") == f"{folder / 'alpha.zip'}\n{folder / 'charlie.zip'}"
    # Also in the game menu, with the number of ticked games
    page.evaluate("navigator.clipboard.writeText('')")
    page.click("#gi-3")
    page.wait_for_selector("#editor:not([hidden])")
    page.click("#btn-game-menu")
    assert page.is_visible("#btn-copy-selection-paths")
    assert "2" in page.inner_text("#copy-selection-sub")
    page.click("#btn-copy-selection-paths")
    page.wait_for_function("navigator.clipboard.readText().then(t => t.length > 0)")
    assert page.evaluate("navigator.clipboard.readText()").count("\n") == 1
    page.keyboard.press("Escape")                                   # clears the ticks
    page.click("#btn-game-menu")
    assert page.is_hidden("#btn-copy-selection-paths")
