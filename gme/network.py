"""Gamelists on a retro machine's network share (SMB): Batocera, Recalbox, a RetroBat PC.

Windows opens ``\\\\HOST\\share\\...`` paths (UNC) natively, so the editor reads
and writes them like local files. This module adds what a network folder needs:

* ``location(path)``: is a path on a share (UNC path, mapped network drive,
  or an SMB mount on Linux / macOS), and on which host;
* ``call(fn, timeout)``: file system calls that cannot hang the interface when
  the machine goes off the network (Windows waits 20 to 60 s on a dead host);
* ``discover()``: the known machine names (``BATOCERA``, ``RECALBOX``) or an
  address typed by the user: name lookup, SMB port, the ``roms`` folder and
  EmulationStation's web API;
* ``shares(host)``: the shares of a machine (``\\\\HOST`` in the folder browser);
* ``connect()``: sign in to a share that asks for a user (Batocera with
  "Enforce security": user ``root``, the password shown in its menu);
* favourite network folders, and the optional reload of the game lists on the
  machine after saving (Batocera's documented ``GET :1234/reloadgames``).

Credentials are kept only when the user ticks "remember", in
``network_credentials.json`` next to the app (never in the repository: it is in
``.gitignore``), and they are never written to the log or sent to the page.
"""

import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

from flask import Blueprint, copy_current_request_context, has_request_context, jsonify, request

from gme import xml_store
from gme.fsutil import atomic_write
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.paths import APP_DIR

bp = Blueprint("network", __name__)

IS_WINDOWS = os.name == "nt"
PLACES_FILE = os.path.join(APP_DIR, "network_places.json")
CREDENTIALS_FILE = os.path.join(APP_DIR, "network_credentials.json")

SMB_PORT = 445
ES_API_PORT = 1234            # EmulationStation's web server (Batocera, RetroBat)
CONNECT_TIMEOUT = 1.5         # one TCP probe
RESOLVE_TIMEOUT = 2.0         # a name lookup (NetBIOS / mDNS can be slow)
IO_TIMEOUT = 12.0             # a folder listing over the network
API_TIMEOUT = 3.0
RELOAD_DELAY = 4.0            # several saves in a row: one reload
FAVORITES_MAX = 20

# The machines that publish a share under a fixed name (official docs:
# wiki.batocera.org/network_issues, wiki.recalbox.com/en/basic-usage/file-management).
KNOWN = (
    {"host": "BATOCERA", "kind": "batocera", "share": "share", "roms": "roms"},
    {"host": "RECALBOX", "kind": "recalbox", "share": "share", "roms": "roms"},
)

# Windows error codes of a share that needs a user or refuses guests
AUTH_ERRORS = {5, 86, 1219, 1244, 1272, 1326, 1327, 1331, 1909}
UNREACHABLE_ERRORS = {51, 53, 64, 67, 1222, 1231, 1232}

_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$|^\[?[0-9A-Fa-f:]+\]?$")
_lock = threading.Lock()
_reload = {"timer": None, "last": None}
_Timer = threading.Timer          # overridable in tests (no real waiting)
_connected = set()            # host\share signed in by this process


class NetworkError(Exception):
    """A network folder that cannot be reached: ``code`` tells the page what to show."""

    def __init__(self, code, message, host=None, share=None):
        super().__init__(message)
        self.code = code
        self.host = host
        self.share = share

    def response(self):
        return api_err(str(self), 504 if self.code == "net_timeout" else 503 if self.code == "net_unreachable"
                       else 401 if self.code == "net_auth" else 400, code=self.code,
                       host=self.host, share=self.share)


# --- Paths --------------------------------------------------------------------

def is_unc(path):
    """``\\\\host\\share...`` or ``//host/share...`` (not the ``\\\\?\\`` / ``\\\\.\\`` device forms)."""
    p = str(path or "")
    return len(p) > 2 and p[0] in "\\/" and p[1] in "\\/" and p[2] not in "\\/?." and not p.startswith(("\\\\?", "//?"))


def split_unc(path):
    """``(host, share, rest)`` of a UNC path; share and rest may be empty."""
    parts = [x for x in re.split(r"[\\/]+", str(path)[2:]) if x]
    host = parts[0] if parts else ""
    share = parts[1] if len(parts) > 1 else ""
    return host, share, "\\".join(parts[2:])


def unc(host, share="", *rest):
    out = "\\\\" + host
    for part in (share,) + rest:
        if part:
            out += "\\" + str(part).strip("\\/").replace("/", "\\")
    return out


def normalize(raw):
    """A path typed by the user: UNC paths keep their form, others become absolute."""
    raw = str(raw or "").strip().strip('"').strip("'")
    if is_unc(raw):
        host, share, rest = split_unc(raw)
        return unc(host, share, rest)
    return os.path.abspath(raw) if raw else raw


def _mapped_drive(path):
    """Windows: the UNC path behind a mapped network drive (``Z:\\`` -> ``\\\\host\\share``)."""
    if not IS_WINDOWS or len(path) < 2 or path[1] != ":":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        drive = path[:2]
        if ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") != 4:      # DRIVE_REMOTE
            return None
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size)) != 0:
            return None
        return buf.value + path[2:]
    except Exception:
        return None


def _mounts():
    """``[(mount point, "//host/share")]`` of the SMB mounts (Linux /proc/mounts, macOS ``mount``)."""
    out = []
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            return out
        for line in lines:
            bits = line.split()
            if len(bits) >= 3 and bits[2] in ("cifs", "smb3", "smbfs") and bits[0].startswith("//"):
                out.append((bits[1].replace("\\040", " "), bits[0]))
    elif sys.platform == "darwin":
        import subprocess
        try:
            text = subprocess.run(["mount"], capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return out
        for line in text.splitlines():
            m = re.match(r"^(//\S+) on (.+) \(smbfs", line)
            if m:
                out.append((m.group(2), re.sub(r"^//[^@/]*@", "//", m.group(1))))
    return out


def _mount_of(path):
    best = None
    for point, source in _mounts():
        point = point.rstrip("/") or "/"
        if path == point or path.startswith(point + "/"):
            if best is None or len(point) > len(best[0]):
                best = (point, source)
    if not best:
        return None
    host, share, _ = split_unc(best[1])
    host = re.sub(r"\._smb\._tcp\.local$", "", host, flags=re.I)
    return {"host": host, "share": share, "via": "mount", "mount": best[0]}


def unc_path_of(path):
    """The UNC form of ``path`` (itself, or the target of a mapped drive), else None."""
    if is_unc(path):
        return str(path)
    mapped = _mapped_drive(str(path or ""))
    return mapped if mapped and is_unc(mapped) else None


def location(path):
    """``{"host", "share", "via"}`` when ``path`` is on a network share, else None.

    Only local work: string parsing, the drive type, the list of mounts.
    """
    if not path:
        return None
    path = str(path)
    if is_unc(path):
        host, share, _ = split_unc(path)
        return {"host": host, "share": share, "via": "unc"} if host else None
    mapped = _mapped_drive(path)
    if mapped and is_unc(mapped):
        host, share, _ = split_unc(mapped)
        return {"host": host, "share": share, "via": "drive"}
    if not IS_WINDOWS:
        return _mount_of(os.path.abspath(path))
    return None


def quick_exists(path, check=os.path.isfile):
    """``check(path)`` for a local path; True without touching the network for a
    share (a list of recent files must not wait 30 s for a machine that is off:
    opening it reports the problem)."""
    return True if location(path) else check(path)


def kind_of(host):
    name = (host or "").split(".")[0].lower()
    for known in KNOWN:
        if name == known["host"].lower():
            return known["kind"]
    return None


# --- I/O that cannot hang -----------------------------------------------------

def call(fn, *args, timeout=None, host=None):
    """Run ``fn(*args)`` in a daemon thread; NetworkError("net_timeout") after ``timeout`` s.

    A dead SMB host blocks the calling thread for a long time and Python cannot
    cancel it: the thread is left to finish on its own, the request answers now.
    """
    timeout = IO_TIMEOUT if timeout is None else timeout
    if has_request_context():
        fn = copy_current_request_context(fn)     # st() / jsonify() in the worker
    box = {}
    done = threading.Event()

    def run():
        try:
            box["value"] = fn(*args)
        except BaseException as exc:          # noqa: BLE001 - handed back to the caller
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=run, name="gme-net-io", daemon=True).start()
    if not done.wait(timeout):
        raise NetworkError("net_timeout", st("network.timeout", host=host or "?", s=int(round(timeout))), host)
    if "error" in box:
        raise box["error"]
    return box.get("value")


def resolve(host, timeout=RESOLVE_TIMEOUT):
    """The address of ``host`` (NetBIOS / mDNS / DNS), None when unknown or too slow."""
    try:
        infos = call(socket.getaddrinfo, host, SMB_PORT, 0, socket.SOCK_STREAM, timeout=timeout, host=host)
    except (NetworkError, OSError, UnicodeError):
        return None
    for family, _, _, _, addr in infos or ():
        if family in (socket.AF_INET, socket.AF_INET6):
            return addr[0]
    return None


def port_open(address, port, timeout=CONNECT_TIMEOUT):
    try:
        with socket.create_connection((address, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def reachable(host):
    """Raise NetworkError("net_unreachable") when ``host`` does not answer on the SMB port."""
    address = resolve(host)
    if not address or not port_open(address, SMB_PORT):
        raise NetworkError("net_unreachable", st("network.unreachable", host=host), host)
    return address


def os_error(exc, host, share=""):
    """A NetworkError for an OSError met on a share (auth, missing share, gone host)."""
    code = getattr(exc, "winerror", None)
    if code in AUTH_ERRORS or (code is None and isinstance(exc, PermissionError)):
        return NetworkError("net_auth", st("network.auth_needed", host=host, share=share or "?"), host, share)
    if code in UNREACHABLE_ERRORS:
        return NetworkError("net_unreachable", st("network.unreachable", host=host), host, share)
    return None


# --- Shares -------------------------------------------------------------------

def _net_share_enum(host):
    """Windows NetShareEnum: the disk shares of ``host`` (not the hidden ``C$``-style ones)."""
    import ctypes
    from ctypes import wintypes

    class SHARE_INFO_1(ctypes.Structure):
        _fields_ = [("netname", wintypes.LPWSTR), ("type", wintypes.DWORD), ("remark", wintypes.LPWSTR)]

    netapi = ctypes.WinDLL("Netapi32.dll")
    buf = ctypes.c_void_p()
    read, total, resume = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
    status = netapi.NetShareEnum(ctypes.c_wchar_p("\\\\" + host), 1, ctypes.byref(buf), 0xFFFFFFFF,
                                 ctypes.byref(read), ctypes.byref(total), ctypes.byref(resume))
    try:
        if status not in (0, 234):                    # NERR_Success, ERROR_MORE_DATA
            raise OSError(None, "NetShareEnum", None, status)
        items = ctypes.cast(buf, ctypes.POINTER(SHARE_INFO_1))
        names = []
        for i in range(read.value):
            item = items[i]
            if (item.type & 0xFF) == 0 and not (item.type & 0x80000000):     # STYPE_DISKTREE, not special
                names.append(item.netname)
        return names
    finally:
        if buf:
            netapi.NetApiBufferFree(buf)


def shares(host):
    """Share names of ``host``: Windows asks the machine; the known names are tried too."""
    if not IS_WINDOWS:
        raise NetworkError("net_windows_only", st("network.windows_only"), host)
    reachable(host)
    names = []
    try:
        names = call(_net_share_enum, host, host=host) or []
    except NetworkError:
        raise
    except OSError as exc:
        err = os_error(exc, host)
        if err and err.code == "net_auth":
            raise err
        log.info("Share list of %s unavailable (%s): trying the usual names", host, exc)
    if not names:
        for name in ("share", "roms"):
            try:
                if call(os.path.isdir, unc(host, name), host=host):
                    names.append(name)
            except (NetworkError, OSError):
                continue
    return sorted(set(names), key=str.lower)


# --- Sign-in (Windows) ----------------------------------------------------------

def _wnet_add(remote, user, password):
    import ctypes
    from ctypes import wintypes

    class NETRESOURCE(ctypes.Structure):
        _fields_ = [("dwScope", wintypes.DWORD), ("dwType", wintypes.DWORD),
                    ("dwDisplayType", wintypes.DWORD), ("dwUsage", wintypes.DWORD),
                    ("lpLocalName", wintypes.LPWSTR), ("lpRemoteName", wintypes.LPWSTR),
                    ("lpComment", wintypes.LPWSTR), ("lpProvider", wintypes.LPWSTR)]

    res = NETRESOURCE()
    res.dwType = 1                                   # RESOURCETYPE_DISK
    res.lpRemoteName = remote
    return ctypes.windll.mpr.WNetAddConnection2W(ctypes.byref(res), password or None, user or None, 0)


def connect(host, share, user, password):
    """Open a session on ``\\\\host\\share`` for this Windows logon (no drive letter)."""
    if not IS_WINDOWS:
        raise NetworkError("net_windows_only", st("network.windows_only"), host, share)
    status = call(_wnet_add, unc(host, share), user, password, host=host)
    if status == 1219:
        # Already connected with other credentials: the open session works, keep it
        log.info("Network share %s already has a session", unc(host, share))
        status = 0
    if status != 0:
        err = os_error(OSError(None, "WNetAddConnection2", None, status), host, share)
        if err and err.code == "net_auth":
            raise NetworkError("net_auth", st("network.auth_refused", host=host, share=share), host, share)
        raise err or NetworkError("net_failed", st("network.connect_failed", host=host, share=share, code=status),
                                  host, share)
    with _lock:
        _connected.add((host.lower(), share.lower()))


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))


def _cred_key(host, share):
    return (host or "").lower() + "\\" + (share or "").lower()


def remember_credentials(host, share, user, password):
    with _lock:
        creds = _load_json(CREDENTIALS_FILE, {})
        creds[_cred_key(host, share)] = {"user": user or "", "password": password or ""}
        _save_json(CREDENTIALS_FILE, creds)


def forget_credentials(host, share):
    with _lock:
        creds = _load_json(CREDENTIALS_FILE, {})
        if creds.pop(_cred_key(host, share), None) is not None:
            _save_json(CREDENTIALS_FILE, creds)


def saved_user(host, share):
    entry = _load_json(CREDENTIALS_FILE, {}).get(_cred_key(host, share))
    return entry.get("user") if isinstance(entry, dict) else None


def auto_connect(path):
    """Sign in with remembered credentials before the first access to their share."""
    if not IS_WINDOWS or not is_unc(path):
        return
    host, share, _ = split_unc(path)
    if not share or (host.lower(), share.lower()) in _connected:
        return
    entry = _load_json(CREDENTIALS_FILE, {}).get(_cred_key(host, share))
    if not isinstance(entry, dict):
        return
    try:
        connect(host, share, entry.get("user"), entry.get("password"))
    except NetworkError as exc:
        log.warning("Remembered sign-in to %s refused (%s)", unc(host, share), exc.code)


# --- Favourites and settings ----------------------------------------------------

def _places():
    data = _load_json(PLACES_FILE, {})
    favs = [f for f in data.get("favorites", []) if isinstance(f, dict) and isinstance(f.get("path"), str)]
    return {"favorites": favs[:FAVORITES_MAX], "reload_after_save": data.get("reload_after_save") is True}


def _save_places(data):
    try:
        _save_json(PLACES_FILE, data)
    except OSError as exc:
        log.warning("Could not save the network folders (%s)", exc)


def add_favorite(path, label=None):
    path = normalize(path)
    if not path:
        raise ValueError(st("network.fav_empty"))
    with _lock:
        data = _places()
        key = path.lower()
        favs = [f for f in data["favorites"] if f["path"].lower() != key]
        label = str(label or "").strip()[:80] or _default_label(path)
        data["favorites"] = ([{"path": path, "label": label}] + favs)[:FAVORITES_MAX]
        _save_places(data)
        return data


def remove_favorite(path):
    with _lock:
        data = _places()
        key = normalize(path).lower()
        data["favorites"] = [f for f in data["favorites"] if f["path"].lower() != key]
        _save_places(data)
        return data


def set_reload_after_save(value):
    with _lock:
        data = _places()
        data["reload_after_save"] = bool(value)
        _save_places(data)
        return data


def _default_label(path):
    if is_unc(path):
        host, share, rest = split_unc(path)
        tail = rest.split("\\")[-1] if rest else share
        return host + (" · " + tail if tail else "")
    return os.path.basename(path.rstrip("\\/")) or path


# --- EmulationStation's web API (Batocera, RetroBat) ---------------------------

def _http_get(url, timeout=API_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "GamelistMediaEditor"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 - http on the LAN only
        return resp.status, resp.read(65536)


def _api_base(host, address=None):
    target = address or host
    if ":" in target and not target.startswith("["):
        target = "[" + target + "]"
    return "http://%s:%d" % (target, ES_API_PORT)


def es_api(host, address=None):
    """``{"state": "ok"|"forbidden"|"off", "version"}`` of EmulationStation's web server.

    ``forbidden``: the server answers only the machine itself until "Enable
    public web access" is turned on (Batocera: System settings > Frontend
    developer options), see wiki.batocera.org/es-webserver.
    """
    if address is None:
        address = resolve(host)
        if not address:
            return {"state": "off"}
    if not port_open(address, ES_API_PORT):
        return {"state": "off"}
    try:
        status, body = _http_get(_api_base(host, address) + "/caps")
    except urllib.error.HTTPError as exc:
        return {"state": "forbidden" if exc.code == 403 else "off"}
    except (OSError, ValueError):
        return {"state": "off"}
    version = None
    try:
        caps = json.loads(body.decode("utf-8", "replace"))
        if isinstance(caps, dict):
            version = caps.get("Version") or caps.get("version")
    except ValueError:
        pass
    return {"state": "ok" if status == 200 else "off", "version": version}


def reload_games(host):
    """``GET /reloadgames``: EmulationStation saves the entries it changed itself, then
    reads every gamelist again. Returns ``{"ok", "error"}`` and remembers it."""
    try:
        status, _ = _http_get(_api_base(host) + "/reloadgames", timeout=API_TIMEOUT + 2)
        result = {"ok": 200 <= status < 300, "error": None if status < 300 else "HTTP %d" % status}
    except urllib.error.HTTPError as exc:
        result = {"ok": False, "error": st("network.api_forbidden") if exc.code == 403 else "HTTP %d" % exc.code}
    except (OSError, ValueError) as exc:
        result = {"ok": False, "error": st("network.api_unreachable", host=host, detail=getattr(exc, "reason", exc))}
    result.update({"host": host, "at": time.time()})
    _reload["last"] = result
    if result["ok"]:
        log.info("Game lists reloaded on %s", host)
    else:
        log.warning("Game list reload on %s failed: %s", host, result["error"])
    return result


def after_save(xml_path):
    """Called after each gamelist save: schedule one reload when the user asked for it."""
    loc = location(xml_path)
    if not loc or not _places()["reload_after_save"]:
        return
    with _lock:
        if _reload["timer"] is not None:
            _reload["timer"].cancel()
        timer = _Timer(RELOAD_DELAY, reload_games, args=(loc["host"],))
        timer.daemon = True
        _reload["timer"] = timer
        timer.start()


# --- Discovery ------------------------------------------------------------------

def probe(host, kind=None, share="share", roms="roms"):
    """What a machine offers: address, SMB, its roms folder, EmulationStation's API."""
    out = {"host": host, "kind": kind or kind_of(host), "address": None, "smb": False,
           "share": unc(host, share), "roms": None, "api": {"state": "off"}}
    address = resolve(host)
    if not address and "." not in host and not re.match(r"^[0-9:]+$", host):
        address = resolve(host + ".local")              # mDNS (Linux, macOS, recent Windows)
    if not address:
        return out
    out["address"] = address
    out["smb"] = port_open(address, SMB_PORT)
    if out["smb"] and IS_WINDOWS:
        auto_connect(unc(host, share))
        for path in (unc(host, share, roms), unc(host, roms)):
            try:
                if call(os.path.isdir, path, timeout=IO_TIMEOUT / 2, host=host):
                    out["roms"] = path
                    break
            except (NetworkError, OSError):
                continue
    out["api"] = es_api(host, address)
    if out["kind"] is None and out["api"]["state"] != "off":
        out["kind"] = "emulationstation"
    return out


def discover(extra=None):
    """Probe the known machine names (and ``extra``, a name or an address) in parallel."""
    targets = [dict(k) for k in KNOWN]
    if extra:
        targets = [{"host": extra, "kind": kind_of(extra), "share": "share", "roms": "roms"}] + \
                  [t for t in targets if t["host"].lower() != extra.lower()]
    results = [None] * len(targets)

    def run(i, t):
        try:
            results[i] = probe(t["host"], t["kind"], t["share"], t["roms"])
        except Exception as exc:                       # noqa: BLE001 - one machine must not stop the others
            log.warning("Network probe of %s failed: %s", t["host"], exc)
            results[i] = {"host": t["host"], "kind": t["kind"], "address": None, "smb": False,
                          "share": unc(t["host"], t["share"]), "roms": None, "api": {"state": "off"}}

    threads = [threading.Thread(target=run, args=(i, t), daemon=True) for i, t in enumerate(targets)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(RESOLVE_TIMEOUT * 2 + CONNECT_TIMEOUT * 2 + IO_TIMEOUT + API_TIMEOUT)
    return [r for r in results if r]


def describe(path):
    """What the page shows for the open gamelist (no network access)."""
    loc = location(path)
    if not loc:
        return None
    last = _reload["last"]
    return dict(loc, kind=kind_of(loc["host"]),
                reload_after_save=_places()["reload_after_save"],
                last_reload=last if last and last.get("host") == loc["host"] else None)


# --- Routes ---------------------------------------------------------------------

def _host_arg(value):
    host = str(value or "").strip().strip("\\/")
    if not _HOST.match(host):
        raise ValueError(st("network.bad_host"))
    return host


@bp.route("/api/network")
def api_network():
    data = _places()
    return jsonify({"windows": IS_WINDOWS, "favorites": data["favorites"],
                    "reload_after_save": data["reload_after_save"],
                    "current": describe(xml_store.XML_PATH) if xml_store.has_gamelist() else None,
                    "known": [k["host"] for k in KNOWN]})


@bp.route("/api/network/discover", methods=["POST"])
def api_discover():
    body = request.get_json(silent=True) or {}
    extra = None
    if body.get("host"):
        try:
            extra = _host_arg(body.get("host"))
        except ValueError as exc:
            return api_err(str(exc), 400, code="net_bad_host")
    return jsonify({"windows": IS_WINDOWS, "machines": discover(extra)})


@bp.route("/api/network/connect", methods=["POST"])
def api_connect():
    body = request.get_json(silent=True) or {}
    try:
        host = _host_arg(body.get("host"))
    except ValueError as exc:
        return api_err(str(exc), 400, code="net_bad_host")
    share = str(body.get("share") or "").strip().strip("\\/")
    if not share or not re.match(r"^[^\\/:*?\"<>|\x00-\x1f]{1,80}$", share):
        return api_err(st("network.bad_share"), 400, code="net_bad_share")
    user = str(body.get("user") or "")[:256]
    password = str(body.get("password") or "")[:256]
    try:
        reachable(host)
        connect(host, share, user, password)
    except NetworkError as exc:
        return exc.response()
    try:
        if body.get("remember"):
            remember_credentials(host, share, user, password)
        else:
            forget_credentials(host, share)
    except OSError as exc:
        log.warning("Could not save the network sign-in (%s)", exc)
    return jsonify({"success": True, "path": unc(host, share)})


@bp.route("/api/network/favorites", methods=["POST"])
def api_favorites():
    body = request.get_json(silent=True) or {}
    try:
        if body.get("action") == "remove":
            data = remove_favorite(body.get("path"))
        else:
            data = add_favorite(body.get("path"), body.get("label"))
    except ValueError as exc:
        return api_err(str(exc), 400, code="net_bad_favorite")
    return jsonify({"favorites": data["favorites"]})


@bp.route("/api/network/settings", methods=["POST"])
def api_network_settings():
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("reload_after_save"), bool):
        return api_err("reload_after_save", 400, code="invalid_setting")
    data = set_reload_after_save(body["reload_after_save"])
    return jsonify({"reload_after_save": data["reload_after_save"]})


@bp.route("/api/network/api-status")
def api_status():
    loc = location(xml_store.XML_PATH) if xml_store.has_gamelist() else None
    if not loc:
        return jsonify({"current": None})
    return jsonify({"current": describe(xml_store.XML_PATH), "api": es_api(loc["host"])})


@bp.route("/api/network/reload", methods=["POST"])
def api_reload():
    """Reload the game lists on the machine of the open gamelist (never another host)."""
    loc = location(xml_store.XML_PATH) if xml_store.has_gamelist() else None
    if not loc:
        return api_err(st("network.not_remote"), 400, code="net_not_remote")
    result = reload_games(loc["host"])
    if not result["ok"]:
        return api_err(result["error"], 502, code="net_reload_failed")
    return jsonify(dict(result, success=True))

