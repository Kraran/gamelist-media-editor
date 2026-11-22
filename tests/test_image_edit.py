"""Built-in image editor (gme/imageedit.py): operations on real pictures,
saving (overwrite with a copy of the original, or a new file), the gamelist
path when the format changes, batch apply and undo. ROMs never change."""
import io
import os

import pytest
from lxml import etree
from PIL import Image, ImageDraw

from gme import imageedit, xml_store
from tests.conftest import LOCAL, picture


def png(size=(120, 60), bg=(255, 255, 255, 255), box=None, color=(200, 30, 30, 255), fmt="PNG"):
    im = Image.new("RGBA", size, bg)
    if box:
        ImageDraw.Draw(im).rectangle(box, fill=color)
    buf = io.BytesIO()
    (im.convert("RGB") if fmt == "JPEG" else im).save(buf, fmt)
    return buf.getvalue()


def load(path):
    with Image.open(path) as im:
        im.load()
        return im.convert("RGBA"), im.format


@pytest.fixture
def media(gamelist, tmp_path):
    """alpha has an image (white border around a red box) and a wheel; bravo an image."""
    images = tmp_path / "images"
    images.mkdir()
    (images / "alpha-image.png").write_bytes(png(box=(20, 10, 99, 49)))
    (images / "alpha-wheel.png").write_bytes(png(size=(80, 40), box=(10, 10, 69, 29)))
    (images / "bravo-image.jpg").write_bytes(picture((200, 100), fmt="JPEG"))
    tree = etree.parse(str(gamelist))
    games = tree.getroot().findall("game")
    etree.SubElement(games[0], "image").text = "./images/alpha-image.png"
    etree.SubElement(games[0], "wheel").text = "./images/alpha-wheel.png"
    etree.SubElement(games[1], "image").text = "./images/bravo-image.jpg"
    tree.write(str(gamelist))
    xml_store.set_gamelist_path(str(gamelist))
    return images


def tag(gamelist, index, field):
    return etree.parse(str(gamelist)).getroot().findall("game")[index].findtext(field)


def post(client, url, body):
    return client.post(url, json=body, headers=LOCAL)


def rom_bytes(tmp_path):
    return {n: (tmp_path / n).read_bytes() for n in ("alpha.zip", "bravo.zip", "charlie.zip")}


# --- Pure operations -------------------------------------------------------------------

def test_trim_removes_uniform_and_transparent_borders():
    img, _ = imageedit.open_image(png(box=(20, 10, 99, 49)))
    assert imageedit.trim_box(img, 5) == (20, 10, 100, 50)
    clear, _ = imageedit.open_image(png(bg=(0, 0, 0, 0), box=(5, 6, 30, 20)))
    assert imageedit.trim_box(clear, 5) == (5, 6, 31, 21)


def test_flood_keeps_inner_area_of_the_same_colour():
    im = Image.new("RGBA", (60, 60), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((10, 10, 49, 49), fill=(0, 0, 255, 255))
    d.rectangle((25, 25, 34, 34), fill=(255, 255, 255, 255))   # white hole inside the logo
    flood = imageedit.make_transparent(im, "flood", None, 10)
    assert flood.getpixel((0, 0))[3] == 0
    assert flood.getpixel((30, 30))[3] == 255
    assert flood.getpixel((15, 15))[3] == 255
    key = imageedit.make_transparent(im, "key", (255, 255, 255), 10)
    assert key.getpixel((30, 30))[3] == 0


def test_crop_rotate_flip_resize():
    src = Image.new("RGBA", (100, 50), (0, 0, 0, 255))
    src.putpixel((0, 0), (255, 0, 0, 255))
    ops = imageedit.clean_ops({"crop": {"x": 0, "y": 0, "w": 40, "h": 20}, "rotate": 90})
    out = imageedit.apply_ops(src, ops)
    assert out.size == (20, 40)
    assert out.getpixel((19, 0))[:3] == (255, 0, 0)      # top-left went to top-right
    flip = imageedit.apply_ops(src, imageedit.clean_ops({"flip_h": True}))
    assert flip.getpixel((99, 0))[:3] == (255, 0, 0)
    small = imageedit.apply_ops(src, imageedit.clean_ops({"resize": {"max_w": 50}}))
    assert small.size == (50, 25)
    same = imageedit.apply_ops(src, imageedit.clean_ops({"resize": {"max_w": 400}}))
    assert same.size == (100, 50)                          # no upscale by default
    big = imageedit.apply_ops(src, imageedit.clean_ops({"resize": {"max_w": 400, "max_h": 100, "upscale": True}}))
    assert big.size == (200, 100)


def test_clean_ops_refuses_bad_values():
    for bad in ({"rotate": 45}, {"format": "tiff"}, {"bg": {"mode": "key", "color": "red"}}, "x"):
        with pytest.raises(imageedit.EditError):
            imageedit.clean_ops(bad)
    ops = imageedit.clean_ops({"quality": 500, "trim": {"tolerance": -4}})
    assert ops["quality"] == 100 and ops["trim"]["tolerance"] == 0
    # Batch: only trim / resize / format
    assert imageedit.clean_ops({"rotate": 90, "crop": {"x": 0, "y": 0, "w": 5, "h": 5}}, batch=True)["rotate"] == 0


def test_jpg_flattens_on_matte():
    img, _ = imageedit.open_image(png(bg=(0, 0, 0, 0), box=(5, 5, 20, 20)))
    data = imageedit.encode(img, "jpg", 90, (0, 255, 0))
    with Image.open(io.BytesIO(data)) as out:
        assert out.format == "JPEG"
        r, g, b = out.convert("RGB").getpixel((60, 40))
        assert g > 200 and r < 40


# --- Routes ------------------------------------------------------------------------------

def test_preview_writes_nothing(client, media, gamelist, tmp_path):
    before = {p.name: p.read_bytes() for p in media.iterdir()}
    xml_before = gamelist.read_bytes()
    r = post(client, "/api/image-edit/0/image/preview?path=./alpha.zip",
             {"ops": {"trim": {"tolerance": 5}, "format": "webp", "quality": 80}})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["data"].startswith("data:image/webp;base64,")
    assert (d["width"], d["height"], d["exact"]) == (80, 40, True)
    assert d["source"] == {"width": 120, "height": 60, "format": "png", "bytes": len(before["alpha-image.png"])}
    assert d["bytes"] > 0
    assert {p.name: p.read_bytes() for p in media.iterdir()} == before
    assert gamelist.read_bytes() == xml_before
    assert not (tmp_path / ".gme-backups").exists() or not (tmp_path / ".gme-backups" / "gamelist.xml" / "media").exists()


def test_preview_refuses_video_and_missing(client, media, gamelist):
    assert post(client, "/api/image-edit/0/video/preview", {"ops": {}}).status_code == 400
    assert post(client, "/api/image-edit/2/image/preview", {"ops": {}}).status_code == 404


def test_overwrite_keeps_original_and_undo(client, media, gamelist, tmp_path):
    roms = rom_bytes(tmp_path)
    original = (media / "alpha-image.png").read_bytes()
    r = post(client, "/api/image-edit/0/image?path=./alpha.zip",
             {"ops": {"trim": {"tolerance": 5}}, "mode": "overwrite"})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["path"] == "./images/alpha-image.png" and not d["path_changed"]
    img, fmt = load(media / "alpha-image.png")
    assert img.size == (80, 40) and fmt == "PNG"
    kept = tmp_path / ".gme-backups" / "gamelist.xml" / "media" / d["undo"]
    assert (kept / "0001.png").read_bytes() == original
    r = post(client, "/api/image-edit/undo", {"id": d["undo"]})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["restored"] == 1 and r.get_json()["session_id"] is None
    assert (media / "alpha-image.png").read_bytes() == original
    assert not kept.exists()
    assert post(client, "/api/image-edit/undo", {"id": d["undo"]}).status_code == 404
    assert rom_bytes(tmp_path) == roms


def test_format_change_updates_tag_and_trashes_old(client, media, gamelist, trashed):
    original = (media / "alpha-wheel.png").read_bytes()
    r = post(client, "/api/image-edit/0/wheel?path=./alpha.zip",
             {"ops": {"format": "jpg", "quality": 70}, "mode": "overwrite"})
    d = r.get_json()
    assert r.status_code == 200, d
    assert d["path"] == "./images/alpha-wheel.jpg" and d["path_changed"]
    assert tag(gamelist, 0, "wheel") == "./images/alpha-wheel.jpg"
    assert load(media / "alpha-wheel.jpg")[1] == "JPEG"
    assert not (media / "alpha-wheel.png").exists()
    assert str(media / "alpha-wheel.png") in trashed
    r = post(client, "/api/image-edit/undo", {"id": d["undo"]})
    u = r.get_json()
    assert r.status_code == 200, u
    assert u["session_id"] == xml_store.SESSION_ID
    assert (media / "alpha-wheel.png").read_bytes() == original
    assert not (media / "alpha-wheel.jpg").exists()
    assert tag(gamelist, 0, "wheel") == "./images/alpha-wheel.png"


def test_save_as_new_file(client, media, gamelist):
    original = (media / "bravo-image.jpg").read_bytes()
    r = post(client, "/api/image-edit/1/image?path=./bravo.zip",
             {"ops": {"crop": {"x": 0, "y": 0, "w": 100, "h": 100}, "rotate": 270, "format": "png"}, "mode": "new"})
    d = r.get_json()
    assert r.status_code == 200, d
    assert d["path"] == "./images/bravo-image-edit.png"
    assert (media / "bravo-image.jpg").read_bytes() == original
    assert load(media / "bravo-image-edit.png")[0].size == (100, 100)
    assert tag(gamelist, 1, "image") == "./images/bravo-image-edit.png"
    # Second copy gets its own name
    d2 = post(client, "/api/image-edit/1/image?path=./bravo.zip", {"ops": {}, "mode": "new"}).get_json()
    assert d2["path"] == "./images/bravo-image-edit-edit.png"


def test_shared_file_is_not_overwritten(client, media, gamelist):
    tree = etree.parse(str(gamelist))
    etree.SubElement(tree.getroot().findall("game")[0], "thumbnail").text = "./images/alpha-image.png"
    tree.write(str(gamelist))
    xml_store.set_gamelist_path(str(gamelist))
    original = (media / "alpha-image.png").read_bytes()
    d = post(client, "/api/image-edit/0/image?path=./alpha.zip",
             {"ops": {"trim": {"tolerance": 5}}, "mode": "overwrite"}).get_json()
    assert d["shared"] and d["path"] == "./images/alpha-image-edit.png"
    assert (media / "alpha-image.png").read_bytes() == original
    assert tag(gamelist, 0, "thumbnail") == "./images/alpha-image.png"
    assert tag(gamelist, 0, "image") == "./images/alpha-image-edit.png"


def test_stale_game_and_session(client, media, gamelist):
    r = post(client, "/api/image-edit/0/image?path=./nothere.zip", {"ops": {}, "mode": "overwrite"})
    assert r.status_code == 409
    r = client.post("/api/image-edit/0/image?path=./alpha.zip", json={"ops": {}},
                    headers={**LOCAL, "X-Gamelist-Session": "old"})
    assert r.status_code == 409


def test_batch_preview_apply_undo(client, media, gamelist, tmp_path):
    roms = rom_bytes(tmp_path)
    originals = {p.name: p.read_bytes() for p in media.iterdir()}
    body = {"paths": ["./alpha.zip", "./bravo.zip", "./charlie.zip"], "field": "image",
            "ops": {"resize": {"max_w": 100}, "format": "keep"}}
    p = post(client, "/api/image-edit/batch/preview", body).get_json()
    assert p["total"] == 2 and p["missing"] == 1
    assert [r["path"] for r in p["rows"]] == ["./alpha.zip", "./bravo.zip"]
    assert p["rows"][0]["after"]["width"] == 100 and p["rows"][0]["after"]["height"] == 50
    assert {p.name: p.read_bytes() for p in media.iterdir()} == originals
    r = post(client, "/api/image-edit/batch", body).get_json()
    assert r["changed"] == 2 and r["renamed"] == 0 and r["undo"]
    assert load(media / "alpha-image.png")[0].size == (100, 50)
    assert load(media / "bravo-image.jpg")[0].size == (100, 50)
    # A second run changes nothing
    again = post(client, "/api/image-edit/batch", body).get_json()
    assert again["changed"] == 0 and again["unchanged"] == 2 and again["undo"] is None
    u = post(client, "/api/image-edit/undo", {"id": r["undo"]}).get_json()
    assert u["restored"] == 2
    assert {p.name: p.read_bytes() for p in media.iterdir()} == originals
    assert rom_bytes(tmp_path) == roms


def test_batch_convert_renames_and_undo_restores_tags(client, media, gamelist):
    body = {"paths": ["./alpha.zip", "./bravo.zip"], "field": "image", "ops": {"format": "webp", "quality": 80}}
    r = post(client, "/api/image-edit/batch", body).get_json()
    assert r["changed"] == 2 and r["renamed"] == 2
    assert tag(gamelist, 0, "image") == "./images/alpha-image.webp"
    assert tag(gamelist, 1, "image") == "./images/bravo-image.webp"
    assert not (media / "alpha-image.png").exists()
    u = post(client, "/api/image-edit/undo", {"id": r["undo"]}).get_json()
    assert u["session_id"]
    assert tag(gamelist, 0, "image") == "./images/alpha-image.png"
    assert (media / "alpha-image.png").exists() and not (media / "alpha-image.webp").exists()


def test_batch_refuses_nothing_and_non_image_fields(client, media):
    assert post(client, "/api/image-edit/batch/preview",
                {"paths": ["./alpha.zip"], "field": "image", "ops": {}}).status_code == 400
    assert post(client, "/api/image-edit/batch/preview",
                {"paths": ["./alpha.zip"], "field": "video", "ops": {"format": "png"}}).status_code == 400


def test_undo_refuses_bad_ids(client, media):
    for bad in ("../x", "", 5, "20260101T000000000000Z-zzzzzzzz"):
        assert post(client, "/api/image-edit/undo", {"id": bad}).status_code == 404


def test_old_edits_are_pruned(client, media, gamelist, tmp_path, monkeypatch):
    monkeypatch.setattr(imageedit, "MAX_EDITS", 2)
    ids = [post(client, "/api/image-edit/0/image?path=./alpha.zip", {"ops": {"rotate": 180}, "mode": "overwrite"})
           .get_json()["undo"] for _ in range(3)]
    root = tmp_path / ".gme-backups" / "gamelist.xml" / "media"
    assert sorted(os.listdir(root)) == sorted(ids[1:])
