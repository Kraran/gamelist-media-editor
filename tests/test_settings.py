"""Interface settings kept by the server (language, scrape source, required media)."""
from gme import settings
from tests.conftest import LOCAL


def get(client):
    return client.get("/api/settings", headers=LOCAL).get_json()


def post(client, body):
    return client.post("/api/settings", headers=LOCAL, json=body)


def test_defaults_when_nothing_saved(client):
    assert get(client) == {"locale": None, "scrapers": {}, "required_media": {}}


def test_partial_updates_are_merged_and_saved(client, settings_file):
    post(client, {"locale": "de"})
    post(client, {"scrapers": {"mame": "steam", "snes": "arcadeitalia"}})
    post(client, {"required_media": {"snes": ["video", "image", "bezel"]}})
    post(client, {"scrapers": {"snes": None}})                 # back to automatic
    data = get(client)
    assert data["locale"] == "de"
    assert data["scrapers"] == {"mame": "steam"}
    assert data["required_media"] == {"snes": ["image", "video", "bezel"]}   # field order
    assert '"de"' in settings_file.read_text(encoding="utf-8")


def test_an_empty_required_list_is_kept(client):
    post(client, {"required_media": {"psx": []}})
    assert get(client)["required_media"] == {"psx": []}
    post(client, {"required_media": {"psx": None}})
    assert get(client)["required_media"] == {}


def test_bad_values_are_refused(client):
    for body in ({"locale": "french"}, {"scrapers": {"snes": "google"}}, {"scrapers": {"../x": "steam"}},
                 {"required_media": {"snes": ["desc"]}}, {"required_media": ["snes"]}, ["locale"]):
        r = post(client, body)
        assert r.status_code == 400, body
    assert get(client) == {"locale": None, "scrapers": {}, "required_media": {}}


def test_a_broken_file_gives_the_defaults(client, settings_file):
    settings_file.write_text('{"locale": 5, "scrapers": {"snes": "nope", "nes": "steam"}, "required_media": {"x": "image"}}',
                             encoding="utf-8")
    assert get(client) == {"locale": None, "scrapers": {"nes": "steam"}, "required_media": {}}
    settings_file.write_text("not json", encoding="utf-8")
    assert settings.load()["scrapers"] == {}


def test_thumbnail_and_bezel_are_in_the_game_list(gamelist, client):
    text = gamelist.read_text(encoding="utf-8").replace(
        "<name>Alpha</name>", "<name>Alpha</name><thumbnail>./images/t.png</thumbnail><bezel>./images/b.png</bezel>", 1)
    gamelist.write_text(text, encoding="utf-8")
    alpha = client.get("/api/games", headers=LOCAL).get_json()["games"][0]
    assert (alpha["thumbnail"], alpha["bezel"]) == ("./images/t.png", "./images/b.png")
