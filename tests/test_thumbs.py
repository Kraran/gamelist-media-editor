"""List thumbnails: size, format, cache, revalidation, safety."""
import io
import os

import pytest
from PIL import Image

from gme import thumbs, xml_store

H = {"Host": "127.0.0.1:5050"}


@pytest.fixture
def media(tmp_path, monkeypatch):
    """A gamelist folder with a few images; the cache goes to a temp folder."""
    monkeypatch.setattr(thumbs, "CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "roms"
    (root / "images").mkdir(parents=True)
    (root / "gamelist.xml").write_text("<gameList/>", encoding="utf-8")
    Image.new("RGB", (640, 480), (200, 40, 40)).save(root / "images" / "shot.png")
    Image.new("RGBA", (300, 400), (0, 0, 0, 0)).save(root / "images" / "box3d.png")
    (root / "images" / "broken.png").write_bytes(b"not an image")
    (root / "game.zip").write_bytes(b"PK")
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    yield root
    xml_store.close_gamelist()


def get(client, path, **headers):
    return client.get("/api/thumb", query_string={"path": path}, headers={**H, **headers})


def cached(media):
    d = media.parent / "cache"
    return sorted(os.listdir(d)) if d.exists() else []


def test_thumbnail_size_and_format(media, client):
    r = get(client, "./images/shot.png")
    assert r.status_code == 200 and r.mimetype == "image/webp"
    im = Image.open(io.BytesIO(r.get_data()))
    assert im.size == thumbs.THUMB_SIZE
    assert r.headers["Cache-Control"] == "no-cache" and r.headers.get("ETag")


def test_transparency_is_kept(media, client):
    im = Image.open(io.BytesIO(get(client, "./images/box3d.png").get_data()))
    assert im.mode == "RGBA"


def test_generated_once_then_served_from_cache(media, client, monkeypatch):
    get(client, "./images/shot.png")
    assert len(cached(media)) == 1
    monkeypatch.setattr("PIL.Image.open", lambda *a, **k: pytest.fail("regenerated"))
    assert get(client, "./images/shot.png").status_code == 200


def test_unchanged_thumbnail_revalidates_with_304(media, client):
    etag = get(client, "./images/shot.png").headers["ETag"]
    assert get(client, "./images/shot.png", **{"If-None-Match": etag}).status_code == 304


def test_replaced_image_gets_a_new_thumbnail(media, client):
    first = get(client, "./images/shot.png").headers["ETag"]
    Image.new("RGB", (320, 200), (0, 90, 200)).save(media / "images" / "shot.png")
    st = os.stat(media / "images" / "shot.png")
    os.utime(media / "images" / "shot.png", ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    r = get(client, "./images/shot.png", **{"If-None-Match": first})
    assert r.status_code == 200 and r.headers["ETag"] != first


@pytest.mark.parametrize("path, status", [
    ("../../etc/passwd", 404),
    ("./images/missing.png", 404),
    ("./game.zip", 415),
    ("./images/broken.png", 415),
])
def test_bad_requests(media, client, path, status):
    assert get(client, path).status_code == status


def test_no_gamelist_is_404(client):
    xml_store.close_gamelist()
    assert get(client, "./images/shot.png").status_code == 404


def test_prune_keeps_the_newest_files(tmp_path, monkeypatch):
    d = tmp_path / "cache"
    d.mkdir()
    monkeypatch.setattr(thumbs, "CACHE_DIR", str(d))
    for i in range(12):
        f = d / f"{i:02d}.webp"
        f.write_bytes(b"x")
        os.utime(f, (1_000_000 + i, 1_000_000 + i))
    assert thumbs.prune_cache(max_files=5) == 7
    assert sorted(os.listdir(d)) == [f"{i:02d}.webp" for i in range(7, 12)]
