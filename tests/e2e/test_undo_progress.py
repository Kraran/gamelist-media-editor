"""Reliability: multi-level Undo / Redo (buttons, history menu, Ctrl+Z / Ctrl+Y
that never take over a text field) and the long scans' progress bar with Stop."""
import os
import threading

import pytest
from lxml import etree
from PIL import Image

from gme import jobs, romcheck, solidimages, xml_store

from .conftest import wait_until

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")          # folder for documentation screenshots (optional)


def names(xml):
    return [g.findtext("name") for g in etree.parse(str(xml)).getroot().findall("game")]


def select(page, name):
    page.click(f"#game-list >> text={name}")
    page.wait_for_function(f"document.getElementById('game-name-input').value === {name!r}")


def rename(page, old, new):
    select(page, old)
    page.fill("#game-name-input", new)
    page.click("#btn-save")
    page.wait_for_function(f"document.querySelector('#game-list').textContent.includes({new!r})")


def history_ready(page, can_undo=True):
    page.wait_for_function("!document.getElementById('btn-undo').disabled" if can_undo
                           else "document.getElementById('btn-undo').disabled")


def stop_asked():
    """The server got Stop (then the test lets the slowed scan go on)."""
    return wait_until(lambda: jobs._jobs and all(j.stop_event.is_set() for j in jobs._jobs.values()))


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name))


def test_undo_redo_several_steps_with_the_buttons(page, gamelist):
    original = gamelist.read_bytes()
    assert page.is_disabled("#btn-undo") and page.is_disabled("#btn-redo")
    rename(page, "Alpha", "Alpha I")
    rename(page, "Bravo", "Bravo II")
    rename(page, "Charlie", "Charlie III")
    history_ready(page)
    page.wait_for_function("document.getElementById('btn-undo').title.includes('Charlie III')")
    assert page.get_attribute("#btn-undo", "title").startswith("Annuler : Enregistrement : Charlie III")
    page.click("#btn-undo")
    assert wait_until(lambda: names(gamelist) == ["Alpha I", "Bravo II", "Charlie"])
    page.wait_for_function("!document.getElementById('btn-redo').disabled")
    assert "Charlie III" in page.get_attribute("#btn-redo", "title")
    page.wait_for_selector("#toast.show")
    shot(page, "undo-toast.png")
    page.click("#btn-undo")
    assert wait_until(lambda: names(gamelist) == ["Alpha I", "Bravo", "Charlie"])
    page.wait_for_function("document.getElementById('btn-undo').title.includes('Alpha I')")
    page.click("#btn-undo")
    assert wait_until(lambda: gamelist.read_bytes() == original)
    history_ready(page, can_undo=False)
    page.click("#btn-redo")
    assert wait_until(lambda: names(gamelist) == ["Alpha I", "Bravo", "Charlie"])
    page.wait_for_function("document.querySelector('#game-list').textContent.includes('Alpha I')")


def test_history_menu_lists_steps_and_jumps(page, gamelist):
    original = gamelist.read_bytes()
    rename(page, "Alpha", "A1")
    rename(page, "Bravo", "B1")
    history_ready(page)
    page.click("#btn-undo")
    assert wait_until(lambda: names(gamelist) == ["A1", "Bravo", "Charlie"])
    page.wait_for_function("!document.getElementById('btn-redo').disabled")
    page.click("#btn-history")
    page.wait_for_selector("#history-menu:not([hidden]) .history-item")
    items = page.locator("#history-list .history-item")
    assert items.count() == 3                                   # 2 steps + "before these changes"
    assert "is-undone" in items.nth(0).get_attribute("class")
    assert "is-current" in items.nth(1).get_attribute("class")
    assert "annulé" in items.nth(0).inner_text()
    shot(page, "history-menu.png")
    page.click("#history-list [data-history-origin]")           # back to the start
    assert wait_until(lambda: gamelist.read_bytes() == original)
    page.wait_for_function("document.getElementById('btn-undo').disabled")
    page.click("#btn-history")
    page.wait_for_selector("#history-menu:not([hidden]) .history-item")
    page.click("#history-list .history-item >> nth=0")          # the newest: redo both
    assert wait_until(lambda: names(gamelist) == ["A1", "B1", "Charlie"])


def test_shortcuts_leave_text_fields_alone(page, gamelist):
    rename(page, "Alpha", "Alpha I")
    history_ready(page)
    undo_calls = []
    page.on("request", lambda r: undo_calls.append(r.url) if "/api/history/" in r.url and r.method == "POST" else None)
    # Typing, then Ctrl+Z in the field: the browser undoes the typing, not the gamelist
    page.click("#game-name-input")
    page.keyboard.press("End")
    page.keyboard.insert_text(" typed")          # one edit for the field's own undo
    assert page.input_value("#game-name-input") == "Alpha I typed"
    page.keyboard.press("Control+z")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha I'")
    page.click("#desc-textarea")
    page.keyboard.insert_text("note")
    page.keyboard.press("Control+z")
    page.wait_for_function("document.getElementById('desc-textarea').value === 'Alpha desc'")
    page.keyboard.press("Control+Shift+z")                     # redo of the typing, still native
    page.wait_for_function("document.getElementById('desc-textarea').value.includes('note')")
    page.keyboard.press("Control+z")
    page.wait_for_function("document.getElementById('desc-textarea').value === 'Alpha desc'")
    page.wait_for_timeout(300)
    assert undo_calls == [] and names(gamelist)[0] == "Alpha I"
    # Out of the fields: Ctrl+Z undoes the gamelist step, Ctrl+Y / Ctrl+Shift+Z redo it
    page.click("#game-path")
    page.keyboard.press("Control+z")
    assert wait_until(lambda: names(gamelist)[0] == "Alpha")
    page.wait_for_function("!document.getElementById('btn-redo').disabled")
    page.keyboard.press("Control+y")
    assert wait_until(lambda: names(gamelist)[0] == "Alpha I")
    page.wait_for_function("!document.getElementById('btn-undo').disabled && document.getElementById('btn-redo').disabled")
    page.keyboard.press("Control+z")
    assert wait_until(lambda: names(gamelist)[0] == "Alpha")
    page.wait_for_function("!document.getElementById('btn-redo').disabled")
    page.keyboard.press("Control+Shift+z")
    assert wait_until(lambda: names(gamelist)[0] == "Alpha I")


def test_a_new_edit_clears_redo(page, gamelist):
    rename(page, "Alpha", "A1")
    rename(page, "Bravo", "B1")
    history_ready(page)
    page.click("#btn-undo")
    page.wait_for_function("!document.getElementById('btn-redo').disabled")
    rename(page, "Charlie", "C1")
    page.wait_for_function("document.getElementById('btn-redo').disabled")
    assert page.get_attribute("#btn-redo", "title") == "Rien à rétablir"
    assert names(gamelist) == ["A1", "Bravo", "C1"]
    page.keyboard.press("Control+y")
    page.wait_for_selector("#toast.show")
    assert "Rien à rétablir" in page.inner_text("#toast")
    assert names(gamelist) == ["A1", "Bravo", "C1"]


def test_bulk_toast_undo_goes_through_the_history(page, gamelist):
    page.click("#btn-actions")
    page.click("#btn-bulk")
    page.wait_for_selector("#bulk-modal.open")
    page.select_option("#bulk-set-field", "publisher")
    page.fill("#bulk-set-value", "Interton")
    page.click("#bulk-preview-btn")
    page.wait_for_selector("#bulk-preview tbody tr")
    page.click("#bulk-apply")
    page.wait_for_selector("#toast.show .toast-action")
    page.click("#toast .toast-action")
    page.wait_for_function("document.getElementById('toast').textContent.includes('Annulé')")
    assert "<publisher>" not in gamelist.read_text(encoding="utf-8")
    page.wait_for_function("!document.getElementById('btn-redo').disabled")   # and it can be redone
    page.click("#btn-redo")
    assert wait_until(lambda: gamelist.read_text(encoding="utf-8").count("<publisher>Interton</publisher>") == 3)


# --- Progress bar and Stop ---------------------------------------------------------

@pytest.fixture
def images(gamelist):
    folder = gamelist.parent / "images"
    folder.mkdir()
    tree = etree.parse(str(gamelist))
    for i, game in enumerate(tree.getroot().findall("game")):
        Image.new("RGB", (60, 40), (10 * i, 20, 30)).save(str(folder / f"g{i}.png"))
        etree.SubElement(game, "image").text = f"./images/g{i}.png"
    tree.write(str(gamelist), xml_declaration=True, encoding="UTF-8")
    solidimages._cache.clear()
    xml_store.set_gamelist_path(str(gamelist))
    return folder


def open_solid(page):
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    page.click("#btn-actions")
    page.click("#btn-bulk")
    page.wait_for_selector("#bulk-modal.open")
    page.click('[data-bulk-tab="solid"]')
    page.wait_for_selector("#bulk-solid-files")


def test_small_scan_shows_no_bar(page, gamelist, images):
    open_solid(page)
    page.evaluate("""() => { window.__sawBar = false;
      new MutationObserver(() => { if (document.querySelector('[data-job-progress]')) window.__sawBar = true; })
        .observe(document.body, { childList: true, subtree: true }); }""")
    page.click("#bulk-preview-btn")
    page.wait_for_selector("#bulk-preview .bulk-summary, #bulk-preview .bulk-empty:not(.bulk-error)")
    assert page.evaluate("window.__sawBar") is False


def test_slow_scan_shows_progress_and_stops_cleanly(page, gamelist, images, monkeypatch):
    gate, seen = threading.Event(), []
    real = solidimages.file_colour

    def slow(full):
        seen.append(full)
        if len(seen) > 1:
            gate.wait(20)
        return real(full)

    monkeypatch.setattr(solidimages, "WORKERS", 1)
    monkeypatch.setattr(solidimages, "file_colour", slow)
    before = gamelist.read_bytes()
    files = {p.name: p.read_bytes() for p in images.iterdir()}
    open_solid(page)
    page.click("#bulk-preview-btn")
    page.wait_for_selector("#bulk-preview [data-job-progress]")
    page.wait_for_function("document.querySelector('[data-job-progress] .dat-progress-text').textContent.includes('1 / 3')")
    text = page.inner_text("[data-job-progress] .dat-progress-text")
    assert "Recherche des images unies" in text or "images" in text.lower()
    assert "g0.png" in text or "g1.png" in text or "g2.png" in text
    assert page.get_attribute("[data-job-progress] .dat-bar", "aria-valuenow") == "33"
    shot(page, "solid-scan-progress.png")
    page.click("[data-job-progress] .job-stop")
    assert stop_asked()
    gate.set()
    page.wait_for_function("document.getElementById('bulk-preview').textContent.includes('Analyse arrêtée')")
    assert page.is_disabled("#bulk-apply")
    assert gamelist.read_bytes() == before
    assert {p.name: p.read_bytes() for p in images.iterdir()} == files


def test_rom_check_progress_and_stop(page, gamelist, monkeypatch):
    gate = threading.Event()
    real = romcheck._entry_full
    calls = []

    def slow(path):
        calls.append(path)
        gate.wait(20)
        return real(path)

    monkeypatch.setattr(romcheck, "_entry_full", slow)
    before = gamelist.read_bytes()
    page.click("#btn-actions")
    page.click("#btn-rom-check")
    page.wait_for_selector("#check-intro [data-job-progress]")
    page.wait_for_function("document.querySelector('#check-intro .dat-progress-text').textContent.includes('/ 3')")
    shot(page, "romcheck-progress.png")
    page.click("#check-intro .job-stop")
    assert stop_asked()
    gate.set()
    page.wait_for_function("!document.getElementById('check-modal').classList.contains('open')")
    page.wait_for_function("document.getElementById('toast').textContent.includes('Analyse arrêtée')")
    assert gamelist.read_bytes() == before


def test_media_check_with_a_slow_scan_then_apply(page, gamelist, monkeypatch):
    import time
    folder = gamelist.parent / "images"
    folder.mkdir()
    (folder / "orphan.png").write_bytes(b"x")
    from gme import mediacheck
    real = mediacheck._folders
    monkeypatch.setattr(mediacheck, "_folders", lambda: (time.sleep(0.8), real())[1])
    page.click("#btn-actions")
    page.click("#btn-media-check")
    page.wait_for_selector("#check-intro [data-job-progress]")
    page.wait_for_selector("#check-stats .rc-stat")
    page.click("#check-apply")
    page.wait_for_selector("#toast.show")
    assert wait_until(lambda: not (folder / "orphan.png").exists())
    page.wait_for_selector("#check-intro [data-job-progress]")    # scanned again afterwards, with progress
    page.wait_for_selector("#check-stats .rc-stat")
