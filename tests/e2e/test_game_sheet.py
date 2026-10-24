"""Game sheet: media gallery, rating stars, date picker, language/region lists, one save."""
import pytest
from lxml import etree
from PIL import Image

from gme import thumbs, xml_store
from .conftest import wait_until

pytestmark = pytest.mark.e2e


@pytest.fixture
def gamelist(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbs, "CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "roms" / "snes"
    (root / "images").mkdir(parents=True)
    Image.new("RGB", (640, 480), (200, 60, 60)).save(root / "images" / "alpha-image.png")
    Image.new("RGBA", (600, 200), (0, 0, 0, 0)).save(root / "images" / "alpha-marquee.png")
    Image.new("RGB", (320, 240), (40, 120, 220)).save(tmp_path / "new-shot.png")
    xml = root / "gamelist.xml"
    xml.write_text("""<?xml version="1.0"?>
<gameList>
  <game><path>./alpha.zip</path><name>Alpha</name><desc>A</desc><image>./images/alpha-image.png</image>
    <marquee>./images/alpha-marquee.png</marquee><rating>0.85</rating><releasedate>19970915T000000</releasedate>
    <lang>en,fr</lang><region>eu</region><developer>Capcom</developer></game>
  <game><path>./bravo.zip</path><name>Bravo</name><releasedate>1997</releasedate><lang>ja</lang><region>jp</region></game>
</gameList>
""", encoding="utf-8")
    for rom in ("alpha", "bravo"):
        (root / f"{rom}.zip").write_bytes(b"rom")
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


def game(xml, name):
    for g in etree.parse(str(xml)).getroot().findall("game"):
        if g.findtext("name") == name:
            return {c.tag: c.text or "" for c in g}


def select(page, name):
    page.click(f"#game-list >> text={name}")
    page.wait_for_function(f"document.getElementById('game-name-input').value === {name!r}")


def save(page):
    page.click("#btn-save")
    page.wait_for_selector("#save-bar[hidden]", state="attached")


# --- Rating -------------------------------------------------------------------

def test_stars_show_the_stored_rating(page):
    select(page, "Alpha")
    assert page.get_attribute("#rating-stars", "aria-valuenow") == "4.3"
    assert page.inner_text("#rating-value") == "4,3"
    width = page.eval_on_selector("#rating-fill", "e => e.style.width")
    assert width == "85%"


def test_clicking_a_star_sets_half_steps(page, gamelist):
    select(page, "Alpha")
    box = page.locator("#rating-stars").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.65, box["y"] + box["height"] / 2)   # 3.25 stars -> 3.5
    assert page.input_value("#meta-rating") == "0.7"
    save(page)
    assert game(gamelist, "Alpha")["rating"] == "0.7"


def test_arrow_keys_change_the_rating_not_the_game(page):
    select(page, "Alpha")
    page.focus("#rating-stars")
    page.keyboard.press("ArrowLeft")
    assert page.input_value("#meta-rating") == "0.8"
    assert page.input_value("#game-name-input") == "Alpha"


def test_rating_can_be_cleared(page, gamelist):
    select(page, "Alpha")
    page.click("#rating-clear")
    save(page)
    assert "rating" not in game(gamelist, "Alpha")


# --- Release date -------------------------------------------------------------

def test_date_picker_reads_and_writes_the_gamelist_format(page, gamelist):
    select(page, "Alpha")
    assert page.input_value("#meta-releasedate-input") == "1997-09-15"
    page.fill("#meta-releasedate-input", "2001-03-04")
    page.dispatch_event("#meta-releasedate-input", "change")
    save(page)
    assert game(gamelist, "Alpha")["releasedate"] == "20010304T000000"


def test_unrecognized_date_is_kept_and_shown(page, gamelist):
    select(page, "Bravo")
    assert page.input_value("#meta-releasedate-input") == ""
    assert "1997" in page.inner_text("#releasedate-raw")
    page.fill("#meta-players", "2")
    save(page)
    assert game(gamelist, "Bravo")["releasedate"] == "1997"


# --- Language and region ------------------------------------------------------

def test_codes_are_shown_by_name_and_unknown_values_kept(page, gamelist):
    select(page, "Alpha")
    assert page.input_value("#meta-lang") == "en,fr"
    lang_label = page.eval_on_selector("#meta-lang", "s => s.options[s.selectedIndex].textContent")
    assert lang_label.lower() == "anglais, français"
    region_label = page.eval_on_selector("#meta-region", "s => s.options[s.selectedIndex].textContent")
    assert region_label == "Europe"
    page.select_option("#meta-region", "jp")
    save(page)
    assert game(gamelist, "Alpha")["region"] == "jp" and game(gamelist, "Alpha")["lang"] == "en,fr"


# --- One save -----------------------------------------------------------------

def test_one_request_saves_every_changed_field(page, gamelist):
    select(page, "Alpha")
    posts = []
    page.on("request", lambda r: r.method == "POST" and "/api/" in r.url and posts.append(r.url))
    page.fill("#game-name-input", "Alpha Prime")
    page.fill("#desc-textarea", "Better")
    page.fill("#meta-players", "1-2")
    save(page)
    assert len(posts) == 1 and "/api/game/0" in posts[0]
    g = game(gamelist, "Alpha Prime")
    assert g["desc"] == "Better" and g["players"] == "1-2" and g["rating"] == "0.85"


# --- Media gallery ------------------------------------------------------------

def test_present_media_are_tiles_and_missing_ones_chips(page):
    select(page, "Alpha")
    assert page.locator("#media-grid .media-tile").count() == 2
    assert page.eval_on_selector(".media-tile[data-field='marquee'] .tile-media", "e => getComputedStyle(e).aspectRatio") == "3 / 1"
    page.wait_for_function("document.querySelector(\".media-tile[data-field='image'] .tile-dims\").textContent === '640 × 480'")
    assert page.locator("#missing-chips .missing-chip").count() == 8
    select(page, "Bravo")
    assert page.is_hidden("#media-grid")
    assert page.locator("#missing-chips .missing-chip").count() == 10


def test_clicking_a_missing_media_uploads_a_file(page, gamelist, tmp_path):
    select(page, "Bravo")
    with page.expect_file_chooser() as fc:
        page.click(".missing-chip[data-field='image']")
    fc.value.set_files(str(tmp_path / "new-shot.png"))
    page.wait_for_selector(".media-tile[data-field='image']")
    assert wait_until(lambda: game(gamelist, "Bravo").get("image", "").endswith(".png"))
    assert page.locator("#game-list .game-item.active .gi-count").inner_text() == "1/10"


# --- Suggestions --------------------------------------------------------------

def test_suggestions_come_from_the_gamelist(page):
    select(page, "Bravo")
    page.focus("#meta-developer")
    assert "Capcom" in page.eval_on_selector_all("#dl-developer option", "os => os.map(o => o.value)")


def test_tiles_take_the_shape_of_their_media(page, gamelist):
    """A media whose shape differs from the usual one is shown whole (here, a round
    logo marquee in 16:9 and a tall cabinet photo as boxart), never cut."""
    images = gamelist.parent / "images"
    Image.new("RGB", (400, 225), (30, 40, 140)).save(images / "alpha-marquee.png")
    Image.new("RGB", (314, 650), (90, 110, 200)).save(images / "alpha-boxart.png")
    xml = gamelist.read_text(encoding="utf-8").replace(
        "<marquee>", "<boxart>./images/alpha-boxart.png</boxart><marquee>", 1)
    gamelist.write_text(xml, encoding="utf-8")
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    select(page, "Alpha")
    page.wait_for_function("[...document.querySelectorAll('.media-tile .tile-dims')].every(d => d.textContent)")
    boxes = page.evaluate("""[...document.querySelectorAll('.media-tile')].filter(t => t.querySelector('img')).map(t => {
        const frame = t.querySelector('.tile-media').getBoundingClientRect();
        const img = t.querySelector('img');
        return {field: t.dataset.field, fw: frame.width, fh: frame.height,
                ratio: img.naturalWidth / img.naturalHeight};
    })""")
    assert {b["field"] for b in boxes} == {"image", "marquee", "boxart"}
    for b in boxes:
        assert abs(b["fw"] / b["fh"] - b["ratio"]) < 0.03, b      # the frame has the image's shape
