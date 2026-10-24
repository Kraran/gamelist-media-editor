"""The virtualized game list: large gamelists, filter, keyboard, thumbnails, description on demand."""
import pytest
from PIL import Image

from gme import thumbs, xml_store

pytestmark = pytest.mark.e2e

N = 3000


@pytest.fixture
def gamelist(tmp_path, monkeypatch):
    """Overrides the 3-game gamelist: N games, every 3rd one without image."""
    monkeypatch.setattr(thumbs, "CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "roms" / "mame"
    (root / "images").mkdir(parents=True)
    Image.new("RGB", (320, 240), (60, 140, 220)).save(root / "images" / "shot.png")
    games = []
    for i in range(N):
        image = "" if i % 3 == 0 else "<image>./images/shot.png</image>"
        games.append(f"<game><path>./g{i:04d}.zip</path><name>Game {i:04d}</name>"
                     f"<desc>Description of game {i:04d}</desc>{image}</game>")
    xml = root / "gamelist.xml"
    xml.write_text('<?xml version="1.0"?>\n<gameList>\n' + "\n".join(games) + "\n</gameList>", encoding="utf-8")
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


def rows(page):
    return page.locator("#game-list .game-item")


def test_only_the_visible_rows_exist(page):
    assert page.inner_text("#game-count").startswith(str(N))
    assert 10 < rows(page).count() < 80


def test_end_key_reaches_the_last_game_and_shows_it(page):
    page.click("#game-list .game-item >> nth=0")
    page.click("#game-path")
    page.keyboard.press("End")
    page.wait_for_function(f"document.getElementById('game-name-input').value === 'Game {N - 1:04d}'")
    assert page.locator("#game-list .game-item.active").is_visible()
    assert page.get_attribute("#game-list", "aria-activedescendant") == page.get_attribute(".game-item.active", "id")


def test_scrolling_renders_the_rows_in_view(page):
    page.eval_on_selector("#game-list", "el => { el.scrollTop = el.scrollHeight / 2; }")
    page.wait_for_function("document.querySelector('#game-list .game-item .name').textContent >= 'Game 1400'")
    names = rows(page).locator(".name").all_inner_texts()
    assert any(n.startswith("Game 15") for n in names)


def test_filter_menu_counts_and_filters(page):
    options = page.locator("#media-filter option").all_inner_texts()
    assert options[0].endswith(f"({N})")
    image_option = [o for o in options if o.endswith(f"({N // 3})")]
    assert image_option, options
    page.select_option("#media-filter", "image")
    page.wait_for_function(f"document.getElementById('game-count').textContent.startsWith('{N // 3}')")
    assert rows(page).first.locator(".name").inner_text() == "Game 0000"


def test_search_narrows_the_list(page):
    page.fill("#search", "Game 29")
    page.wait_for_function(f"document.getElementById('game-count').textContent.startsWith('100 / {N}')")
    assert rows(page).first.locator(".name").inner_text() == "Game 2900"


def test_description_is_loaded_when_a_game_opens(page):
    page.click("#game-list .game-item >> nth=5")
    page.wait_for_function("document.getElementById('desc-textarea').value === 'Description of game 0005'")
    assert not page.evaluate("document.getElementById('desc-textarea').readOnly")
    assert "has-changes" not in page.get_attribute("#btn-save-desc", "class")


def test_thumbnails_load_and_missing_ones_show_an_icon(page):
    page.wait_for_function("""() => {
        const img = document.querySelector('#game-list .game-item:nth-child(2) .gi-thumb img');
        return img && img.complete && img.naturalWidth === 112;
    }""")
    assert page.locator("#game-list .game-item >> nth=0").locator(".gi-thumb svg").count() == 1


def test_media_count_and_tooltip(page):
    first = page.locator("#game-list .game-item >> nth=0 >> .gi-count")
    assert first.inner_text() == "0/10" and "is-empty" in first.get_attribute("class")
    second = page.locator("#game-list .game-item >> nth=1 >> .gi-count")
    assert second.inner_text() == "1/10"
    assert "Vidéo" in second.get_attribute("title")
