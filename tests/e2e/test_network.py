"""Network shares in the interface: discovery, favourites, sign-in, errors and the
machine dialog. The network is mocked in the server process (no real host)."""
import os

import pytest

from gme import network

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")


class WinError(OSError):
    def __init__(self, code):
        super().__init__(None, "simulated")
        self.winerror = code


def open_dialog(page):
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")
    page.wait_for_selector("#open-gl-listing .open-gl-item")


def machines(roms):
    return [
        {"host": "BATOCERA", "kind": "batocera", "address": "192.168.1.42", "smb": True,
         "share": "\\\\BATOCERA\\share", "roms": roms, "api": {"state": "ok", "version": "41"}},
        {"host": "RECALBOX", "kind": "recalbox", "address": None, "smb": False,
         "share": "\\\\RECALBOX\\share", "roms": None, "api": {"state": "off"}},
    ]


def test_scan_finds_a_machine_and_opens_its_roms(page, gamelist, monkeypatch):
    roms = str(gamelist.parent.parent)
    monkeypatch.setattr(network, "discover", lambda extra=None: machines(roms))
    monkeypatch.setattr(network, "IS_WINDOWS", True)        # the .exe's view: no "mount the share" hint
    open_dialog(page)
    page.click("#open-gl-net-scan")
    page.wait_for_selector(".open-gl-net-machine.is-found")
    found = page.locator(".open-gl-net-machine.is-found")
    assert "BATOCERA" in found.inner_text() and "192.168.1.42" in found.inner_text()
    assert "41" in found.locator(".open-gl-net-api").inner_text()
    assert "RECALBOX" in page.locator(".open-gl-net-machine:not(.is-found)").inner_text()
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "network-scan.png"))
    page.click("#open-gl-cancel")
    gamelist_dir = str(gamelist.parent)
    open_dialog(page)                                   # starts in roms/: go elsewhere first
    page.fill("#open-gl-path", gamelist_dir)
    page.press("#open-gl-path", "Enter")
    page.wait_for_function("document.getElementById('open-gl-browse-path').textContent === %r" % gamelist_dir)
    page.click("#open-gl-net-scan")
    page.locator(".open-gl-net-machine.is-found .open-gl-net-go").click()
    page.wait_for_function("document.getElementById('open-gl-browse-path').textContent === %r" % roms)
    page.wait_for_selector("#open-gl-listing .open-gl-dir >> text=snes")


def test_favourites_persist_and_can_be_removed(page, gamelist):
    open_dialog(page)
    folder = str(gamelist.parent)
    page.fill("#open-gl-path", folder)
    page.press("#open-gl-path", "Enter")                 # a folder: browsed, not opened
    page.wait_for_function("document.getElementById('open-gl-browse-path').textContent === %r" % folder)
    page.click("#open-gl-net-fav")
    page.wait_for_selector("#open-gl-net-favs .open-gl-net-fav")
    assert network._places()["favorites"][0]["path"] == folder
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "network-favorites.png"))
    page.click("#open-gl-cancel")
    open_dialog(page)
    page.wait_for_selector("#open-gl-net-favs .open-gl-net-fav")
    page.click("#open-gl-net-favs .open-gl-net-fav-del")
    page.wait_for_function("document.getElementById('open-gl-net-favs').hidden")
    assert network._places()["favorites"] == []


def test_a_share_that_asks_for_a_password(page, gamelist, monkeypatch):
    from gme import editor
    real = editor._browse_listing
    state = {"signed_in": False, "creds": None}
    monkeypatch.setattr(network, "reachable", lambda host: "192.168.1.42")

    def listing(target):
        if not network.is_unc(target):
            return real(target)
        if not state["signed_in"]:
            raise WinError(1326)
        return real(str(gamelist.parent))
    monkeypatch.setattr(editor, "_browse_listing", listing)

    def connect(host, share, user, password):
        state["signed_in"] = True
        state["creds"] = (host, share, user, password)
    monkeypatch.setattr(network, "connect", connect)

    open_dialog(page)
    page.fill("#open-gl-path", "\\\\BATOCERA\\share")
    page.press("#open-gl-path", "Enter")
    page.wait_for_selector("#open-gl-net-login:not([hidden])")
    assert "\\\\BATOCERA\\share" in page.inner_text("#open-gl-net-login-text")
    page.fill("#open-gl-net-user", "root")
    page.fill("#open-gl-net-pass", "linux")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "network-login.png"))
    page.click("#open-gl-net-connect")
    page.wait_for_selector("#open-gl-net-login[hidden]", state="attached")
    page.wait_for_selector("#open-gl-listing .open-gl-file.is-gamelist")
    assert state["creds"] == ("BATOCERA", "share", "root", "linux")
    assert page.input_value("#open-gl-net-pass") == ""
    assert not os.path.exists(network.CREDENTIALS_FILE)          # not remembered unless ticked


def test_unreachable_machine_offers_a_retry(page, gamelist, monkeypatch):
    monkeypatch.setattr(network, "resolve", lambda host, timeout=None: None)
    open_dialog(page)
    page.fill("#open-gl-path", "\\\\RECALBOX\\share\\roms")
    page.press("#open-gl-path", "Enter")
    page.wait_for_selector("#open-gl-net-retry")
    assert "RECALBOX" in page.inner_text("#open-gl-listing")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "network-unreachable.png"))
    monkeypatch.setattr(network, "reachable", lambda host: "192.168.1.43")
    from gme import editor
    real = editor._browse_listing
    monkeypatch.setattr(editor, "_browse_listing",
                        lambda target: real(str(gamelist.parent) if network.is_unc(target) else target))
    page.click("#open-gl-net-retry")
    page.wait_for_selector("#open-gl-listing .open-gl-file.is-gamelist")


def test_machine_dialog_reloads_the_lists(page, gamelist, monkeypatch):
    calls = []
    monkeypatch.setattr(network, "location", lambda path: {"host": "BATOCERA", "share": "share", "via": "unc"}
                        if path and str(path).startswith(str(gamelist.parent.parent)) else None)
    monkeypatch.setattr(network, "es_api", lambda host, address=None: {"state": "ok", "version": "41"})

    def reload_games(host):
        calls.append(host)
        result = {"ok": True, "error": None, "host": host, "at": 0}
        network._reload["last"] = result
        return result
    monkeypatch.setattr(network, "reload_games", reload_games)
    page.reload()
    page.wait_for_selector("#system-network:not([hidden])")
    assert page.inner_text("#system-network-host") == "BATOCERA"
    page.click("#system-network")
    page.wait_for_selector("#network-modal.open")
    page.wait_for_function("!document.getElementById('network-reload-now').disabled")
    assert "41" in page.inner_text("#network-api")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "network-machine.png"))
    page.click("#network-reload-now")
    page.wait_for_function("document.getElementById('toast').textContent.includes('BATOCERA')")
    assert calls == ["BATOCERA"]
    page.check("#network-reload-auto")
    page.wait_for_function("window.__gmeNetwork && window.__gmeNetwork.reload_after_save === true")
    assert network._places()["reload_after_save"] is True


def test_forbidden_api_explains_the_setting(page, gamelist, monkeypatch):
    monkeypatch.setattr(network, "location", lambda path: {"host": "BATOCERA", "share": "share", "via": "unc"}
                        if path and str(path).startswith(str(gamelist.parent.parent)) else None)
    monkeypatch.setattr(network, "es_api", lambda host, address=None: {"state": "forbidden"})
    page.reload()
    page.click("#system-network")
    page.wait_for_function("document.getElementById('network-api').dataset.state === 'forbidden'")
    assert page.locator("#network-reload-now").is_disabled()
