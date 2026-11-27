"""Loading spinner: shown while a slow request runs, cleared when it ends, even on error.

Requests are held with page.route until the test releases them, so the busy state is
checked without depending on timing."""
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e
LOCALES = Path(__file__).resolve().parents[2] / "static" / "locales"


class Held:
    """Hold the matching requests until release() / fail()."""

    def __init__(self, page, pattern):
        self.routes = []
        self.page = page
        page.route(pattern, lambda route: self.routes.append(route))

    def wait(self):
        for _ in range(200):           # the route handler runs while Playwright waits
            if self.routes:
                break
            self.page.wait_for_timeout(25)
        assert self.routes, "request was not sent"

    def release(self):
        self.wait()
        while self.routes:
            self.routes.pop(0).continue_()

    def fail(self, status=500, message="Erreur simulée"):
        self.wait()
        while self.routes:
            self.routes.pop(0).fulfill(status=status, content_type="application/json",
                                       body=json.dumps({"error": message}))


def status_ring_shown(page):
    return page.evaluate("!document.getElementById('status-spinner').hidden")


def wait_status_ring(page, shown):
    page.wait_for_function(
        f"document.getElementById('status-spinner').hidden === {'false' if shown else 'true'}")


def open_browser(page):
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")


def open_bulk_solid(page):
    page.click("#btn-actions")
    page.click("#btn-bulk")
    page.wait_for_selector("#bulk-modal.open")
    page.click('[data-bulk-tab="solid"]')
    page.wait_for_selector("#bulk-solid-files")


def test_folder_browser_shows_a_spinner_while_listing(page):
    held = Held(page, "**/api/browse*")
    open_browser(page)
    held.wait()
    listing = page.locator("#open-gl-listing")
    assert listing.get_attribute("aria-busy") == "true"
    assert listing.locator(".busy-line[role=status] .spinner").count() == 1
    assert "Chargement" in listing.inner_text()
    wait_status_ring(page, True)
    assert page.get_attribute(".status-bar", "aria-busy") == "true"
    held.release()
    page.wait_for_selector("#open-gl-listing .open-gl-entry, #open-gl-listing button")
    assert listing.get_attribute("aria-busy") is None
    assert listing.locator(".spinner").count() == 0
    wait_status_ring(page, False)
    assert page.get_attribute(".status-bar", "aria-busy") is None


def test_folder_browser_spinner_clears_on_error(page):
    held = Held(page, "**/api/browse*")
    open_browser(page)
    held.fail(message="Dossier illisible")
    page.wait_for_function("document.getElementById('open-gl-listing').textContent.includes('Dossier illisible')")
    assert page.locator("#open-gl-listing .spinner").count() == 0
    assert page.get_attribute("#open-gl-listing", "aria-busy") is None
    wait_status_ring(page, False)


def test_solid_images_scan_busy_button_then_result(page):
    open_bulk_solid(page)
    held = Held(page, "**/api/solid-images/scan")
    page.click("#bulk-preview-btn")
    held.wait()
    btn = page.locator("#bulk-preview-btn")
    assert btn.is_disabled() and btn.get_attribute("aria-busy") == "true"
    assert btn.locator(".spinner").count() == 1
    box = page.locator("#bulk-preview")
    assert box.get_attribute("aria-busy") == "true"
    assert "Analyse" in box.locator(".busy-line").inner_text()
    held.release()
    page.wait_for_selector("#bulk-preview .bulk-summary, #bulk-preview .bulk-empty")
    assert not btn.is_disabled() and btn.get_attribute("aria-busy") is None
    assert page.locator("#bulk-preview .spinner, #bulk-preview-btn .spinner").count() == 0
    assert box.get_attribute("aria-busy") is None


def test_solid_images_scan_error_clears_the_spinner(page):
    open_bulk_solid(page)
    held = Held(page, "**/api/solid-images/scan")
    page.click("#bulk-preview-btn")
    held.fail(message="Analyse impossible")
    page.wait_for_selector("#bulk-preview .bulk-error")
    assert "Analyse impossible" in page.inner_text("#bulk-preview")
    assert not page.is_disabled("#bulk-preview-btn")
    assert page.locator("#bulk-preview-btn").get_attribute("aria-busy") is None
    assert page.locator("#bulk-preview .spinner, #bulk-preview-btn .spinner").count() == 0
    assert page.is_disabled("#bulk-apply")
    wait_status_ring(page, False)


def test_reload_button_is_busy_and_comes_back_after_an_error(page):
    held = Held(page, "**/api/games*")
    page.click("#btn-reload")
    held.wait()
    assert page.is_disabled("#btn-reload")
    assert page.get_attribute("#btn-reload", "aria-busy") == "true"
    held.fail()
    page.wait_for_function("!document.getElementById('btn-reload').disabled")
    assert page.get_attribute("#btn-reload", "aria-busy") is None
    assert page.locator("#btn-reload .spinner").count() == 0
    wait_status_ring(page, False)


def test_spinners_wait_200ms_so_quick_actions_do_not_flicker(page):
    held = Held(page, "**/api/games*")
    # Right after the click: the status ring timer has not fired, the button ring is still transparent.
    early = page.evaluate("""async () => {
      document.getElementById('btn-reload').click();
      await new Promise(r => setTimeout(r, 0));
      const ring = document.querySelector('#btn-reload .spinner');
      return { status: document.getElementById('status-spinner').hidden,
               opacity: getComputedStyle(ring).opacity,
               disabled: document.getElementById('btn-reload').disabled };
    }""")
    assert early == {"status": True, "opacity": "0", "disabled": True}
    later = page.evaluate("""() => new Promise(r => setTimeout(() => {
      const ring = document.querySelector('#btn-reload .spinner');
      r({ status: document.getElementById('status-spinner').hidden, opacity: getComputedStyle(ring).opacity });
    }, 600))""")
    assert later == {"status": False, "opacity": "1"}
    held.release()
    page.wait_for_function("!document.getElementById('btn-reload').disabled")
    wait_status_ring(page, False)


def test_rom_check_scan_shows_a_spinner(page):
    held = Held(page, "**/api/check-roms/scan")
    page.click("#btn-actions")
    page.click("#btn-rom-check")
    held.wait()
    intro = page.locator("#check-intro")
    assert intro.locator(".busy-line .spinner").count() == 1
    held.release()
    page.wait_for_function("!document.querySelector('#check-intro .spinner')")


def test_stats_show_a_spinner_until_loaded(page):
    held = Held(page, "**/api/stats*")
    page.click("#btn-actions")
    page.click("#btn-stats")
    held.wait()
    assert page.locator("#stats-body .busy-line .spinner").count() == 1
    held.fail(message="Stats en panne")
    page.wait_for_selector("#stats-body .bulk-error")
    assert page.locator("#stats-body .spinner").count() == 0


def test_spinner_label_is_translated_in_every_language(page):
    assert page.get_attribute("#status-spinner", "role") == "status"
    assert page.get_attribute("#status-spinner", "aria-label") == "Chargement…"
    labels = {p.stem: json.loads(p.read_text(encoding="utf-8"))["common"]["loading"] for p in LOCALES.glob("*.json")}
    assert len(labels) == 13 and all(labels.values())
    assert len(set(labels.values())) >= 12          # really translated, not copied
