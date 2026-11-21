"""Batch scrape: ticking games, complete or replace, uncertain games, stop, quota."""
import time

import pytest
from lxml import etree

from gme.scrapers import ss
from gme.scrapers import apply as scrape_apply

pytestmark = pytest.mark.e2e


def games_by_name(gamelist):
    return {g.findtext("name"): g for g in etree.parse(str(gamelist)).getroot().findall("game")}


def rows(page):
    return page.locator("#game-list .game-item")


def run(page, start_from="#btn-batch-selection"):
    page.click(start_from)
    page.wait_for_selector("#batch-modal.open")


def start_and_wait(page):
    page.click("#batch-start")
    page.wait_for_selector("#batch-export:not([hidden])", timeout=30000)


def stats(page):
    return page.eval_on_selector_all("#batch-body .rc-stat-n", "els => els.map(e => e.textContent)")


def test_ticks_then_complete_only_the_ticked_games(page, gamelist, fake_sources):
    page.click("#game-list .game-item >> nth=0 >> .gi-select input")   # Alpha
    rows(page).nth(2).click(modifiers=["Shift"])                       # … to Charlie
    assert page.inner_text("#list-selection-count") == "3 coché(s)"
    page.keyboard.press("Escape")
    assert page.is_hidden("#list-selection")
    rows(page).nth(0).click()                                          # open Alpha
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")
    page.locator("#game-list").focus()
    page.keyboard.press("x")                                           # ticks the open game
    rows(page).nth(2).click(modifiers=["Control"])                     # Ctrl+click: Charlie
    assert page.inner_text("#list-selection-count") == "2 coché(s)"
    assert page.get_attribute("#game-list .game-item >> nth=1", "class").find("is-ticked") < 0

    run(page)
    assert "2 jeu(x) coché(s)" in page.inner_text("#batch-intro")
    assert not page.is_checked("[data-batch-field='name']")             # never renamed by default
    start_and_wait(page)
    assert stats(page) == ["2", "0", "0", "0"]
    games = games_by_name(gamelist)
    assert games["Alpha"].findtext("developer") == "Studio Alpha"
    assert games["Alpha"].findtext("genre") == "Platform"              # filled only, never replaced
    assert games["Charlie"].findtext("desc") == "Une description venue de la source."
    assert games["Charlie"].findtext("image")
    assert games["Bravo"].findtext("developer") is None                # not ticked
    assert (gamelist.parent / "gamelist.xml.bak").exists()
    assert "Studio Alpha" == page.input_value("#meta-developer")       # the open game follows
    page.click("#batch-cancel")                                        # Close
    assert page.is_hidden("#batch-modal")


def test_replace_mode_on_the_games_shown(page, gamelist, fake_sources):
    page.fill("#search", "bravo")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 1")
    page.click("#btn-actions")
    run(page, "#btn-batch-scrape")
    assert "Les 1 jeu(x) affichés" in page.inner_text("#batch-intro")
    page.click("[data-batch-mode='all']")
    for box in page.locator("[data-batch-field]").all():
        if box.get_attribute("data-batch-field") != "genre":
            box.uncheck()
    start_and_wait(page)
    bravo = games_by_name(gamelist)["Bravo"]
    assert bravo.findtext("genre") == "ACTION"                         # replaced
    assert bravo.findtext("desc") == "Bravo desc"                      # not ticked
    assert "Genre" in page.inner_text("#batch-body")


def test_uncertain_games_are_skipped_then_picked(page, gamelist, fake_sources):
    fake_sources["ambiguous"] = True
    page.click("#btn-actions")
    run(page, "#btn-batch-scrape")
    start_and_wait(page)
    assert stats(page) == ["0", "0", "3", "0"]
    assert games_by_name(gamelist)["Alpha"].findtext("developer") is None
    page.click("[data-batch-pick='./alpha.zip']")
    page.wait_for_selector("#ss-modal.open")
    assert page.locator(".ss-candidate").count() == 2                  # choose the right game
    assert page.input_value("#game-name-input") == "Alpha"


def test_quota_stops_the_run(page, gamelist, monkeypatch):
    calls = []

    def quota(endpoint, extra=None, timeout=25):
        calls.append(endpoint)
        return False, ss.format_ss_error("Votre quota de scrape est dépassé", 200), 200
    monkeypatch.setattr(ss, "ss_request", quota)
    page.click("#btn-actions")
    run(page, "#btn-batch-scrape")
    start_and_wait(page)
    assert stats(page) == ["0", "0", "0", "1"]
    assert "Interrompu après 1 / 3" in page.inner_text("#batch-body")
    assert "Quota" in page.inner_text("#batch-body")
    n = len(calls)
    time.sleep(0.3)
    assert len(calls) == n                                             # nothing more sent


def test_stop_after_the_game_in_progress(page, gamelist, fake_sources, monkeypatch):
    slow = ss.ss_request

    def slow_request(*a, **k):
        time.sleep(0.4)
        return slow(*a, **k)
    monkeypatch.setattr(ss, "ss_request", slow_request)
    page.click("#btn-actions")
    run(page, "#btn-batch-scrape")
    page.click("#batch-start")
    page.wait_for_function("document.getElementById('batch-cancel').textContent === 'Arrêter'")
    assert page.is_hidden("#batch-close")                              # no closing while it runs
    page.click("#batch-cancel")
    page.wait_for_selector("#batch-export:not([hidden])", timeout=30000)
    assert "Arrêté : 1 / 3" in page.inner_text("#batch-body")
    assert games_by_name(gamelist)["Charlie"].findtext("developer") is None


def test_partial_updates_show_and_export_all_download_errors(page, gamelist, fake_sources, monkeypatch, tmp_path):
    def broken_download(*args, **kwargs):
        raise OSError("Download failed <image>")

    monkeypatch.setattr(scrape_apply, "download_remote_media", broken_download)
    page.click("#btn-actions")
    run(page, "#btn-batch-scrape")
    start_and_wait(page)
    assert stats(page) == ["0", "3", "0", "0", "0"]
    assert page.locator("strong.batch-warning").count() == 3
    assert "Partiellement mis à jour" in page.inner_text("#batch-body")
    assert "Download failed <image>" in page.inner_text("#batch-body")
    assert page.locator(".batch-warning li").count() == 6   # image + marquee per game
    assert games_by_name(gamelist)["Alpha"].findtext("developer") == "Studio Alpha"
    with page.expect_download() as downloaded:
        page.click("#batch-export")
    report = tmp_path / "report.txt"
    downloaded.value.save_as(str(report))
    text = report.read_text(encoding="utf-8-sig")
    assert "Partiellement mis à jour" in text
    assert text.count("Download failed <image>") == 6
