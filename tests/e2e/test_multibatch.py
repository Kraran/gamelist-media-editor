"""Actions on several systems: tick systems in the overview, choose the operations,
follow the progress system by system, stop, and read the final report."""
import os
import threading

import pytest
from lxml import etree

from gme import batch_jobs, multibatch, overview
from gme.scrapers import ss_limits
from gme.scrapers.compare import scrape_payload
from tests.conftest import picture

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")

NES = """<?xml version="1.0"?>
<gameList>
  <game><path>./zelda.nes</path><name>Zelda</name><genre>Action</genre><image>./images/zelda.png</image></game>
  <game><path>./metroid.nes</path><name>Metroid</name><genre>Action</genre><image>./images/metroid.png</image></game>
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
    for rom in ("zelda", "metroid", "kirby", "luigi"):  # mario.nes is missing, luigi.nes is new
        (nes / f"{rom}.nes").write_bytes(b"rom")
    (nes / "images" / "zelda.png").write_bytes(picture())  # metroid.png is a broken link
    (nes / "images" / "unused.png").write_bytes(picture())
    (root / "gba").mkdir()
    (root / "gba" / "pokemon.gba").write_bytes(b"rom")
    overview.reset()
    multibatch.reset()
    ss_limits.GATE.reset()
    yield root
    multibatch.reset()
    overview.reset()
    ss_limits.GATE.reset()


def open_overview(page):
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")
    page.wait_for_selector("#open-gl-root:not([hidden])")
    page.click("#open-gl-root")
    page.wait_for_selector("#overview-modal.open #overview-table")
    page.wait_for_function("document.getElementById('overview-progress').hidden")


def tick(page, label):
    page.check(f"#overview-table tbody tr:has(.ov-name:text-is('{label}')) [data-ov-pick]")


def open_actions(page, *labels):
    open_overview(page)
    for label in labels:
        tick(page, label)
    page.click("#overview-actions")
    page.wait_for_selector("#mbatch-modal.open [data-mb-section]")


def names(xml):
    return [g.findtext("name") for g in etree.parse(str(xml)).getroot().findall("game")]


def wait_report(page):
    page.wait_for_selector("#mbatch-modal .mbatch-banner", timeout=20000)


def test_ticking_systems_and_running_checks_on_each(page, roms, gamelist):
    open_overview(page)
    assert page.is_disabled("#overview-actions")
    assert page.locator("#overview-table tr.is-no-xml [data-ov-pick]").count() == 0      # gba: no gamelist
    tick(page, "Nintendo (NES)")
    tick(page, "Super Nintendo")
    assert "2 système(s)" in page.inner_text("#overview-actions")
    page.uncheck("#ov-pick-all")
    assert page.is_disabled("#overview-actions")
    page.check("#ov-pick-all")
    page.click("#overview-actions")
    page.wait_for_selector("#mbatch-modal.open [data-mb-section]")
    assert "2 système(s)" in page.inner_text(".mbatch-systems")
    assert page.is_disabled("#mbatch-start")                          # nothing chosen yet
    assert page.is_disabled('[data-mb-opt="roms.add"]')
    page.check('[data-mb-on="roms"]')
    page.check('[data-mb-opt="roms.remove"]')
    page.check('[data-mb-on="media"]')
    page.check('[data-mb-on="clear"]')
    page.check('[data-mb-field="clear"][value="genre"]')
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "multibatch-setup.png"))
    page.click("#mbatch-start")
    page.wait_for_selector("#confirm-modal.open")
    assert "2 système(s)" in page.inner_text("#confirm-body")
    assert "btn-accent" in page.get_attribute("#confirm-ok", "class")   # no file deletion asked
    page.click("#confirm-ok")
    wait_report(page)
    assert "Terminé : 2 système(s) traité(s)." in page.inner_text(".mbatch-banner")
    nes = page.inner_text("#mbatch-table tr[data-mb-system='nes']")
    assert "1 ajoutée(s), 1 retirée(s)" in nes and "1 lien(s) retiré(s), 0 fichier(s) supprimé(s)" in nes
    assert "2 balise(s) retirée(s) de 2 jeu(x)" in nes and "Sauvegarde" in nes
    nes_xml = roms / "nes" / "gamelist.xml"
    assert sorted(names(nes_xml)) == ["Kirby", "Metroid", "Zelda", "luigi"]
    assert "<genre>" not in nes_xml.read_text(encoding="utf-8")
    assert os.path.isfile(str(nes_xml) + ".bak")
    assert os.path.isfile(roms / "nes" / "images" / "unused.png")    # never deleted without the opt-in
    assert "<genre>" not in gamelist.read_text(encoding="utf-8")       # snes too
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "multibatch-report.png"))
    # The editor shows the gamelist that was open before, reloaded.
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 3")
    assert "rouvert" in page.inner_text("#mbatch-body")
    page.click("#mbatch-back")
    page.wait_for_selector("#overview-modal.open #overview-table")
    assert not page.is_visible("#mbatch-modal")


def test_deleting_files_needs_its_box_and_a_danger_confirmation(page, roms):
    open_actions(page, "Nintendo (NES)")
    page.check('[data-mb-on="roms"]')
    assert page.is_disabled('[data-mb-opt="roms.delete_media"]')     # only with "remove"
    page.check('[data-mb-on="media"]')
    page.check('[data-mb-opt="media.delete"]')
    page.click("#mbatch-start")
    page.wait_for_selector("#confirm-modal.open")
    assert "btn-danger" in page.get_attribute("#confirm-ok", "class")
    body = page.inner_text("#confirm-body")
    assert "Corbeille" in body and "Supprimer les médias inutilisés" in body
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "multibatch-confirm-delete.png"))
    page.click("#confirm-cancel")
    assert multibatch._public()["state"] == "idle"
    assert os.path.isfile(roms / "nes" / "images" / "unused.png")
    page.click("#mbatch-start")
    page.wait_for_selector("#confirm-modal.open")
    page.click("#confirm-ok")
    wait_report(page)
    assert not os.path.exists(roms / "nes" / "images" / "unused.png")
    assert os.path.isfile(roms / "nes" / "images" / "zelda.png")
    assert os.path.isfile(roms / "nes" / "zelda.nes")


def test_quota_stops_the_whole_run_and_says_why(page, roms, monkeypatch):
    calls = []

    def quota(game, body=None, system=None):
        calls.append(game.findtext("path"))
        return {"error": "Quota ScreenScraper du jour atteint", "code": "source_blocked"}, 503

    monkeypatch.setitem(batch_jobs.LOOKUPS, "screenscraper", quota)
    open_actions(page, "Nintendo (NES)", "Super Nintendo")
    page.check('[data-mb-on="scrape"]')
    page.click('[data-mb-mode="all"]')
    page.click("#mbatch-start")
    page.wait_for_selector("#confirm-modal.open")
    assert "quota" in page.inner_text("#confirm-body")
    page.click("#confirm-ok")
    wait_report(page)
    assert "Série arrêtée : Quota ScreenScraper du jour atteint" in page.inner_text(".mbatch-banner")
    assert "Non traité" in page.inner_text("#mbatch-table tr[data-mb-system='snes']")
    assert len(calls) <= 4                                            # nothing after the refusal
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "multibatch-quota.png"))


def test_progress_and_stop(page, roms, monkeypatch):
    gate = threading.Event()

    def slow(game, body=None, system=None):
        gate.wait(10)
        proposed = {"developer": "Studio " + game.findtext("name")}
        return {"proposed": proposed, **scrape_payload(game, proposed)}, 200

    monkeypatch.setitem(batch_jobs.LOOKUPS, "screenscraper", slow)
    try:
        open_actions(page, "Nintendo (NES)", "Super Nintendo")
        page.check('[data-mb-on="scrape"]')
        page.click("#mbatch-start")
        page.wait_for_selector("#confirm-modal.open")
        page.click("#confirm-ok")
        page.wait_for_selector("#mbatch-progress:not([hidden])")
        page.wait_for_function("document.getElementById('mbatch-progress-text').textContent.includes('Système 1/2')")
        assert page.is_hidden("#mbatch-close")
        page.keyboard.press("Escape")                                 # cannot close a running series
        assert page.is_visible("#mbatch-modal")
        if SHOTS:
            page.screenshot(path=os.path.join(SHOTS, "multibatch-running.png"))
        page.click("#mbatch-cancel")
        page.wait_for_function("document.getElementById('mbatch-cancel').disabled")
    finally:
        gate.set()
    wait_report(page)
    assert "Série arrêtée à ta demande." in page.inner_text(".mbatch-banner")
    assert "Non traité" in page.inner_text("#mbatch-table tr[data-mb-system='snes']")
    assert page.inner_text("#mbatch-cancel") == "Fermer"
