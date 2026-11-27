"""Update check and self-update (gme/updater.py), against a fake GitHub."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from gme import jobs, settings, updater
from gme.version import APP_VERSION
from tests.conftest import LOCAL
from tests.fake_github import CDN, FakeGitHub, FakeResponse, make_zip


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(updater, "_get", fake)
    return fake


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    exe = app / updater.EXE_NAME
    exe.write_bytes(b"MZ old")
    monkeypatch.setattr(updater, "can_install", lambda: True)
    monkeypatch.setattr(sys, "executable", str(exe))
    return exe


def post(client, url, body=None):
    return client.post(url, json=body or {}, headers=LOCAL)


def finish(job_id):
    job = jobs.wait(job_id, 20)
    assert job.state != "running"
    return job


# --- versions -----------------------------------------------------------------

def test_semver_compare():
    assert updater.is_newer("1.10.0", "1.9.9")
    assert updater.is_newer("v2.0.0", "1.99.99")
    assert updater.is_newer("1.8.0", "1.8.0-beta.2")
    assert updater.is_newer("1.8.0-beta.10", "1.8.0-beta.2")
    assert not updater.is_newer("1.7.5", "1.7.5")
    assert not updater.is_newer("1.7.4", "1.7.5")
    assert not updater.is_newer("latest", "1.7.5")
    assert not updater.is_newer("1.8", "1.7.5")
    assert updater.parse_version(APP_VERSION)


def test_parse_release_keeps_only_official_assets():
    fake = FakeGitHub(asset_urls={updater.SUMS_NAME: "https://evil.example/SHA256SUMS.txt"})
    rel = updater.parse_release(fake.release)
    assert rel["version"] == "9.9.0" and rel["zip"]["url"].startswith(updater.DOWNLOAD_PREFIX + "v9.9.0/")
    assert rel["sums"] is None
    assert updater.parse_release(FakeGitHub(prerelease=True).release) is None
    assert updater.parse_release(dict(fake.release, tag_name="nightly")) is None
    bad_page = updater.parse_release(dict(fake.release, html_url="https://evil.example/"))
    assert bad_page["url"] == updater.RELEASES_PAGE


def test_parse_sums():
    sums = updater.parse_sums("ABC  x\n" + "a" * 64 + "  GME.zip\n" + "b" * 64 + " *star.zip\n")
    assert sums == {"GME.zip": "a" * 64, "star.zip": "b" * 64}


# --- check --------------------------------------------------------------------

def test_check_finds_a_newer_version(client, github):
    data = post(client, "/api/update/check", {"auto": True}).get_json()
    assert data["available"] and data["latest"]["version"] == "9.9.0"
    assert data["current"] == APP_VERSION and "Mise à jour automatique" in data["latest"]["notes"]
    assert data["installable"] is False and data["reason"] == "source"   # tests run from source
    assert github.calls == [updater.API_LATEST]


def test_check_runs_at_most_once_a_day(client, github):
    post(client, "/api/update/check", {"auto": True})
    post(client, "/api/update/check", {"auto": True})
    assert github.calls == [updater.API_LATEST]
    post(client, "/api/update/check", {"force": True})        # "Check for updates"
    assert len(github.calls) == 2
    state = json.load(open(updater.STATE_FILE, encoding="utf-8"))
    state["checked_at"] = time.time() - updater.CHECK_EVERY - 5
    json.dump(state, open(updater.STATE_FILE, "w", encoding="utf-8"))
    post(client, "/api/update/check", {"auto": True})
    assert len(github.calls) == 3


def test_offline_is_silent_at_start_up_and_reported_when_asked(client):
    data = post(client, "/api/update/check", {"auto": True})
    assert data.status_code == 200 and data.get_json()["available"] is False
    r = post(client, "/api/update/check", {"force": True})
    assert r.status_code == 502 and r.get_json()["code"] == "update_check_failed"


def test_automatic_check_can_be_disabled(client, github):
    settings.update({"update_check": False})
    data = post(client, "/api/update/check", {"auto": True}).get_json()
    assert data["checked"] is False and data["auto"] is False and github.calls == []
    assert post(client, "/api/update/check", {"force": True}).get_json()["available"]


def test_same_version_is_not_offered(client, monkeypatch):
    monkeypatch.setattr(updater, "_get", FakeGitHub(version=APP_VERSION))
    assert post(client, "/api/update/check", {"force": True}).get_json()["available"] is False


def test_no_release_yet(client, monkeypatch):
    monkeypatch.setattr(updater, "_get", FakeGitHub(api_status=404))
    data = post(client, "/api/update/check", {"force": True}).get_json()
    assert data["available"] is False and data["latest"] is None


def test_ignore_this_version(client, github):
    post(client, "/api/update/check", {"auto": True})
    assert post(client, "/api/update/ignore", {"version": "9.9.0"}).get_json()["ignored"] is True
    assert client.get("/api/update", headers=LOCAL).get_json()["ignored"] is True
    assert post(client, "/api/update/ignore", {"version": "../x"}).status_code == 400


def test_http_api_url_is_refused(monkeypatch):
    monkeypatch.setattr(updater, "API_LATEST", "http://api.github.com/x")
    with pytest.raises(updater.UpdateError) as e:
        updater.check(force=True)
    assert e.value.key == "insecure"


# --- download -----------------------------------------------------------------

def start_download(client):
    post(client, "/api/update/check", {"force": True})
    r = post(client, "/api/update/download")
    assert r.status_code == 200, r.get_json()
    return finish(r.get_json()["job"]["id"])


def test_download_is_refused_from_source(client, github):
    post(client, "/api/update/check", {"force": True})
    r = post(client, "/api/update/download")
    assert r.status_code == 409 and r.get_json()["reason"] == "source"


def test_download_verifies_and_stages_only_the_exe(client, github, frozen):
    job = start_download(client)
    assert job.state == "done" and job.result == {"version": "9.9.0"}
    staging = os.path.join(updater.WORK_DIR, "staging")
    assert sorted(os.listdir(staging)) == [updater.EXE_NAME, "VERSION"]
    assert open(os.path.join(staging, updater.EXE_NAME), "rb").read() == github.exe
    assert updater.staged_version() == "9.9.0"
    assert job.public()["unit"] == "MB" and job.total > 0
    # Both assets went through their redirect to the CDN, over HTTPS
    assert all(u.startswith("https://") for u in github.calls)
    assert frozen.read_bytes() == b"MZ old"        # nothing replaced before Apply


def test_release_without_checksum_file_is_not_installable(client, monkeypatch, frozen):
    monkeypatch.setattr(updater, "_get", FakeGitHub(sums=False))
    data = post(client, "/api/update/check", {"force": True}).get_json()
    assert data["available"] and not data["installable"] and data["reason"] == "no_checksum"
    assert post(client, "/api/update/download").status_code == 409


@pytest.mark.parametrize("fake, message", [
    (lambda: FakeGitHub(sums_text="0" * 64 + "  " + updater.zip_name("9.9.0") + "\n"), "SHA-256"),
    (lambda: FakeGitHub(sums_text="0" * 64 + "  other.zip\n"), "SHA256SUMS"),
    (lambda: FakeGitHub(zip_bytes=make_zip({"bin/GamelistMediaEditor.exe": b"MZx"})), "archive"),
    (lambda: FakeGitHub(exe=b"#!/bin/sh evil"), "archive"),
    (lambda: FakeGitHub(zip_bytes=b"not a zip at all"), "archive"),
])
def test_bad_downloads_are_refused_and_leave_nothing(client, monkeypatch, frozen, fake, message):
    monkeypatch.setattr(updater, "_get", fake())
    job = start_download(client)
    assert job.state == "error" and message in job.error
    assert os.listdir(os.path.join(updater.WORK_DIR, "staging")) == []
    assert updater.staged_version() is None


def test_redirect_to_http_is_refused(client, monkeypatch, frozen):
    fake = FakeGitHub()
    fake.routes[f"{updater.DOWNLOAD_PREFIX}v9.9.0/{updater.SUMS_NAME}"] = \
        lambda: FakeResponse(302, headers={"Location": "http://objects.githubusercontent.com/sums"})
    monkeypatch.setattr(updater, "_get", fake)
    job = start_download(client)
    assert job.state == "error" and "HTTPS" in job.error


def test_stop_during_download_leaves_nothing(client, monkeypatch, frozen):
    fake = FakeGitHub(delay=0.02)
    monkeypatch.setattr(updater, "_get", fake)
    post(client, "/api/update/check", {"force": True})
    job_id = post(client, "/api/update/download").get_json()["job"]["id"]
    deadline = time.time() + 10
    while CDN + "zip" not in fake.calls and time.time() < deadline:
        time.sleep(0.01)
    post(client, f"/api/jobs/{job_id}/stop")
    assert finish(job_id).state == "stopped"
    assert os.listdir(os.path.join(updater.WORK_DIR, "staging")) == []


def test_download_stays_valid_when_another_gamelist_opens(client, github, frozen, gamelist):
    from gme import xml_store
    job = start_download(client)
    xml_store.set_gamelist_path(str(gamelist))
    assert job.state == "done"


# --- apply --------------------------------------------------------------------

def test_apply_starts_the_helper_then_exits(client, github, frozen, monkeypatch):
    started, exits = [], []
    monkeypatch.setattr(updater, "_spawn", lambda cmd: started.append(cmd))
    monkeypatch.setattr(updater, "_exit_soon", lambda: exits.append(True))
    assert post(client, "/api/update/apply", {"job": "nope"}).status_code == 409
    job = start_download(client)
    r = post(client, "/api/update/apply", {"job": job.id})
    assert r.status_code == 200 and r.get_json()["version"] == "9.9.0" and exits == [True]
    cmd = started[0]
    arg = lambda name: cmd[cmd.index(name) + 1]   # noqa: E731
    assert cmd[0] == "powershell.exe" and "-ExecutionPolicy" in cmd
    assert arg("-Target") == str(frozen)
    assert arg("-NewFile") == os.path.join(updater.WORK_DIR, "staging", updater.EXE_NAME)
    assert arg("-BackupDir") == os.path.join(updater.WORK_DIR, "previous")
    assert arg("-ExpectVersion") == "9.9.0" and arg("-HealthUrl") == updater.HEALTH_URL
    assert str(os.getpid()) in arg("-Pids")
    assert open(arg("-File"), encoding="utf-8-sig").read().replace("\r\n", "\n") == updater.HELPER_PS1


def test_apply_waits_for_a_batch(client, github, frozen, monkeypatch):
    from gme import history
    job = start_download(client)
    monkeypatch.setattr(history, "_busy_reason", lambda: "history.busy_batch")
    r = post(client, "/api/update/apply", {"job": job.id})
    assert r.status_code == 409 and r.get_json()["code"] == "update_busy"


# --- the PowerShell helper on a fake install ---------------------------------
# Windows PowerShell on Windows; PowerShell 7 (pwsh) elsewhere when installed
# (GitHub's Ubuntu runners have it), GME_PWSH to point at another binary.

PWSH = "powershell.exe" if os.name == "nt" else (os.environ.get("GME_PWSH") or shutil.which("pwsh"))
needs_pwsh = pytest.mark.skipif(not PWSH, reason="PowerShell not installed")

USER_FILES = ("ui_settings.json", "screenscraper_config.json", "sources_config.json",
              "network_credentials.json", "network_places.json", "recent_gamelists.json",
              "recent_roms_roots.json", "update_state.json", "cache/thumbs/a.webp",
              ".gme-backups/network/x.xml", "app-window/Default/Preferences", "state/batches/job.json")


def fake_install(tmp_path, old=b"MZ old", new_data=b"MZ new"):
    app = tmp_path / "Gamelist Media Editor"
    (app / ".gme-update" / "staging").mkdir(parents=True)
    exe = app / updater.EXE_NAME
    exe.write_bytes(old)
    new = app / ".gme-update" / "staging" / updater.EXE_NAME
    new.write_bytes(new_data)
    for path in (exe, new):
        path.chmod(0o755)
    for rel in USER_FILES:
        f = app / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("user data " + rel, encoding="utf-8")
    script = app / ".gme-update" / "gme-update.ps1"
    script.write_text(updater.HELPER_PS1, encoding="utf-8-sig")
    return app, exe, new, script


def run_helper(app, exe, new, script, pids, *extra):
    # Output to a file, not a pipe: a restarted fake GME inherits it and would keep a pipe open
    out = open(app / "helper-output.txt", "w+")
    done = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Target", str(exe), "-NewFile", str(new), "-BackupDir", str(app / ".gme-update" / "previous"),
         "-LogFile", str(app / ".gme-update" / "update.log"), "-Pids", pids, "-ExpectVersion", "9.9.0",
         *extra], stdout=out, stderr=subprocess.STDOUT, text=True, timeout=120)
    out.seek(0)
    done.stdout, done.stderr = out.read(), ""
    out.close()
    return done


def helper_log(app):
    return (app / ".gme-update" / "update.log").read_text(encoding="utf-8-sig")


@needs_pwsh
def test_helper_waits_replaces_and_keeps_user_files(tmp_path):
    app, exe, new, script = fake_install(tmp_path)
    gme = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    threading.Thread(target=gme.wait, daemon=True).start()     # reaped at once (no zombie on POSIX)
    t0 = time.time()
    done = run_helper(app, exe, new, script, f"{gme.pid},{os.getpid()}", "-NoRestart")
    assert done.returncode == 0, done.stdout + done.stderr
    assert gme.poll() is not None and time.time() - t0 >= 2      # waited for "GME" to exit
    assert exe.read_bytes() == b"MZ new" and not new.exists()
    assert (app / ".gme-update" / "previous" / updater.EXE_NAME).read_bytes() == b"MZ old"
    for rel in USER_FILES:
        assert (app / rel).read_text(encoding="utf-8") == "user data " + rel
    assert "replaced" in helper_log(app)


@needs_pwsh
def test_helper_keeps_the_current_exe_when_the_new_one_is_missing(tmp_path):
    app, exe, new, script = fake_install(tmp_path)
    new.unlink()
    done = run_helper(app, exe, new, script, "", "-NoRestart")
    assert done.returncode == 1
    assert exe.read_bytes() == b"MZ old"
    assert "update failed" in helper_log(app)


# A fake GME for the restart: a shell script serving /api/session with a version.
FAKE_GME = """#!/bin/sh
exec "{python}" - "$@" <<'PY'
import http.server, json, os, sys
here = os.path.dirname(os.path.abspath({path!r}))
open(os.path.join(here, "started-{version}"), "w").write(" ".join(sys.argv[1:]))
if {crash}:
    sys.exit(3)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({{"version": "{version}"}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass
srv = http.server.HTTPServer(("127.0.0.1", {port}), H)
srv.timeout = 0.5
import time
end = time.time() + 20
while time.time() < end and not os.path.exists(os.path.join(here, "stop")):
    srv.handle_request()
PY
"""


def fake_gme(path, version, port, crash=False):
    return FAKE_GME.format(python=sys.executable, path=str(path), version=version, port=port,
                           crash=crash).encode()


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@needs_pwsh
@pytest.mark.skipif(os.name == "nt", reason="the fake GME is a shell script")
def test_helper_restarts_the_new_version_with_the_gamelist(tmp_path):
    port = free_port()
    app = tmp_path / "Gamelist Media Editor"
    exe = app / updater.EXE_NAME
    app_, exe, new, script = fake_install(tmp_path, fake_gme(exe, "1.7.5", port), fake_gme(exe, "9.9.0", port))
    try:
        done = run_helper(app, exe, new, script, "", "-HealthUrl", f"http://127.0.0.1:{port}/api/session",
                          "-HealthSeconds", "15", "-Gamelist", "/roms/snes/gamelist.xml")
        assert done.returncode == 0, done.stdout + done.stderr + helper_log(app)
        assert (app / "started-9.9.0").read_text() == "/roms/snes/gamelist.xml"
        assert "version 9.9.0 started" in helper_log(app)
    finally:
        (app / "stop").write_text("")


@needs_pwsh
@pytest.mark.skipif(os.name == "nt", reason="the fake GME is a shell script")
def test_helper_rolls_back_when_the_new_version_does_not_start(tmp_path):
    port = free_port()
    app = tmp_path / "Gamelist Media Editor"
    exe = app / updater.EXE_NAME
    old = fake_gme(exe, "1.7.5", port)
    app_, exe, new, script = fake_install(tmp_path, old, fake_gme(exe, "9.9.0", port, crash=True))
    try:
        done = run_helper(app, exe, new, script, "", "-HealthUrl", f"http://127.0.0.1:{port}/api/session",
                          "-HealthSeconds", "8")
        assert done.returncode == 2, done.stdout + done.stderr + helper_log(app)
        assert exe.read_bytes() == old                     # the previous version is back
        assert (app / "started-9.9.0").exists()            # the new one was tried
        deadline = time.time() + 10
        while not (app / "started-1.7.5").exists() and time.time() < deadline:
            time.sleep(0.1)
        assert (app / "started-1.7.5").exists()            # and the old one started again
        assert "rolling back" in helper_log(app) and "previous version restored" in helper_log(app)
    finally:
        (app / "stop").write_text("")


# --- release assets -----------------------------------------------------------

def test_release_assets_are_what_the_updater_expects(tmp_path):
    import zipfile
    from tools.release_assets import build
    exe = tmp_path / "GamelistMediaEditor.exe"
    exe.write_bytes(b"MZ" + os.urandom(1000))
    archive, sums = build(str(exe), "1.8.0", str(tmp_path / "out"))
    assert os.path.basename(archive) == updater.zip_name("1.8.0")
    with zipfile.ZipFile(archive) as z:
        assert z.namelist() == [updater.EXE_NAME] and z.read(updater.EXE_NAME) == exe.read_bytes()
    parsed = updater.parse_sums(open(sums, encoding="ascii").read())
    import hashlib
    assert parsed == {updater.zip_name("1.8.0"): hashlib.sha256(open(archive, "rb").read()).hexdigest()}


def test_release_workflow_publishes_the_checksum_file():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, ".github", "workflows", "release.yml"), encoding="utf-8").read()
    assert "tools/release_assets.py" in text and "SHA256SUMS.txt" in text and "--draft" in text
