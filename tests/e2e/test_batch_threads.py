"""Thread setting and the threads / quota line of a running ScreenScraper batch."""
import json
import time

import pytest

from gme.scrapers import ss, ss_limits
from .test_batch_scrape import run

pytestmark = pytest.mark.e2e


def test_running_batch_shows_threads_and_daily_quota(page, gamelist, fake_sources, monkeypatch):
    real = ss.ss_request

    def slow(*args, **kwargs):
        time.sleep(0.4)
        ss_limits.GATE.update_from_user({"requeststoday": "41", "maxrequestsperday": "20000"})
        return real(*args, **kwargs)

    monkeypatch.setattr(ss, "ss_request", slow)
    page.click("#btn-actions")
    run(page, "#btn-batch-scrape")
    page.click("#batch-start")
    page.wait_for_selector("#batch-threads", timeout=10000)
    text = page.inner_text("#batch-threads")
    assert "Threads : 1/1" in text                                 # no member login: 1 thread
    assert "Requêtes aujourd'hui : 41 / 20" in text
    page.wait_for_selector("#batch-export:not([hidden])", timeout=30000)
    assert page.locator("#batch-threads").count() == 0             # only while it runs


def test_thread_setting_is_saved_and_explained(page, ss_config_file):
    page.click("#btn-settings")
    page.wait_for_selector("#settings-modal.open")
    page.click("#tab-ss")
    assert page.input_value("#ss-threads") == "0"                  # Auto
    assert "1 thread" in page.inner_text("#ss-threads-hint")
    page.select_option("#ss-threads", "4")
    page.wait_for_function("document.getElementById('ss-threads').value === '4'")
    deadline = time.time() + 5
    while time.time() < deadline:
        if ss_config_file.exists() and json.loads(ss_config_file.read_text(encoding="utf-8")).get("threads") == 4:
            break
        time.sleep(0.05)
    assert json.loads(ss_config_file.read_text(encoding="utf-8"))["threads"] == 4
