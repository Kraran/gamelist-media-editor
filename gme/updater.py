"""Update check (GitHub Releases) and self-update of the Windows .exe.

Check
    ``GET https://api.github.com/repos/Kraran/gamelist-media-editor/releases/latest``
    without an account, at most once a day (``update_state.json`` next to the
    .exe keeps the answer), short timeouts, silent when offline. Disabled with
    the ``update_check`` setting; "Check for updates" always asks GitHub.

Update (frozen Windows .exe only)
    1. ``SHA256SUMS.txt`` and ``GamelistMediaEditor-Windows-vX.Y.Z.zip`` are
       downloaded from the release of the official repository only (the asset
       URL must be ``https://github.com/Kraran/gamelist-media-editor/releases/
       download/<tag>/<name>``, every redirect must stay on HTTPS). No checksum
       file, no entry for the zip or a different SHA-256: refused.
    2. Only ``GamelistMediaEditor.exe`` is read from the zip (nothing else is
       extracted, so no path from the archive is ever used) into
       ``.gme-update/staging`` next to the .exe. Stop leaves nothing behind.
    3. Apply writes a small PowerShell helper and starts it detached, then GME
       exits. The helper waits for GME to end, moves the current .exe to
       ``.gme-update/previous`` (rollback), moves the new one in place and
       starts it again with the open gamelist. If the new version does not
       answer on /api/session within a minute, the previous .exe is put back
       and started.

Only the .exe is replaced: settings, keys, network credentials, recent lists,
caches, backups and the app-window profile live in other files next to it and
are never touched.
"""

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from urllib.parse import urljoin

import requests
from flask import Blueprint, jsonify, request

from gme import jobs
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.paths import APP_DIR
from gme.version import APP_UA, APP_VERSION

bp = Blueprint("updater", __name__)

REPO = "Kraran/gamelist-media-editor"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
SUMS_NAME = "SHA256SUMS.txt"
EXE_NAME = "GamelistMediaEditor.exe"
HEALTH_URL = "http://127.0.0.1:5050/api/session"

STATE_FILE = os.path.join(APP_DIR, "update_state.json")
WORK_DIR = os.path.join(APP_DIR, ".gme-update")

CHECK_EVERY = 24 * 3600          # automatic check: once a day
RETRY_AFTER_ERROR = 3 * 3600     # offline at start-up: try again a few hours later
API_TIMEOUT = (4, 6)             # connect, read (seconds)
DL_TIMEOUT = (8, 30)
MAX_API = 1 << 20
MAX_SUMS = 64 << 10
MAX_ZIP = 300 << 20
MAX_EXE = 400 << 20
MAX_NOTES = 1500
CHUNK = 256 << 10

_TAG = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z.-]{1,40}))?$")
_SUM_LINE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(\S.*?)\s*$")
_lock = threading.Lock()


class UpdateError(Exception):
    """A refused or failed step; ``key`` is an ``update.*`` message."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key, self.params = key, params

    def message(self):
        return st("update." + self.key, **self.params)


# --- versions ----------------------------------------------------------------

def parse_version(text):
    """``"v1.8.0"`` -> sort key, None when not X.Y.Z[-pre]."""
    m = _TAG.match(str(text or "").strip())
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    if pre is None:
        tail = (1,)
    else:
        tail = (0,) + tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (int(major), int(minor), int(patch)) + tail


def is_newer(candidate, current=APP_VERSION):
    a, b = parse_version(candidate), parse_version(current)
    return bool(a and b and a > b)


def zip_name(version):
    return f"GamelistMediaEditor-Windows-v{version}.zip"


def can_install():
    """Self-update only for the frozen Windows .exe; source runs get a link."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt" and sys.executable.lower().endswith(".exe")


# --- network -----------------------------------------------------------------

def _get(url, **kwargs):
    """Single seam for every request (tests replace it: no network)."""
    return requests.get(url, **kwargs)


def _fetch(url, timeout, accept="application/octet-stream"):
    """GET over HTTPS only, following redirects by hand so that each one is checked."""
    for _ in range(6):
        if not url.startswith("https://"):
            raise UpdateError("insecure")
        r = _get(url, headers={"User-Agent": APP_UA, "Accept": accept}, timeout=timeout,
                 stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308):
            location = r.headers.get("Location") or ""
            r.close()
            url = urljoin(url, location)
            continue
        if r.status_code != 200:
            r.close()
            raise UpdateError("http", status=r.status_code)
        return r
    raise UpdateError("http", status="redirect")


def _read(r, limit):
    out = bytearray()
    try:
        for chunk in r.iter_content(CHUNK):
            out += chunk
            if len(out) > limit:
                raise UpdateError("too_big")
    finally:
        r.close()
    return bytes(out)


# --- release data ------------------------------------------------------------

def parse_release(data):
    """The fields used from a GitHub release; None for drafts, pre-releases, bad tags."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not parse_version(tag):
        return None
    version = tag[1:] if tag.startswith("v") else tag
    url = str(data.get("html_url") or "")
    if not url.startswith(f"https://github.com/{REPO}/releases/"):
        url = RELEASES_PAGE
    wanted = {zip_name(version): "zip", SUMS_NAME: "sums"}
    out = {"version": version, "tag": tag, "name": str(data.get("name") or tag)[:120],
           "notes": str(data.get("body") or "").strip()[:MAX_NOTES], "url": url,
           "published": str(data.get("published_at") or "")[:10], "zip": None, "sums": None}
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        # Only the official repository's own release assets, nothing else
        if name in wanted and asset.get("browser_download_url") == f"{DOWNLOAD_PREFIX}{tag}/{name}":
            try:
                size = max(0, int(asset.get("size") or 0))
            except (TypeError, ValueError):
                size = 0
            out[wanted[name]] = {"name": name, "url": asset["browser_download_url"], "size": size}
    return out


def parse_sums(text):
    """``SHA256SUMS.txt`` (sha256sum format) -> {file name: hex digest}."""
    sums = {}
    for line in text.splitlines():
        m = _SUM_LINE.match(line.strip())
        if m:
            sums[m.group(2)] = m.group(1).lower()
    return sums


# --- state -------------------------------------------------------------------

def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    try:
        atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError as e:
        log.warning("Could not save the update state (%s)", e)


def auto_enabled():
    from gme import settings
    return settings.load().get("update_check", True)


def check(force=False):
    """Ask GitHub (or reuse today's answer). ``force`` raises UpdateError when offline."""
    with _lock:
        state = _load_state()
        now = time.time()
        wait = RETRY_AFTER_ERROR if state.get("error") else CHECK_EVERY
        if not force and "latest" in state and 0 <= now - float(state.get("checked_at") or 0) < wait:
            return state
        try:
            r = _fetch(API_LATEST, API_TIMEOUT, accept="application/vnd.github+json")
            state["latest"] = parse_release(json.loads(_read(r, MAX_API).decode("utf-8")))
            state["error"] = None
        except UpdateError as e:
            # 404: the repository has no published release yet
            if e.key == "http" and e.params.get("status") == 404:
                state["latest"], state["error"] = None, None
            else:
                state.setdefault("latest", None)
                state["error"] = e.key
        except (requests.RequestException, ValueError, OSError) as e:
            log.info("Update check failed: %s", type(e).__name__)
            state.setdefault("latest", None)
            state["error"] = "offline"
        state["checked_at"] = now
        _save_state(state)
        if force and state.get("error"):
            raise UpdateError("offline" if state["error"] == "offline" else state["error"],
                              status=state["error"])
        return state


def status(state=None):
    state = _load_state() if state is None else state
    latest = state.get("latest")
    available = bool(latest and is_newer(latest.get("version")))
    installable = bool(available and can_install() and latest.get("zip") and latest.get("sums"))
    reason = None
    if available and not installable:
        reason = "source" if not can_install() else "no_checksum"
    return {
        "current": APP_VERSION, "latest": latest, "available": available,
        "ignored": bool(available and state.get("ignored") == latest.get("version")),
        "installable": installable, "reason": reason, "can_install": can_install(),
        "auto": auto_enabled(), "checked_at": state.get("checked_at"),
        "releases_page": RELEASES_PAGE,
    }


# --- download ----------------------------------------------------------------

def _staging():
    return os.path.join(WORK_DIR, "staging")


def _clear_staging():
    folder = _staging()
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass


def download(job, latest):
    """Job body: checksum file, zip (SHA-256 checked), then the .exe alone."""
    folder = _staging()
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".write-test")
        with open(probe, "wb") as f:
            f.write(b"ok")
        os.remove(probe)
    except OSError:
        raise UpdateError("not_writable", folder=APP_DIR)
    _clear_staging()
    version, zinfo = latest["version"], latest["zip"]
    size = zinfo.get("size") or 0
    if size > MAX_ZIP:
        raise UpdateError("too_big")
    job.tick(done=0, total=round(size / 1e6, 1))
    sums = parse_sums(_read(_fetch(latest["sums"]["url"], DL_TIMEOUT), MAX_SUMS).decode("utf-8", "replace"))
    expected = sums.get(zinfo["name"])
    if not expected:
        raise UpdateError("no_checksum")
    part = os.path.join(folder, zinfo["name"] + ".part")
    exe_tmp = os.path.join(folder, EXE_NAME + ".part")
    final = os.path.join(folder, EXE_NAME)
    ok = False
    try:
        digest, got = hashlib.sha256(), 0
        r = _fetch(zinfo["url"], DL_TIMEOUT)
        try:
            with open(part, "wb") as f:
                for chunk in r.iter_content(CHUNK):
                    if not chunk:
                        continue
                    got += len(chunk)
                    if got > MAX_ZIP or (size and got > size):
                        raise UpdateError("too_big")
                    f.write(chunk)
                    digest.update(chunk)
                    job.tick(done=round(got / 1e6, 1))
        finally:
            r.close()
        if size and got != size:
            raise UpdateError("incomplete")
        if not hmac.compare_digest(digest.hexdigest(), expected):
            raise UpdateError("checksum_mismatch")
        job.tick(phase="extract", current=EXE_NAME)
        try:
            with zipfile.ZipFile(part) as z:
                try:
                    info = z.getinfo(EXE_NAME)      # at the root, exact name; nothing else is read
                except KeyError:
                    raise UpdateError("bad_archive")
                if info.file_size > MAX_EXE:
                    raise UpdateError("too_big")
                with z.open(info) as src, open(exe_tmp, "wb") as dst:
                    head = src.read(2)
                    if head != b"MZ":
                        raise UpdateError("bad_archive")
                    dst.write(head)
                    while True:
                        job.tick()
                        block = src.read(CHUNK)
                        if not block:
                            break
                        dst.write(block)
        except zipfile.BadZipFile:
            raise UpdateError("bad_archive")
        os.replace(exe_tmp, final)
        with open(os.path.join(folder, "VERSION"), "w", encoding="utf-8") as f:
            f.write(version)
        ok = True
        return {"version": version}
    finally:
        for path in (part, exe_tmp):
            try:
                os.remove(path)
            except OSError:
                pass
        if not ok:
            _clear_staging()


def staged_version():
    try:
        with open(os.path.join(_staging(), "VERSION"), encoding="utf-8") as f:
            version = f.read().strip()
    except OSError:
        return None
    return version if os.path.isfile(os.path.join(_staging(), EXE_NAME)) and parse_version(version) else None


# --- apply -------------------------------------------------------------------

HELPER_PS1 = r'''# Gamelist Media Editor update helper, written by gme/updater.py.
# Waits for GME to exit, swaps GamelistMediaEditor.exe (the previous one is kept
# in BackupDir), starts GME again and rolls back if the new version does not answer.
param(
  [Parameter(Mandatory=$true)][string]$Target,
  [Parameter(Mandatory=$true)][string]$NewFile,
  [Parameter(Mandatory=$true)][string]$BackupDir,
  [Parameter(Mandatory=$true)][string]$LogFile,
  [string]$Pids = "",
  [string]$ExpectVersion = "",
  [string]$HealthUrl = "",
  [string]$Gamelist = "",
  [int]$WaitSeconds = 60,
  [int]$HealthSeconds = 60,
  [switch]$NoRestart
)
$ErrorActionPreference = "Stop"
function Write-Log([string]$m) {
  try { Add-Content -LiteralPath $LogFile -Value ("{0} {1}" -f (Get-Date -Format s), $m) -Encoding UTF8 } catch {}
}
function Full([string]$p) { try { return [System.IO.Path]::GetFullPath($p) } catch { return $p } }
function Start-Gme {
  $dir = [System.IO.Path]::GetDirectoryName($Target)
  if ($Gamelist) { return Start-Process -FilePath $Target -WorkingDirectory $dir -ArgumentList ('"' + $Gamelist + '"') -PassThru }
  return Start-Process -FilePath $Target -WorkingDirectory $dir -PassThru
}
function Move-Retry([string]$from, [string]$to) {
  for ($i = 0; $i -lt 40; $i++) {
    try {
      if (Test-Path -LiteralPath $to) { Remove-Item -LiteralPath $to -Force }
      Move-Item -LiteralPath $from -Destination $to -Force
      return
    } catch { Start-Sleep -Milliseconds 250 }
  }
  throw "cannot move $from"
}

$code = 1
$replaced = $false
$backup = Join-Path $BackupDir ([System.IO.Path]::GetFileName($Target))
Write-Log "update to $ExpectVersion requested"
try {
  $deadline = (Get-Date).AddSeconds($WaitSeconds)
  $first = $true
  foreach ($id in ($Pids -split ",")) {
    if ($id -notmatch '^\d+$') { continue }
    $p = Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
    # The first pid is GME itself; the others only when they run the same .exe
    # (the PyInstaller launcher that keeps the file locked).
    if ($p -and ($first -or ($p.Path -and ((Full $p.Path) -ieq (Full $Target))))) {
      $left = [int][Math]::Max(0, ($deadline - (Get-Date)).TotalMilliseconds)
      if (-not $p.WaitForExit($left)) { throw "GME is still running (pid $id)" }
    }
    $first = $false
  }
  if (-not (Test-Path -LiteralPath $NewFile)) { throw "the new version is missing: $NewFile" }
  New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
  Move-Retry $Target $backup
  try { Move-Item -LiteralPath $NewFile -Destination $Target -Force }
  catch { Move-Item -LiteralPath $backup -Destination $Target -Force; throw }
  $replaced = $true
  Write-Log "replaced; previous version kept in $backup"
  $code = 0
} catch {
  Write-Log ("update failed: " + $_.Exception.Message)
}

if (-not $NoRestart) {
  try {
    $proc = Start-Gme
    if ($replaced -and $HealthUrl -and $ExpectVersion) {
      $ok = $false
      $end = (Get-Date).AddSeconds($HealthSeconds)
      while (-not $ok -and (Get-Date) -lt $end) {
        Start-Sleep -Milliseconds 700
        try {
          $s = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
          if ("$($s.version)" -eq $ExpectVersion) { $ok = $true }
        } catch {}
        if (-not $ok -and $proc.HasExited) { break }
      }
      if ($ok) {
        Write-Log "version $ExpectVersion started"
      } else {
        Write-Log "the new version did not start: rolling back"
        try { & taskkill.exe /PID $proc.Id /T /F | Out-Null } catch {}
        Start-Sleep -Milliseconds 1000
        Move-Retry $Target ($Target + ".failed")
        Move-Retry $backup $Target
        Start-Gme | Out-Null
        Write-Log "previous version restored"
        $code = 2
      }
    }
  } catch {
    Write-Log ("restart failed: " + $_.Exception.Message)
  }
}
exit $code
'''


def helper_path():
    return os.path.join(WORK_DIR, "gme-update.ps1")


def write_helper():
    os.makedirs(WORK_DIR, exist_ok=True)
    path = helper_path()
    # UTF-8 with BOM: Windows PowerShell 5.1 reads BOM-less scripts as ANSI
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(HELPER_PS1)
    return path


def helper_command(version, gamelist=None):
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-WindowStyle", "Hidden", "-File", write_helper(),
           "-Target", os.path.abspath(sys.executable),
           "-NewFile", os.path.join(_staging(), EXE_NAME),
           "-BackupDir", os.path.join(WORK_DIR, "previous"),
           "-LogFile", os.path.join(WORK_DIR, "update.log"),
           "-Pids", f"{os.getpid()},{os.getppid()}",
           "-ExpectVersion", version, "-HealthUrl", HEALTH_URL]
    if gamelist:
        cmd += ["-Gamelist", gamelist]
    return cmd


def _spawn(cmd):
    """Start the helper outside GME's process group (it must outlive GME)."""
    flags = 0x00000008 | 0x00000200     # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(cmd, creationflags=flags | 0x01000000, close_fds=True)   # + BREAKAWAY_FROM_JOB
    except OSError:
        return subprocess.Popen(cmd, creationflags=flags, close_fds=True)


def _exit_soon():
    def _stop():
        time.sleep(0.6)
        from gme.window import close_ui_window
        close_ui_window()
        os._exit(0)
    threading.Thread(target=_stop, daemon=True).start()


# --- routes ------------------------------------------------------------------

@bp.route("/api/update")
def api_status():
    return jsonify(status())


@bp.route("/api/update/check", methods=["POST"])
def api_check():
    body = request.get_json(silent=True) or {}
    if body.get("auto") and not auto_enabled():
        return jsonify(dict(status(), checked=False))
    try:
        state = check(force=bool(body.get("force")))
    except UpdateError as e:
        return api_err(st("update.check_failed", detail=e.message()), 502, code="update_check_failed")
    return jsonify(dict(status(state), checked=True))


@bp.route("/api/update/ignore", methods=["POST"])
def api_ignore():
    version = (request.get_json(silent=True) or {}).get("version")
    if version is not None and not parse_version(version):
        return api_err("invalid version", 400, code="invalid_version")
    with _lock:
        state = _load_state()
        state["ignored"] = version
        _save_state(state)
    return jsonify(status())


@bp.route("/api/update/download", methods=["POST"])
def api_download():
    info = status()
    if not info["available"]:
        return api_err(st("update.none"), 409, code="update_none")
    if not info["installable"]:
        key = "update.not_frozen" if info["reason"] == "source" else "update.no_checksum"
        return api_err(st(key), 409, code="update_not_installable", reason=info["reason"])
    latest = info["latest"]
    job = jobs.start("update", lambda j: _download_job(j, latest), {"version": latest["version"]},
                     bound=False, unit="MB")
    return jsonify({"job": job.public(with_result=True)})


def _download_job(job, latest):
    try:
        return download(job, latest)
    except UpdateError as e:
        raise RuntimeError(e.message())
    except (requests.RequestException, OSError) as e:
        log.info("Update download failed: %s", e)
        raise RuntimeError(st("update.offline"))


@bp.route("/api/update/apply", methods=["POST"])
def api_apply():
    body = request.get_json(silent=True) or {}
    job = jobs.get(body.get("job"))
    version = staged_version()
    if (not can_install() or job is None or job.kind != "update" or job.state != "done"
            or not version or (job.result or {}).get("version") != version):
        return api_err(st("update.not_ready"), 409, code="update_not_ready")
    from gme import history, xml_store
    busy = history._busy_reason()
    if busy:
        return api_err(st("update.busy"), 409, code="update_busy")
    gamelist = xml_store.XML_PATH if xml_store.has_gamelist() else None
    try:
        _spawn(helper_command(version, gamelist))
    except OSError as e:
        log.warning("Update helper failed to start: %s", e)
        return api_err(st("update.helper_failed"), 500, code="update_helper_failed")
    log.info("Updating to v%s: GME restarts", version)
    _exit_soon()
    return jsonify({"ok": True, "version": version})
