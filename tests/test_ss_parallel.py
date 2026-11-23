"""Parallel ScreenScraper batch scrape: never more than the member's limits.

A fake ScreenScraper (requests.get replaced) counts the requests in flight,
API calls and media downloads together, the way ScreenScraper counts threads.
"""
import json
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from lxml import etree

from gme import batch_jobs, remote_cache, xml_store
from gme.i18n import st
from gme.scrapers import ss, ss_limits
from gme.scrapers.ss_limits import Cancelled, RateLimiter, SSBlocked, SSGate
from conftest import LOCAL, picture

PNG = picture()


# --- Requests per minute (fake clock) -------------------------------------------

def run_limiter(limiter, n):
    """Start n requests as soon as allowed; returns their start times (fake clock)."""
    now, starts = 0.0, []
    while len(starts) < n:
        wait = limiter.reserve(now)
        if wait:
            now += wait
        else:
            starts.append(now)
    return starts


def max_in_window(starts, window=60.0):
    return max(sum(1 for t in starts if s <= t < s + window) for s in starts)


@pytest.mark.parametrize("per_minute", [10, 60, 300, 1200])
def test_rate_limiter_never_exceeds_the_per_minute_limit(per_minute):
    limiter = RateLimiter(per_minute)
    starts = run_limiter(limiter, per_minute * 3)
    allowed = per_minute - max(1, per_minute // 10)          # 10 % margin
    assert limiter.per_minute == allowed
    assert max_in_window(starts) <= allowed < per_minute
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert min(gaps) >= 60.0 / allowed - 1e-9                 # evenly spaced: no burst


def test_unknown_limit_keeps_the_historical_spacing():
    starts = run_limiter(RateLimiter(None), 20)
    assert min(b - a for a, b in zip(starts, starts[1:])) >= ss_limits.DEFAULT_INTERVAL - 1e-9


def test_a_waiting_request_is_not_counted():
    limiter = RateLimiter(10)
    assert limiter.reserve(0.0) == 0
    assert limiter.reserve(1.0) > 0
    assert limiter.in_last_minute(1.0) == 1


# --- Threads -------------------------------------------------------------------------

def hammer(gate, n=24, hold=0.02, fill=8):
    """n threads try to send a request at once; returns the peak in flight.

    Each request waits (up to 0.5 s) for ``fill`` requests in flight before
    ending, so a slow CI machine still shows every slot the gate allows."""
    lock, state = threading.Lock(), {"now": 0, "peak": 0}

    def one():
        with gate.slot():
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                with lock:
                    if state["now"] >= fill:
                        break
                time.sleep(0.005)
            time.sleep(hold)
            with lock:
                state["now"] -= 1

    threads = [threading.Thread(target=one) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    return state["peak"]


def fast_gate(maxthreads, logged_in=True, user_threads=0):
    gate = SSGate()
    gate.set_account("member" if logged_in else None, user_threads)
    gate.update_from_user({"maxthreads": str(maxthreads), "maxrequestspermin": "60000"})
    gate._rate._next = 0.0
    return gate


@pytest.mark.parametrize("maxthreads, logged_in, setting, expected", [
    (3, True, 0, 3),        # Auto = maxthreads
    (4, True, 2, 2),        # the setting lowers it
    (2, True, 8, 2),        # ...never raises it
    (5, False, 0, 1),       # no member login: 1 thread
])
def test_concurrency_never_exceeds_maxthreads(maxthreads, logged_in, setting, expected):
    gate = fast_gate(maxthreads, logged_in, setting)
    assert gate.thread_limit() == expected
    assert hammer(gate, fill=expected) == expected     # used, and never more
    assert gate.peak == expected


def test_unknown_limits_mean_one_thread():
    gate = SSGate()
    gate.set_account("member")
    assert gate.thread_limit() == 1


def test_a_lower_maxthreads_in_an_answer_applies_to_the_next_requests():
    gate = fast_gate(4)
    assert hammer(gate, fill=4) == 4
    gate.update_from_user({"maxthreads": "2"})
    gate.peak = 0
    assert hammer(gate, n=8, fill=4) == 2                     # waits for 4, gets 2


def test_http_429_drops_to_one_thread_then_recovers():
    clock = {"t": 1000.0}
    gate = SSGate(clock=lambda: clock["t"])
    gate.set_account("member")
    gate.update_from_user({"maxthreads": "4"})
    assert gate.note_status(429)
    assert gate.thread_limit() == 1
    clock["t"] += ss_limits.PENALTY_SECONDS + 1
    assert gate.thread_limit() == 4


@pytest.mark.parametrize("status, key", [(430, "server.ss_quota_day"), (431, "server.ss_quota_ko"),
                                          (423, "server.ss_api_closed"), (426, "server.ss_blacklisted"),
                                          (401, "server.ss_busy")])
def test_quota_and_ban_statuses_stop_every_request(status, key):
    clock = {"t": 0.0}
    gate = SSGate(clock=lambda: clock["t"])
    gate.note_status(status)
    with pytest.raises(SSBlocked) as err:
        with gate.slot():
            pass
    assert err.value.key == key and err.value.status == status
    clock["t"] += ss_limits.COOLDOWNS[status][0] + 1
    with gate.slot():
        pass


def test_daily_quota_is_respected_before_ScreenScraper_refuses():
    gate = fast_gate(2)
    gate.update_from_user({"requeststoday": "98", "maxrequestsperday": "100"})
    for _ in range(2):
        with gate.slot():
            pass
    with pytest.raises(SSBlocked) as err:
        with gate.slot():
            pass
    assert err.value.status == 430
    gate.update_from_user({"requestskotoday": "50", "maxrequestskoperday": "50", "requeststoday": "0"})
    with pytest.raises(SSBlocked) as err:
        with gate.slot():
            pass
    assert err.value.status == 431


def test_a_stopped_batch_stops_waiting_at_once():
    gate = fast_gate(1)
    cancel = threading.Event()
    entered, out = threading.Event(), {}

    def holder():
        with gate.slot():
            entered.set()
            time.sleep(1.0)

    def waiter():
        start = time.monotonic()
        try:
            with gate.slot(cancel=cancel):
                out["ran"] = True
        except Cancelled:
            out["cancelled"] = time.monotonic() - start

    threading.Thread(target=holder).start()
    entered.wait(2)
    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)
    cancel.set()
    t.join(2)
    assert "ran" not in out and out["cancelled"] < 0.6


def test_rate_limit_is_shared_by_all_threads():
    gate = SSGate()
    gate.set_account("member")
    gate.update_from_user({"maxthreads": "4", "maxrequestspermin": "600"})   # 540/min: one per 0.111 s
    gate._rate._next = 0.0
    starts, lock = [], threading.Lock()

    def one():
        with gate.slot():
            with lock:
                starts.append(time.monotonic())

    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    starts.sort()
    assert min(b - a for a, b in zip(starts, starts[1:])) >= 60 / 540 - 0.03     # Windows clock: ~16 ms resolution


# --- A fake ScreenScraper ------------------------------------------------------------

class Resp:
    def __init__(self, status=200, payload=None, content=b"", text=None):
        self.status_code = status
        self._payload = payload
        self.content = content if payload is None else json.dumps(payload).encode()
        self.text = text if text is not None else self.content.decode("latin-1")
        self.headers = {"content-type": "image/png" if payload is None else "application/json"}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, size):
        yield self.content

    def close(self):
        pass


class FakeSS:
    """API + media server; counts requests in flight like ScreenScraper counts threads."""

    def __init__(self, maxthreads=2, delays=None, delay=0.05):
        self.maxthreads = maxthreads
        self.delays = delays or {}
        self.delay = delay
        self.lock = threading.Lock()
        self._progress = threading.Condition(self.lock)
        self.active = self.peak = 0
        self._inflight_roms = {}
        self._finished = {}              # rom → endpoints that have completed a request
        self.calls = []
        self.refuse_from = None          # rom name: from it on, every API call gets this status
        self.refusing = None
        # Roms that must finish their lookup (API + media) before refuse_from answers.
        self.ready_before_refuse = None

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        parsed = urlparse(url)
        params = dict(params or {})
        params.update({k: v[0] for k, v in parse_qs(parsed.query).items()})
        endpoint = parsed.path.rsplit("/", 1)[-1]
        rom = params.get("romnom") or params.get("game") or ""
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self._inflight_roms[rom] = self._inflight_roms.get(rom, 0) + 1
            self.calls.append((time.monotonic(), endpoint, rom))
        try:
            time.sleep(self.delays.get(rom, self.delay))
            # A 430 must not race a lookup already in flight: wait until the
            # earlier games have finished their media download, then refuse.
            if self.ready_before_refuse and self.refuse_from and rom == self.refuse_from:
                self.wait_until_ready(self.ready_before_refuse)
            return self.answer(parsed.path, params, rom)
        finally:
            with self.lock:
                self.active -= 1
                self._inflight_roms[rom] -= 1
                if self._inflight_roms[rom] <= 0:
                    del self._inflight_roms[rom]
                self._finished.setdefault(rom, set()).add(endpoint)
                self._progress.notify_all()

    def wait_until_ready(self, roms, endpoint="mediaJeu.php", timeout=10):
        """Block until each rom has completed ``endpoint`` and has no request in flight.

        Used so a quota refusal is only issued after the games running in
        parallel have finished their own lookups, without a sleep.
        """
        roms = list(roms)

        def done():
            return all(
                endpoint in self._finished.get(rom, ()) and rom not in self._inflight_roms
                for rom in roms
            )

        with self._progress:
            if not self._progress.wait_for(done, timeout=timeout):
                finished = {rom: sorted(self._finished.get(rom, ())) for rom in roms}
                raise AssertionError(
                    f"timed out waiting for {roms} to finish {endpoint}: "
                    f"finished={finished} inflight={dict(self._inflight_roms)}"
                )

    def answer(self, path, params, rom):
        if "mediaJeu" in path:
            return Resp(content=PNG)
        if self.refuse_from and rom == self.refuse_from:
            self.refusing = 430
        if self.refusing:
            return Resp(self.refusing, text="Votre quota de scrape est dépassé pour aujourd'hui !")
        user = {"id": "member", "maxthreads": str(self.maxthreads), "maxrequestspermin": "60000",
                "requeststoday": str(len(self.calls)), "maxrequestsperday": "20000"}
        if path.endswith("ssuserInfos.php"):
            return Resp(payload={"header": {"success": "true"}, "response": {"ssuser": user}})
        if path.endswith("jeuInfos.php") and rom:
            name = rom[:-4].title()
            jeu = {"id": "1", "noms": [{"region": "wor", "text": name}],
                   "developpeur": {"text": "Studio " + name},
                   "medias": [{"type": "ss", "region": "wor",
                               "url": f"https://neoclone.screenscraper.fr/api2/mediaJeu.php?media=ss&game={rom}"}]}
            return Resp(payload={"header": {"success": "true"}, "response": {"ssuser": user, "jeu": jeu}})
        return Resp(404, text="Erreur : Jeu non trouvée !")


ROMS = [f"game{n}.zip" for n in range(8)]


@pytest.fixture
def big_gamelist(tmp_path):
    folder = tmp_path / "unknownsystem"
    folder.mkdir()
    games = "".join(f"<game><path>./{rom}</path><name>{rom[:-4]}</name></game>" for rom in ROMS)
    xml = folder / "gamelist.xml"
    xml.write_text(f'<?xml version="1.0"?><gameList>{games}</gameList>', encoding="utf-8")
    for rom in ROMS:
        (folder / rom).write_bytes(rom.encode())
    xml_store.set_gamelist_path(str(xml))
    yield xml
    xml_store.close_gamelist()


@pytest.fixture
def fake_ss(monkeypatch, tmp_path, ss_config_file):
    def make(member=True, threads=0, **kwargs):
        server = FakeSS(**kwargs)
        monkeypatch.setattr(requests, "get", server.get)
        monkeypatch.setattr(remote_cache, "CACHE_DIR", str(tmp_path / "remote-cache"))
        config = {"ssid": "member", "sspassword": "pw"} if member else {}
        ss_config_file.write_text(json.dumps({**config, "threads": threads}), encoding="utf-8")
        return server
    return make


def start(client, paths=None, fields=("developer", "image")):
    r = client.post("/api/batch", headers=LOCAL, json={
        "source": "screenscraper", "mode": "missing", "fields": list(fields),
        "paths": paths or [f"./{rom}" for rom in ROMS], "backup": False})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["job"]


def run_all(client, job):
    responses = []
    while job["i"] < len(job["targets"]) and not job.get("halted"):
        data = client.post("/api/batch/step", headers=LOCAL,
                           json={"id": job["id"], "owner": job["owner"], "i": job["i"]}).get_json()
        responses.append(data)
        if "job" in data:
            return responses
        job["i"], job["halted"] = data["i"], data["halted"]
    return responses


def developers(xml):
    return [g.findtext("developer") for g in etree.parse(str(xml)).getroot().findall("game")]


def journal(job):
    return [json.loads(line) for line in Path(batch_jobs._events_path(job)).read_text(encoding="utf-8").splitlines()]


def test_batch_runs_maxthreads_lookups_at_once_and_writes_in_list_order(big_gamelist, client, fake_ss):
    # The first game is the slowest: the others finish first, but are written after it.
    server = fake_ss(maxthreads=2, delay=0.1, delays={"game0.zip": 0.5})
    job = start(client)
    responses = run_all(client, job)
    assert server.peak == 2                              # parallel, and never above maxthreads
    assert ss_limits.GATE.peak <= 2
    assert developers(big_gamelist) == ["Studio " + rom[:-4].title() for rom in ROMS]
    events = journal(job)
    assert [e["i"] for e in events] == list(range(1, len(ROMS) + 1))
    assert [e["game"]["path"] for e in events] == [f"./{rom}" for rom in ROMS]
    assert all(e["kind"] == "updated" and e["game"]["fields"] == ["developer", "image"] for e in events)
    assert all((big_gamelist.parent / "images" / f"{rom[:-4]}-image.png").is_file() for rom in ROMS)
    threads = responses[0]["threads"]
    assert threads["limit"] == 2 and threads["maxthreads"] == 2 and threads["per_day"] == 20000
    assert max(r["threads"]["workers"] for r in responses) == 2          # "Threads: 2/2"
    assert all(r["threads"]["workers"] <= r["threads"]["limit"] for r in responses)


@pytest.mark.parametrize("member, setting, maxthreads, expected", [
    (True, 1, 4, 1),       # the setting
    (False, 0, 4, 1),      # no member login
    (True, 0, 3, 3),
])
def test_batch_peak_follows_the_allowed_threads(big_gamelist, client, fake_ss, member, setting, maxthreads, expected):
    server = fake_ss(member=member, threads=setting, maxthreads=maxthreads, delay=0.15)
    run_all(client, start(client))
    assert server.peak == expected
    assert developers(big_gamelist).count(None) == 0


def test_two_batches_and_single_requests_share_one_limit(big_gamelist, client, fake_ss):
    server = fake_ss(maxthreads=2, delay=0.06)
    job = start(client)
    stop = threading.Event()

    def extra_requests():
        while not stop.is_set():
            ss.ss_request("jeuInfos.php", {"romnom": "other.zip"})

    others = [threading.Thread(target=extra_requests) for _ in range(3)]
    for t in others:
        t.start()
    try:
        run_all(client, job)
    finally:
        stop.set()
        for t in others:
            t.join(5)
    assert server.peak == 2
    assert developers(big_gamelist).count(None) == 0


def test_stop_ends_every_worker_and_resume_finishes_the_rest(big_gamelist, client, fake_ss, app_client):
    server = fake_ss(maxthreads=3, delay=0.3)
    job = start(client)
    out = {}
    worker = threading.Thread(target=lambda: out.update(run=run_all(app_client(), dict(job))))
    worker.start()
    deadline = time.monotonic() + 5
    while len([c for c in server.calls if c[1] == "jeuInfos.php"]) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    stop_at = time.monotonic()
    r = client.post("/api/batch/stop", headers=LOCAL, json={"id": job["id"], "owner": job["owner"]})
    assert r.status_code == 200
    worker.join(5)
    assert not worker.is_alive()
    assert time.monotonic() - stop_at < 2.0                  # within one request
    time.sleep(0.05)
    sent = len(server.calls)
    time.sleep(0.6)
    assert len(server.calls) == sent                          # nothing more is sent
    assert not [c for c in server.calls if c[0] > stop_at + 0.05]
    saved = client.get("/api/batch", headers=LOCAL).get_json()["job"]
    assert saved["i"] < len(ROMS)
    resumed = client.post("/api/batch/claim", headers=LOCAL, json={"id": job["id"]}).get_json()["job"]
    run_all(client, resumed)
    events = journal(job)
    assert [e["game"]["path"] for e in events] == [f"./{rom}" for rom in ROMS]   # each game once, in order
    assert developers(big_gamelist).count(None) == 0


def test_daily_quota_answer_halts_the_batch_and_nothing_more_is_sent(big_gamelist, client, fake_ss):
    server = fake_ss(maxthreads=2, delay=0.05)
    server.refuse_from = "game3.zip"
    # With 2 threads, game2 is still in flight when game3 is requested. Wait
    # until games 0–2 have finished so the 430 cannot also refuse game2.
    server.ready_before_refuse = ROMS[:3]
    job = start(client)
    run_all(client, job)
    saved = client.get("/api/batch", headers=LOCAL).get_json()["job"]
    assert saved["halted"] == st("server.ss_quota_day")
    assert [g["path"] for g in saved["results"]["updated"]] == ["./game0.zip", "./game1.zip", "./game2.zip"]
    assert saved["results"]["errors"][-1]["path"] == "./game3.zip"
    refused = [c for c in server.calls if c[2] == "game3.zip" and c[1] == "jeuInfos.php"]
    assert len(refused) == 1                                  # no retry against a 430
    time.sleep(0.3)
    sent = len(server.calls)
    assert client.post("/api/ss/scrape/5?path=./game5.zip", headers=LOCAL, json={}).status_code == 503
    assert len(server.calls) == sent                          # refused locally, not sent
    # Tomorrow: the quota is back; resuming finishes the remaining games.
    ss_limits.GATE.reset()
    server.refusing = server.refuse_from = None
    resumed = client.post("/api/batch/claim", headers=LOCAL, json={"id": job["id"]}).get_json()["job"]
    run_all(client, resumed)
    assert developers(big_gamelist) == [None if rom == "game3.zip" else "Studio " + rom[:-4].title() for rom in ROMS]
    retry = client.post("/api/batch/claim", headers=LOCAL, json={"id": job["id"], "retry": True}).get_json()["job"]
    assert [g["path"] for g in retry["targets"]] == ["./game3.zip"]
    run_all(client, retry)
    assert developers(big_gamelist).count(None) == 0


def test_http_429_retries_on_one_thread(monkeypatch, fake_ss, big_gamelist):
    server = fake_ss(maxthreads=4)
    answers = iter([Resp(429, text="The maximum threads is already used")])
    real = server.answer
    monkeypatch.setattr(server, "answer", lambda *a: next(answers, None) or real(*a))
    monkeypatch.setattr(ss, "_RETRY_429", (0.01, 0.01))
    ok, data, status = ss.ss_request("jeuInfos.php", {"romnom": "game0.zip"})
    assert ok and status == 200
    assert ss_limits.GATE.limits["maxthreads"] == 4
    assert ss_limits.GATE.thread_limit() == 1                 # penalty after the 429


def test_thread_setting_is_saved_and_clamped(client, fake_ss):
    fake_ss(maxthreads=2)
    r = client.post("/api/ss/config", headers=LOCAL, json={"threads": 99})
    assert r.get_json()["config"]["threads"] == 0             # out of range: Auto
    r = client.post("/api/ss/config", headers=LOCAL, json={"threads": 6})
    cfg = r.get_json()["config"]
    assert cfg["threads"] == 6
    ss.ss_request("ssuserInfos.php")
    assert ss_limits.GATE.thread_limit() == 2                 # 6 asked, 2 allowed
    assert client.get("/api/ss/config", headers=LOCAL).get_json()["limits"]["maxthreads"] == 2


@pytest.fixture
def app_client():
    from gme.server import app
    return app.test_client


def test_a_refused_media_download_halts_the_batch(big_gamelist, client, fake_ss, monkeypatch):
    server = fake_ss(maxthreads=2, delay=0.02)
    real = server.answer

    def answer(path, params, rom):
        if "mediaJeu" in path and rom == "game1.zip":
            # game0 runs in the other slot; let it finish before the 430
            # blocks the gate and would otherwise fail that lookup too.
            server.wait_until_ready(["game0.zip"])
            return Resp(430, text="Votre quota de scrape est dépassé pour aujourd'hui !")
        return real(path, params, rom)

    monkeypatch.setattr(server, "answer", answer)
    job = start(client)
    run_all(client, job)
    saved = client.get("/api/batch", headers=LOCAL).get_json()["job"]
    assert saved["halted"] == st("server.ss_quota_day")
    assert saved["i"] == 2                                     # stopped at that game
    assert saved["results"]["errors"][-1]["path"] == "./game1.zip"
    time.sleep(0.3)
    sent = len(server.calls)
    time.sleep(0.3)
    assert len(server.calls) == sent
