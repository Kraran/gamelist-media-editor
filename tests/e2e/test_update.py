"""Updates: the start-up notice, "Check for updates", Skip / Later, and the
download with its progress bar until the restart screen (fake GitHub, the
helper and the exit are replaced: nothing leaves the test)."""
import os
import sys

import pytest

from gme import settings, updater
from gme.version import APP_VERSION
from tests.fake_github import FakeGitHub

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name))


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHub(notes="## Nouveautés\n- **Mise à jour automatique** de l'exe Windows\n"
                            "- Vidéo de démonstration dans le README\n\n## Corrections\n- Divers [détails](https://example.com)")
    monkeypatch.setattr(updater, "_get", fake)
    return fake


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    exe = tmp_path / "app" / updater.EXE_NAME
    exe.parent.mkdir()
    exe.write_bytes(b"MZ old")
    monkeypatch.setattr(updater, "can_install", lambda: True)
    monkeypatch.setattr(sys, "executable", str(exe))
    started = []
    monkeypatch.setattr(updater, "_spawn", lambda cmd: started.append(cmd))
    monkeypatch.setattr(updater, "_exit_soon", lambda: started.append("exit"))
    return started


def notice(page):
    page.wait_for_selector("#update-modal.open", timeout=10000)


def test_start_up_notice_then_later(github, page):
    notice(page)
    assert "v9.9.0" in page.inner_text("#update-version") and f"v{APP_VERSION}" in page.inner_text("#update-version")
    notes = page.inner_text("#update-notes")
    assert "Mise à jour automatique" in notes and "**" not in notes and "https://example.com" not in notes
    assert page.get_attribute("#update-link", "href") == f"https://github.com/{updater.REPO}/releases/tag/v9.9.0"
    # Tests run from source: a link to the download page, not a self-update
    assert page.inner_text("#update-now") == "Ouvrir la page de téléchargement"
    assert "git pull" in page.inner_text("#update-hint")
    page.click("#update-later")
    page.wait_for_selector("#update-modal", state="hidden")
    assert github.calls.count(updater.API_LATEST) == 1


def test_skip_this_version(github, page):
    notice(page)
    page.click("#update-ignore")
    page.wait_for_selector("#update-modal", state="hidden")
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    page.wait_for_timeout(3500)
    assert not page.is_visible("#update-modal")
    assert github.calls.count(updater.API_LATEST) == 1            # once a day
    # Asked by hand: shown again, with a note
    page.click("#btn-actions")
    page.click("#btn-update-check-menu")
    notice(page)
    assert "ignorer cette version" in page.inner_text("#update-hint")
    assert not page.is_visible("#update-ignore")
    assert github.calls.count(updater.API_LATEST) == 2


def test_offline_start_up_is_silent(page):
    page.wait_for_timeout(3500)
    assert not page.is_visible("#update-modal") and not page.is_visible("#toast.show.error")
    page.click("#btn-actions")
    page.click("#btn-update-check-menu")
    page.wait_for_selector("#toast.show")
    assert "Impossible de vérifier les mises à jour" in page.inner_text("#toast")


def test_up_to_date_and_setting(monkeypatch, page):
    monkeypatch.setattr(updater, "_get", FakeGitHub(version=APP_VERSION))
    page.click("#btn-settings")
    assert page.is_checked("#update-auto")
    page.click("#btn-update-check")
    page.wait_for_function("document.getElementById('update-status').textContent.includes('dernière version')")
    assert "Dernière vérification" in page.inner_text("#update-status")
    shot(page, "update-settings.png")
    page.uncheck("#update-auto")
    page.wait_for_function("1", timeout=500)
    page.wait_for_timeout(300)
    assert settings.load()["update_check"] is False


def test_update_now_downloads_then_restarts(monkeypatch, frozen, page):
    fake = FakeGitHub(delay=0.05, notes="## Nouveautés\n- Mise à jour automatique\n- Vidéo de démo")
    monkeypatch.setattr(updater, "_get", fake)
    page.click("#game-list >> text=Bravo")
    notice(page)
    assert page.inner_text("#update-now") == "Mettre à jour maintenant"
    assert "SHA-256" in page.inner_text("#update-hint")
    shot(page, "update-available.png")
    page.click("#update-now")
    page.wait_for_selector("#update-progress [data-job-progress]")
    page.wait_for_function("/Mo \\(\\d+ %\\)/.test(document.querySelector('#update-progress .dat-progress-text').textContent)")
    shot(page, "update-download.png")
    page.wait_for_selector(".update-restart", timeout=20000)
    assert "Mise à jour vers la version v9.9.0" in page.inner_text(".update-restart")
    shot(page, "update-restart.png")
    assert frozen[-1] == "exit" and frozen[0][0] == "powershell.exe"
    assert updater.staged_version() == "9.9.0"


def test_stop_download(monkeypatch, frozen, page):
    monkeypatch.setattr(updater, "_get", FakeGitHub(delay=0.1))
    notice(page)
    page.click("#update-now")
    page.wait_for_selector("#update-progress .job-stop")
    page.click("#update-progress .job-stop")
    page.wait_for_selector("#toast.show")
    assert "rien n'a été modifié" in page.inner_text("#toast")
    assert frozen == [] and updater.staged_version() is None
    assert page.is_visible("#update-modal")
