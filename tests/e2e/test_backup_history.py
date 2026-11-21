"""Users can inspect, cancel, restore, and undo a restoration from the UI."""
import pytest

from .test_editor_safety import select, game

pytestmark = pytest.mark.e2e


def open_history(page):
    page.click("#btn-actions")
    page.click("#btn-backup-history")
    page.wait_for_selector("#backups-modal.open")


def test_history_restore_cancel_and_undo(page, gamelist):
    open_history(page)
    assert page.locator("[data-restore-backup]").count() == 0
    assert "ROMs" in page.inner_text("#backups-modal")
    page.click("#backups-create")
    page.wait_for_selector("[data-restore-backup]")
    assert page.locator("[data-restore-backup]").count() == 1
    page.click("#backups-cancel")
    select(page, "Alpha")
    page.fill("#game-name-input", "Edited Alpha")
    page.click("#btn-save")
    page.wait_for_function("!_saving")
    assert game(gamelist, "Edited Alpha")
    open_history(page)
    page.click("[data-restore-backup]")
    page.wait_for_selector("#confirm-modal.open")
    assert "sauvegardé avant" in page.inner_text("#confirm-body")
    page.click("#confirm-cancel")
    assert game(gamelist, "Edited Alpha")
    page.click("[data-restore-backup]")
    page.click("#confirm-ok")
    page.wait_for_function("!restoringBackup")
    assert game(gamelist, "Alpha")
    assert page.locator("[data-restore-backup]").count() == 2
    page.locator("[data-restore-backup]").first.click()
    page.click("#confirm-ok")
    page.wait_for_function("!restoringBackup")
    assert game(gamelist, "Edited Alpha")
    assert page.locator("[data-restore-backup]").count() == 3
    page.keyboard.press("Escape")
    assert not page.is_visible("#backups-modal.open")


def test_full_history_scrolls_in_a_small_window(page):
    for _ in range(31):
        response = page.request.post(page.url + "api/backup")
        assert response.status == 200
    page.set_viewport_size({"width": 900, "height": 650})
    open_history(page)
    assert page.locator("[data-restore-backup]").count() == 30
    assert page.eval_on_selector("#backups-body", "el => el.scrollHeight > el.clientHeight")
    page.locator("[data-restore-backup]").last.scroll_into_view_if_needed()
    box = page.locator(".backups-modal").bounding_box()
    assert box["height"] <= 602
    assert box["x"] >= 0 and box["x"] + box["width"] <= 900
    assert page.is_visible("#backups-cancel")
