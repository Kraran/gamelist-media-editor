"""ScreenScraper limits shared by the whole process: threads, requests per minute, daily quota.

ScreenScraper bans software that does not respect the limits it reports for
each member (https://www.screenscraper.fr/webapi2.php, "Quota"):

* ``ssuser.maxthreads``          simultaneous requests allowed for the member
* ``ssuser.maxrequestspermin``   requests per minute (the docs also spell it
  ``maxrequestsperdmin``; both are read)
* ``ssuser.maxrequestsperday`` / ``requeststoday``          daily quota
* ``ssuser.maxrequestskoperday`` / ``requestskotoday``      daily "not found" quota

Every API call *and* every media download (``mediaJeu.php`` and
``mediaVideoJeu.php`` are API calls too) goes through the single ``GATE``
below, whatever started it: a batch worker, a single-game scrape, a preview.
So two batches, or a batch and a single scrape, can never add up to more
than the member's limits.

* Threads: a semaphore whose size is re-read from every answer. Without a
  member login, or before ScreenScraper said anything, it is 1. The setting
  in Settings can lower it, never raise it above ``maxthreads``.
* Requests per minute: requests start evenly spaced (60 / limit seconds) and
  never more than the limit in any 60-second window. A 10 % margin is kept
  because ScreenScraper counts on its own clock. Unknown limit: one request
  every 1.1 s, as before parallel scraping.
* Daily quota: once the reported count (plus the requests sent since that
  report) reaches the quota, nothing more is sent.
* HTTP 429 (too many threads / requests per minute): 1 thread for two
  minutes, then the reported limit again. 430/431 (daily quotas), 423 (API
  closed), 426 (software blacklisted) and 401 (server saturated): nothing is
  sent for a while; every request fails at once with the reason.
"""

import threading
import time
from collections import deque
from contextlib import contextmanager
from urllib.parse import urlparse

DEFAULT_INTERVAL = 1.1          # unknown requests-per-minute limit: the historical spacing
WINDOW = 60.0
PENALTY_SECONDS = 120.0         # after HTTP 429
MAX_USER_THREADS = 32           # sanity bound for the setting (ScreenScraper decides anyway)
# HTTP status -> (seconds without any request, translation key of the reason)
COOLDOWNS = {
    401: (120.0, "server.ss_busy"),
    423: (600.0, "server.ss_api_closed"),
    426: (3600.0, "server.ss_blacklisted"),
    430: (1800.0, "server.ss_quota_day"),
    431: (1800.0, "server.ss_quota_ko"),
}
QUOTA_STATUSES = frozenset(COOLDOWNS) | {429}


class Cancelled(Exception):
    """The batch that asked for this request was stopped."""

    def __str__(self):
        from gme.i18n import st
        return st("batch.stopped_short")


class SSBlocked(Exception):
    """ScreenScraper must not be called now; ``key`` is the reason to show."""

    def __init__(self, key, status):
        super().__init__(key)
        self.key = key
        self.status = status

    def __str__(self):
        from gme.i18n import st
        return st(self.key)


def is_ss_url(url):
    host = (urlparse(url or "").hostname or "").lower()
    return host == "screenscraper.fr" or host.endswith(".screenscraper.fr")


def _int(value):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


class RateLimiter:
    """Requests per minute, without bursts. Pure: the caller gives the time.

    ``reserve(now)`` returns 0 and counts a request when one may start at
    ``now``, else the number of seconds to wait (nothing is counted).
    """

    def __init__(self, per_minute=None):
        self.per_minute = None
        self._starts = deque()
        self._next = 0.0
        self.set_limit(per_minute)

    def set_limit(self, per_minute):
        per_minute = _int(per_minute)
        if per_minute:
            # ScreenScraper counts on its own clock: keep a 10 % margin.
            per_minute = max(1, per_minute - max(1, per_minute // 10))
        self.per_minute = per_minute or None

    @property
    def interval(self):
        return WINDOW / self.per_minute if self.per_minute else DEFAULT_INTERVAL

    def reserve(self, now):
        while self._starts and now - self._starts[0] >= WINDOW:
            self._starts.popleft()
        wait = self._next - now
        if self.per_minute and len(self._starts) >= self.per_minute:
            wait = max(wait, self._starts[0] + WINDOW - now)
        if wait > 0:
            return wait
        self._starts.append(now)
        self._next = now + self.interval
        return 0.0

    def in_last_minute(self, now):
        return sum(1 for t in self._starts if now - t < WINDOW)


_local = threading.local()


@contextmanager
def cancel_scope(event):
    """Requests made by this thread inside the block stop waiting once ``event`` is set."""
    previous = getattr(_local, "cancel", None)
    _local.cancel = event
    try:
        yield
    finally:
        _local.cancel = previous


def current_cancel():
    return getattr(_local, "cancel", None)


class SSGate:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._cond = threading.Condition()
        self._rate = RateLimiter()
        self.active = 0
        self.peak = 0
        self.logged_in = False
        self.account = None
        self.user_threads = 0           # 0 = Auto (the member's maxthreads)
        self.limits = {}
        self._since_report = 0
        self._penalty_until = 0.0
        self._blocked_until = 0.0
        self._blocked = None            # (key, status)

    # --- what ScreenScraper reported ---------------------------------------
    def set_account(self, account, user_threads=0):
        """``account``: member login or None (developer credentials only)."""
        with self._cond:
            if account != self.account:
                self.account = account
                self.limits = {}
                self._since_report = 0
                self._rate.set_limit(None)
            self.logged_in = bool(account)
            self.user_threads = max(0, min(MAX_USER_THREADS, _int(user_threads) or 0))
            self._cond.notify_all()

    def update_from_user(self, ssuser):
        """Read the limits from an ``ssuser`` object (any API answer, or ssuserInfos)."""
        if not isinstance(ssuser, dict):
            return
        values = {
            "maxthreads": _int(ssuser.get("maxthreads")),
            "maxrequestspermin": _int(ssuser.get("maxrequestspermin", ssuser.get("maxrequestsperdmin"))),
            "maxrequestsperday": _int(ssuser.get("maxrequestsperday")),
            "requeststoday": _int(ssuser.get("requeststoday")),
            "maxrequestskoperday": _int(ssuser.get("maxrequestskoperday")),
            "requestskotoday": _int(ssuser.get("requestskotoday")),
            "maxdownloadspeed": _int(ssuser.get("maxdownloadspeed")),
        }
        with self._cond:
            for key, value in values.items():
                if value is not None:
                    self.limits[key] = value
            if values["requeststoday"] is not None:
                self._since_report = 0
            if values["maxrequestspermin"] is not None:
                self._rate.set_limit(values["maxrequestspermin"])
            self.limits["updated"] = time.time()
            self._cond.notify_all()

    def known(self):
        with self._cond:
            return bool(self.limits.get("maxthreads"))

    def thread_limit(self):
        with self._cond:
            return self._thread_limit()

    def _thread_limit(self):
        n = self.limits.get("maxthreads") if self.logged_in else None
        n = n or 1
        if self.user_threads:
            n = min(n, self.user_threads)
        if self._clock() < self._penalty_until:
            n = 1
        return max(1, n)

    # --- errors -------------------------------------------------------------
    def note_status(self, status):
        """Record an HTTP status from ScreenScraper. Returns True for a quota/ban status."""
        if status not in QUOTA_STATUSES:
            return False
        with self._cond:
            now = self._clock()
            if status == 429:
                self._penalty_until = max(self._penalty_until, now + PENALTY_SECONDS)
            else:
                seconds, key = COOLDOWNS[status]
                if now + seconds > self._blocked_until:
                    self._blocked_until = now + seconds
                    self._blocked = (key, status)
            self._cond.notify_all()
        return True

    def blocked(self):
        """(key, status) when nothing may be sent now, else None."""
        with self._cond:
            return self._blocked_reason()

    def _blocked_reason(self):
        if self._blocked and self._clock() < self._blocked_until:
            return self._blocked
        lim = self.limits
        if self.logged_in or lim.get("maxrequestsperday"):
            perday, today = lim.get("maxrequestsperday"), lim.get("requeststoday")
            if perday and today is not None and today + self._since_report >= perday:
                return ("server.ss_quota_day", 430)
            koday, kotoday = lim.get("maxrequestskoperday"), lim.get("requestskotoday")
            if koday and kotoday is not None and kotoday >= koday:
                return ("server.ss_quota_ko", 431)
        return None

    def reset(self):
        """Forget everything (tests, or a new member login)."""
        with self._cond:
            self.__init__(self._clock)

    # --- one request ----------------------------------------------------------
    @contextmanager
    def slot(self, cancel=None):
        """Hold one of the member's threads for one HTTP request.

        Waits for a free thread, then for the requests-per-minute limit.
        Raises SSBlocked (quota, ban) or Cancelled (batch stopped).
        """
        cancel = cancel or current_cancel()
        with self._cond:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                reason = self._blocked_reason()
                if reason:
                    raise SSBlocked(*reason)
                if self.active < self._thread_limit():
                    break
                self._cond.wait(0.2)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            with self._cond:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    reason = self._blocked_reason()
                    if reason:
                        raise SSBlocked(*reason)
                    wait = self._rate.reserve(self._clock())
                    if not wait:
                        self._since_report += 1
                        break
                    self._cond.wait(min(wait, 0.2))
            yield
        finally:
            with self._cond:
                self.active -= 1
                self._cond.notify_all()

    def snapshot(self):
        """Limits and usage for the interface (no login, no URL)."""
        with self._cond:
            lim = self.limits
            today = lim.get("requeststoday")
            reason = self._blocked_reason()
            return {
                "active": self.active,
                "limit": self._thread_limit(),
                "maxthreads": lim.get("maxthreads") if self.logged_in else None,
                "logged_in": self.logged_in,
                "user_threads": self.user_threads,
                "per_minute": lim.get("maxrequestspermin"),
                "last_minute": self._rate.in_last_minute(self._clock()),
                "today": None if today is None else today + self._since_report,
                "per_day": lim.get("maxrequestsperday"),
                "ko_today": lim.get("requestskotoday"),
                "ko_per_day": lim.get("maxrequestskoperday"),
                "penalty": self._clock() < self._penalty_until,
                "blocked": reason[0] if reason else None,
            }


GATE = SSGate()
