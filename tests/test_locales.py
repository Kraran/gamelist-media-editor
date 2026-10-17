"""The 13 UI languages stay complete and consistent with the code."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCALES = sorted((ROOT / "static" / "locales").glob("*.json"))
REFERENCE = "fr"  # the language the UI is written in


def flatten(data, prefix=""):
    out = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out.update(flatten(value, f"{prefix}{key}."))
        else:
            out[prefix + key] = value
    return out


def load(path):
    return flatten(json.loads(path.read_text(encoding="utf-8")))


REF = load(ROOT / "static" / "locales" / f"{REFERENCE}.json")


def placeholders(text):
    return set(re.findall(r"\{(\w+)\}", str(text)))


def test_thirteen_languages():
    assert len(LOCALES) == 13


@pytest.mark.parametrize("path", LOCALES, ids=lambda p: p.stem)
def test_same_keys_as_reference(path):
    keys = set(load(path))
    assert not set(REF) - keys, f"missing in {path.name}"
    assert not keys - set(REF), f"unknown keys in {path.name}"


@pytest.mark.parametrize("path", LOCALES, ids=lambda p: p.stem)
def test_same_placeholders_as_reference(path):
    data = load(path)
    bad = [k for k in REF if placeholders(REF[k]) != placeholders(data.get(k, ""))]
    assert not bad, f"{path.name}: placeholders differ for {bad[:10]}"


def test_keys_used_in_code_exist():
    ui = (ROOT / "static" / "app.js").read_text(encoding="utf-8") \
        + (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    server = "".join(f.read_text(encoding="utf-8") for f in sorted((ROOT / "gme").rglob("*.py")))
    key = r"([a-z_]+\.[a-z0-9_.]+)"
    used = set(re.findall(r'\bt\(\s*"' + key + '"', ui))
    used |= set(re.findall(r'data-i18n(?:-[a-z]+)?="' + key + '"', ui))
    server_keys = set(re.findall(r'\bst\(\s*"' + key + '"', server))
    assert len(server_keys) > 20, "server translation keys not found in gme/"
    used |= server_keys
    assert used, "no translation keys found: the regexes need updating"
    assert not used - set(REF), f"keys used in code but missing: {sorted(used - set(REF))}"
