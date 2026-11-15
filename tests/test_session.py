"""/api/session: diagnostics of the running app."""


def test_session_reports_the_open_gamelist(gamelist, client):
    """Used by the exe smoke test in CI (.github/workflows/tests.yml)."""
    data = client.get("/api/session", headers={"Host": "127.0.0.1:5050"}).get_json()
    assert data["loaded"] is True and data["xml_path"] == str(gamelist)
    assert data["version"] and data["frozen"] is False
