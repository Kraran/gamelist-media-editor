"""Scrape in the browser: one button, source menu, comparison dialog (fake sources)."""
import io
import json

import pytest
from lxml import etree

from gme import remote_cache
from gme.scrapers import ss

pytestmark = pytest.mark.e2e


def png(size=(64, 48)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (40, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def media(kind):
    return {"type": kind, "region": "wor",
            "url": f"https://neoclone.screenscraper.fr/api2/mediaJeu.php?sspassword=secret&media={kind}"}


JEU = {
    "id": "777",
    "noms": [{"region": "wor", "text": "Alpha"}],
    "synopsis": [{"langue": "fr", "text": "Une description venue de la source."}],
    "genres": [{"noms": [{"langue": "fr", "text": "Action"}]}],
    "joueurs": {"text": "1"},
    "developpeur": {"text": "Studio Alpha"},
    "medias": [media("ss"), media("wheel-hd")],
}


@pytest.fixture
def fake_sources(monkeypatch, tmp_path):
    """ScreenScraper answers with JEU (hash match, or a list when `ambiguous`)."""
    state = {"ambiguous": False, "downloads": []}

    def fake_request(endpoint, extra=None, timeout=25):
        extra = extra or {}
        if endpoint == "jeuInfos.php" and (extra.get("gameid") or not state["ambiguous"]):
            return True, {"response": {"jeu": JEU}}, 200
        if endpoint == "jeuRecherche.php":
            twin = dict(JEU, id="778", noms=[{"region": "wor", "text": "Alpha Plus"}])
            return True, {"response": {"jeux": [JEU, twin]}}, 200
        return False, "not found", 404

    def fake_fetch(url, headers=None, timeout=40, max_bytes=0):
        state["downloads"].append(url)
        return png(), "image/png"

    monkeypatch.setattr(ss, "ss_request", fake_request)
    monkeypatch.setattr(remote_cache, "fetch", fake_fetch)
    monkeypatch.setattr(remote_cache, "CACHE_DIR", str(tmp_path / "remote-cache"))
    return state


def open_alpha(page):
    page.click("#game-list .game-item >> nth=0")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")


def checked_fields(page):
    return page.eval_on_selector_all("#ss-fields input[data-ss-field]:checked", "els => els.map(e => e.dataset.ssField)")


def test_compare_checks_only_what_is_missing(page, gamelist, fake_sources):
    open_alpha(page)
    assert page.inner_text("#scrape-source-name") == "ScreenScraper"   # snes → ScreenScraper
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-modal.open")
    # Missing in the game: checked. Different (genre Platform → Action): shown, not checked.
    assert sorted(checked_fields(page)) == ["developer", "image", "marquee"]
    genre = page.locator(".ss-meta-row:has(input[data-ss-field='genre'])")
    assert genre.get_attribute("data-status") == "different"
    assert "Platform" in genre.inner_text() and "ACTION" in genre.inner_text()
    rest = page.inner_text(".ss-rests")
    assert "Nom" in rest and "Joueurs" in rest                         # identical values
    assert page.inner_text("#ss-apply-label") == "Appliquer (3)"
    # Previews: real images through the preview route, URLs never in the page
    page.wait_for_function("[...document.querySelectorAll('.is-proposed img')].every(i => i.complete && i.naturalWidth > 0)")
    assert "secret" not in page.content()
    assert len(fake_sources["downloads"]) == 2

    # Keyboard: the result opens with "Apply" focused, Enter applies
    page.wait_for_function("document.activeElement && document.activeElement.id === 'ss-modal-apply'")
    page.keyboard.press("Enter")
    page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')")
    page.wait_for_function("document.querySelector('#media-grid [data-field=marquee]') !== null")
    assert len(fake_sources["downloads"]) == 2                       # applied from the preview cache
    game = etree.parse(str(gamelist)).getroot().find("game")
    assert game.findtext("developer") == "Studio Alpha"
    assert game.findtext("desc") == "Alpha desc"                      # different: not replaced
    assert game.findtext("genre") == "Platform"
    assert game.findtext("image") == "./images/alpha-image.png"


def test_presets_and_apply_count(page, fake_sources):
    open_alpha(page)
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-modal.open")
    page.click(".seg[data-preset='all']")
    assert "genre" in checked_fields(page)
    assert page.get_attribute(".seg[data-preset='all']", "aria-pressed") == "true"
    page.click(".seg[data-preset='none']")
    assert checked_fields(page) == []
    assert page.is_disabled("#ss-modal-apply")
    page.click(".ss-meta-row:has(input[data-ss-field='desc'])")       # the whole row toggles
    assert checked_fields(page) == ["desc"]
    assert page.get_attribute(".seg[data-preset='none']", "aria-pressed") == "false"
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')")


def test_ambiguous_name_then_pick(page, gamelist, fake_sources):
    fake_sources["ambiguous"] = True
    open_alpha(page)
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-candidates .ss-candidate")
    assert page.locator("#ss-candidates .ss-candidate").count() == 2
    assert page.is_hidden("#ss-modal-apply")
    page.click("#ss-candidates .ss-candidate >> nth=0")
    page.wait_for_selector("#ss-fields .ss-meta-row")
    assert "ton choix dans la liste" in page.inner_text("#ss-modal-info")


def test_source_menu_is_remembered_per_system(page, fake_sources):
    adb_answer = {"success": True, "source": "arcadeitalia", "match_method": "romset",
                  "proposed": {"name": "Alpha", "adb_romset": "alpha", "medias": {}},
                  "current": {}, "compare": [{"key": "name", "kind": "meta", "status": "same",
                                              "current": "Alpha", "proposed": "Alpha"}]}
    page.route("**/api/adb/scrape/**", lambda r: r.fulfill(status=200, content_type="application/json",
                                                           body=json.dumps(adb_answer)))
    open_alpha(page)
    page.click("#btn-scrape-menu")
    assert page.get_attribute("#btn-scrape-menu", "aria-expanded") == "true"
    page.keyboard.press("ArrowDown")                                 # moves in the menu…
    assert page.evaluate("document.activeElement.dataset.source") == "arcadeitalia"
    assert page.input_value("#game-name-input") == "Alpha"           # …not in the game list
    page.keyboard.press("Enter")
    page.wait_for_selector("#ss-modal.open")
    assert "Rien de nouveau" in page.inner_text("#ss-fields")
    assert page.is_hidden("#ss-select-bar")
    page.click("#ss-modal-cancel")
    assert page.inner_text("#scrape-source-name") == "Arcade Database"

    page.reload()
    page.wait_for_selector("#game-list .game-item")
    open_alpha(page)
    page.wait_for_function("document.getElementById('scrape-source-name').textContent === 'Arcade Database'")
    page.click("#btn-scrape-menu")
    assert "Ton choix pour" in page.inner_text("#scrape-menu-note")
    page.click("#scrape-menu-auto")
    assert page.inner_text("#scrape-source-name") == "ScreenScraper"
    page.click("#btn-scrape-menu")
    page.keyboard.press("Escape")
    assert page.is_hidden("#scrape-menu")
