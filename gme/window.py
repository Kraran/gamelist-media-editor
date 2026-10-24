"""Application window: Chromium --app mode (Edge / Chrome / Brave) or default browser."""

import os
import threading
import time
import subprocess

from gme.log import log
from gme.paths import APP_DIR


# Chromium "app mode" window (no tabs / address bar). Process is watched so
# closing the window also stops the local server.
_UI_PROC = None


def _chromium_candidates():
    """Known Edge / Chrome / Brave install paths (Windows + a few extras)."""
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    pfx86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    local = os.environ.get("LOCALAPPDATA") or ""
    return [
        os.path.join(pfx86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(local, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(local, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
    ]


def _is_chromium_exe(path):
    name = os.path.basename(path or "").lower()
    return name in {
        "msedge.exe", "chrome.exe", "brave.exe", "chromium.exe",
        "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
    }


def _windows_http_progid():
    """User's default HTTP handler ProgId (ChromeHTML, MSEdgeHTM, FirefoxURL…)."""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            progid, _ = winreg.QueryValueEx(key, "ProgId")
        return (progid or "").strip()
    except Exception:
        return ""


def _exe_from_progid(progid):
    """Resolve a Windows ProgId to its .exe path."""
    if not progid or os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command") as key:
            cmd, _ = winreg.QueryValueEx(key, None)
        cmd = (cmd or "").strip()
        if cmd.startswith('"'):
            end = cmd.find('"', 1)
            if end > 1:
                return cmd[1:end]
        return cmd.split()[0] if cmd else None
    except Exception:
        return None


def _find_app_mode_browser():
    """
    Prefer the *default* browser when it is Chromium-based (supports --app=).
    Otherwise use Edge / Chrome / Brave if installed.
    Returns exe path or None.
    """
    progid = _windows_http_progid().lower()
    default_exe = _exe_from_progid(_windows_http_progid())
    if default_exe and os.path.isfile(default_exe) and _is_chromium_exe(default_exe):
        return default_exe
    # ProgId hint even if command path is odd
    if "chrome" in progid or "edge" in progid or "brave" in progid:
        for path in _chromium_candidates():
            if not path or not os.path.isfile(path):
                continue
            base = os.path.basename(path).lower()
            if "chrome" in progid and "chrome" in base:
                return path
            if "edge" in progid and "msedge" in base:
                return path
            if "brave" in progid and "brave" in base:
                return path
    for path in _chromium_candidates():
        if path and os.path.isfile(path):
            return path
    return None


def close_ui_window():
    """Terminate the dedicated app-mode window if we started it."""
    global _UI_PROC
    proc = _UI_PROC
    if proc is None:
        return
    try:
        if proc.poll() is None:
            # Ask the window to close first, so that the browser writes its
            # storage (language, scrape sources…) to disk; force it after 3 s.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
    except Exception:
        pass
    _UI_PROC = None


def _watch_ui_process():
    """If the user closes the app window, stop the local server too."""
    time.sleep(3)
    proc = _UI_PROC
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.wait()
    except Exception:
        return
    os._exit(0)


def open_browser(url):
    """
    Open a dedicated Chromium app window (no tabs / address bar) when possible.
    Fallback: system default browser (with normal chrome).
    """
    global _UI_PROC
    exe = _find_app_mode_browser()
    if exe:
        profile = os.path.join(APP_DIR, "app-window")
        try:
            os.makedirs(profile, exist_ok=True)
        except OSError:
            profile = None
        cmd = [
            exe,
            f"--app={url}",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--window-size=1280,840",
        ]
        if profile:
            cmd.append(f"--user-data-dir={profile}")
        try:
            _UI_PROC = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            threading.Thread(target=_watch_ui_process, daemon=True).start()
            log.info("App window: %s", exe)
            return
        except Exception as e:
            log.warning("App window failed (%s), fallback browser", e)
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
