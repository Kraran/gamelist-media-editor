"""The UI shows the version from gme.version.APP_VERSION (single source)."""
import re
from pathlib import Path

from gme.version import APP_RELEASE_DATE, APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_header_and_about_use_app_version(client):
    html = client.get("/", headers={"Host": "127.0.0.1:5050"}).get_data(as_text=True)
    assert f'id="brand-version">v{APP_VERSION}<' in html
    assert f'id="about-version">{APP_VERSION}<' in html
    assert f'data-app-date="{APP_RELEASE_DATE}"' in html


def test_no_hardcoded_version_in_ui():
    for path in ("templates/index.html", "static/app.js"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert not re.search(r"\b1\.\d+\.\d+\b", text), f"hard-coded version in {path}"
