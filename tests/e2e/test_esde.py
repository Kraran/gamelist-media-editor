"""ES-DE in the browser: media found by name in downloaded_media, ES-DE's media
types only, the file written where ES-DE looks, and the ES-DE overview."""
import os

import pytest
from lxml import etree

from gme import overview, xml_store
from tests.esde_tree import make_esde, picture

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")


@pytest.fixture
def esde_tree(page, tmp_path):
    paths = make_esde(tmp_path / "esde")
    xml_store.set_gamelist_path(paths["snes_xml"])
    overview.reset()
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    page.wait_for_selector("#system-profile:not([hidden])")
    yield paths
    overview.reset()


def open_game(page, name):
    page.click(f"#game-list .game-item:has-text('{name}')")
    page.wait_for_function(f"document.getElementById('game-name-input').value === '{name}'")


def test_editor_shows_esde_media_and_only_esde_types(page, esde_tree):
    assert page.inner_text("#system-profile") == "ES-DE"
    open_game(page, "Alpha")
    for field in ("thumbnail", "image", "marquee"):
        page.wait_for_selector(f"#media-grid .media-tile[data-field='{field}'] img")
    page.wait_for_function("[...document.querySelectorAll('#media-grid .media-tile img')].every(i => i.complete && i.naturalWidth > 0)")
    # ES-DE has no wheel, map, bezel or music folder: no tile, no "missing" chip
    for field in ("wheel", "map", "bezel", "music"):
        assert page.locator(f"[data-field='{field}']").count() == 0
    assert page.locator(".missing-chip[data-field='video']").count() == 1
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "esde-editor.png"))


def test_upload_and_remove_follow_the_file_names(page, esde_tree, tmp_path, trashed):
    open_game(page, "Charlie")
    page.wait_for_selector(".missing-chip[data-field='thumbnail']")
    src = tmp_path / "my cover.png"
    src.write_bytes(picture((180, 60, 20)))
    with page.expect_file_chooser() as fc:
        page.click(".missing-chip[data-field='thumbnail']")
    fc.value.set_files(str(src))
    page.wait_for_selector(".media-tile[data-field='thumbnail'] img")
    cover = os.path.join(esde_tree["snes_media"], "covers", "Charlie.png")
    assert os.path.isfile(cover)
    assert "<thumbnail>" not in open(esde_tree["snes_xml"], encoding="utf-8").read()
    page.click(".media-tile[data-field='thumbnail'] [data-action='clear']")
    page.wait_for_selector("#confirm-modal.open")
    assert "corbeille" in page.inner_text("#confirm-body")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "esde-remove-media.png"))
    page.click("#confirm-ok")
    page.wait_for_selector(".missing-chip[data-field='thumbnail']")
    assert not os.path.exists(cover) and trashed == [cover]


def test_scrape_writes_into_downloaded_media(page, esde_tree, fake_sources):
    open_game(page, "Charlie")
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-modal.open #ss-fields .ss-meta-row")
    fields = page.eval_on_selector_all("#ss-fields input[data-ss-field]", "els => els.map(e => e.dataset.ssField)")
    assert "image" in fields and "marquee" in fields and "wheel" not in fields
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "esde-scrape.png"))
    page.click("#ss-modal-apply")
    page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')")
    page.wait_for_selector("#media-grid .media-tile[data-field='image'] img")
    assert os.path.isfile(os.path.join(esde_tree["snes_media"], "screenshots", "Charlie.png"))
    assert os.path.isfile(os.path.join(esde_tree["snes_media"], "marquees", "Charlie.png"))
    game = [g for g in etree.parse(esde_tree["snes_xml"]).getroot().findall("game")
            if g.findtext("path") == "./Charlie.zip"][0]
    assert game.findtext("developer") == "Studio Alpha"
    assert game.find("image") is None and game.find("marquee") is None


def test_batch_scrape_offers_esde_media_only(page, esde_tree):
    page.click("#btn-actions")
    page.click("#btn-batch-scrape")
    page.wait_for_selector("#batch-modal.open")
    boxes = page.eval_on_selector_all("#batch-modal input[data-batch-field]", "els => els.map(e => e.dataset.batchField)")
    assert "thumbnail" in boxes and "video" in boxes
    assert not {"wheel", "map", "bezel", "pad2key"} & set(boxes)


def test_overview_from_the_esde_folder(page, esde_tree):
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")
    page.evaluate(f"browseDirectory({esde_tree['home']!r})")
    page.wait_for_selector("#open-gl-esde:not([hidden])")
    assert page.is_hidden("#open-gl-new")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "esde-open-folder.png"))
    page.click("#open-gl-esde-overview")
    page.wait_for_selector("#overview-modal.open #overview-table")
    page.wait_for_function("document.getElementById('overview-progress').hidden")
    names = page.locator("#overview-table tbody tr .ov-name").all_inner_texts()
    assert sorted(names) == ["Sega Mega Drive", "Super Nintendo"]          # not CLEANUP
    assert page.locator("#overview-table .ov-chip.is-esde").count() == 2
    assert page.locator("#overview-table .ov-media.is-na").count() == 2   # the wheel column
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "esde-overview.png"))
