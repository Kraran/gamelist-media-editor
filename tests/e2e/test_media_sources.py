"""ScreenScraper media settings, and the wheel / titleshot / music media in the browser."""
import io
import json
import os
import wave

import pytest
from lxml import etree

from tests.conftest import picture

pytestmark = pytest.mark.e2e
SHOTS = os.environ.get("GME_SHOTS")          # folder for documentation screenshots (optional)


def open_alpha(page):
    page.click("#game-list .game-item >> nth=0")
    page.wait_for_function("document.getElementById('game-name-input').value === 'Alpha'")


def saved(ss_config_file):
    return json.loads(ss_config_file.read_text(encoding="utf-8")) if ss_config_file.exists() else {}


def wav(seconds=2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x10" * 8000 * seconds)
    return buf.getvalue()


def test_media_settings_choose_type_region_and_turn_media_on(page, ss_config_file):
    page.click("#btn-settings")
    page.wait_for_selector("#settings-modal.open")
    page.click("#tab-ssmedia")
    page.wait_for_selector("#ssm-rows .ssm-row")
    assert page.locator("#ssm-rows .ssm-row").count() == 14
    # Defaults: what earlier versions asked for; the new media are off
    assert page.input_value("#ssm-type-image") == "ss"
    assert page.input_value("#ssm-type-marquee") == "wheel-hd"
    assert page.input_value("#ssm-type-boxart") == "box-3D"
    assert page.is_checked("#ssm-on-image") and not page.is_checked("#ssm-on-wheel")
    assert not page.is_checked("#ssm-on-titleshot")
    assert page.input_value("#ssm-region-boxart") == ""
    assert "Logo HD (wheel-hd)" in page.inner_text("#ssm-type-marquee")
    assert page.is_disabled("#ssm-type-fanart")                 # a single ScreenScraper type
    page.check("#ssm-on-wheel")
    page.wait_for_function("document.getElementById('ssm-type-wheel') && document.getElementById('ssm-on-wheel').checked")
    page.select_option("#ssm-type-wheel", "wheel-hd")
    page.wait_for_function("document.getElementById('ssm-type-wheel').value === 'wheel-hd'")
    page.select_option("#ssm-region-boxart", "jp")
    page.wait_for_function("document.getElementById('ssm-region-boxart').value === 'jp'")
    page.uncheck("#ssm-on-video")
    page.wait_for_selector(".ssm-row[data-field='video'].is-off")
    cfg = saved(ss_config_file)
    for _ in range(50):
        if cfg.get("media_enabled", {}).get("video") is False:
            break
        page.wait_for_timeout(100)
        cfg = saved(ss_config_file)
    assert cfg["media_enabled"]["wheel"] is True and cfg["media_enabled"]["video"] is False
    assert cfg["media_types"]["wheel"] == "wheel-hd" and cfg["media_regions"] == {"boxart": "jp"}
    assert "ScreenScraper" in page.inner_text(".ssm-music")
    if SHOTS:
        page.evaluate("document.getElementById('ssm-on-wheel').scrollIntoView({block: 'center'})")
        page.screenshot(path=os.path.join(SHOTS, "settings-ss-media.png"))


def test_scrape_proposes_and_writes_the_wheel(page, gamelist, fake_sources, ss_config_file):
    ss_config_file.write_text(json.dumps({"media_enabled": {"wheel": True}, "media_types": {"wheel": "wheel-hd"}}),
                              encoding="utf-8")
    open_alpha(page)
    page.click("#btn-scrape")
    page.wait_for_selector("#ss-modal.open")
    page.wait_for_selector(".ss-media-card:has(input[data-ss-field='wheel'])")
    checked = page.eval_on_selector_all("#ss-fields input[data-ss-field]:checked", "els => els.map(e => e.dataset.ssField)")
    assert "wheel" in checked and "titleshot" not in checked
    page.click("#ss-modal-apply")
    page.wait_for_function("!document.getElementById('ss-modal').classList.contains('open')")
    page.wait_for_selector("#media-grid .media-tile[data-field='wheel']")
    game = etree.parse(str(gamelist)).getroot().find("game")
    assert game.findtext("wheel") == "./images/alpha-wheel.png"
    assert (gamelist.parent / "images" / "alpha-wheel.png").is_file()


def test_music_has_an_audio_player_and_titleshot_a_tile(page, gamelist):
    folder = gamelist.parent
    (folder / "images").mkdir()
    (folder / "music").mkdir()
    (folder / "images" / "alpha-titleshot.png").write_bytes(picture((320, 240)))
    (folder / "images" / "alpha-wheel.png").write_bytes(picture((400, 150)))
    (folder / "music" / "alpha-music.wav").write_bytes(wav())
    xml = gamelist.read_text(encoding="utf-8").replace(
        "<name>Alpha</name>", "<name>Alpha</name><titleshot>./images/alpha-titleshot.png</titleshot>"
        "<wheel>./images/alpha-wheel.png</wheel><music>./music/alpha-music.wav</music>")
    gamelist.write_text(xml, encoding="utf-8")
    page.reload()
    page.wait_for_selector("#game-list .game-item")
    open_alpha(page)
    page.wait_for_selector(".media-tile[data-field='music'] audio")
    page.wait_for_function("document.querySelector(\".media-tile[data-field='music'] .tile-dims\").textContent === '0:02'")
    assert page.locator(".media-tile[data-field='titleshot'] img").count() == 1
    page.wait_for_function("document.querySelector(\".media-tile[data-field='wheel'] .tile-dims\").textContent === '400 × 150'")
    assert page.locator(".missing-chip[data-field='music']").count() == 0
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "editor-wheel-titleshot-music.png"))
    # Music is added like any media, with an audio file picker
    page.click(".media-tile[data-field='music'] [data-action='clear']")
    page.click("#confirm-ok")
    page.wait_for_selector(".missing-chip[data-field='music']")
    with page.expect_file_chooser() as fc:
        page.click(".missing-chip[data-field='music']")
    assert "audio/*" in page.get_attribute("#media-file-input", "accept")
    (folder / "theme.wav").write_bytes(wav(1))
    fc.value.set_files(str(folder / "theme.wav"))
    page.wait_for_selector(".media-tile[data-field='music'] audio")
    game = etree.parse(str(gamelist)).getroot().find("game")
    assert game.findtext("music") == "./music/alpha-music.wav"
