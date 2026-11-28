"""Pause/reload, lost responses, and retrying only the failed fields."""
import pytest

from gme.scrapers import apply as scrape_apply
from .conftest import wait_until
from .test_batch_scrape import games_by_name, hold_first_ss_request, run, start_and_wait, stats

pytestmark = pytest.mark.e2e


def open_all(page):
    page.click("#btn-actions")
    run(page, "#btn-batch-scrape")


def reopen_saved(page):
    page.reload()
    page.wait_for_selector("#saved-batch-entry:not([hidden])")
    page.click("#saved-batch-entry")
    page.wait_for_selector("#batch-modal.open")


def test_stopped_batch_resumes_after_reload(page, gamelist, fake_sources, monkeypatch):
    entered, release, calls = hold_first_ss_request(monkeypatch)
    open_all(page)
    page.click("#batch-start")
    assert entered.wait(10)
    page.click("#batch-cancel")
    release.set()
    page.wait_for_selector("#batch-export:not([hidden])")
    assert "1 / 3" in page.inner_text("#batch-body")
    reopen_saved(page)
    assert page.is_visible("#batch-resume")
    page.click("#batch-resume")
    page.wait_for_selector("#batch-export:not([hidden])", timeout=30000)
    assert stats(page) == ["3", "0", "0", "0"]
    assert len(calls) == 3
    assert games_by_name(gamelist)["Charlie"].findtext("developer") == "Studio Alpha"


def test_reload_during_a_game_keeps_its_server_checkpoint(page, gamelist, fake_sources, monkeypatch):
    entered, release, calls = hold_first_ss_request(monkeypatch)
    open_all(page)
    page.click("#batch-start")
    assert entered.wait(10)
    page.once("dialog", lambda dialog: dialog.accept())
    page.reload()                                                      # browser gone, the step is still held
    release.set()
    assert wait_until(lambda: games_by_name(gamelist)["Alpha"].findtext("developer") == "Studio Alpha")
    page.wait_for_selector("#saved-batch-entry:not([hidden])")
    page.click("#saved-batch-entry")
    page.wait_for_selector("#batch-modal.open")
    assert page.evaluate("batch.i") == 1
    assert len(calls) == 1
    assert games_by_name(gamelist)["Alpha"].findtext("developer") == "Studio Alpha"
    page.click("#batch-resume")
    page.wait_for_selector("#batch-export:not([hidden])", timeout=30000)
    assert len(calls) == 3
    assert stats(page) == ["3", "0", "0", "0"]


def test_retry_only_failed_fields_even_in_replace_mode(page, gamelist, fake_sources, monkeypatch):
    real_download = scrape_apply.download_remote_media
    real_apply = scrape_apply.apply_proposed
    downloads, submissions = [], []

    def download(url, media_dir, base_name, field, **kwargs):
        downloads.append(field)
        if field == "image" and downloads.count("image") == 1:
            raise OSError("Temporary image failure")
        return real_download(url, media_dir, base_name, field, **kwargs)

    def apply(game, fields, proposed, **kwargs):
        submissions.append(fields)
        return real_apply(game, fields, proposed, **kwargs)

    monkeypatch.setattr(scrape_apply, "download_remote_media", download)
    monkeypatch.setattr(scrape_apply, "apply_proposed", apply)
    page.locator("#game-list .gi-select input").first.check()
    run(page)
    page.click("[data-batch-mode='all']")
    start_and_wait(page)
    assert page.is_visible("#batch-retry")
    assert "Partiellement" in page.inner_text("#batch-body")
    page.click("#batch-retry")
    page.wait_for_selector("#batch-export:not([hidden])", timeout=30000)
    assert stats(page) == ["1", "0", "0", "0"]
    assert submissions[-1] == ["image"]
    assert downloads.count("marquee") == 1
    assert downloads.count("image") == 2
    assert page.is_hidden("#batch-retry")
