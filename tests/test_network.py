"""Gamelists on a network share (gme/network.py). No real host is ever reached:
names, ports and EmulationStation's web API are mocked, the API by a small
HTTP server on 127.0.0.1."""
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from gme import backups, network, xml_store
from tests.conftest import LOCAL

BATO = "\\\\BATOCERA\\share\\roms\\snes\\gamelist.xml"


# --- Paths ------------------------------------------------------------------

@pytest.mark.parametrize("path, expected", [
    ("\\\\BATOCERA\\share\\roms", True),
    ("//RECALBOX/share/roms", True),
    ("\\\\192.168.1.20\\share", True),
    ("\\\\?\\C:\\long\\path", False),
    ("\\\\.\\pipe\\x", False),
    ("C:\\RetroBat\\roms", False),
    ("/home/me/roms", False),
    ("\\\\", False),
])
def test_is_unc(path, expected):
    assert network.is_unc(path) is expected


def test_split_and_build_unc_paths():
    assert network.split_unc(BATO) == ("BATOCERA", "share", "roms\\snes\\gamelist.xml")
    assert network.split_unc("//RECALBOX/share/") == ("RECALBOX", "share", "")
    assert network.split_unc("\\\\BATOCERA") == ("BATOCERA", "", "")
    assert network.unc("BATOCERA", "share", "roms/snes") == "\\\\BATOCERA\\share\\roms\\snes"
    # Typed with forward slashes, quotes or doubled separators: the Windows form
    assert network.normalize('"//BATOCERA/share//roms/"') == "\\\\BATOCERA\\share\\roms"


def test_location_of_unc_mount_and_local_paths(tmp_path, monkeypatch):
    assert network.location(BATO) == {"host": "BATOCERA", "share": "share", "via": "unc"}
    assert network.location(str(tmp_path / "gamelist.xml")) is None
    assert network.location(None) is None
    if os.name != "nt":
        mount = str(tmp_path / "bato")
        monkeypatch.setattr(network, "_mounts", lambda: [(mount, "//BATOCERA/share")])
        loc = network.location(os.path.join(mount, "roms", "snes", "gamelist.xml"))
        assert loc == {"host": "BATOCERA", "share": "share", "via": "mount", "mount": mount}
        assert network.location(str(tmp_path / "batocera-other")) is None     # a prefix is not the mount


def test_kind_of_known_machines():
    assert network.kind_of("BATOCERA") == "batocera"
    assert network.kind_of("recalbox.local") == "recalbox"
    assert network.kind_of("192.168.1.20") is None


# --- I/O with a time limit ----------------------------------------------------

def test_call_returns_raises_and_times_out():
    assert network.call(lambda a, b: a + b, 2, 3, timeout=1) == 5
    with pytest.raises(ZeroDivisionError):
        network.call(lambda: 1 / 0, timeout=1)
    release = threading.Event()
    started = time.monotonic()
    with pytest.raises(network.NetworkError) as err:
        network.call(release.wait, 5, timeout=0.2, host="BATOCERA")
    assert err.value.code == "net_timeout" and err.value.host == "BATOCERA"
    assert time.monotonic() - started < 2           # the request answers, the worker is left behind
    release.set()


def test_unreachable_host(monkeypatch):
    monkeypatch.setattr(network, "resolve", lambda host, timeout=None: None)
    with pytest.raises(network.NetworkError) as err:
        network.reachable("BATOCERA")
    assert err.value.code == "net_unreachable"
    monkeypatch.setattr(network, "resolve", lambda host, timeout=None: "192.0.2.1")
    monkeypatch.setattr(network, "port_open", lambda address, port, timeout=None: False)
    with pytest.raises(network.NetworkError):
        network.reachable("BATOCERA")


class WinError(OSError):
    def __init__(self, code):
        super().__init__(None, "simulated")
        self.winerror = code


def test_windows_errors_are_explained():
    assert network.os_error(WinError(1326), "BATOCERA", "share").code == "net_auth"
    assert network.os_error(WinError(1272), "BATOCERA", "share").code == "net_auth"   # guest access blocked
    assert network.os_error(WinError(53), "BATOCERA").code == "net_unreachable"
    assert network.os_error(WinError(2), "BATOCERA") is None


# --- EmulationStation's web API (a fake server on 127.0.0.1) ------------------

class FakeES(BaseHTTPRequestHandler):
    calls = []
    forbidden = False

    def do_GET(self):
        FakeES.calls.append(self.path)
        if FakeES.forbidden:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"403 - Forbidden")
            return
        if self.path == "/caps":
            body = json.dumps({"Version": "41-test"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/reloadgames":
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_es(monkeypatch):
    FakeES.calls = []
    FakeES.forbidden = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeES)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(network, "ES_API_PORT", server.server_address[1])
    yield FakeES
    server.shutdown()
    server.server_close()


def test_es_api_states(fake_es, monkeypatch):
    assert network.es_api("BATOCERA", "127.0.0.1") == {"state": "ok", "version": "41-test"}
    fake_es.forbidden = True
    assert network.es_api("BATOCERA", "127.0.0.1")["state"] == "forbidden"
    monkeypatch.setattr(network, "ES_API_PORT", 9)                  # nothing listens there
    assert network.es_api("BATOCERA", "127.0.0.1")["state"] == "off"


def test_reload_games_uses_the_documented_endpoint(fake_es):
    result = network.reload_games("127.0.0.1")
    assert result["ok"] and fake_es.calls == ["/reloadgames"]
    fake_es.forbidden = True
    result = network.reload_games("127.0.0.1")
    assert not result["ok"] and result["error"]


def test_saves_in_a_row_trigger_one_reload(gamelist, monkeypatch, client):
    calls = []
    monkeypatch.setattr(network, "RELOAD_DELAY", 0.15)
    monkeypatch.setattr(network, "location", lambda path: {"host": "BATOCERA", "share": "share", "via": "unc"})
    monkeypatch.setattr(network, "reload_games", lambda host: calls.append(host))
    network.set_reload_after_save(True)
    for name in ("One", "Two", "Three"):
        r = client.post("/api/game/0?path=./alpha.zip", json={"name": name}, headers=LOCAL)
        assert r.status_code == 200
    time.sleep(0.6)
    assert calls == ["BATOCERA"]


def test_no_reload_unless_asked(gamelist, monkeypatch, client):
    calls = []
    monkeypatch.setattr(network, "RELOAD_DELAY", 0.05)
    monkeypatch.setattr(network, "location", lambda path: {"host": "BATOCERA", "share": "share", "via": "unc"})
    monkeypatch.setattr(network, "reload_games", lambda host: calls.append(host))
    assert client.post("/api/game/0?path=./alpha.zip", json={"name": "X"}, headers=LOCAL).status_code == 200
    time.sleep(0.2)
    assert calls == []


def test_reload_route_only_targets_the_open_gamelists_machine(gamelist, client, fake_es, monkeypatch):
    r = client.post("/api/network/reload", headers=LOCAL)
    assert r.status_code == 400 and r.get_json()["code"] == "net_not_remote"
    monkeypatch.setattr(network, "location", lambda path: {"host": "127.0.0.1", "share": "share", "via": "unc"})
    r = client.post("/api/network/reload", headers=LOCAL)
    assert r.status_code == 200 and r.get_json()["success"]
    assert fake_es.calls == ["/reloadgames"]
    info = client.get("/api/network", headers=LOCAL).get_json()["current"]
    assert info["host"] == "127.0.0.1" and info["last_reload"]["ok"]


# --- Discovery --------------------------------------------------------------------

def test_discover_known_machines(monkeypatch):
    monkeypatch.setattr(network, "resolve", lambda host, timeout=None: "192.0.2.10" if host == "BATOCERA" else None)
    monkeypatch.setattr(network, "port_open", lambda address, port, timeout=None: True)
    monkeypatch.setattr(network, "es_api", lambda host, address=None: {"state": "forbidden"})
    monkeypatch.setattr(network.os.path, "isdir", lambda p: p == "\\\\BATOCERA\\share\\roms")
    machines = {m["host"]: m for m in network.discover()}
    assert set(machines) == {"BATOCERA", "RECALBOX"}
    bato = machines["BATOCERA"]
    assert bato["address"] == "192.0.2.10" and bato["smb"] and bato["kind"] == "batocera"
    assert bato["api"] == {"state": "forbidden"}
    assert bato["roms"] == ("\\\\BATOCERA\\share\\roms" if network.IS_WINDOWS else None)
    assert machines["RECALBOX"]["address"] is None


def test_discover_a_typed_address(client, monkeypatch):
    seen = []
    monkeypatch.setattr(network, "probe", lambda host, kind=None, share="share", roms="roms": seen.append(host) or
                        {"host": host, "kind": kind, "address": None, "smb": False, "share": "", "roms": None,
                         "api": {"state": "off"}})
    r = client.post("/api/network/discover", headers=LOCAL, json={"host": "192.168.1.20"})
    assert r.status_code == 200 and seen[0] == "192.168.1.20" and set(seen) >= {"BATOCERA", "RECALBOX"}
    r = client.post("/api/network/discover", headers=LOCAL, json={"host": "bad host; rm"})
    assert r.status_code == 400 and r.get_json()["code"] == "net_bad_host"


# --- Folder browser and opening --------------------------------------------------

def test_browse_a_machine_lists_its_shares(client, monkeypatch):
    monkeypatch.setattr(network, "shares", lambda host: ["roms", "share"])
    data = client.get("/api/browse?path=" + "\\\\BATOCERA", headers=LOCAL).get_json()
    assert data["path"] == "\\\\BATOCERA"
    assert [d["path"] for d in data["dirs"]] == ["\\\\BATOCERA\\roms", "\\\\BATOCERA\\share"]
    assert data["network"]["kind"] == "batocera"


def test_browse_unreachable_and_slow_shares(client, monkeypatch):
    monkeypatch.setattr(network, "resolve", lambda host, timeout=None: None)
    r = client.get("/api/browse?path=" + "\\\\BATOCERA\\share\\roms", headers=LOCAL)
    assert r.status_code == 503 and r.get_json()["code"] == "net_unreachable"
    assert "BATOCERA" in r.get_json()["error"]

    monkeypatch.setattr(network, "reachable", lambda host: "192.0.2.10")
    monkeypatch.setattr(network, "IO_TIMEOUT", 0.2)
    release = threading.Event()
    monkeypatch.setattr("gme.editor._browse_listing", lambda target: release.wait(5))
    started = time.monotonic()
    r = client.get("/api/browse?path=" + "\\\\BATOCERA\\share\\roms", headers=LOCAL)
    release.set()
    assert r.status_code == 504 and r.get_json()["code"] == "net_timeout"
    assert time.monotonic() - started < 3


def test_browse_share_that_asks_for_a_password(client, monkeypatch):
    monkeypatch.setattr(network, "reachable", lambda host: "192.0.2.10")

    def denied(target):
        raise WinError(1326)
    monkeypatch.setattr("gme.editor._browse_listing", denied)
    r = client.get("/api/browse?path=" + "\\\\BATOCERA\\share", headers=LOCAL)
    data = r.get_json()
    assert r.status_code == 401 and data["code"] == "net_auth"
    assert data["host"] == "BATOCERA" and data["share"] == "share"


def test_open_on_an_unreachable_machine_keeps_the_current_gamelist(gamelist, client, monkeypatch):
    monkeypatch.setattr(network, "resolve", lambda host, timeout=None: None)
    r = client.post("/api/open-gamelist", headers=LOCAL, json={"path": BATO})
    assert r.status_code == 503 and r.get_json()["code"] == "net_unreachable"
    assert xml_store.XML_PATH == str(gamelist)


def test_local_browse_reports_no_network(gamelist, client):
    data = client.get("/api/browse?path=" + str(gamelist.parent), headers=LOCAL).get_json()
    assert data["network"] is None and data["has_gamelist"]


# --- Favourites, sign-in, backups ------------------------------------------------

def test_favourites_are_kept_without_duplicates(client, tmp_path):
    for path in ("//BATOCERA/share/roms", "\\\\BATOCERA\\share\\roms", "\\\\RECALBOX\\share\\roms"):
        r = client.post("/api/network/favorites", headers=LOCAL, json={"path": path})
        assert r.status_code == 200
    favs = client.get("/api/network", headers=LOCAL).get_json()["favorites"]
    assert [f["path"] for f in favs] == ["\\\\RECALBOX\\share\\roms", "\\\\BATOCERA\\share\\roms"]
    assert favs[1]["label"] == "BATOCERA · roms"
    r = client.post("/api/network/favorites", headers=LOCAL, json={"action": "remove", "path": "//batocera/share/roms"})
    assert [f["path"] for f in r.get_json()["favorites"]] == ["\\\\RECALBOX\\share\\roms"]
    assert client.post("/api/network/favorites", headers=LOCAL, json={"path": ""}).status_code == 400


def test_reload_setting(client):
    assert client.post("/api/network/settings", headers=LOCAL, json={"reload_after_save": "yes"}).status_code == 400
    assert client.post("/api/network/settings", headers=LOCAL, json={"reload_after_save": True}).get_json() == {"reload_after_save": True}
    assert client.get("/api/network", headers=LOCAL).get_json()["reload_after_save"] is True


def test_sign_in_is_remembered_only_when_asked_and_never_shown(client, monkeypatch, caplog):
    secret_word = "p4ss-w0rd-xyz"
    monkeypatch.setattr(network, "reachable", lambda host: "192.0.2.10")
    monkeypatch.setattr(network, "connect", lambda host, share, user, password: None)
    caplog.set_level(logging.DEBUG)
    body = {"host": "BATOCERA", "share": "share", "user": "root", "password": secret_word}
    r = client.post("/api/network/connect", headers=LOCAL, json=body)
    assert r.status_code == 200 and secret_word not in r.get_data(as_text=True)
    assert not os.path.exists(network.CREDENTIALS_FILE)
    r = client.post("/api/network/connect", headers=LOCAL, json=dict(body, remember=True))
    assert r.status_code == 200 and secret_word not in r.get_data(as_text=True)
    with open(network.CREDENTIALS_FILE, encoding="utf-8") as f:
        assert json.load(f) == {"batocera\\share": {"user": "root", "password": secret_word}}
    assert network.saved_user("BATOCERA", "share") == "root"
    assert secret_word not in client.get("/api/network", headers=LOCAL).get_data(as_text=True)
    assert secret_word not in caplog.text
    # Unticked again: forgotten
    client.post("/api/network/connect", headers=LOCAL, json=body)
    with open(network.CREDENTIALS_FILE, encoding="utf-8") as f:
        assert json.load(f) == {}


def test_sign_in_input_is_checked(client):
    r = client.post("/api/network/connect", headers=LOCAL, json={"host": "a b", "share": "share"})
    assert r.status_code == 400
    r = client.post("/api/network/connect", headers=LOCAL, json={"host": "BATOCERA", "share": "../x"})
    assert r.status_code == 400 and r.get_json()["code"] == "net_bad_share"


def test_sign_in_off_windows_says_how_to_mount(client, monkeypatch):
    monkeypatch.setattr(network, "IS_WINDOWS", False)
    monkeypatch.setattr(network, "reachable", lambda host: "192.0.2.10")
    r = client.post("/api/network/connect", headers=LOCAL, json={"host": "BATOCERA", "share": "share"})
    assert r.get_json()["code"] == "net_windows_only" and "smb://" in r.get_json()["error"]


def test_snapshots_of_a_network_gamelist_stay_on_this_pc(gamelist, monkeypatch, tmp_path):
    app_dir = tmp_path / "app"
    monkeypatch.setattr(backups, "APP_DIR", str(app_dir))
    monkeypatch.setattr(network, "location", lambda path: {"host": "BATOCERA", "share": "share", "via": "unc"})
    monkeypatch.setattr(network, "unc_path_of", lambda path: BATO)
    expected = app_dir / ".gme-backups" / "network" / "batocera" / "share" / "roms" / "snes" / "gamelist.xml"
    assert backups.backup_dir() == str(expected)
    snap = backups.create_snapshot()
    assert (expected / snap).read_bytes() == gamelist.read_bytes()
    assert not (gamelist.parent / ".gme-backups").exists()


def test_system_info_flags_a_network_gamelist(gamelist, client, monkeypatch):
    from gme.systems import get_system_info
    assert get_system_info()["network"] is None
    monkeypatch.setattr(network, "location", lambda path: {"host": "BATOCERA", "share": "share", "via": "unc"})
    info = get_system_info()["network"]
    assert info["host"] == "BATOCERA" and info["kind"] == "batocera" and info["reload_after_save"] is False


# --- Windows: a real UNC path through the administrative share of this PC ----------

def _admin_unc(path):
    drive, rest = os.path.splitdrive(str(path))
    return "\\\\localhost\\" + drive[0] + "$" + rest


@pytest.mark.skipif(os.name != "nt", reason="UNC paths are a Windows feature")
def test_windows_unc_open_browse_and_save(tmp_path, client, monkeypatch):
    folder = tmp_path / "snes"
    folder.mkdir()
    (folder / "gamelist.xml").write_text("<gameList><game><path>./a.zip</path><name>A</name></game></gameList>",
                                         encoding="utf-8")
    (folder / "a.zip").write_bytes(b"rom")
    unc_folder = _admin_unc(folder)
    if not os.path.isdir(unc_folder):
        pytest.skip("administrative share \\\\localhost\\C$ not available")
    monkeypatch.setattr(backups, "APP_DIR", str(tmp_path / "app"))
    data = client.get("/api/browse?path=" + unc_folder, headers=LOCAL).get_json()
    assert data["network"]["host"] == "localhost" and data["has_gamelist"]
    assert [f["name"] for f in data["files"]] == ["gamelist.xml"]
    xml = unc_folder + "\\gamelist.xml"
    try:
        r = client.post("/api/open-gamelist", headers=LOCAL, json={"path": xml})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["system"]["network"]["host"] == "localhost"
        session = {"X-Gamelist-Session": r.get_json()["session_id"]}
        r = client.post("/api/game/0?path=./a.zip", json={"name": "Over SMB"}, headers=dict(LOCAL, **session))
        assert r.status_code == 200, r.get_json()
        assert "Over SMB" in (folder / "gamelist.xml").read_text(encoding="utf-8")
        assert not [p for p in os.listdir(folder) if p.endswith(".tmp")]     # atomic: no temp file left
        assert backups.backup_dir().startswith(str(tmp_path / "app"))
    finally:
        xml_store.close_gamelist()


def test_recent_network_gamelists_are_listed_without_network_access(client, monkeypatch):
    from gme import recent
    recent.remember(BATO)
    touched = []
    real = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: touched.append(p) or real(p))
    data = client.get("/api/recent", headers=LOCAL).get_json()["recent"]
    assert data[0]["exists"] is True
    assert not [p for p in touched if network.is_unc(p)]
