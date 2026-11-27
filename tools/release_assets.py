"""Build the release assets from a built GamelistMediaEditor.exe.

    python tools/release_assets.py dist/GamelistMediaEditor.exe 1.8.0 release-out

writes ``release-out/GamelistMediaEditor-Windows-v1.8.0.zip`` (the .exe at the
root of the zip) and ``release-out/SHA256SUMS.txt`` (sha256sum format). The
in-app updater (gme/updater.py) refuses a release without that checksum file,
so both files must be attached to every GitHub release.
"""
import hashlib
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gme.updater import EXE_NAME, SUMS_NAME, parse_sums, zip_name  # noqa: E402


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build(exe, version, out_dir):
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        raise SystemExit(f"version must be X.Y.Z, got {version!r}")
    with open(exe, "rb") as f:
        if f.read(2) != b"MZ":
            raise SystemExit(f"{exe} is not a Windows executable")
    os.makedirs(out_dir, exist_ok=True)
    archive = os.path.join(out_dir, zip_name(version))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(exe, EXE_NAME)
    sums = os.path.join(out_dir, SUMS_NAME)
    line = f"{sha256(archive)}  {os.path.basename(archive)}\n"
    with open(sums, "w", encoding="ascii", newline="\n") as f:
        f.write(line)
    assert parse_sums(line) == {os.path.basename(archive): sha256(archive)}
    return archive, sums


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    for path in build(*sys.argv[1:]):
        print(path)
