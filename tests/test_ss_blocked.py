"""A ScreenScraper refusal (quota, login…) is not a "not found": the batch scrape stops on it."""
from gme.scrapers import ss
from tests.conftest import LOCAL


def test_quota_is_source_blocked(gamelist, client, monkeypatch):
    monkeypatch.setattr(ss, "ss_request", lambda *a, **k: (False, ss.format_ss_error("Quota dépassé", 200), 200))
    r = client.post("/api/ss/scrape/0?path=./alpha.zip", headers={**LOCAL, "X-Locale": "ru"}, json={})
    assert r.status_code == 503
    assert r.get_json()["code"] == "source_blocked"
    assert "ScreenScraper" in r.get_json()["error"]


def test_unknown_game_stays_not_found(gamelist, client, monkeypatch):
    monkeypatch.setattr(ss, "ss_request", lambda *a, **k: (False, "Erreur : Jeu non trouvé !", 404))
    r = client.post("/api/ss/scrape/0?path=./alpha.zip", headers=LOCAL, json={})
    assert r.status_code == 404
    assert r.get_json().get("code") != "source_blocked"
