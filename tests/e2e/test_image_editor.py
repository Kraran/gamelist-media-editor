"""Image editor (tile button) and Edit in bulk › Images, in the browser."""
import io
import os

import pytest
from lxml import etree
from PIL import Image, ImageDraw

from gme import xml_store
from tests.e2e.conftest import wait_until

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><image>./images/alpha-image.png</image><wheel>./images/alpha-wheel.png</wheel><video>./videos/alpha.mp4</video></game>
  <game><path>./bravo.zip</path><name>Bravo</name><image>./images/bravo-image.png</image></game>
  <game><path>./charlie.zip</path><name>Charlie</name></game>
</gameList>
"""


def logo(size, box, bg=(255, 255, 255)):
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    d.rectangle(box, fill=(200, 40, 40))
    d.rectangle((box[0] + 6, box[1] + 6, box[0] + 16, box[1] + 16), fill=(250, 250, 250))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def gamelist(tmp_path):
    root = tmp_path / "roms" / "snes"
    (root / "images").mkdir(parents=True)
    (root / "videos").mkdir()
    xml = root / "gamelist.xml"
    xml.write_text(GAMELIST, encoding="utf-8")
    for rom in ("alpha", "bravo", "charlie"):
        (root / f"{rom}.zip").write_bytes(b"rom")
    (root / "images" / "alpha-image.png").write_bytes(logo((320, 200), (40, 30, 279, 169)))
    (root / "images" / "alpha-wheel.png").write_bytes(logo((300, 100), (30, 20, 269, 79)))
    (root / "images" / "bravo-image.png").write_bytes(logo((400, 300), (10, 10, 389, 289)))
    (root / "videos" / "alpha.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


def size_of(path):
    with Image.open(path) as im:
        return im.size


def tag(xml, index, field):
    return etree.parse(str(xml)).getroot().findall("game")[index].findtext(field)


def open_editor(page, field):
    page.click("#game-list .game-item >> nth=0")
    page.click(f'.media-tile[data-field="{field}"] [data-action="edit"]')
    page.wait_for_selector("#imgedit-modal.open")
    page.wait_for_function("document.getElementById('imgedit-out').src.startsWith('data:')")
    page.wait_for_function("!document.getElementById('imgedit-save').disabled")


def wait_info(page, text):
    page.wait_for_function("t => document.getElementById('imgedit-out-info').textContent.includes(t)", arg=text)


def test_edit_button_only_on_images(page):
    page.click("#game-list .game-item >> nth=0")
    page.wait_for_selector('.media-tile[data-field="image"]')
    assert page.locator('.media-tile[data-field="image"] [data-action="edit"]').count() == 1
    assert page.locator('.media-tile[data-field="wheel"] [data-action="edit"]').count() == 1
    assert page.locator('.media-tile[data-field="video"] [data-action="edit"]').count() == 0


def test_trim_save_overwrite_then_undo(page, gamelist):
    image = gamelist.parent / "images" / "alpha-image.png"
    original = image.read_bytes()
    roms = {p.name: p.read_bytes() for p in gamelist.parent.glob("*.zip")}
    open_editor(page, "image")
    assert "320 × 200" in page.text_content("#imgedit-src-info")
    page.check("#imgedit-trim")
    wait_info(page, "240 × 140")
    page.click("#imgedit-save")
    page.wait_for_selector(".toast .toast-action")
    assert not page.is_visible("#imgedit-modal.open")
    assert wait_until(lambda: size_of(image) == (240, 140))
    assert tag(gamelist, 0, "image") == "./images/alpha-image.png"
    # The tile shows the new picture (cache-busting stamp)
    page.wait_for_function("document.querySelector('.media-tile[data-field=image] .tile-dims').textContent.includes('240')")
    page.click(".toast .toast-action")
    assert wait_until(lambda: image.read_bytes() == original)
    page.wait_for_function("document.querySelector('.media-tile[data-field=image] .tile-dims').textContent.includes('320')")
    assert {p.name: p.read_bytes() for p in gamelist.parent.glob("*.zip")} == roms


def test_crop_with_ratio_rotate_and_new_jpg_file(page, gamelist):
    open_editor(page, "image")
    page.select_option("#imgedit-ratio", "1")
    wait_info(page, "200 × 200")
    page.click("#imgedit-rot-right")
    page.select_option("#imgedit-format", "jpg")
    assert page.is_visible("#imgedit-quality-wrap")
    page.check('input[name="imgedit-mode"][value="new"]')
    wait_info(page, "JPG")
    page.click("#imgedit-save")
    page.wait_for_selector(".toast .toast-action")
    assert wait_until(lambda: tag(gamelist, 0, "image") == "./images/alpha-image-edit.jpg")
    new = gamelist.parent / "images" / "alpha-image-edit.jpg"
    assert size_of(new) == (200, 200)
    assert (gamelist.parent / "images" / "alpha-image.png").exists()
    page.wait_for_function("document.querySelector('.media-tile[data-field=image] .tile-file').textContent === 'alpha-image-edit.jpg'")


def test_draw_crop_with_the_mouse(page):
    open_editor(page, "wheel")
    box = page.locator("#imgedit-src").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.1, box["y"] + box["height"] * 0.2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.7, steps=5)
    page.mouse.up()
    assert page.is_visible("#imgedit-crop")
    crop = page.evaluate("imgEdit.crop")
    assert abs(crop["x"] - 30) <= 2 and abs(crop["w"] - 150) <= 3 and abs(crop["h"] - 50) <= 3
    wait_info(page, f"{crop['w']} × {crop['h']}")
    page.click("#imgedit-crop-clear")
    assert not page.is_visible("#imgedit-crop")
    wait_info(page, "300 × 100")


def test_transparent_background_preview(page):
    open_editor(page, "wheel")
    page.select_option("#imgedit-bg-mode", "flood")
    page.check("#imgedit-trim")
    wait_info(page, "240 × 60")
    # Inner white square is kept with "From the edges"
    assert page.evaluate("imgEdit && !document.getElementById('imgedit-warn').textContent")
    # Trimmed, nothing is transparent any more; untrimmed, a JPG loses the transparency
    page.uncheck("#imgedit-trim")
    page.select_option("#imgedit-format", "jpg")
    page.wait_for_function("document.getElementById('imgedit-warn').textContent.length > 0")
    assert page.is_visible("#imgedit-matte-wrap")
    if SHOTS:
        page.select_option("#imgedit-format", "keep")
        wait_info(page, "PNG")
        page.screenshot(path=os.path.join(SHOTS, "image-editor.png"))
    page.keyboard.press("Escape")
    assert not page.is_visible("#imgedit-modal.open")


def test_batch_images_preview_apply_undo(page, gamelist):
    images = gamelist.parent / "images"
    originals = {p.name: p.read_bytes() for p in images.iterdir()}
    page.evaluate("openBulk('images', {scope: 'all'})")
    page.wait_for_selector("#bulk-img-field")
    page.select_option("#bulk-img-field", "image")
    page.fill("#bulk-img-max-w", "160")
    page.select_option("#bulk-img-format", "webp")
    page.click("#bulk-preview-btn")
    page.wait_for_selector("#bulk-preview .bulk-table")
    assert page.locator("#bulk-preview tbody tr").count() == 2
    assert "160 × 100" in page.text_content("#bulk-preview tbody tr >> nth=0")
    assert {p.name: p.read_bytes() for p in images.iterdir()} == originals
    page.click("#bulk-apply")
    page.wait_for_selector(".toast .toast-action")
    assert wait_until(lambda: tag(gamelist, 0, "image") == "./images/alpha-image.webp")
    assert size_of(images / "alpha-image.webp") == (160, 100)
    assert size_of(images / "bravo-image.webp") == (160, 120)
    page.click(".toast .toast-action")
    assert wait_until(lambda: tag(gamelist, 0, "image") == "./images/alpha-image.png")
    assert wait_until(lambda: {p.name: p.read_bytes() for p in images.iterdir()} == originals)
