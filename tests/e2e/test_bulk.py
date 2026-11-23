"""Edit in bulk, removing many games, the column filter, Ctrl+A and the statistics."""
import os

import pytest
from lxml import etree

from gme import xml_store

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")          # folder for documentation screenshots (optional)

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./Alpha (Europe).zip</path><name>alpha</name><genre>Platform</genre><developer>Interton</developer>
    <image>./images/alpha.png</image><favorite>true</favorite><playcount>4</playcount></game>
  <game><path>./Bravo (USA) [!].zip</path><name>Bravo Shoot</name><genre>Shoot'em up</genre><image>./images/gone.png</image></game>
  <game><path>./charlie.zip</path><name>Charlie</name><genre>Shoot'em up</genre><developer>Radofin</developer></game>
  <game><path>./delta.zip</path><name>Delta</name></game>
</gameList>
"""


@pytest.fixture
def gamelist(tmp_path, trashed):
    xml = tmp_path / "roms" / "vc4000" / "gamelist.xml"
    (xml.parent / "images").mkdir(parents=True)
    xml.write_text(GAMELIST, encoding="utf-8")
    for rel in ("Alpha (Europe).zip", "Bravo (USA) [!].zip", "charlie.zip", "delta.zip", "images/alpha.png"):
        (xml.parent / rel).write_bytes(b"x" * 10)
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


def names(page):
    return page.locator("#game-list .game-item .name").all_inner_texts()


def xml_names(xml):
    return [g.findtext("name") for g in etree.parse(str(xml)).getroot().findall("game")]


def open_bulk(page, tab):
    page.click("#btn-actions")
    page.click("#btn-bulk")
    page.wait_for_selector("#bulk-modal.open")
    page.click(f'[data-bulk-tab="{tab}"]')


def run_preview(page):
    page.click("#bulk-preview-btn")
    page.wait_for_selector("#bulk-preview .bulk-summary, #bulk-preview .bulk-empty:not(:has-text('Aperçu'))")


def undo(page):
    page.click("#toast .toast-action")
    page.wait_for_function("document.getElementById('toast').textContent.includes('restaur')")


def test_set_a_field_on_the_ticked_games_then_undo(page, gamelist):
    page.click("#game-list .game-item >> nth=1", modifiers=["Control"])
    page.click("#game-list .game-item >> nth=3", modifiers=["Control"])
    page.click("#btn-bulk-selection")
    page.wait_for_selector("#bulk-modal.open")
    assert page.input_value("#bulk-scope") == "checked"
    page.select_option("#bulk-set-field", "publisher")
    page.fill("#bulk-set-value", "Interton")
    assert page.is_disabled("#bulk-apply")
    run_preview(page)
    assert page.locator("#bulk-preview tbody tr").count() == 2
    assert page.inner_text("#bulk-apply-label") == "Appliquer (2)"
    page.fill("#bulk-set-value", "Other")                       # any change drops the preview
    assert page.is_disabled("#bulk-apply")
    page.fill("#bulk-set-value", "Interton")
    run_preview(page)
    page.click("#bulk-apply")
    page.wait_for_selector("#toast.show .toast-action")
    assert not page.is_visible("#bulk-modal")
    pubs = [g.findtext("publisher") for g in etree.parse(str(gamelist)).getroot().findall("game")]
    assert pubs == [None, "Interton", None, "Interton"]
    undo(page)
    pubs = [g.findtext("publisher") for g in etree.parse(str(gamelist)).getroot().findall("game")]
    assert pubs == [None, None, None, None]


def test_find_replace_with_a_regex_preview(page, gamelist):
    open_bulk(page, "replace")
    page.select_option("#bulk-rep-field", "name")
    page.fill("#bulk-rep-find", "(")                            # invalid regex: shown, nothing applied
    page.check("#bulk-rep-regex")
    run_preview(page)
    assert "invalide" in page.inner_text("#bulk-preview")
    assert page.is_disabled("#bulk-apply")
    page.fill("#bulk-rep-find", r"^(\w)")
    page.fill("#bulk-rep-with", r"[\1]")
    run_preview(page)
    after = page.locator("#bulk-preview .bulk-after").all_inner_texts()
    assert after == ["[a]lpha", "[B]ravo Shoot", "[C]harlie", "[D]elta"]
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "bulk-replace-preview.png"))
    page.click("#bulk-apply")
    page.wait_for_selector("#toast.show .toast-action")
    assert xml_names(gamelist)[:2] == ["[a]lpha", "[B]ravo Shoot"]


def test_reset_names_from_file_names(page, gamelist):
    open_bulk(page, "reset_name")
    assert page.is_checked("#bulk-name-tags")
    run_preview(page)
    page.click("#bulk-apply")
    page.wait_for_selector("#toast.show .toast-action")
    assert xml_names(gamelist) == ["Alpha", "Bravo", "charlie", "delta"]
    page.wait_for_function("[...document.querySelectorAll('#game-list .game-item .name')].map(e => e.textContent).includes('Bravo')")


def test_remove_games_keeps_roms_and_can_be_undone(page, gamelist, trashed):
    page.click("#game-list .game-item >> nth=0", modifiers=["Control"])
    page.click("#game-list .game-item >> nth=1", modifiers=["Control"])
    page.click("#btn-bulk-selection")
    page.click('[data-bulk-tab="delete"]')
    assert not page.is_checked("#bulk-del-media")              # media off by default
    run_preview(page)
    assert page.locator("#bulk-preview .bulk-list li").all_inner_texts() == ["alpha", "Bravo Shoot"]
    assert "jamais" in page.inner_text("#bulk-preview")
    page.check("#bulk-del-media")
    assert page.is_disabled("#bulk-apply")
    run_preview(page)
    assert "images/alpha.png" in page.inner_text("#bulk-preview")
    page.uncheck("#bulk-del-media")
    run_preview(page)
    page.click("#bulk-apply")
    page.wait_for_selector("#confirm-modal.open")
    page.click("#confirm-ok")
    page.wait_for_selector("#toast.show .toast-action")
    assert xml_names(gamelist) == ["Charlie", "Delta"]
    assert trashed == []
    assert (gamelist.parent / "Alpha (Europe).zip").exists() and (gamelist.parent / "images" / "alpha.png").exists()
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 2")
    assert page.is_hidden("#list-selection")
    undo(page)
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 4")
    assert xml_names(gamelist) == ["alpha", "Bravo Shoot", "Charlie", "Delta"]


def with_regions(page, gamelist):
    xml = gamelist.read_text(encoding="utf-8")
    xml = xml.replace("<name>alpha</name>", "<name>alpha</name><region>eu</region>", 1)
    xml = xml.replace("<name>Delta</name>", "<name>Delta</name><region>us</region><region/>", 1)
    gamelist.write_text(xml, encoding="utf-8")
    page.reload()
    page.wait_for_selector("#game-list .game-item")


def tags(xml, tag):
    return [len(g.findall(tag)) for g in etree.parse(str(xml)).getroot().findall("game")]


def open_clear_fields(page):
    open_bulk(page, "clear_fields")
    page.wait_for_selector("#bulk-clear-list [data-bulk-clear]")


def test_clear_fields_with_counts_confirmation_and_undo(page, gamelist):
    with_regions(page, gamelist)
    page.click("#game-list .game-item >> nth=0")
    page.wait_for_function("document.getElementById('meta-region').value === 'eu'")
    open_clear_fields(page)
    count = lambda k: page.inner_text(f'#bulk-clear-list label:has([data-bulk-clear="{k}"]) .bulk-count')
    assert count("genre") == "3" and count("region") == "2" and count("publisher") == "0"
    assert page.locator('[data-bulk-clear="playcount"]').count() == 1      # a tag some game has
    assert page.locator('[data-bulk-clear="md5"]').count() == 0            # one no game has
    assert page.locator('[data-bulk-clear="name"], [data-bulk-clear="path"], [data-bulk-clear="image"]').count() == 0
    run_preview(page)
    assert "Cochez au moins un champ" in page.inner_text("#bulk-preview")
    page.check('[data-bulk-clear="region"]')
    page.check('[data-bulk-clear="favorite"]')
    run_preview(page)
    assert page.locator("#bulk-preview tbody tr").count() == 3     # region of alpha and Delta, favorite of alpha
    assert "balise retirée" in page.inner_text("#bulk-preview")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "bulk-clear-fields.png"))
    before = gamelist.read_bytes()
    page.click("#bulk-apply")
    page.wait_for_selector("#confirm-modal.open")
    assert page.evaluate("document.activeElement.id") == "confirm-cancel"
    body = page.inner_text("#confirm-body")
    assert "Région" in body and "Favori" in body and "2 jeu" in body
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "bulk-clear-fields-confirm.png"))
    page.click("#confirm-cancel")
    page.wait_for_timeout(200)
    assert gamelist.read_bytes() == before                         # cancelled: nothing written
    page.click("#bulk-apply")
    page.wait_for_selector("#confirm-modal.open")
    page.click("#confirm-ok")
    page.wait_for_selector("#toast.show .toast-action")
    assert not page.is_visible("#bulk-modal")
    assert tags(gamelist, "region") == [0, 0, 0, 0] and tags(gamelist, "favorite") == [0, 0, 0, 0]
    assert "<region" not in gamelist.read_text(encoding="utf-8")   # no empty tag left
    assert tags(gamelist, "genre") == [1, 1, 1, 0]
    page.wait_for_function("document.getElementById('meta-region').value === ''")   # the open game too
    assert (gamelist.parent / "Alpha (Europe).zip").read_bytes() == b"x" * 10
    undo(page)
    assert tags(gamelist, "region") == [1, 0, 0, 2] and tags(gamelist, "favorite") == [1, 0, 0, 0]


def test_clear_fields_follows_the_scope(page, gamelist):
    with_regions(page, gamelist)
    page.click("#game-list .game-item >> nth=3", modifiers=["Control"])
    page.click("#btn-bulk-selection")
    page.wait_for_selector("#bulk-modal.open")
    page.click('[data-bulk-tab="clear_fields"]')
    page.wait_for_selector("#bulk-clear-list [data-bulk-clear]")
    assert page.inner_text('#bulk-clear-list label:has([data-bulk-clear="region"]) .bulk-count') == "1"
    page.check('[data-bulk-clear="region"]')
    page.select_option("#bulk-scope", "all")                      # re-counted, the tick is kept
    page.wait_for_function("""document.querySelector('#bulk-clear-list label:has([data-bulk-clear="region"]) .bulk-count')
                              .textContent === '2'""")
    assert page.is_checked('[data-bulk-clear="region"]')
    page.select_option("#bulk-scope", "checked")
    page.wait_for_function("""document.querySelector('#bulk-clear-list label:has([data-bulk-clear="region"]) .bulk-count')
                              .textContent === '1'""")
    run_preview(page)
    page.click("#bulk-apply")
    page.wait_for_selector("#confirm-modal.open")
    page.click("#confirm-ok")
    page.wait_for_selector("#toast.show .toast-action")
    assert tags(gamelist, "region") == [1, 0, 0, 0]               # only Delta, the ticked game


def test_column_filter_combines_with_the_other_filters_and_ctrl_a(page, gamelist):
    page.click("#btn-col-filter")
    assert page.is_visible("#col-filter")
    page.select_option("#col-field", "genre")
    page.select_option("#col-op", "contains")
    page.fill("#col-value", "shoot")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 2")
    assert names(page) == ["Bravo Shoot", "Charlie"]
    page.select_option("#col-field", "developer")
    page.select_option("#col-op", "empty")
    assert page.is_hidden("#col-value")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 2")
    assert names(page) == ["Bravo Shoot", "Delta"]
    page.fill("#search", "delta")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 1")
    page.fill("#search", "")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 2")
    page.click("#game-list .game-item >> nth=0")               # focus the list, not a field
    page.keyboard.press("Control+a")
    page.wait_for_selector("#list-selection:not([hidden])")
    assert page.inner_text("#list-selection-count").startswith("2")
    page.click("#col-clear")
    assert page.is_hidden("#col-filter")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 4")
    page.click("#btn-select-shown")
    assert page.inner_text("#list-selection-count").startswith("4")


def test_statistics(page, gamelist):
    page.click("#btn-actions")
    page.click("#btn-stats")
    page.wait_for_selector("#stats-body .stat-card")
    cards = dict(zip(page.locator(".stat-label").all_inner_texts(), page.locator(".stat-value").all_inner_texts()))
    assert cards["Jeux"] == "4" and cards["Favori"] == "1" and cards["Joués"] == "1"
    row = page.locator(".stats-table tr", has_text="Image").first
    assert row.locator("td").all_inner_texts()[2:5] == ["1", "1", "2"]
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "stats.png"))
    row.locator("[data-stats-missing]").click()
    assert not page.is_visible("#stats-modal")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 2")
    assert names(page) == ["Charlie", "Delta"]
    assert page.input_value("#col-op") == "empty"


def test_escape_closes_and_unsaved_changes_block(page, gamelist):
    open_bulk(page, "set")
    page.keyboard.press("Escape")
    assert not page.is_visible("#bulk-modal")
    page.click("#game-list .game-item >> nth=0")
    page.fill("#game-name-input", "Changed")
    page.click("#btn-actions")
    page.click("#btn-bulk")
    page.wait_for_selector("#toast.show.warning")
    assert not page.is_visible("#bulk-modal")
    assert xml_names(gamelist)[0] == "alpha"
