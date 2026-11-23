"""Multi-system overview: a roms root opened from the folder browser, its systems in a
sortable table, one click to edit a system, the ▾ switcher and the recent roms folders."""
import os
import threading

import pytest

from gme import overview
from tests.conftest import picture

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")

NES = """<?xml version="1.0"?>
<gameList>
  <game><path>./zelda.nes</path><name>Zelda</name><desc>Link</desc><image>./images/zelda.png</image></game>
  <game><path>./metroid.nes</path><name>Metroid</name><image>./images/metroid.png</image></game>
  <game><path>./kirby.nes</path><name>Kirby</name></game>
  <game><path>./mario.nes</path><name>Mario</name></game>
</gameList>
"""


@pytest.fixture
def roms(gamelist):
    root = gamelist.parent.parent                       # tmp/roms (snes is the open gamelist)
    nes = root / "nes"
    (nes / "images").mkdir(parents=True)
    (nes / "gamelist.xml").write_text(NES, encoding="utf-8")
    for rom in ("zelda", "metroid", "kirby"):            # mario.nes is missing
        (nes / f"{rom}.nes").write_bytes(b"rom")
    (nes / "images" / "zelda.png").write_bytes(picture())  # metroid.png is a broken link
    (root / "gba").mkdir()
    (root / "gba" / "pokemon.gba").write_bytes(b"rom")
    (root / "bios").mkdir()
    (root / "bios" / "bios.bin").write_bytes(b"bios")
    overview.reset()
    yield root
    overview.reset()


def open_overview(page):
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")
    page.wait_for_selector("#open-gl-root:not([hidden])")
    page.click("#open-gl-root")
    page.wait_for_selector("#overview-modal.open #overview-table")
    page.wait_for_function("document.getElementById('overview-progress').hidden")


def rows(page):
    return page.locator("#overview-table tbody tr .ov-name").all_inner_texts()


def cell(page, name, col):
    """Text of column ``col`` (1-based) of the row of ``name``."""
    return page.locator(f"#overview-table tbody tr:has(.ov-name:text-is('{name}')) td:nth-child({col + 1})").inner_text().strip()


def test_overview_lists_every_system_with_its_counts(page, roms):
    open_overview(page)
    assert page.inner_text("#overview-root") == str(roms)
    assert rows(page) == ["Game Boy Advance", "Nintendo (NES)", "Super Nintendo"]   # bios/ is not a system
    assert cell(page, "Nintendo (NES)", 2) == "4"
    assert cell(page, "Nintendo (NES)", 3) == "1"                    # mario.nes missing
    assert cell(page, "Nintendo (NES)", 5) == "25 %"                 # one image on disk out of 4 games
    assert "1 liens cassés" in page.get_attribute(
        "#overview-table tbody tr:has(.ov-name:text-is('Nintendo (NES)')) td:nth-child(6)", "title")
    assert cell(page, "Super Nintendo", 2) == "3"
    assert page.locator("#overview-table tr.is-current .ov-name").inner_text() == "Super Nintendo"
    gba = page.locator("#overview-table tr.is-no-xml")
    assert "Pas de gamelist" in gba.inner_text() and "1 ROM" in gba.inner_text()
    totals = page.inner_text("#overview-totals")
    assert "3\nSystèmes" in totals and "1 sans gamelist" in totals and "7\nJeux" in totals
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "overview.png"))


def test_columns_sort_both_ways(page, roms):
    open_overview(page)
    page.click('[data-ov-sort="games"]')
    assert rows(page)[:2] == ["Nintendo (NES)", "Super Nintendo"]
    th = page.locator("th:has([data-ov-sort='games'])")
    assert th.get_attribute("aria-sort") == "descending"
    page.click('[data-ov-sort="games"]')
    assert th.get_attribute("aria-sort") == "ascending"
    assert rows(page)[-1] == "Nintendo (NES)"
    assert page.evaluate("document.activeElement.dataset.ovSort") == "games"


def test_open_a_system_then_switch_back_with_the_switcher(page, roms):
    open_overview(page)
    page.click("#overview-table [data-ov-open$='nes" + os.sep.replace("\\", "\\\\") + "gamelist.xml']")
    page.wait_for_function("document.getElementById('system-name').textContent === 'nes'")
    assert not page.is_visible("#overview-modal")
    assert page.locator("#game-list .game-item").count() == 4
    assert page.is_visible("#btn-systems")
    page.click("#btn-systems")
    items = page.locator("#systems-menu [role=menuitemradio]")
    assert items.count() == 2                                 # gba has no gamelist
    assert page.locator("#systems-menu [aria-checked=true] .menu-item-title").inner_text() == "Nintendo (NES)"
    page.click("#systems-menu [role=menuitemradio]:has-text('Super Nintendo')")
    page.wait_for_function("document.getElementById('system-name').textContent === 'snes'")
    assert page.locator("#game-list .game-item").count() == 3
    page.click("#btn-systems")
    page.click("#systems-menu [data-ov-overview]")
    page.wait_for_selector("#overview-modal.open #overview-table")
    assert page.locator("#overview-table tr.is-current .ov-name").inner_text() == "Super Nintendo"


def test_unsaved_changes_are_not_lost_when_switching(page, roms):
    open_overview(page)
    page.click("#overview-close")
    page.click("#game-list >> text=Alpha")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")
    page.fill("#game-name-input", "Alpha changed")
    page.click("#btn-systems")
    page.click("#systems-menu [data-ov-overview]")               # the overview itself asks nothing
    page.wait_for_selector("#overview-modal.open #overview-table")
    page.click("#overview-table tr:has(.ov-name:text-is('Nintendo (NES)')) .ov-open")
    page.wait_for_selector("#confirm-modal.open")
    page.click("#confirm-cancel")
    page.wait_for_timeout(200)
    assert page.inner_text("#system-name") == "snes"
    assert page.input_value("#game-name-input") == "Alpha changed"


def test_switcher_and_recent_roms_folders_survive_a_reload(page, roms):
    open_overview(page)
    page.click("#overview-close")
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    page.wait_for_selector("#btn-systems")                    # the open snes is in a recent roms root
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gl-roots .open-gl-root-item")
    assert page.get_attribute("#open-gl-roots .open-gl-root-item", "data-path") == str(roms)
    page.click("#open-gl-roots .open-gl-root-item")
    page.wait_for_selector("#overview-modal.open #overview-table")


def test_a_folder_without_gamelist_offers_to_create_one(page, roms):
    open_overview(page)
    page.click("#overview-table [data-ov-create]")
    page.wait_for_selector("#newgl-modal.open")
    assert page.inner_text("#newgl-folder") == str(roms / "gba")
    page.wait_for_selector("#newgl-preview .bulk-summary")
    assert page.locator("#newgl-preview tbody tr").count() == 1


def test_progress_spinner_and_stop(page, roms, monkeypatch):
    gate = threading.Event()
    real = overview.scan_system
    monkeypatch.setattr(overview, "WORKERS", 1)
    monkeypatch.setattr(overview, "scan_system", lambda s: gate.wait(10) and real(s))
    try:
        page.click("#btn-open-gamelist")
        page.wait_for_selector("#open-gl-root:not([hidden])")
        page.click("#open-gl-root")
        page.wait_for_selector("#overview-progress:not([hidden])")
        assert "0 / 3" in page.inner_text("#overview-progress-text")
        assert page.get_attribute("#overview-body", "aria-busy") == "true"
        assert page.locator("#overview-progress .spinner").count() == 1
        page.click("#overview-stop")
    finally:
        gate.set()
    page.wait_for_function("document.getElementById('overview-progress').hidden")
    assert "Analyse arrêtée" in page.inner_text("#overview-body")
    assert page.get_attribute("#overview-body", "aria-busy") is None


def test_a_folder_without_systems_shows_an_error(page, roms, tmp_path):
    (tmp_path / "docs").mkdir()
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gl-root:not([hidden])")
    page.fill("#open-gl-path", str(tmp_path / "docs"))
    page.click("#open-gl-root")
    page.wait_for_selector("#overview-body .bulk-error")
    assert "Aucun dossier de système" in page.inner_text("#overview-body")
