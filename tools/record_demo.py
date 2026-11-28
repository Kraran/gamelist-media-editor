"""Record the README demo (Playwright video), on a copy of a system folder.

    python tools/record_demo.py <system folder to copy> <output folder>

Nothing leaves the machine: ScreenScraper and the image downloads are answered
by local fakes (the copy's own images), GitHub is offline, and every app file
(settings, caches, backups) goes to the output folder. The source folder is
only read. Writes ``demo.webm`` (raw), then ``tools/encode_demo.sh`` makes the
MP4 and the animated WebP used in the README.
"""
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SRC = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
WORK = OUT / "work"
if WORK.exists():
    shutil.rmtree(WORK)
(WORK / "app-data").mkdir(parents=True)

import gme.paths  # noqa: E402
gme.paths.APP_DIR = str(WORK / "app-data")       # before any other gme import

import requests  # noqa: E402
from lxml import etree  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from gme import fsutil, overview, remote_cache, updater, xml_store  # noqa: E402
from gme.scrapers import ss  # noqa: E402
from gme.server import app  # noqa: E402

# --- the demo collection: a copy of SRC + two small systems -----------------------
ROMS = Path(tempfile.gettempdir()) / "RetroBat" / "roms"     # a short path on screen
if ROMS.exists():
    shutil.rmtree(ROMS)
ROMS.mkdir(parents=True)
SYS = ROMS / SRC.name
shutil.copytree(SRC, SYS, ignore=shutil.ignore_patterns("gamelist_*.xml", "*.old"))
DEMO_GAME = "./pinball.zip"
tree = etree.parse(str(SYS / "gamelist.xml"))
for g in tree.getroot().findall("game"):
    if g.findtext("path") == DEMO_GAME:                 # a game left to scrape
        for tag in ("boxart", "wheel", "marquee", "cartridge", "desc", "developer", "publisher", "genre"):
            for el in g.findall(tag):
                g.remove(el)
tree.write(str(SYS / "gamelist.xml"), encoding="utf-8", xml_declaration=True)

OTHER = {
    "o2em": ["Alien Invaders - Plus!", "Pick Axe Pete!", "K.C. Munchkin!", "Quest for Rings", "Turtles", "Killer Bees!"],
    "channelf": ["Videocart-1 Tic-Tac-Toe", "Videocart-12 Baseball", "Videocart-17 Pinball Challenge", "Videocart-26 Alien Invasion"],
}
for folder, names in OTHER.items():
    d = ROMS / folder
    d.mkdir()
    games = []
    for i, name in enumerate(names):
        rom = f"game{i + 1}.bin"
        if i != len(names) - 1:                       # one ROM missing on disk
            (d / rom).write_bytes(b"demo")
        desc = f"<desc>{name}</desc>" if i % 2 == 0 else ""
        games.append(f"<game><path>./{rom}</path><name>{name}</name>{desc}</game>")
    (d / "gamelist.xml").write_text('<?xml version="1.0"?>\n<gameList>' + "".join(games) + "</gameList>",
                                    encoding="utf-8")
(WORK / "app-data" / "ui_settings.json").write_text('{"locale": "en", "theme": "dark"}', encoding="utf-8")

# --- local fakes -------------------------------------------------------------------
IMAGES = SYS / "downloaded_images"
MEDIA = {"ss": "pinball-screenshot.png", "box-2D": "pinball-boxart.png", "box-3D": "pinball-boxart.png",
         "wheel-hd": "pinball-wheel.png", "wheel": "pinball-wheel.png", "support-2D": "pinball-cartridge.png"}
MEDIA = {k: v for k, v in MEDIA.items() if (IMAGES / v).exists()}
JEU = {
    "id": "54321",
    "noms": [{"region": "wor", "text": "Cassette 23 - Flipper"}],
    "synopsis": [{"langue": "en", "text": "Flip the ball, light the bumpers and keep it out of the drain: "
                                          "a two-player pinball game for the Interton VC 4000."}],
    "genres": [{"noms": [{"langue": "en", "text": "Pinball"}]}],
    "joueurs": {"text": "1-2"},
    "developpeur": {"text": "Interton"},
    "editeur": {"text": "Interton"},
    "medias": [{"type": k, "region": "wor", "format": "png",
                "url": f"https://neoclone.screenscraper.fr/api2/mediaJeu.php?media={k}"} for k in MEDIA],
}


def fake_request(endpoint, extra=None, timeout=25):
    if endpoint == "jeuInfos.php":
        return True, {"response": {"jeu": JEU}}, 200
    return False, "not found", 404


def fake_fetch(url, headers=None, timeout=40, max_bytes=0):
    kind = url.rsplit("media=", 1)[-1]
    return (IMAGES / MEDIA[kind]).read_bytes(), "image/png"


def offline(url, **kwargs):
    raise requests.ConnectionError("offline demo")


ss.ss_request = fake_request
ss.SS_API = "http://127.0.0.1:9/api2"
remote_cache.fetch = fake_fetch
updater._get = offline
fsutil.trash = lambda path: None
overview.reset()
xml_store.set_gamelist_path(str(SYS / "gamelist.xml"))

srv = make_server("127.0.0.1", 0, app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"

# --- recording helpers: a visible cursor, captions, human-paced actions -------------
CURSOR = """
(() => {
  const c = document.createElement('div');
  c.id = 'demo-cursor';
  c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;z-index:99999;pointer-events:none;' +
    'transform:translate(-3px,-2px);transition:transform .06s;';
  c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 3l7 17 2.5-7.5L21 10z" ' +
    'fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  const cap = document.createElement('div');
  cap.id = 'demo-caption';
  cap.style.cssText = 'position:fixed;left:50%;bottom:44px;transform:translateX(-50%);z-index:99998;' +
    'pointer-events:none;padding:9px 18px;border-radius:999px;background:rgba(124,92,255,.94);color:#fff;' +
    'font:600 17px/1.2 system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.35);opacity:0;transition:opacity .25s;';
  const add = () => { document.body.appendChild(c); document.body.appendChild(cap); };
  document.body ? add() : document.addEventListener('DOMContentLoaded', add);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('mousedown', () => { c.style.transform = 'translate(-3px,-2px) scale(.85)'; }, true);
  document.addEventListener('mouseup', () => { c.style.transform = 'translate(-3px,-2px)'; }, true);
})();
"""

W, H = 1280, 800
pos = [W // 2, H // 2]


def caption(page, text):
    page.evaluate("t => { const c = document.getElementById('demo-caption'); c.textContent = t; "
                  "c.style.opacity = t ? 1 : 0; }", text)


def move(page, selector):
    box = page.locator(selector).first.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y, steps=max(8, int(abs(x - pos[0]) + abs(y - pos[1])) // 25))
    pos[:] = [x, y]


def click(page, selector, pause=350):
    page.locator(selector).first.wait_for(state="visible")
    move(page, selector)
    page.wait_for_timeout(120)
    page.mouse.down()
    page.mouse.up()
    page.wait_for_timeout(pause)


def type_in(page, selector, text, delay=45):
    click(page, selector, 150)
    page.keyboard.type(text, delay=delay)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                  record_video_dir=str(OUT / "raw"), record_video_size={"width": W, "height": H})
        ctx.route("https://flagcdn.com/**", lambda r: r.abort())
        ctx.add_init_script(CURSOR)
        page = ctx.new_page()
        page.goto(BASE + "/")
        page.wait_for_selector("#game-list .game-item")
        page.evaluate("document.fonts.ready")
        page.mouse.move(*pos)
        page.wait_for_timeout(900)

        # 1. Browse
        caption(page, "Open a gamelist.xml and browse your games")
        click(page, "#game-list .game-item >> nth=0", 700)
        for _ in range(3):
            page.keyboard.press("j")
            page.wait_for_timeout(550)
        type_in(page, "#search", "chess")
        page.wait_for_timeout(900)
        click(page, "#game-list .game-item >> nth=1", 900)
        page.fill("#search", "")
        page.wait_for_timeout(400)

        # 2. Edit
        caption(page, "Edit metadata, then save with Ctrl+S")
        click(page, "#desc-textarea", 150)
        page.keyboard.press("Control+End")
        page.keyboard.type(" — a classic of the Interton VC 4000.", delay=28)
        page.wait_for_timeout(300)
        box = page.locator("#rating-stars").bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.78, box["y"] + box["height"] / 2, steps=12)
        pos[:] = [box["x"] + box["width"] * 0.78, box["y"] + box["height"] / 2]
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(500)
        page.keyboard.press("Control+s")
        page.wait_for_selector("#toast.show")
        page.wait_for_timeout(1200)

        # 3. Scrape with a preview
        caption(page, "Scrape: compare, pick, apply")
        type_in(page, "#search", "flipper")
        page.wait_for_timeout(500)
        click(page, "#game-list .game-item >> nth=0", 700)
        page.fill("#search", "")
        click(page, "#btn-scrape", 300)
        page.wait_for_selector("#ss-modal.open")
        page.wait_for_function("[...document.querySelectorAll('.is-proposed img')].every(i => i.complete && i.naturalWidth > 0)")
        page.wait_for_timeout(1800)
        click(page, "#ss-modal-apply", 300)
        page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')")
        page.wait_for_timeout(1500)

        # 4. Media
        caption(page, "Every media type, with a preview")
        click(page, "#media-grid .media-tile img >> nth=1", 900)
        page.wait_for_timeout(900)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        # 5. Bulk edit
        caption(page, "Bulk edit with a preview")
        click(page, "#btn-actions", 400)
        click(page, "#btn-bulk", 400)
        page.wait_for_selector("#bulk-modal.open")
        click(page, '[data-bulk-tab="replace"]', 300)
        page.select_option("#bulk-rep-field", "name")
        type_in(page, "#bulk-rep-find", r"^Cassette \d+ - ", 35)
        click(page, "#bulk-rep-regex", 200)
        click(page, "#bulk-preview-btn", 300)
        page.wait_for_selector("#bulk-preview .bulk-summary")
        page.wait_for_timeout(1700)
        click(page, "#bulk-apply", 300)
        page.wait_for_selector("#toast.show")
        page.wait_for_timeout(1500)

        # 6. Undo
        caption(page, "Multi-level undo / redo")
        click(page, "#btn-history", 1300)
        page.keyboard.press("Escape")
        click(page, "#btn-undo", 300)
        page.wait_for_function("document.getElementById('toast').textContent.includes('Undone')")
        page.wait_for_timeout(1400)
        page.evaluate("document.getElementById('toast').classList.remove('show')")   # out of the next shot

        # 7. Multi-system overview
        caption(page, "All your systems at a glance")
        click(page, "#btn-open-gamelist", 400)
        page.wait_for_selector("#open-gl-root:not([hidden])")
        click(page, "#open-gl-root", 300)
        page.wait_for_selector("#overview-modal.open #overview-table")
        page.wait_for_function("document.getElementById('overview-progress').hidden")
        page.wait_for_timeout(1200)
        move(page, "#overview-table tbody tr >> nth=1")
        page.wait_for_timeout(2200)
        caption(page, "")
        page.wait_for_timeout(500)
        video = page.video
        ctx.close()
        browser.close()
        shutil.move(video.path(), OUT / "demo.webm")
    srv.shutdown()
    shutil.rmtree(ROMS.parent, ignore_errors=True)
    print(OUT / "demo.webm")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"recorded in {time.time() - t0:.0f} s")
