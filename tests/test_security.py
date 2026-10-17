"""Local-only guard: CSRF from other sites and DNS rebinding are rejected."""
import pytest

from conftest import names

SAME = {"Origin": "http://127.0.0.1:5050", "Sec-Fetch-Site": "same-origin"}


@pytest.mark.parametrize("host", ["127.0.0.1:5050", "localhost:5050", "[::1]:5050"])
def test_ui_same_origin_allowed(gamelist, client, host):
    r = client.post("/api/name/0", json={"name": "A2"},
                    headers={"Host": host, "Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


def test_script_without_origin_allowed(gamelist, client):
    assert client.post("/api/backup").status_code == 200


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "null"},
    {"Origin": "http://127.0.0.1:8080", "Sec-Fetch-Site": "same-site"},
])
def test_cross_site_post_rejected(gamelist, client, headers):
    r = client.post("/api/delete-game/0", json={}, headers=headers)
    assert r.status_code == 403
    assert names(gamelist) == ["Alpha", "Bravo", "Charlie"]
    assert (gamelist.parent / "alpha.zip").exists()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_dns_rebinding_host_rejected(gamelist, client, method):
    r = client.open("/api/games", method=method, headers={"Host": "evil.example:5050"})
    assert r.status_code == 403


def test_page_loads(client):
    assert client.get("/").status_code == 200
