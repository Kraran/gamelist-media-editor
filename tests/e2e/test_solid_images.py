"""Edit in bulk › Solid images: preview with thumbnails and colours, tags only by
default, files to the Recycle Bin only when asked, confirmed and unused elsewhere."""
import os

import pytest
from lxml import etree
from PIL import Image

from gme import solidimages, xml_store

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><image>./images/red.png</image><marquee>./images/art.png</marquee></game>
  <game><path>./bravo.zip</path><name>Bravo</name><image>./images/art.png</image><wheel>./images/clear.png</wheel></game>
  <game><path>./charlie.zip</path><name>Charlie</name><image>./images/black.png</image><thumbnail>./images/red.png</thumbnail></game>
  <game><path>./delta.zip</path><name>Delta</name><image>./images/black.png</image></game>
</gameList>
"""


@pytest.fixture
def gamelist(tmp_path, trashed):
    xml = tmp_path / "roms" / "vc4000" / "gamelist.xml"
    img = xml.parent / "images"
    img.mkdir(parents=True)
    Image.new("RGB", (200, 150), (200, 10, 10)).save(str(img / "red.png"))
    Image.new("RGB", (100, 100), (0, 0, 0)).save(str(img / "black.png"))
    Image.new("RGBA", (300, 100), (0, 0, 0, 0)).save(str(img / "clear.png"))
    art = Image.new("RGB", (120, 90))
    art.putdata([(x * 2, y * 2, 120) for y in range(90) for x in range(120)])
    art.save(str(img / "art.png"))
    for rom in ("alpha", "bravo", "charlie", "delta"):
        (xml.parent / f"{rom}.zip").write_bytes(b"rom")
    xml.write_text(GAMELIST, encoding="utf-8")
    solidimages._cache.clear()
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


def tags(xml):
    return [[c.tag for c in g if c.tag not in ("path", "name")] for g in etree.parse(str(xml)).getroot().findall("game")]


def open_solid(page):
    page.click("#btn-actions")
    page.click("#btn-bulk")
    page.wait_for_selector("#bulk-modal.open")
    page.click('[data-bulk-tab="solid"]')
    page.wait_for_selector("#bulk-solid-files")


def run_preview(page):
    page.click("#bulk-preview-btn")
    page.wait_for_selector("#bulk-preview .bulk-summary")


def test_tags_only_by_default_then_undo(page, gamelist, trashed):
    open_solid(page)
    assert not page.is_checked("#bulk-solid-files")
    assert page.locator("[data-bulk-solid]").count() > 5 and page.locator('[data-bulk-solid="video"]').count() == 0
    run_preview(page)
    assert page.locator("#bulk-preview tbody tr").count() == 5
    body = page.inner_text("#bulk-preview")
    assert "#c80a0a" in body and "#000000" in body and "transparente" in body and "art.png" not in body
    page.wait_for_function("[...document.querySelectorAll('.solid-thumb img')].every(i => i.complete && i.naturalWidth)")
    assert page.inner_text("#bulk-apply-label") == "Appliquer (5)"
    page.click("#bulk-apply")
    page.wait_for_selector("#confirm-modal.open")
    assert page.evaluate("document.activeElement.id") == "confirm-cancel"
    assert "Corbeille" not in page.inner_text("#confirm-body")
    page.click("#confirm-ok")
    page.wait_for_selector("#toast.show .toast-action")
    assert tags(gamelist) == [["marquee"], ["image"], [], []]
    assert trashed == [] and (gamelist.parent / "images" / "red.png").exists()
    page.click("#toast .toast-action")
    page.wait_for_function("document.getElementById('toast').textContent.includes('Annulé')")
    assert tags(gamelist) == [["image", "marquee"], ["image", "wheel"], ["image", "thumbnail"], ["image"]]


def test_delete_files_is_confirmed_and_keeps_shared_files(page, gamelist, trashed):
    page.click("#game-list .game-item >> nth=0", modifiers=["Control"])
    page.click("#game-list .game-item >> nth=1", modifiers=["Control"])
    page.click("#game-list .game-item >> nth=2", modifiers=["Control"])
    open_solid(page)
    assert page.input_value("#bulk-scope") == "checked"
    page.check("#bulk-solid-files")
    assert "btn-danger" in page.get_attribute("#bulk-apply", "class")
    run_preview(page)
    body = page.inner_text("#bulk-preview")
    assert "2 fichier(s) à envoyer à la Corbeille" in body                 # red.png, clear.png
    assert "./images/black.png" in body and "utilisé par une autre balise" in body   # Delta still uses it
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "solid-images-preview.png"))
    page.click("#bulk-apply")
    page.wait_for_selector("#confirm-modal.open")
    confirm = page.inner_text("#confirm-body")
    assert "supprimés du disque" in confirm and "pas les fichiers" in confirm
    assert page.inner_text("#confirm-ok") == "Retirer et supprimer 2 fichier(s)"
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "solid-images-confirm.png"))
    page.click("#confirm-cancel")
    page.wait_for_timeout(200)
    assert trashed == [] and tags(gamelist)[0] == ["image", "marquee"]
    page.click("#bulk-apply")
    page.wait_for_selector("#confirm-modal.open")
    page.click("#confirm-ok")
    page.wait_for_selector("#toast.show .toast-action")
    assert "Corbeille" in page.inner_text("#toast")
    assert sorted(p.replace("\\", "/").rsplit("/", 1)[-1] for p in trashed) == ["clear.png", "red.png"]
    assert (gamelist.parent / "images" / "black.png").exists() and (gamelist.parent / "images" / "art.png").exists()
    assert all((gamelist.parent / f"{r}.zip").exists() for r in ("alpha", "bravo", "charlie", "delta"))
    assert tags(gamelist) == [["marquee"], ["image"], [], ["image"]]
