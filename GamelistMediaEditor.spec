# -*- mode: python ; coding: utf-8 -*-
# Build on Windows:  pyinstaller --noconfirm GamelistMediaEditor.spec
import sys
from pathlib import Path

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "static"), "static"),
]

a = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "lxml",
        "lxml.etree",
        "lxml._elementpath",
        "flask",
        "jinja2",
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
        "werkzeug",
        "click",
        "itsdangerous",
        "markupsafe",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GamelistMediaEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # keep console for status / errors (Quit still stops process)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "icon.ico") if (ROOT / "icon.ico").is_file() else None,
)
