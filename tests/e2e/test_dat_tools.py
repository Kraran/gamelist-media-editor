"""DAT tool, names from a DAT (Edit in bulk › Names) and a new gamelist from a ROM folder."""
import os
import time
import zipfile
import zlib

import pytest
from lxml import etree

from gme import dattool, xml_store

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")          # folder for documentation screenshots (optional)

ALPHA, BRAVO, CHARLIE = b"alpha-rom" * 50, b"bravo-rom" * 70, b"charlie" * 30


def crc(data):
    return "%08x" % (zlib.crc32(data) & 0xFFFFFFFF)


DAT = f"""<?xml version="1.0"?>
<datafile>
  <header><name>Nintendo - Super Nintendo Entertainment System (test)</name></header>
  <game name="Alpha Quest (Europe)"><description>Alpha Quest (Europe)</description>
    <rom name="Alpha Quest (Europe).sfc" size="{len(ALPHA)}" crc="{crc(ALPHA)}"/></game>
  <game name="Bravo Racing (USA)" cloneof="Alpha Quest (Europe)"><description>Bravo Racing (USA)</description>
    <rom name="Bravo Racing (USA).sfc" size="{len(BRAVO)}" crc="{crc(BRAVO)}"/></game>
  <game name="Charlie Land (Japan)"><description>Charlie Land (Japan)</description>
    <rom name="Charlie Land (Japan).sfc" size="10" crc="12345678"/></game>
  <game name="Delta Force (World)"><description>Delta Force (World)</description>
    <rom name="Delta Force (World).sfc" size="10" crc="87654321"/></game>
  <game name="[BIOS] Satellaview (Japan)" isbios="yes"><description>[BIOS] Satellaview (Japan)</description>
    <rom name="bios.bin" size="4" crc="deadbeef"/></game>
</datafile>
"""
GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./Alpha Quest (Europe).zip</path><name>alpha</name></game>
  <game><path>./bravo.sfc</path><name>bravo</name></game>
  <game><path>./Charlie Land (Japan).sfc</path><name>charlie</name></game>
  <game><path>./homebrew.sfc</path><name>My Homebrew</name></game>
</gameList>
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


@pytest.fixture
def gamelist(tmp_path):
    xml = tmp_path / "roms" / "snes" / "gamelist.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(GAMELIST, encoding="utf-8")
    with zipfile.ZipFile(xml.parent / "Alpha Quest (Europe).zip", "w") as z:
        z.writestr("Alpha Quest (Europe).sfc", ALPHA)
    (xml.parent / "bravo.sfc").write_bytes(BRAVO)
    (xml.parent / "Charlie Land (Japan).sfc").write_bytes(CHARLIE)
    (xml.parent / "homebrew.sfc").write_bytes(b"home")
    (tmp_path / "snes-test.dat").write_text(DAT, encoding="utf-8")
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


def xml_names(xml):
    return {g.findtext("path"): g.findtext("name") for g in etree.parse(str(xml)).getroot().findall("game")}


def rom_bytes(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file() and p.suffix != ".xml" and ".bak" not in p.name}


def chip(page, status):
    return int(page.inner_text(f'[data-dat-status="{status}"] strong'))


def test_dat_tool_compares_by_crc_then_names_come_from_the_dat(page, gamelist, tmp_path):
    before = rom_bytes(gamelist.parent)
    page.click("#btn-actions")
    page.click("#btn-dat-tool")
    page.wait_for_selector("#dat-modal.open")
    page.wait_for_function("document.getElementById('dat-source').textContent.includes('Aucun DAT')")
    assert page.is_disabled("#dat-compare")
    page.set_input_files("#dat-file", str(tmp_path / "snes-test.dat"))
    page.wait_for_function("document.getElementById('dat-source').textContent.includes('5 jeux')")
    page.select_option("#dat-hash", "crc")
    assert "index" in page.inner_text("#dat-hash-hint")
    page.click("#dat-compare")
    page.wait_for_selector(".dat-chips")
    assert chip(page, "ok") == 1 and chip(page, "renamed") == 1 and chip(page, "bad") == 1
    assert chip(page, "unknown") == 1 and chip(page, "missing") == 2
    assert page.locator("#dat-report tbody tr").count() == 6
    page.click('[data-dat-status="renamed"]')
    page.wait_for_function("document.querySelectorAll('#dat-report tbody tr').length === 1")
    assert "Bravo Racing (USA)" in page.inner_text("#dat-report tbody")
    page.click('[data-dat-status="renamed"]')                     # same chip again: every status
    page.wait_for_function("document.querySelectorAll('#dat-report tbody tr').length === 6")
    page.check('[data-dat-filter="bios"]')
    page.wait_for_function("document.querySelector('[data-dat-status=\"missing\"] strong').textContent === '1'")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "dat-tool-report.png"))

    page.click("#dat-names")
    page.wait_for_selector("#bulk-modal.open")
    assert page.input_value("#bulk-scope") == "all"
    assert page.is_checked('input[name="bulk-name-src"][value="dat"]')
    page.wait_for_function("document.getElementById('bulk-dat-info').textContent.includes('5 jeux')")
    page.click("#bulk-preview-btn")
    page.wait_for_selector("#bulk-preview .bulk-summary")
    assert page.locator("#bulk-preview tbody tr").count() == 3       # homebrew is not in the DAT
    assert "Bravo Racing (USA)" in page.inner_text("#bulk-preview")
    page.click("#bulk-apply")
    page.wait_for_selector("#toast.show .toast-action")
    names = xml_names(gamelist)
    assert names["./bravo.sfc"] == "Bravo Racing (USA)" and names["./homebrew.sfc"] == "My Homebrew"
    page.click("#toast .toast-action")
    page.wait_for_function("document.getElementById('toast').textContent.includes('restaur')")
    assert xml_names(gamelist)["./bravo.sfc"] == "bravo"
    assert rom_bytes(gamelist.parent) == before                    # ROM files untouched
    assert (gamelist.parent / "bravo.sfc").exists()


def test_names_tab_loads_a_mame_list_by_path(page, gamelist, tmp_path):
    mame = tmp_path / "mame.xml"
    mame.write_text('<?xml version="1.0"?><mame build="0.270"><machine name="homebrew"><description>Homebrew Hero (bootleg)</description></machine></mame>',
                    encoding="utf-8")
    page.click("#btn-actions")
    page.click("#btn-bulk")
    page.wait_for_selector("#bulk-modal.open")
    page.click('[data-bulk-tab="reset_name"]')
    page.check('input[name="bulk-name-src"][value="dat"]')
    page.wait_for_function("document.getElementById('bulk-dat-info').textContent.includes('Aucun DAT')")
    page.fill("#bulk-dat-path", str(mame))
    page.click("#bulk-dat-path-load")
    page.wait_for_function("document.getElementById('bulk-dat-info').textContent.includes('MAME 0.270')")
    page.select_option("#bulk-scope", "all")
    page.check("#bulk-name-tags")
    page.click("#bulk-preview-btn")
    page.wait_for_selector("#bulk-preview .bulk-summary")
    assert page.locator("#bulk-preview tbody tr").count() == 1
    assert "Homebrew Hero" in page.inner_text("#bulk-preview .bulk-after")
    assert "bootleg" not in page.inner_text("#bulk-preview .bulk-after")


def test_create_a_gamelist_from_a_rom_folder(page, gamelist, tmp_path):
    folder = tmp_path / "roms" / "megadrive"
    (folder / "images").mkdir(parents=True)
    for name in ("Sonic (Europe).md", "Streets (USA) [!].bin", "Columns.zip"):
        (folder / name).write_bytes(b"rom")
    (folder / "readme.txt").write_text("no")
    (folder / "images" / "Sonic (Europe).md").write_bytes(b"media folder")
    before = rom_bytes(folder)
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")
    page.evaluate("p => browseDirectory(p)", str(folder))
    page.wait_for_function("!document.getElementById('open-gl-new').hidden")
    assert "Créer un gamelist ici" in page.inner_text("#open-gl-new")
    page.click("#open-gl-new")
    page.wait_for_selector("#newgl-modal.open")
    page.wait_for_selector("#newgl-preview .bulk-summary")
    assert "md" in page.input_value("#newgl-exts")
    assert page.locator("#newgl-preview tbody tr").count() == 3
    page.check("#newgl-tags")
    assert page.is_disabled("#newgl-create")                        # a change drops the preview
    page.click("#newgl-preview-btn")
    page.wait_for_selector("#newgl-preview .bulk-summary")
    names = page.locator("#newgl-preview tbody td:nth-child(2)").all_inner_texts()
    assert names == ["Columns", "Sonic", "Streets"]
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "new-gamelist.png"))
    page.click("#newgl-create")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 3")
    assert not page.is_visible("#newgl-modal")
    assert xml_store.XML_PATH == str(folder / "gamelist.xml")
    assert sorted(xml_names(folder / "gamelist.xml").values()) == ["Columns", "Sonic", "Streets"]
    assert rom_bytes(folder) == before


def test_a_folder_with_a_gamelist_offers_to_add_the_missing_roms(page, gamelist):
    (gamelist.parent / "Extra Game (USA).sfc").write_bytes(b"new")
    page.click("#btn-open-gamelist")
    page.wait_for_selector("#open-gamelist-modal.open")
    page.evaluate("p => browseDirectory(p)", str(gamelist.parent))
    page.wait_for_function("document.getElementById('open-gl-new-label').textContent.includes('manquantes')")
    page.click("#open-gl-new")
    page.wait_for_selector("#check-modal.open")
    page.wait_for_function("document.getElementById('check-body').textContent.includes('Extra Game (USA)')")
