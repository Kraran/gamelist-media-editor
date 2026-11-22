"""Scraped images are checked before they are written: broken, tiny or one-colour files are refused."""
import io

import pytest
from PIL import Image

from gme import media, remote_cache, xml_store
from gme.media import MIN_IMAGE_PIXELS, MIN_IMAGE_SIDE, MediaRejected, check_image
from gme.scrapers.apply import apply_proposed
from tests.conftest import picture


def encode(im, fmt="PNG", **kw):
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def rejected(data):
    with pytest.raises(MediaRejected) as e:
        check_image(data)
    return e.value.code


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "GIF", "WEBP", "BMP"])
def test_real_pictures_pass(fmt):
    check_image(picture((320, 240), fmt=fmt))


def test_transparent_logo_passes():
    im = Image.new("RGBA", (400, 150), (0, 0, 0, 0))
    im.paste((255, 255, 255, 255), (50, 40, 350, 110))     # a white logo on a transparent background
    check_image(encode(im))


def test_mostly_dark_screenshot_passes():
    im = Image.new("RGB", (256, 224), (0, 0, 0))
    im.paste((255, 255, 255), (100, 100, 140, 108))           # a short line of text on black
    check_image(encode(im))


@pytest.mark.parametrize("data", [
    b"",
    b"<html><body>Erreur : media introuvable</body></html>",   # an error page saved as .png
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,                        # a PNG signature and nothing else
])
def test_not_an_image(data):
    assert rejected(data) == "image_unreadable"


def test_truncated_file():
    data = picture((320, 240), fmt="JPEG")
    assert rejected(data[: len(data) // 2]) == "image_unreadable"
    data = picture((320, 240))
    assert rejected(data[: len(data) - 40]) == "image_unreadable"


@pytest.mark.parametrize("size", [(1, 1), (MIN_IMAGE_SIDE - 1, 400), (400, MIN_IMAGE_SIDE - 1), (24, 24)])
def test_too_small(size):
    assert size[0] * size[1] < MIN_IMAGE_PIXELS or min(size) < MIN_IMAGE_SIDE
    im = Image.new("RGB", size, (10, 10, 10))
    im.putpixel((0, 0), (250, 250, 250))
    assert rejected(encode(im)) == "image_too_small"


def test_too_small_reports_the_size():
    with pytest.raises(MediaRejected) as e:
        check_image(encode(Image.new("RGB", (10, 8), (1, 2, 3))))
    assert e.value.params == {"w": 10, "h": 8}


@pytest.mark.parametrize("im", [
    Image.new("RGB", (320, 240), (30, 30, 30)),               # flat grey
    Image.new("RGB", (320, 240), (255, 255, 255)),            # blank white
    Image.new("RGBA", (300, 400), (0, 0, 0, 0)),              # fully transparent
    Image.new("L", (320, 240), 128),
], ids=["grey", "white", "transparent", "grayscale"])
def test_uniform(im):
    assert rejected(encode(im)) == "image_uniform"


def test_uniform_jpeg_with_compression_noise():
    data = encode(Image.new("RGB", (640, 480), (120, 60, 200)), "JPEG", quality=30)
    assert rejected(data) == "image_uniform"


def test_nearly_uniform_with_slight_noise():
    im = Image.new("RGB", (200, 200), (100, 100, 100))
    for x in range(0, 200, 7):
        im.putpixel((x, x), (104, 103, 102))
    assert rejected(encode(im)) == "image_uniform"


# --- In the scrape ----------------------------------------------------------------

GAMELIST = """<?xml version="1.0"?>
<gameList><game><path>./alpha.zip</path><name>Alpha</name><image>./images/alpha-image.png</image></game></gameList>
"""


@pytest.fixture
def game(tmp_path):
    xml = tmp_path / "gamelist.xml"
    xml.write_text(GAMELIST, encoding="utf-8")
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "alpha-image.png").write_bytes(picture((320, 240)))
    xml_store.set_gamelist_path(str(xml))
    yield xml_store.load_xml().getroot().find("game"), tmp_path
    xml_store.close_gamelist()


def serve(monkeypatch, data):
    monkeypatch.setattr(remote_cache, "get", lambda url: data)


def test_rejected_media_is_reported_and_not_written(game, monkeypatch):
    elem, root = game
    serve(monkeypatch, encode(Image.new("RGB", (320, 240), (0, 0, 0))))
    applied, errors = apply_proposed(elem, ["image", "boxart"], {"medias": {
        "image": {"url": "https://x.test/ss.png"}, "boxart": {"url": "https://x.test/box.png"}}})
    assert applied == []
    assert len(errors) == 2 and all("une seule couleur" in e for e in errors)
    assert errors[0].startswith("image: ")
    assert elem.findtext("image") == "./images/alpha-image.png"       # the old picture stays
    assert elem.find("boxart") is None
    assert sorted(p.name for p in (root / "images").iterdir()) == ["alpha-image.png"]


def test_good_media_is_written(game, monkeypatch):
    elem, root = game
    serve(monkeypatch, picture((300, 400)))
    applied, errors = apply_proposed(elem, ["boxart"], {"medias": {"boxart": {"url": "https://x.test/box.png"}}})
    assert (applied, errors) == (["boxart"], [])
    assert (root / "images" / "alpha-boxart.png").is_file()


def test_videos_and_manuals_are_not_checked(game, monkeypatch):
    elem, root = game
    serve(monkeypatch, b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    applied, errors = apply_proposed(elem, ["video"], {"medias": {"video": {"url": "https://x.test/v.mp4"}}})
    assert (applied, errors) == (["video"], [])
    serve(monkeypatch, b"%PDF-1.4 tiny")
    applied, errors = apply_proposed(elem, ["manual"], {"medias": {"manual": {"url": "https://x.test/m.pdf"}}})
    assert (applied, errors) == (["manual"], [])


def test_upload_from_a_web_page_is_not_checked(tmp_path, monkeypatch):
    """Dropping a picture on purpose (Upload from URL) keeps it, even a tiny one."""
    serve(monkeypatch, encode(Image.new("RGB", (8, 8), (5, 5, 5))))
    name = media.download_remote_media("https://x.test/dot.png", str(tmp_path), "alpha", "image")
    assert (tmp_path / name).is_file()


@pytest.mark.parametrize("code, params", [("image_unreadable", {}), ("image_too_small", {"w": 1, "h": 1}), ("image_uniform", {})])
def test_messages_exist_in_every_language(code, params):
    import json
    from pathlib import Path
    for path in sorted((Path(__file__).resolve().parents[1] / "static" / "locales").glob("*.json")):
        text = json.loads(path.read_text(encoding="utf-8"))["server"][code]
        assert text and text.format(**params)
