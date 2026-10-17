"""Where things live: bundled resources (PyInstaller) and the writable app folder."""

import os
import sys


def resource_path(*parts):
    """Bundled resources (PyInstaller _MEIPASS) or source tree."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts) if parts else base


def app_data_dir():
    """Writable directory next to the .exe (or next to app.py in source mode)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Writable app dir (config next to .exe); BUNDLE_DIR holds templates/static
APP_DIR = app_data_dir()
BUNDLE_DIR = resource_path()
