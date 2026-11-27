"""Background analyses with progress and Stop (gme/jobs.py): solid images,
ROM check, media check. A scan never writes; the apply reuses its report only
while the gamelist is unchanged."""
import threading
import time

from PIL import Image

from gme import jobs, solidimages, xml_store
from tests.conftest import LOCAL, names
from tests.test_solid_images import ALL, IMAGES, folder  # noqa: F401  (fixture)
from tests.test_romcheck import folder as rom_folder  # noqa: F401


def start(client, url, **body):
    r = client.post(url, headers=LOCAL, json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["job"]


def poll(client, job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}", headers=LOCAL).get_json()["job"]
        if job["state"] != "running":
            return job
        time.sleep(0.01)
    raise AssertionError("job still running")


def test_solid_scan_job_matches_the_preview(folder, client):
    body = {"paths": ALL, "fields": IMAGES, "files": True}
    preview = client.post("/api/solid-images/preview", headers=LOCAL, json=body).get_json()
    job = poll(client, start(client, "/api/solid-images/scan", **body)["id"])
    assert job["state"] == "done"
    assert job["result"] == preview
    assert job["total"] == preview["files_checked"] and job["done"] == job["total"]


def test_solid_apply_reuses_the_scan(folder, client, monkeypatch):
    body = {"paths": ALL, "fields": IMAGES, "files": False}
    job = poll(client, start(client, "/api/solid-images/scan", **body)["id"])
    calls = []
    monkeypatch.setattr(solidimages, "file_colour", lambda f: calls.append(f) or (None, 0, 0))
    r = client.post("/api/solid-images", headers=LOCAL, json=dict(body, job=job["id"]))
    d = r.get_json()
    assert r.status_code == 200, d
    assert d["removed"] == job["result"]["total"] and not calls       # no second scan
    h = client.get("/api/history", headers=LOCAL).get_json()
    assert h["undo"]["label"] == {"key": "solid", "params": {"n": d["removed"]}}


def test_solid_apply_refuses_a_stale_scan(folder, client):
    body = {"paths": ALL, "fields": IMAGES, "files": False}
    job = poll(client, start(client, "/api/solid-images/scan", **body)["id"])
    # an image is replaced after the scan: the report no longer says what is on disk
    Image.new("RGB", (100, 100), (0, 0, 0)).save(str(folder / "images" / "red.png"))
    import os
    os.utime(str(folder / "images" / "red.png"), ns=(1, 1))
    before = (folder / "gamelist.xml").read_bytes()
    r = client.post("/api/solid-images", headers=LOCAL, json=dict(body, job=job["id"]))
    assert r.status_code == 409 and r.get_json()["code"] == "scan_stale"
    assert (folder / "gamelist.xml").read_bytes() == before
    # another body than the scanned one: stale too
    job = poll(client, start(client, "/api/solid-images/scan", **body)["id"])
    r = client.post("/api/solid-images", headers=LOCAL, json=dict(body, fields=["image"], job=job["id"]))
    assert r.status_code == 409


def test_gamelist_change_makes_the_scan_stale(folder, client):
    body = {"paths": ALL, "fields": IMAGES, "files": False}
    job = poll(client, start(client, "/api/solid-images/scan", **body)["id"])
    client.post("/api/game/2?path=./charlie.zip", headers=LOCAL, json={"name": "Charlie 2"})
    r = client.post("/api/solid-images", headers=LOCAL, json=dict(body, job=job["id"]))
    assert r.status_code == 409


def test_stop_a_slow_scan_writes_nothing(folder, client, monkeypatch):
    gate = threading.Event()
    real = solidimages.file_colour

    def slow(full):
        gate.wait(5)
        return real(full)

    monkeypatch.setattr(solidimages, "file_colour", slow)
    before = (folder / "gamelist.xml").read_bytes()
    images = sorted(p.read_bytes() for p in (folder / "images").iterdir())
    job = start(client, "/api/solid-images/scan", paths=ALL, fields=IMAGES, files=True)
    assert job["state"] == "running"
    r = client.post(f"/api/jobs/{job['id']}/stop", headers=LOCAL)
    assert r.status_code == 200
    gate.set()
    job = poll(client, job["id"])
    assert job["state"] == "stopped" and "result" not in job
    assert (folder / "gamelist.xml").read_bytes() == before
    assert sorted(p.read_bytes() for p in (folder / "images").iterdir()) == images
    r = client.post("/api/solid-images", headers=LOCAL, json={"paths": ALL, "fields": IMAGES, "job": job["id"]})
    assert r.status_code == 409


def test_progress_is_reported_while_running(folder, client, monkeypatch):
    release = threading.Event()
    seen = []
    real = solidimages.file_colour

    def slow(full):
        seen.append(full)
        if len(seen) > 1:
            release.wait(5)
        return real(full)

    monkeypatch.setattr(solidimages, "WORKERS", 1)
    monkeypatch.setattr(solidimages, "file_colour", slow)
    job = start(client, "/api/solid-images/scan", paths=ALL, fields=IMAGES)
    end = time.time() + 5
    while time.time() < end:
        j = client.get(f"/api/jobs/{job['id']}", headers=LOCAL).get_json()["job"]
        if j["done"] >= 1:
            break
        time.sleep(0.01)
    assert j["state"] == "running" and j["total"] > 1 and 1 <= j["done"] < j["total"] and j["current"]
    release.set()
    assert poll(client, job["id"])["state"] == "done"


def test_unknown_job(client):
    assert client.get("/api/jobs/nope", headers=LOCAL).status_code == 404
    assert client.post("/api/jobs/nope/stop", headers=LOCAL).status_code == 404


def test_romcheck_scan_and_apply_with_the_job(rom_folder, client):
    report = client.get("/api/check-roms", headers=LOCAL).get_json()
    job = poll(client, start(client, "/api/check-roms/scan")["id"])
    assert job["state"] == "done" and job["result"] == report
    xml = rom_folder / "gamelist.xml"
    r = client.post("/api/check-roms/apply", headers=LOCAL,
                    json={"add": [report["unlisted"][0]["path"]], "backup": False, "job": job["id"]})
    d = r.get_json()
    assert r.status_code == 200, d
    assert d["added"] == 1 and d["report"] is None          # the page scans again (progress)
    assert report["unlisted"][0]["name"] in names(xml)
    # the gamelist changed: that report is stale now
    r = client.post("/api/check-roms/apply", headers=LOCAL,
                    json={"add": [report["unlisted"][1]["path"]], "job": job["id"]})
    assert r.status_code == 409 and r.get_json()["code"] == "scan_stale"
    h = client.get("/api/history", headers=LOCAL).get_json()
    assert h["undo"]["label"]["key"] == "romcheck"


def test_romcheck_stop(rom_folder, client, monkeypatch):
    from gme import romcheck
    gate = threading.Event()
    real = romcheck._entry_full
    monkeypatch.setattr(romcheck, "_entry_full", lambda p: (gate.wait(5), real(p))[1])
    job = start(client, "/api/check-roms/scan")
    client.post(f"/api/jobs/{job['id']}/stop", headers=LOCAL)
    gate.set()
    assert poll(client, job["id"])["state"] == "stopped"


def test_mediacheck_scan_and_apply_with_the_job(rom_folder, client):
    (rom_folder / "images" / "gone-image.png").unlink()        # a broken link
    report = client.get("/api/check-media", headers=LOCAL).get_json()
    job = poll(client, start(client, "/api/check-media/scan")["id"])
    assert job["state"] == "done" and job["result"] == report
    assert report["broken"], report
    b = report["broken"][0]
    r = client.post("/api/check-media/apply", headers=LOCAL,
                    json={"unlink": [{"path": b["path"], "tag": b["tag"]}], "backup": False, "job": job["id"]})
    d = r.get_json()
    assert r.status_code == 200, d
    assert d["unlinked"] == 1 and d["report"] is None
    h = client.get("/api/history", headers=LOCAL).get_json()
    assert h["undo"]["label"] == {"key": "mediacheck", "params": {"n": 1}}
    client.post("/api/history/undo", headers=LOCAL)
    assert b["value"] in (rom_folder / "gamelist.xml").read_text(encoding="utf-8")


def test_a_new_scan_stops_the_previous_one_of_its_kind(folder, client, monkeypatch):
    gate = threading.Event()
    real = solidimages.file_colour
    monkeypatch.setattr(solidimages, "file_colour", lambda f: (gate.wait(5), real(f))[1])
    first = start(client, "/api/solid-images/scan", paths=ALL, fields=IMAGES)
    second = start(client, "/api/solid-images/scan", paths=ALL, fields=IMAGES)
    gate.set()
    assert poll(client, first["id"])["state"] == "stopped"
    assert poll(client, second["id"])["state"] == "done"


def test_switching_gamelist_discards_the_result(folder, client, monkeypatch, tmp_path):
    gate = threading.Event()
    real = solidimages.file_colour
    monkeypatch.setattr(solidimages, "file_colour", lambda f: (gate.wait(5), real(f))[1])
    job = start(client, "/api/solid-images/scan", paths=ALL, fields=IMAGES)
    xml_store.set_gamelist_path(str(folder / "gamelist.xml"))     # a new session
    gate.set()
    done = poll(client, job["id"])
    assert done["state"] == "error"
    assert jobs.reusable(job["id"], "solid") is None
