"""DAT tool (gme/datfile.py, gme/dattool.py), names from a DAT (Edit in bulk)
and a new gamelist from a ROM folder (gme/newgamelist.py). Small synthetic
DATs only; ROM files must never change."""
import io
import os
import time
import zipfile
import zlib

import pytest
from lxml import etree

from gme import dattool, xml_store
from gme.datfile import DatError, read_dat
from tests.conftest import LOCAL


def crc(data):
    return "%08x" % (zlib.crc32(data) & 0xFFFFFFFF)


ALPHA, BRAVO, CHARLIE, PAC1, PAC2 = b"alpha-rom" * 50, b"bravo-rom" * 70, b"charlie" * 30, b"pac-1" * 64, b"pac-2" * 64

LOGIQX = f"""<?xml version="1.0"?>
<!DOCTYPE datafile PUBLIC "-//Logiqx//DTD ROM Management Datafile//EN" "http://www.logiqx.com/Dats/datafile.dtd">
<datafile>
  <header><name>Test - Super Console</name><description>Test DAT</description></header>
  <game name="Alpha (Europe)"><description>Alpha (Europe)</description>
    <rom name="Alpha (Europe).sfc" size="{len(ALPHA)}" crc="{crc(ALPHA)}"/></game>
  <game name="Bravo (USA)" cloneof="Alpha (Europe)"><description>Bravo (USA)</description>
    <rom name="Bravo (USA).sfc" size="{len(BRAVO)}" crc="{crc(BRAVO)}"/></game>
  <game name="Charlie (Japan)"><description>Charlie (Japan)</description>
    <rom name="Charlie (Japan).sfc" size="{len(CHARLIE)}" crc="{crc(CHARLIE)}" status="baddump"/></game>
  <game name="Delta (World)"><description>Delta (World)</description>
    <rom name="Delta (World).sfc" size="10" crc="12345678"/></game>
  <game name="[BIOS] Console" isbios="yes"><description>[BIOS] Console</description>
    <rom name="bios.bin" size="4" crc="deadbeef"/></game>
</datafile>
"""

LISTXML = f"""<?xml version="1.0"?>
<!DOCTYPE mame [<!ELEMENT mame (machine+)>]>
<mame build="0.270">
  <machine name="pacman" sourcefile="pacman/pacman.cpp"><description>Pac-Man (Midway)</description>
    <rom name="pm1" size="{len(PAC1)}" crc="{crc(PAC1)}"/><rom name="pm2" size="{len(PAC2)}" crc="{crc(PAC2)}"/>
    <driver status="good"/></machine>
  <machine name="puckman" cloneof="pacman" romof="pacman" sourcefile="pacman/pacman.cpp"><description>Puck Man (Japan set 1)</description>
    <rom name="pm1" merge="pm1" size="{len(PAC1)}" crc="{crc(PAC1)}"/><driver status="good"/></machine>
  <machine name="kinst" sourcefile="midway/kinst.cpp"><description>Killer Instinct (v1.5d)</description>
    <rom name="ki.u98" size="4" crc="0badc0de"/><disk name="kinst" sha1="0000000000000000000000000000000000000000"/>
    <driver status="preliminary"/></machine>
  <machine name="neogeo" isbios="yes"><description>Neo-Geo</description><rom name="sp-s2.sp1" size="4" crc="9036d879"/></machine>
  <machine name="z80" isdevice="yes"><description>Zilog Z80</description></machine>
</mame>
"""

CMP = f"""clrmamepro (
\tname "Test - Text DAT"
\tdescription "Test - Text DAT (20260101)"
)

game (
\tname "Alpha (Europe)"
\tdescription "Alpha (Europe)"
\trom ( name "Alpha (Europe).sfc" size {len(ALPHA)} crc {crc(ALPHA)} )
)

game (
\tname "Bravo (USA)"
\tcloneof "Alpha (Europe)"
\tdescription "Bravo \\"the\\" game"
\trom ( name "Bravo (USA).sfc" size {len(BRAVO)} crc {crc(BRAVO).upper()} )
)

resource (
\tname "neogeo"
\tdescription "Neo-Geo BIOS"
\trom ( name sp-s2.sp1 size 4 crc 9036d879 )
)
"""


@pytest.fixture(autouse=True)
def fresh_dat_state():
    dattool._stop.set()
    for _ in range(200):
        job = dattool.STATE["job"]
        if not job or job["state"] != "running":
            break
        time.sleep(0.01)
    dattool.STATE.update(dat=None, job=None, report=None)
    dattool._stop.clear()
    yield
    dattool._stop.set()


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def zip_with(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def wait(client):
    for _ in range(500):
        data = client.get("/api/dat", headers=LOCAL).get_json()
        job = data["job"]
        if job and job["state"] != "running":
            return data
        time.sleep(0.01)
    raise AssertionError("DAT job did not finish")


def load(client, path):
    r = client.post("/api/dat/load", headers=LOCAL, json={"path": str(path)})
    assert r.status_code == 200, r.get_json()
    data = wait(client)
    assert data["job"]["state"] == "done", data["job"]
    return data


def compare(client, mode="none"):
    r = client.post("/api/dat/compare", headers=LOCAL, json={"hash": mode})
    assert r.status_code == 200, r.get_json()
    data = wait(client)
    assert data["job"]["state"] == "done", data["job"]
    return data


def report(client, **args):
    r = client.get("/api/dat/report", headers=LOCAL, query_string=args)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def rows_by_file(rep):
    return {r["file"] or r["dat"]: r for r in rep["rows"]}


# --- parsing ------------------------------------------------------------------------

def test_reads_a_logiqx_dat(tmp_path):
    dat = read_dat(str(write(tmp_path / "t.dat", LOGIQX)))
    assert dat.fmt == "logiqx" and dat.title == "Test - Super Console"
    assert dat.info()["games"] == 5 and dat.info()["clones"] == 1 and dat.info()["bios"] == 1
    alpha = dat.games["alpha (europe)"]
    assert alpha.roms[0].crc == crc(ALPHA) and alpha.roms[0].size == len(ALPHA)
    assert dat.games["charlie (japan)"].roms[0].baddump
    assert dat.find("Alpha (Europe).zip") is alpha            # archive named after the game
    assert dat.find("Alpha (Europe).sfc") is alpha            # loose ROM named like its file
    assert dat.find("Nope.sfc") is None


def test_reads_a_mame_listxml_without_devices(tmp_path):
    dat = read_dat(str(write(tmp_path / "mame.xml", LISTXML)))
    assert dat.fmt == "listxml" and "z80" not in dat.games
    assert dat.games["pacman"].desc == "Pac-Man (Midway)"
    puck = dat.games["puckman"]
    assert puck.cloneof == "pacman" and not puck.roms[0].required     # merged ROM lives in the parent
    kinst = dat.games["kinst"]
    assert kinst.disks == ["kinst"] and not kinst.playable
    assert dat.games["neogeo"].bios


def test_reads_a_clrmamepro_text_dat(tmp_path):
    dat = read_dat(str(write(tmp_path / "t.dat", CMP)))
    assert dat.fmt == "clrmamepro" and dat.title == "Test - Text DAT"
    assert dat.games["bravo (usa)"].desc == 'Bravo "the" game'
    assert dat.games["bravo (usa)"].roms[0].crc == crc(BRAVO)        # upper case CRC accepted
    assert dat.games["neogeo"].bios


@pytest.mark.parametrize("content", ["not a dat at all )", "<html><body>nope</body></html>", "<datafile><game"])
def test_refuses_what_is_not_a_dat(tmp_path, content):
    with pytest.raises(DatError):
        read_dat(str(write(tmp_path / "x.dat", content)))


# --- the system folder ---------------------------------------------------------------

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./Alpha (Europe).zip</path><name>alpha</name></game>
  <game><path>./bravo_renamed.sfc</path><name>bravo</name></game>
  <game><path>./Charlie (Japan).sfc</path><name>charlie</name></game>
  <game><path>./Delta (World).zip</path><name>delta</name></game>
  <game><path>./homebrew.sfc</path><name>Homebrew</name></game>
</gameList>
"""


@pytest.fixture
def snes(tmp_path):
    root = tmp_path / "roms" / "snes"
    (root / "images").mkdir(parents=True)
    write(root / "gamelist.xml", GAMELIST)
    zip_with(root / "Alpha (Europe).zip", {"Alpha (Europe).sfc": ALPHA})
    (root / "bravo_renamed.sfc").write_bytes(BRAVO)
    (root / "Charlie (Japan).sfc").write_bytes(CHARLIE)
    zip_with(root / "Delta (World).zip", {"Delta (World).sfc": b"wrong content"})
    (root / "homebrew.sfc").write_bytes(b"home")
    (root / "images" / "Alpha (Europe).sfc").write_bytes(b"not a rom: media folder")
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    yield root
    xml_store.close_gamelist()


def snapshot_files(root):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file() and p.suffix != ".xml"}


def test_load_by_upload_and_by_path(client, snes, tmp_path):
    dat_path = write(tmp_path / "t.dat", LOGIQX)
    r = client.post("/api/dat/load", headers=LOCAL, data={"file": (io.BytesIO(LOGIQX.encode()), "Super.dat")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    data = wait(client)
    assert data["job"]["state"] == "done" and data["dat"], data
    assert data["dat"]["games"] == 5 and data["dat"]["source"] == "Super.dat"
    assert not [p for p in os.listdir(dattool.tempfile.gettempdir()) if p.startswith("gme-dat-")]   # upload removed
    data = load(client, dat_path)
    assert data["dat"]["title"] == "Test - Super Console"
    bad = client.post("/api/dat/load", headers=LOCAL, json={"path": str(tmp_path / "missing.dat")})
    assert bad.status_code == 404
    other = write(tmp_path / "t.txt", LOGIQX)
    assert client.post("/api/dat/load", headers=LOCAL, json={"path": str(other)}).status_code == 400


def test_a_broken_dat_is_an_error_and_keeps_the_previous_one(client, snes, tmp_path):
    load(client, write(tmp_path / "t.dat", LOGIQX))
    client.post("/api/dat/load", headers=LOCAL, json={"path": str(write(tmp_path / "bad.dat", "<datafile><game"))})
    data = wait(client)
    assert data["job"]["state"] == "error" and data["job"]["error"]
    assert data["dat"]["title"] == "Test - Super Console"


def test_compare_by_name_only_reads_no_rom(client, snes, tmp_path, monkeypatch):
    load(client, write(tmp_path / "t.dat", LOGIQX))
    opened = []
    monkeypatch.setattr(dattool, "_crc_file", lambda *a: opened.append(a) or (None, None))
    compare(client, "none")
    assert not opened
    rows = rows_by_file(report(client))
    assert rows["Alpha (Europe).zip"]["status"] == "ok"
    assert rows["Delta (World).zip"]["status"] == "ok"           # name only: content not checked
    assert rows["bravo_renamed.sfc"]["status"] == "unknown"
    assert rows["homebrew.sfc"]["status"] == "unknown"
    assert rows["Bravo (USA)"]["status"] == "missing"
    assert "Alpha (Europe).sfc" not in rows                       # images/ is not a ROM folder


def test_compare_with_crc_finds_renamed_and_bad_dumps(client, snes, tmp_path):
    load(client, write(tmp_path / "t.dat", LOGIQX))
    before = snapshot_files(snes)
    data = compare(client, "crc")
    assert data["report"]["counts"]["renamed"] == 1
    rep = report(client)
    rows = rows_by_file(rep)
    assert rows["Alpha (Europe).zip"]["status"] == "ok"           # CRC read from the zip index
    assert rows["bravo_renamed.sfc"]["status"] == "renamed"
    assert rows["bravo_renamed.sfc"]["dat"] == "Bravo (USA)" and "clone" in rows["bravo_renamed.sfc"]["flags"]
    assert rows["Charlie (Japan).sfc"]["status"] == "bad"         # the DAT marks it as a bad dump
    assert rows["Delta (World).zip"]["status"] == "bad"           # content differs
    assert rows["homebrew.sfc"]["status"] == "unknown"
    assert rows["[BIOS] Console"]["status"] == "missing"
    assert "Bravo (USA)" not in rows                              # found under its other name
    assert snapshot_files(snes) == before                          # ROM files untouched


def test_report_filters_and_csv(client, snes, tmp_path):
    load(client, write(tmp_path / "t.dat", LOGIQX))
    compare(client, "crc")
    assert report(client)["counts"]["missing"] == 1
    assert report(client, hide_bios=1)["counts"]["missing"] == 0
    assert report(client, hide_clones=1)["counts"]["renamed"] == 0
    only_bad = report(client, status="bad")
    assert only_bad["total"] == 2 and {r["status"] for r in only_bad["rows"]} == {"bad"}
    csv = client.get("/api/dat/report", headers=LOCAL, query_string={"format": "csv"})
    assert csv.status_code == 200 and "text/csv" in csv.content_type
    text = csv.get_data(as_text=True)
    assert "bravo_renamed.sfc" in text and "Bravo (USA)" in text


def test_arcade_romsets_against_a_mame_list(client, tmp_path):
    root = tmp_path / "roms" / "mame"
    root.mkdir(parents=True)
    write(root / "gamelist.xml", '<?xml version="1.0"?><gameList><game><path>./pacman.zip</path><name>pacman</name></game></gameList>')
    zip_with(root / "pacman.zip", {"pm1": PAC1, "pm2": PAC2})
    zip_with(root / "puckman.zip", {"other": b"x"})              # split clone: its own ROMs only (none here)
    zip_with(root / "kinst.zip", {"ki.u98": b"oops"})
    zip_with(root / "mspacman.zip", {"pm1": PAC1})
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    try:
        load(client, write(tmp_path / "mame.xml", LISTXML))
        compare(client, "crc")
        rows = rows_by_file(report(client))
        assert rows["pacman.zip"]["status"] == "ok" and rows["pacman.zip"]["desc"] == "Pac-Man (Midway)"
        assert rows["puckman.zip"]["status"] == "ok"               # merged ROMs are not required
        assert rows["kinst.zip"]["status"] == "bad"
        assert {"chd_missing", "not_playable"} <= set(rows["kinst.zip"]["flags"])
        assert rows["mspacman.zip"]["status"] == "unknown"
        assert rows["neogeo"]["status"] == "missing" and "bios" in rows["neogeo"]["flags"]
        (root / "pacman.zip").unlink()
        zip_with(root / "pacman.zip", {"pm1": PAC1})
        compare(client, "crc")
        assert rows_by_file(report(client))["pacman.zip"]["status"] == "incomplete"
    finally:
        xml_store.close_gamelist()


def test_sha1_mode_reads_contents(client, snes, tmp_path):
    import hashlib
    text = LOGIQX.replace(f'crc="{crc(ALPHA)}"', f'crc="{crc(ALPHA)}" sha1="{hashlib.sha1(ALPHA).hexdigest()}"')
    load(client, write(tmp_path / "t.dat", text))
    compare(client, "sha1")
    assert rows_by_file(report(client))["Alpha (Europe).zip"]["status"] == "ok"


def test_compare_needs_a_dat_and_a_report_needs_a_compare(client, snes):
    assert client.post("/api/dat/compare", headers=LOCAL, json={}).status_code == 400
    assert client.get("/api/dat/report", headers=LOCAL).status_code == 404


def test_stop_ends_a_hashing_job(client, snes, tmp_path, monkeypatch):
    load(client, write(tmp_path / "t.dat", LOGIQX))
    real = dattool._crc_file

    def slow(*args):
        time.sleep(0.05)
        return real(*args)
    monkeypatch.setattr(dattool, "_crc_file", slow)
    client.post("/api/dat/compare", headers=LOCAL, json={"hash": "crc"})
    client.post("/api/dat/stop", headers=LOCAL)
    data = wait(client)
    assert data["job"]["state"] == "stopped" and data["report"] is None


def test_report_belongs_to_the_gamelist_it_was_made_for(client, snes, tmp_path):
    load(client, write(tmp_path / "t.dat", LOGIQX))
    compare(client)
    xml_store.set_gamelist_path(str(snes / "gamelist.xml"))       # reopened: new session
    assert client.get("/api/dat/report", headers=LOCAL).status_code == 404


# --- names from the DAT (Edit in bulk › Names) ------------------------------------------

ALL = ["./Alpha (Europe).zip", "./bravo_renamed.sfc", "./Charlie (Japan).sfc", "./Delta (World).zip", "./homebrew.sfc"]


def names(root):
    return {g.findtext("path"): g.findtext("name") for g in etree.parse(str(root / "gamelist.xml")).getroot()}


def test_names_from_the_dat_with_preview_backup_and_undo(client, snes, tmp_path):
    load(client, write(tmp_path / "t.dat", LOGIQX))
    op = {"kind": "dat_name", "strip_tags": False}
    before = (snes / "gamelist.xml").read_bytes()
    r = client.post("/api/bulk/preview", headers=LOCAL, json={"paths": ALL, "op": op})
    data = r.get_json()
    assert r.status_code == 200 and data["total"] == 3                # bravo is unknown by name, homebrew too
    assert (snes / "gamelist.xml").read_bytes() == before
    compare(client, "crc")                                             # now bravo is matched by content
    data = client.post("/api/bulk/preview", headers=LOCAL, json={"paths": ALL, "op": op}).get_json()
    assert data["total"] == 4
    res = client.post("/api/bulk", headers=LOCAL, json={"paths": ALL, "op": op}).get_json()
    assert res["changed"] == 4 and res["snapshot"]
    n = names(snes)
    assert n["./bravo_renamed.sfc"] == "Bravo (USA)" and n["./homebrew.sfc"] == "Homebrew"
    assert (snes / "bravo_renamed.sfc").exists()                       # the file keeps its name
    r = client.post("/api/backups/restore", headers=LOCAL, json={"id": res["snapshot"]})
    assert r.status_code == 200
    assert names(snes)["./bravo_renamed.sfc"] == "bravo"


def test_names_from_a_mame_list_can_drop_tags(client, tmp_path):
    root = tmp_path / "roms" / "mame"
    root.mkdir(parents=True)
    write(root / "gamelist.xml", '<?xml version="1.0"?><gameList><game><path>./pacman.zip</path><name>pacman</name></game>'
          '<game><path>./unknown.zip</path><name>unknown</name></game></gameList>')
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    try:
        load(client, write(tmp_path / "mame.xml", LISTXML))
        paths = ["./pacman.zip", "./unknown.zip"]
        data = client.post("/api/bulk/preview", headers=LOCAL,
                           json={"paths": paths, "op": {"kind": "dat_name", "strip_tags": False}}).get_json()
        assert [c["after"] for c in data["changes"]] == ["Pac-Man (Midway)"]
        data = client.post("/api/bulk/preview", headers=LOCAL,
                           json={"paths": paths, "op": {"kind": "dat_name", "strip_tags": True}}).get_json()
        assert [c["after"] for c in data["changes"]] == ["Pac-Man"]
    finally:
        xml_store.close_gamelist()


def test_names_from_the_dat_need_a_dat(client, snes):
    r = client.post("/api/bulk/preview", headers=LOCAL, json={"paths": ALL, "op": {"kind": "dat_name"}})
    assert r.status_code == 400 and r.get_json()["code"] == "dat_none_loaded"


# --- new gamelist from a ROM folder ------------------------------------------------------

@pytest.fixture
def new_folder(tmp_path):
    root = tmp_path / "roms" / "snes"
    (root / "images").mkdir(parents=True)
    (root / "USA").mkdir()
    (root / "Super Game (Europe) [!].sfc").write_bytes(b"1")
    (root / "Other.smc").write_bytes(b"2")
    (root / "USA" / "Third (USA).zip").write_bytes(b"3")
    (root / "readme.txt").write_text("not a rom")
    (root / "notes.bin").write_bytes(b"bin is not a SNES extension")
    (root / "images" / "Other.png").write_bytes(b"png")
    (root / "images" / "Other.smc").write_bytes(b"media folder")
    return root


def test_new_gamelist_preview_uses_the_system_extensions(client, new_folder):
    r = client.post("/api/new-gamelist/preview", headers=LOCAL, json={"folder": str(new_folder)})
    data = r.get_json()
    assert r.status_code == 200 and data["system"] == "snes" and "sfc" in data["exts"]
    assert sorted(x["path"] for x in data["roms"]) == ["./Other.smc", "./Super Game (Europe) [!].sfc", "./USA/Third (USA).zip"]
    assert not data["exists"]
    assert not (new_folder / "gamelist.xml").exists()                 # a preview writes nothing
    tagged = client.post("/api/new-gamelist/preview", headers=LOCAL,
                         json={"folder": str(new_folder), "strip_tags": True}).get_json()
    assert "Super Game" in [x["name"] for x in tagged["roms"]]
    custom = client.post("/api/new-gamelist/preview", headers=LOCAL,
                         json={"folder": str(new_folder), "exts": ".bin, smc"}).get_json()
    assert sorted(x["path"] for x in custom["roms"]) == ["./Other.smc", "./notes.bin"]
    bad = client.post("/api/new-gamelist/preview", headers=LOCAL, json={"folder": str(new_folder), "exts": "x/y"})
    assert bad.status_code == 400
    missing = client.post("/api/new-gamelist/preview", headers=LOCAL, json={"folder": str(new_folder / "nope")})
    assert missing.status_code == 404


def test_new_gamelist_is_written_and_opened(client, new_folder):
    before = snapshot_files(new_folder)
    r = client.post("/api/new-gamelist", headers=LOCAL, json={"folder": str(new_folder), "strip_tags": True})
    data = r.get_json()
    assert r.status_code == 200 and data["created"] == 3 and data["count"] == 3
    assert xml_store.XML_PATH == str(new_folder / "gamelist.xml") and data["session_id"] == xml_store.SESSION_ID
    n = names(new_folder)
    assert n == {"./Other.smc": "Other", "./Super Game (Europe) [!].sfc": "Super Game", "./USA/Third (USA).zip": "Third"}
    assert snapshot_files(new_folder) == before                        # ROM files untouched
    again = client.post("/api/new-gamelist", headers=LOCAL, json={"folder": str(new_folder)})
    assert again.status_code == 409                                    # never replaces a gamelist
    xml_store.close_gamelist()


def test_new_gamelist_refuses_an_empty_folder(client, tmp_path):
    empty = tmp_path / "roms" / "nes"
    empty.mkdir(parents=True)
    r = client.post("/api/new-gamelist", headers=LOCAL, json={"folder": str(empty)})
    assert r.status_code == 400 and not (empty / "gamelist.xml").exists()


def test_browse_tells_whether_the_folder_has_a_gamelist(client, new_folder):
    data = client.get("/api/browse", headers=LOCAL, query_string={"path": str(new_folder)}).get_json()
    assert data["has_gamelist"] is False
    (new_folder / "gamelist.xml").write_text("<gameList/>")
    data = client.get("/api/browse", headers=LOCAL, query_string={"path": str(new_folder)}).get_json()
    assert data["has_gamelist"] is True
