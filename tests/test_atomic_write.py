"""gamelist.xml is never seen empty or half-written, even while it is being saved."""
import os
import sys
import threading

import pytest
from lxml import etree

from gme import fsutil, xml_store


@pytest.mark.skipif(sys.platform == "win32", reason=(
    "Windows cannot replace a file another process holds open; this tight-loop "
    "reader keeps it open almost constantly, so atomic_write falls back to the "
    "old in-place write by design (covered by test_locked_file_falls_back...)"))
def test_reader_never_sees_an_empty_gamelist(gamelist):
    tree = xml_store.load_xml()
    errors, stop = [], threading.Event()

    def reader():
        while not stop.is_set():
            try:
                etree.parse(str(gamelist))
            except etree.XMLSyntaxError as e:   # empty or truncated file
                errors.append(str(e))

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(300):
            tree.getroot().find("game/name").text = f"Alpha {i}"
            xml_store.save_xml(tree)
    finally:
        stop.set()
        t.join()
    assert not errors, errors[:3]
    assert etree.parse(str(gamelist)).getroot().find("game/name").text == "Alpha 299"


def test_no_temporary_file_left_behind(gamelist):
    xml_store.save_xml(xml_store.load_xml())
    assert sorted(p.name for p in gamelist.parent.iterdir() if p.suffix in (".tmp", ".xml")) == ["gamelist.xml"]


def test_locked_file_falls_back_to_a_direct_write(tmp_path, monkeypatch):
    target = tmp_path / "gamelist.xml"
    target.write_bytes(b"old")
    monkeypatch.setattr(fsutil, "_REPLACE_DELAY", 0)

    def locked(*_):
        raise PermissionError("file in use")

    monkeypatch.setattr(fsutil.os, "replace", locked)
    fsutil.atomic_write(str(target), b"new")
    assert target.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["gamelist.xml"]


def test_failed_write_keeps_the_original(tmp_path, monkeypatch):
    target = tmp_path / "gamelist.xml"
    target.write_bytes(b"<gameList/>")

    def disk_full(*_):
        raise OSError("No space left on device")

    monkeypatch.setattr(fsutil.os, "fsync", disk_full)
    with pytest.raises(OSError):
        fsutil.atomic_write(str(target), b"<gameList><game/></gameList>")
    assert target.read_bytes() == b"<gameList/>"
    assert [p.name for p in tmp_path.iterdir()] == ["gamelist.xml"]


def test_screenscraper_config_is_written_atomically(tmp_path, monkeypatch):
    from gme.scrapers import ss
    monkeypatch.setattr(ss, "ss_config_path", lambda: str(tmp_path / "screenscraper_config.json"))
    calls = []
    real = ss.atomic_write
    monkeypatch.setattr(ss, "atomic_write", lambda p, d: (calls.append(p), real(p, d)))
    ss.save_ss_config({"ssid": "me", "prefer_region": "eu"})
    assert calls and os.path.isfile(calls[0])
    assert ss.load_ss_config()["ssid"] == "me"
