"""Confirmations, deletion, replaced pictures: nothing lost by a stray key, nothing stale on screen."""
import io

import pytest
from lxml import etree
from PIL import Image

pytestmark = pytest.mark.e2e


def png(size, color):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def open_game(page, n=0, name="Alpha"):
    page.click(f"#game-list .game-item >> nth={n}")
    page.wait_for_function(f"document.getElementById('game-name-input').value === '{name}'")


def with_region(gamelist, page):
    xml = gamelist.read_text(encoding="utf-8").replace("<name>Alpha</name>", "<name>Alpha</name><region>eu</region>", 1)
    gamelist.write_text(xml, encoding="utf-8")
    page.reload()
    page.wait_for_selector("#game-list .game-item")


def test_enter_on_cancel_cancels(page, gamelist):
    with_region(gamelist, page)
    page.click("#btn-actions")
    page.click("#btn-purge-regions")
    page.wait_for_selector("#confirm-modal.open")
    assert page.evaluate("document.activeElement.id") == "confirm-cancel"
    page.keyboard.press("Enter")
    page.wait_for_function("!document.getElementById('confirm-modal').classList.contains('open')")
    page.wait_for_timeout(300)
    assert "<region>eu</region>" in gamelist.read_text(encoding="utf-8")


def test_enter_on_dont_save_does_not_save(page, gamelist):
    open_game(page)
    page.fill("#meta-developer", "Typo Studio")
    page.click("#game-list .game-item >> nth=1")
    page.wait_for_selector("#confirm-modal.open")
    page.focus("#confirm-extra")
    page.keyboard.press("Enter")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Bravo'")
    assert "Typo Studio" not in gamelist.read_text(encoding="utf-8")


def test_purge_clears_the_open_game(page, gamelist):
    with_region(gamelist, page)
    open_game(page)
    assert page.input_value("#meta-region") == "eu"
    page.click("#btn-actions")
    page.click("#btn-purge-regions")
    page.wait_for_selector("#confirm-modal.open")
    page.click("#confirm-ok")
    page.wait_for_function("document.getElementById('meta-region').value === ''")
    assert page.is_hidden("#save-bar")


def test_delete_lists_the_files_and_keeps_shared_ones(page, gamelist, trashed):
    folder = gamelist.parent
    (folder / "images").mkdir()
    (folder / "images" / "box.png").write_bytes(png((30, 40), (200, 0, 0)))
    xml = gamelist.read_text(encoding="utf-8")
    for name in ("Alpha", "Bravo"):
        xml = xml.replace(f"<name>{name}</name>", f"<name>{name}</name><boxart>./images/box.png</boxart>", 1)
    gamelist.write_text(xml, encoding="utf-8")
    page.reload()
    open_game(page)
    page.click("#btn-game-menu")
    page.click("#btn-delete-game")
    page.wait_for_selector("#confirm-modal.open")
    body = page.inner_text("#confirm-body")
    assert "./alpha.zip" in body and "./images/box.png" in body and "Gardés" in body
    assert page.is_checked("#delete-trash")
    page.click("#confirm-ok")
    page.wait_for_function("document.querySelectorAll('#game-list .game-item').length === 2")
    assert [p.replace("\\", "/").rsplit("/", 1)[-1] for p in trashed] == ["alpha.zip"]
    assert (folder / "images" / "box.png").exists()
    assert "Corbeille" in page.inner_text("#toast")
    bravo = etree.parse(str(gamelist)).getroot().find("game")
    assert bravo.findtext("boxart") == "./images/box.png"


def test_replaced_picture_is_shown(page, gamelist):
    folder = gamelist.parent
    (folder / "images").mkdir()
    (folder / "images" / "alpha-image.png").write_bytes(png((64, 48), (200, 0, 0)))
    gamelist.write_text(gamelist.read_text(encoding="utf-8").replace(
        "<name>Alpha</name>", "<name>Alpha</name><image>./images/alpha-image.png</image>", 1), encoding="utf-8")
    page.reload()
    open_game(page)
    page.wait_for_function("document.querySelector('.media-tile[data-field=image] img').naturalWidth === 64")
    page.evaluate("document.getElementById('media-file-input').dataset.field = 'image'")
    page.set_input_files("#media-file-input", {"name": "new.png", "mimeType": "image/png",
                                                "buffer": png((100, 50), (0, 200, 0))})
    page.wait_for_function("document.querySelector('.media-tile[data-field=image] img').naturalWidth === 100")
    assert page.inner_text(".media-tile[data-field=image] .tile-file") == "alpha-image.png"   # same name
    page.wait_for_function("document.querySelector('#gi-0 .gi-thumb img').src.includes('&v=')")
