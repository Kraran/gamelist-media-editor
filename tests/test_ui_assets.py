"""The UI only uses embedded assets: icons from the sprite, local fonts, no emoji."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPRITE = (ROOT / "templates" / "_icons.svg").read_text(encoding="utf-8")
SYMBOLS = set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', SPRITE))
HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️]")


def used_icons():
    names = set(re.findall(r'icon\("([a-z0-9-]+)"', HTML + JS))            # icon("x") in Jinja and JS
    names |= set(re.findall(r'icon:\s*"([a-z0-9-]+)"', JS))                 # FIELD_DEFS
    return names


def test_every_icon_used_exists_in_the_sprite():
    names = used_icons()
    assert len(names) > 20, "icon references not found: the regexes need updating"
    assert not names - SYMBOLS, f"missing in templates/_icons.svg: {sorted(names - SYMBOLS)}"


def test_sprite_is_rendered_in_the_page(client):
    html = client.get("/", headers={"Host": "127.0.0.1:5050"}).get_data(as_text=True)
    assert 'class="icon-sprite"' in html and 'id="i-device-floppy"' in html


def test_every_declared_font_file_exists():
    css = (ROOT / "static" / "fonts" / "fonts.css").read_text(encoding="utf-8")
    files = re.findall(r'url\("/static/fonts/([^"]+)"\)', css)
    assert files
    missing = [f for f in files if not (ROOT / "static" / "fonts" / f).is_file()]
    assert not missing, missing


def test_preloaded_fonts_exist():
    for href in re.findall(r'<link rel="preload" href="/static/([^"]+)"', HTML):
        assert (ROOT / "static" / href).is_file(), href


@pytest.mark.parametrize("path", ["templates/index.html", "static/app.js"])
def test_no_emoji_in_the_interface(path):
    hits = [line.strip()[:80] for line in (ROOT / path).read_text(encoding="utf-8").splitlines() if EMOJI.search(line)]
    assert not hits, hits


@pytest.mark.parametrize("path", sorted((ROOT / "static" / "locales").glob("*.json")), ids=lambda p: p.stem)
def test_no_emoji_in_translations(path):
    def walk(node, prefix=""):
        for k, v in node.items():
            if isinstance(v, dict):
                yield from walk(v, prefix + k + ".")
            elif EMOJI.search(str(v)):
                yield prefix + k
    assert not list(walk(json.loads(path.read_text(encoding="utf-8"))))


def test_no_duplicate_ids_in_the_page(client):
    html = client.get("/", headers={"Host": "127.0.0.1:5050"}).get_data(as_text=True)
    ids = re.findall(r'\sid="([^"]+)"', html)
    dups = sorted({i for i in ids if ids.count(i) > 1})
    assert not dups, dups
