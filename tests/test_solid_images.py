"""Edit in bulk › Solid images (/api/solid-images*): one-colour pictures leave the
gamelist, and their files go to the Recycle Bin only when nothing else uses them."""
import io
import random

import pytest
from lxml import etree
from PIL import Image

from gme import solidimages, xml_store
from gme.media import uniform_colour
from tests.conftest import LOCAL


def save(path, img, fmt="PNG", **kw):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path), fmt, **kw)


def noisy(size, colour, spread):
    rnd = random.Random(1)
    img = Image.new("RGB", size, colour)
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = tuple(max(0, min(255, c + rnd.randint(-spread, spread))) for c in colour)
    return img


def gradient(size):
    img = Image.new("RGB", size)
    img.putdata([(x * 255 // size[0], 80, 160) for y in range(size[1]) for x in range(size[0])])
    return img


GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name>
    <image>./images/red.png</image><thumbnail>./images/art.png</thumbnail>
    <marquee>./images/shared-logo.png</marquee><wheel>./images/shared-logo.png</wheel></game>
  <game><path>./bravo.zip</path><name>Bravo</name>
    <image>./images/noisy.jpg</image><boxart>./images/clear.png</boxart><video>./images/red.png</video></game>
  <game><path>./charlie.zip</path><name>Charlie</name><image>./images/black.png</image></game>
  <game><path>./delta.zip</path><name>Delta</name><image>./images/black.png</image>
    <fanart>./images/logo.png</fanart><marquee>./images/gone.png</marquee><boxart>../outside.png</boxart></game>
  <game><path>./images/rom.png</path><name>Echo</name><image>./images/rom.png</image></game>
</gameList>
"""
ALL = ["./alpha.zip", "./bravo.zip", "./charlie.zip", "./delta.zip", "./images/rom.png"]
IMAGES = list(solidimages.IMAGE_FIELDS)


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "roms" / "snes"
    img = root / "images"
    save(img / "red.png", Image.new("RGB", (200, 150), (200, 10, 10)))
    save(img / "art.png", gradient((120, 90)))
    save(img / "shared-logo.png", Image.new("RGBA", (300, 100), (0, 0, 0, 0)))   # fully transparent
    save(img / "noisy.jpg", noisy((320, 240), (30, 90, 200), 4), "JPEG", quality=60)
    save(img / "clear.png", Image.new("RGBA", (64, 64), (255, 255, 255, 0)))
    save(img / "black.png", Image.new("RGB", (100, 100), (0, 0, 0)))
    logo = Image.new("RGBA", (100, 50), (255, 255, 255, 0))                       # one colour, but a shape
    logo.paste((255, 255, 255, 255), (20, 10, 80, 40))
    save(img / "logo.png", logo)
    save(img / "rom.png", Image.new("RGB", (40, 40), (9, 9, 9)))
    save(tmp_path / "roms" / "outside.png", Image.new("RGB", (50, 50), (1, 2, 3)))
    for rom in ("alpha", "bravo", "charlie", "delta"):
        (root / f"{rom}.zip").write_bytes(b"rom")
    (root / "gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    solidimages._cache.clear()
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    yield root
    xml_store.close_gamelist()


def post(client, url, **body):
    return client.post(url, headers=LOCAL, json=body)


def game_tags(root):
    return {g.findtext("name"): [c.tag for c in g if c.tag not in ("path", "name")]
            for g in etree.parse(str(root / "gamelist.xml")).getroot().findall("game")}


def test_uniform_rule():
    assert uniform_colour(Image.new("RGBA", (10, 10), (255, 0, 0, 255))) == "#ff0000"
    assert uniform_colour(Image.new("RGBA", (10, 10), (1, 2, 3, 0))) == "transparent"
    assert uniform_colour(noisy((256, 256), (100, 100, 100), 6).convert("RGBA")) is not None  # noise averages out
    assert uniform_colour(gradient((80, 80)).convert("RGBA")) is None
    half = Image.new("RGBA", (80, 80), (0, 0, 0, 255))
    half.paste((40, 40, 40, 255), (0, 0, 40, 80))                               # two close but distinct greys
    assert uniform_colour(half) is None


def test_preview_lists_solid_images_only(folder, client):
    before = (folder / "gamelist.xml").read_bytes()
    r = post(client, "/api/solid-images/preview", paths=ALL, fields=IMAGES)
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    found = sorted((row["name"], row["field"], row["colour"]) for row in data["rows"])
    assert found == [("Alpha", "image", "#c80a0a"), ("Alpha", "marquee", "transparent"),
                     ("Alpha", "wheel", "transparent"), ("Bravo", "boxart", "transparent"),
                     ("Bravo", "image", found[4][2]), ("Charlie", "image", "#000000"),
                     ("Delta", "image", "#000000"), ("Echo", "image", "#090909")]
    assert found[4][2].startswith("#")                                          # the noisy JPEG, ≈ #1e5ac8
    assert data["total"] == 8 and data["games"] == 5
    assert data["missing"] == 2                                                 # gone.png, ../outside.png
    assert "delete" not in data                                                 # files not asked
    assert (folder / "gamelist.xml").read_bytes() == before


def test_fields_and_scope_are_respected(folder, client):
    data = post(client, "/api/solid-images/preview", paths=["./charlie.zip"], fields=["image"]).get_json()
    assert [(r["name"], r["field"]) for r in data["rows"]] == [("Charlie", "image")]
    data = post(client, "/api/solid-images/preview", paths=ALL, fields=["wheel"]).get_json()
    assert [(r["name"], r["field"]) for r in data["rows"]] == [("Alpha", "wheel")]


@pytest.mark.parametrize("fields", [[], ["video"], ["manual"], ["name"], "image"])
def test_bad_fields_are_refused(folder, client, fields):
    r = post(client, "/api/solid-images/preview", paths=ALL, fields=fields)
    assert r.status_code == 400 and r.get_json()["code"] == "bulk_bad_field"
    assert post(client, "/api/solid-images", paths=[], fields=["image"]).status_code == 400


def test_tags_only_keeps_every_file(folder, client, trashed):
    res = post(client, "/api/solid-images", paths=ALL, fields=IMAGES).get_json()
    assert res["removed"] == 8 and res["games"] == 5 and res["snapshot"]
    assert res["deleted_files"] == [] and trashed == []
    tags = game_tags(folder)
    assert tags["Alpha"] == ["thumbnail"]
    assert tags["Bravo"] == ["video"]                                           # a video tag is not scanned
    assert tags["Delta"] == ["fanart", "marquee", "boxart"]
    assert (folder / "images" / "red.png").exists()
    again = post(client, "/api/solid-images", paths=ALL, fields=IMAGES).get_json()
    assert again["removed"] == 0 and again["snapshot"] is None


def test_files_go_to_the_trash_only_when_nothing_else_uses_them(folder, client, trashed):
    data = post(client, "/api/solid-images/preview", paths=ALL[:3], fields=IMAGES, files=True).get_json()
    assert sorted(e["path"] for e in data["delete"]) == ["./images/clear.png", "./images/noisy.jpg",
                                                         "./images/shared-logo.png"]
    kept = {e["path"]: e["reason"] for e in data["kept"]}
    assert kept == {"./images/red.png": "used",                                # Bravo's <video> points to it
                    "./images/black.png": "used"}                              # Delta is outside the scope
    res = post(client, "/api/solid-images", paths=ALL[:3], fields=IMAGES, files=True).get_json()
    assert sorted(p.replace("\\", "/").rsplit("/", 1)[-1] for p in trashed) == ["clear.png", "noisy.jpg",
                                                                                "shared-logo.png"]
    assert sorted(res["kept_files"]) == ["./images/black.png", "./images/red.png"]
    assert (folder / "images" / "red.png").exists() and (folder / "images" / "black.png").exists()
    assert (folder / "images" / "art.png").exists()
    assert all((folder / f"{rom}.zip").exists() for rom in ("alpha", "bravo", "charlie", "delta"))


def test_a_rom_is_never_deleted_and_shared_files_go_once_unused(folder, client, trashed):
    res = post(client, "/api/solid-images", paths=ALL, fields=["image"], files=True).get_json()
    names = sorted(p.replace("\\", "/").rsplit("/", 1)[-1] for p in trashed)
    assert names == ["black.png", "noisy.jpg"]                  # black.png: Charlie and Delta both lose it
    assert "./images/rom.png" in res["kept_files"] and (folder / "images" / "rom.png").exists()
    assert "./images/red.png" in res["kept_files"]                              # still Bravo's video
    assert (folder.parent / "outside.png").exists()


def test_undo_restores_the_gamelist(folder, client, trashed):
    before = game_tags(folder)
    res = post(client, "/api/solid-images", paths=ALL, fields=IMAGES, files=True).get_json()
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": res["snapshot"]}).status_code == 200
    assert game_tags(folder) == before


def test_unreadable_files_are_not_solid(folder, client):
    (folder / "images" / "red.png").write_bytes(b"<html>not an image</html>")
    data = post(client, "/api/solid-images/preview", paths=["./alpha.zip"], fields=["image"]).get_json()
    assert data["total"] == 0 and data["checked"] == 1


def test_results_are_cached_by_date_and_size(folder, client, monkeypatch):
    post(client, "/api/solid-images/preview", paths=ALL, fields=IMAGES)
    calls = []
    real = solidimages.uniform_colour
    monkeypatch.setattr(solidimages, "uniform_colour", lambda im: calls.append(1) or real(im))
    post(client, "/api/solid-images/preview", paths=ALL, fields=IMAGES)
    assert calls == []
    buf = io.BytesIO()
    gradient((90, 90)).save(buf, "PNG")
    (folder / "images" / "black.png").write_bytes(buf.getvalue())              # changed: decoded again
    data = post(client, "/api/solid-images/preview", paths=ALL, fields=IMAGES).get_json()
    assert calls == [1] and not any(r["file"] == "./images/black.png" for r in data["rows"])
