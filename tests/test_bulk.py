"""Edit in bulk (/api/bulk*), removing many games (/api/bulk-delete*) and /api/stats."""
import pytest
from lxml import etree

from gme import xml_store
from gme.bulk import clean_name
from tests.conftest import LOCAL

GAMELIST = """<?xml version="1.0"?>
<gameList>
  <game><path>./Alpha (Europe) [!].zip</path><name>alpha</name><desc>An Alpha game.</desc><genre>Platform</genre>
    <image>./images/alpha.png</image><video>./videos/alpha.mp4</video><boxart>./images/shared.png</boxart>
    <playcount>3</playcount><gametime>4000</gametime><favorite>true</favorite></game>
  <game><path>./bravo.zip</path><name>Bravo</name><genre>Shoot'em up / Vertical</genre>
    <boxart>./images/shared.png</boxart><marquee>./images/gone.png</marquee><rating>0.8</rating></game>
  <game><path>./charlie.zip</path><name>Charlie</name><image>./charlie.zip</image><releasedate>19830101T000000</releasedate></game>
  <game><path>./delta.zip</path><name>Delta</name><image>../outside.png</image></game>
</gameList>
"""


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "roms" / "vc4000"
    (root / "images").mkdir(parents=True)
    (root / "videos").mkdir()
    (root / "gamelist.xml").write_text(GAMELIST, encoding="utf-8")
    for rel in ("Alpha (Europe) [!].zip", "bravo.zip", "charlie.zip", "delta.zip",
                "images/alpha.png", "videos/alpha.mp4", "images/shared.png"):
        (root / rel).write_bytes(b"x" * 10)
    (tmp_path / "roms" / "outside.png").write_bytes(b"x" * 10)
    xml_store.set_gamelist_path(str(root / "gamelist.xml"))
    yield root
    xml_store.close_gamelist()


def games(root):
    return {g.findtext("path"): g for g in etree.parse(str(root / "gamelist.xml")).getroot().findall("game")}


def post(client, url, **body):
    return client.post(url, headers=LOCAL, json=body)


def preview(client, paths, op):
    r = post(client, "/api/bulk/preview", paths=paths, op=op)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def apply(client, paths, op):
    r = post(client, "/api/bulk", paths=paths, op=op)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


ALL = ["./Alpha (Europe) [!].zip", "./bravo.zip", "./charlie.zip", "./delta.zip"]


def test_set_a_field_previews_then_applies_in_one_write(folder, client):
    op = {"kind": "set", "field": "developer", "value": "Interton"}
    before = (folder / "gamelist.xml").read_bytes()
    data = preview(client, ALL[:2], op)
    assert data["total"] == 2 and data["games"] == 2
    assert {c["after"] for c in data["changes"]} == {"Interton"}
    assert (folder / "gamelist.xml").read_bytes() == before            # a dry run
    res = apply(client, ALL[:2], op)
    assert res["changed"] == 2 and res["snapshot"]
    g = games(folder)
    assert g["./bravo.zip"].findtext("developer") == "Interton"
    assert g["./charlie.zip"].find("developer") is None


def test_set_flags_dates_and_clearing(folder, client):
    apply(client, ALL, {"kind": "set", "field": "hidden", "value": "true"})
    assert all(g.findtext("hidden") == "true" for g in games(folder).values())
    apply(client, ALL, {"kind": "set", "field": "favorite", "value": ""})
    assert all(g.find("favorite") is None for g in games(folder).values())
    apply(client, ALL[:1], {"kind": "set", "field": "releasedate", "value": "1978-05"})
    assert games(folder)[ALL[0]].findtext("releasedate") == "19780501T000000"
    apply(client, ALL, {"kind": "set", "field": "releasedate", "value": ""})
    assert all(g.find("releasedate") is None for g in games(folder).values())


@pytest.mark.parametrize("value", ["1978-13", "78", "tomorrow"])
def test_bad_date_is_refused(folder, client, value):
    r = post(client, "/api/bulk", paths=ALL, op={"kind": "set", "field": "releasedate", "value": value})
    assert r.status_code == 400 and r.get_json()["code"] == "bulk_bad_date"


def test_unknown_fields_and_ops_are_refused(folder, client):
    for op in ({"kind": "set", "field": "path", "value": "x"}, {"kind": "set", "field": "image", "value": "x"},
               {"kind": "replace", "fields": ["path"], "find": "a"}, {"kind": "clear_media", "fields": ["name"]},
               {"kind": "drop_table"}):
        r = post(client, "/api/bulk", paths=ALL, op=op)
        assert r.status_code == 400, op
    assert post(client, "/api/bulk", paths=[], op={"kind": "reset_name"}).status_code == 400


def test_replace_plain_text_is_literal_and_case_insensitive(folder, client):
    op = {"kind": "replace", "fields": "all", "find": "SHOOT'EM UP", "replace": "Shooter \\1"}
    data = preview(client, ALL, op)
    assert [(c["field"], c["after"]) for c in data["changes"]] == [("genre", "Shooter \\1 / Vertical")]
    assert preview(client, ALL, {**op, "case": True})["total"] == 0


def test_replace_regex_with_groups_in_one_field(folder, client):
    op = {"kind": "replace", "fields": ["name"], "find": r"^(\w)(\w+)$", "replace": r"\2-\1", "regex": True, "case": True}
    data = preview(client, ALL, op)
    assert {c["after"] for c in data["changes"]} == {"lpha-a", "ravo-B", "harlie-C", "elta-D"}
    res = apply(client, ALL, op)
    assert res["changed"] == 4
    assert games(folder)["./bravo.zip"].findtext("name") == "ravo-B"
    assert games(folder)[ALL[0]].findtext("desc") == "An Alpha game."      # other fields untouched


def test_replace_never_empties_a_name_and_can_clear_a_description(folder, client):
    assert preview(client, ALL, {"kind": "replace", "fields": ["name"], "find": ".*", "replace": "", "regex": True})["total"] == 0
    apply(client, ALL, {"kind": "replace", "fields": ["desc"], "find": "An Alpha game.", "replace": ""})
    assert games(folder)[ALL[0]].find("desc") is None


@pytest.mark.parametrize("find,replace", [("(", "x"), ("a", r"\5")])
def test_bad_regex_is_reported(folder, client, find, replace):
    r = post(client, "/api/bulk/preview", paths=ALL, op={"kind": "replace", "fields": "all", "find": find,
                                                          "replace": replace, "regex": True})
    assert r.status_code == 400 and r.get_json()["code"] == "bulk_bad_regex"


def test_empty_find_is_refused(folder, client):
    r = post(client, "/api/bulk/preview", paths=ALL, op={"kind": "replace", "fields": "all", "find": ""})
    assert r.get_json()["code"] == "bulk_no_find"


def test_clean_name():
    assert clean_name("./Alpha (Europe) [!].zip") == "Alpha (Europe) [!]"
    assert clean_name("./Alpha (Europe) [!].zip", True) == "Alpha"
    assert clean_name("./sub/Bravo - The Game (v1.1).7z", True) == "Bravo - The Game"
    assert clean_name("./(Europe).zip", True) == "(Europe)"             # never empty
    assert clean_name(".\\win\\Delta.zip") == "Delta"


def test_reset_names_from_file_names(folder, client):
    data = preview(client, ALL, {"kind": "reset_name", "strip_tags": True})
    assert [(c["before"], c["after"]) for c in data["changes"]] == [("alpha", "Alpha"), ("Bravo", "bravo"),
                                                                    ("Charlie", "charlie"), ("Delta", "delta")]
    apply(client, ALL[:1], {"kind": "reset_name", "strip_tags": False})
    assert games(folder)[ALL[0]].findtext("name") == "Alpha (Europe) [!]"


def test_clear_media_keeps_the_files(folder, client):
    res = apply(client, ALL, {"kind": "clear_media", "fields": ["image", "video"]})
    assert res["changed"] == 4
    g = games(folder)[ALL[0]]
    assert g.find("image") is None and g.find("video") is None and g.findtext("boxart")
    assert (folder / "images" / "alpha.png").exists() and (folder / "videos" / "alpha.mp4").exists()


def test_clear_fields_removes_whole_elements(folder, client):
    xml = (folder / "gamelist.xml").read_text(encoding="utf-8")
    xml = xml.replace("<name>Bravo</name>", "<name>Bravo</name><region>eu</region><region>us</region>", 1)
    xml = xml.replace("<name>Charlie</name>", "<name>Charlie</name><region/>", 1)    # an empty tag goes too
    xml = xml.replace("<name>Delta</name>", "<name>Delta</name><region>jp</region>", 1)
    (folder / "gamelist.xml").write_text(xml, encoding="utf-8")
    op = {"kind": "clear_fields", "fields": ["region", "genre", "favorite", "playcount"]}
    before = (folder / "gamelist.xml").read_bytes()
    data = preview(client, ALL[:3], op)                         # Delta is not in the scope
    assert data["games"] == 3
    assert sorted((c["path"], c["field"]) for c in data["changes"]) == sorted([
        (ALL[0], "genre"), (ALL[0], "favorite"), (ALL[0], "playcount"),
        (ALL[1], "region"), (ALL[1], "genre"), (ALL[2], "region")])
    assert all(c["after"] == "" for c in data["changes"])
    assert (folder / "gamelist.xml").read_bytes() == before     # a dry run
    res = apply(client, ALL[:3], op)
    assert res["games"] == 3 and res["changed"] == 6 and res["snapshot"]
    g = games(folder)
    for path in ALL[:3]:
        assert all(g[path].find(f) is None for f in op["fields"]), path
    assert g[ALL[3]].findtext("region") == "jp"                  # outside the scope
    assert g[ALL[0]].findtext("desc") == "An Alpha game." and g[ALL[0]].findtext("gametime") == "4000"
    assert g[ALL[0]].findtext("name") == "alpha" and g[ALL[0]].findtext("image") == "./images/alpha.png"
    assert (folder / "Alpha (Europe) [!].zip").read_bytes() == b"x" * 10   # ROMs untouched
    again = apply(client, ALL[:3], op)
    assert again["changed"] == 0 and again["snapshot"] is None


def test_clear_fields_undo_restores(folder, client):
    res = apply(client, ALL, {"kind": "clear_fields", "fields": ["genre", "desc"]})
    assert res["changed"] == 3
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": res["snapshot"]}).status_code == 200
    assert games(folder)[ALL[1]].findtext("genre") == "Shoot'em up / Vertical"
    assert games(folder)[ALL[0]].findtext("desc") == "An Alpha game."


@pytest.mark.parametrize("fields", [["name"], ["path"], ["image"], ["video"], ["region", "music"], [], "region"])
def test_clear_fields_refuses_name_path_and_media(folder, client, fields):
    r = post(client, "/api/bulk", paths=ALL, op={"kind": "clear_fields", "fields": fields})
    assert r.status_code == 400 and r.get_json()["code"] == "bulk_bad_field"


def test_field_counts_for_the_scope(folder, client):
    r = post(client, "/api/bulk/fields", paths=ALL[:2])
    assert r.status_code == 200
    data = r.get_json()
    assert data["games"] == 2
    assert data["counts"]["genre"] == 2 and data["counts"]["playcount"] == 1
    assert data["counts"]["region"] == 0 and data["counts"]["rating"] == 1
    assert "name" not in data["counts"] and "image" not in data["counts"]
    assert post(client, "/api/bulk/fields", paths=[]).status_code == 400


def test_purge_regions_route_is_gone(folder, client):
    assert post(client, "/api/purge-regions").status_code in (404, 405)


def test_nothing_to_change_makes_no_backup(folder, client):
    res = apply(client, ALL, {"kind": "set", "field": "genre", "value": "Platform"})
    assert res["changed"] == 3                                    # Alpha already had it
    again = apply(client, ALL, {"kind": "set", "field": "genre", "value": "Platform"})
    assert again == {"success": True, "changed": 0, "games": 0, "snapshot": None}


def test_undo_restores_the_snapshot(folder, client):
    before = {p: g.findtext("name") for p, g in games(folder).items()}
    res = apply(client, ALL, {"kind": "reset_name", "strip_tags": True})
    entries = client.get("/api/backups", headers=LOCAL).get_json()["backups"]
    assert res["snapshot"] in [e["id"] for e in entries]
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": res["snapshot"]}).status_code == 200
    assert {p: g.findtext("name") for p, g in games(folder).items()} == before


def test_stale_session_is_refused(folder, client):
    r = client.post("/api/bulk", headers={**LOCAL, "X-Gamelist-Session": "old"},
                    json={"paths": ALL, "op": {"kind": "reset_name"}})
    assert r.status_code == 409


# --- Removing games ------------------------------------------------------------------

def test_delete_preview_without_media_lists_only_games(folder, client):
    data = post(client, "/api/bulk-delete/preview", paths=ALL[:2]).get_json()
    assert data["games"] == 2 and data["names"] == ["alpha", "Bravo"]
    assert data["media"] == [] and data["media_total"] == 0


def test_delete_removes_entries_and_never_roms(folder, client, trashed):
    res = post(client, "/api/bulk-delete", paths=ALL).get_json()
    assert res["removed"] == 4 and res["deleted_files"] == [] and res["snapshot"]
    assert games(folder) == {}
    assert trashed == []                                           # media off by default
    for rom in ("Alpha (Europe) [!].zip", "bravo.zip", "charlie.zip", "delta.zip"):
        assert (folder / rom).exists()


def test_delete_with_media_keeps_shared_roms_and_outside_files(folder, client, trashed):
    data = post(client, "/api/bulk-delete/preview", paths=[ALL[0], ALL[2], ALL[3]], media=True).get_json()
    assert sorted(m["path"] for m in data["media"]) == ["./images/alpha.png", "./videos/alpha.mp4"]
    # shared.png: Bravo stays; ./charlie.zip as an image is a ROM; ../outside.png is outside the folder
    assert [k["path"] for k in data["kept"]] == ["./images/shared.png", "./charlie.zip"]
    res = post(client, "/api/bulk-delete", paths=[ALL[0], ALL[2], ALL[3]], media=True).get_json()
    assert sorted(res["deleted_files"]) == ["./images/alpha.png", "./videos/alpha.mp4"]
    assert sorted(p.replace("\\", "/").rsplit("/", 2)[-2] + "/" + p.replace("\\", "/").rsplit("/", 1)[-1]
                  for p in trashed) == ["images/alpha.png", "videos/alpha.mp4"]
    assert list(games(folder)) == ["./bravo.zip"]
    assert (folder / "images" / "shared.png").exists() and (folder / "charlie.zip").exists()
    assert (folder.parent / "outside.png").exists()


def test_delete_can_be_undone(folder, client, trashed):
    res = post(client, "/api/bulk-delete", paths=ALL[:2]).get_json()
    assert list(games(folder)) == ALL[2:]
    assert client.post("/api/backups/restore", headers=LOCAL, json={"id": res["snapshot"]}).status_code == 200
    assert list(games(folder)) == ALL


def test_delete_needs_games(folder, client):
    assert post(client, "/api/bulk-delete", paths=["./nope.zip"]).status_code == 400


# --- Statistics ----------------------------------------------------------------------

def test_stats(folder, client):
    d = client.get("/api/stats?required=image,boxart", headers=LOCAL).get_json()
    assert d["games"] == 4 and d["favorite"] == 1 and d["with_desc"] == 1 and d["rated"] == 1 and d["dated"] == 1
    assert d["played"] == 1 and d["playcount"] == 3 and d["gametime"] == 4000
    assert d["most_played"] == {"name": "alpha", "playcount": 3}
    media = {m["field"]: m for m in d["media"]}
    assert media["image"] == {"field": "image", "present": 2, "broken": 1, "missing": 1}   # ../outside.png counts
    assert media["marquee"]["broken"] == 1 and media["boxart"]["present"] == 2
    assert d["complete"] == 1                                       # only Alpha has image + boxart
    assert d["scraped"] == 3 and d["no_genre"] == 2
    assert sorted(g["genre"] for g in d["genres"]) == ["PLATFORM", "SHOOT'EM UP"] and d["genre_count"] == 2


def test_clear_fields_keeps_the_case_of_retroachievements_tags(folder, client):
    xml = (folder / "gamelist.xml").read_text(encoding="utf-8")
    xml = xml.replace("<name>Bravo</name>", "<name>Bravo</name><cheevosId>21620</cheevosId><cheevosHash>62AB</cheevosHash>", 1)
    (folder / "gamelist.xml").write_text(xml, encoding="utf-8")
    counts = post(client, "/api/bulk/fields", paths=ALL).get_json()["counts"]
    assert counts["cheevosId"] == 1 and counts["cheevosHash"] == 1
    res = apply(client, ALL, {"kind": "clear_fields", "fields": ["cheevosId", "cheevosHash"]})
    assert res["changed"] == 2
    assert games(folder)["./bravo.zip"].find("cheevosId") is None
