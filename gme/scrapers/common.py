"""Helpers shared by the scrapers: API throttling, name matching, ROM hashes."""

import os
import re
import threading
import time
import hashlib
import zlib


def file_hashes(path, max_bytes=None):
    """Return crc32 (hex upper), md5, sha1, size for a ROM file."""
    size = os.path.getsize(path)
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    crc = 0
    read = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            if max_bytes is not None and read + len(chunk) > max_bytes:
                chunk = chunk[: max_bytes - read]
            md5.update(chunk)
            sha1.update(chunk)
            crc = zlib.crc32(chunk, crc) & 0xFFFFFFFF
            read += len(chunk)
            if max_bytes is not None and read >= max_bytes:
                break
    return {
        "crc": f"{crc:08X}",
        "md5": md5.hexdigest(),
        "sha1": sha1.hexdigest(),
        "size": size,
        "source": "file",
    }


def rom_identification(path):
    """
    Build the best ScreenScraper identification for a ROM path.
    For .zip: hash the *inner* ROM (No-Intro style) — SS matches that CRC, not the zip's.
    """
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    info = {"outer_name": os.path.basename(path), "outer_size": os.path.getsize(path)}

    if ext == ".zip":
        # ScreenScraper matches the *inner* ROM CRC (No-Intro), not the outer ZIP CRC.
        try:
            import zipfile
            with zipfile.ZipFile(path, "r") as zf:
                # Prefer real ROM members (skip .txt, .nfo, directories)
                skip_ext = {".txt", ".nfo", ".diz", ".url", ".xml", ".htm", ".html"}
                members = [
                    m for m in zf.infolist()
                    if not m.is_dir() and os.path.splitext(m.filename)[1].lower() not in skip_ext
                ]
                if not members:
                    members = [m for m in zf.infolist() if not m.is_dir()]
                if members:
                    # Largest member is usually the ROM
                    members.sort(key=lambda m: m.file_size, reverse=True)
                    member = members[0]
                    md5 = hashlib.md5()
                    sha1 = hashlib.sha1()
                    crc = 0
                    with zf.open(member, "r") as f:
                        while True:
                            chunk = f.read(1024 * 1024)
                            if not chunk:
                                break
                            md5.update(chunk)
                            sha1.update(chunk)
                            crc = zlib.crc32(chunk, crc) & 0xFFFFFFFF
                    info.update({
                        "crc": f"{crc:08X}",
                        "md5": md5.hexdigest(),
                        "sha1": sha1.hexdigest(),
                        "size": member.file_size,
                        "source": "zip-inner",
                        "inner_name": os.path.basename(member.filename),
                    })
                    return info
        except Exception as e:
            info["zip_error"] = str(e)

    # Plain file (or zip fallback)
    try:
        h = file_hashes(path)
        info.update(h)
        return info
    except OSError as e:
        info["error"] = str(e)
        return info


_SS_NAME_STRIP = re.compile(
    r"\s*[\(\[].*?[\)\]]\s*|\s*[Tt]he\s+",
    re.UNICODE,
)


def clean_game_name(name):
    """Strip region/dump tags for softer name matching."""
    if not name:
        return ""
    base = os.path.splitext(os.path.basename(name))[0]
    # remove (...) and [...] groups repeatedly
    prev = None
    while prev != base:
        prev = base
        base = re.sub(r"\s*[\(\[].*?[\)\]]", "", base)
    base = re.sub(r"[._]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip().lower()
    if base.startswith("the "):
        base = base[4:]
    return base


def name_similarity(a, b):
    """Rough 0..1 similarity for ranking search candidates."""
    ca, cb = clean_game_name(a), clean_game_name(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    if ca in cb or cb in ca:
        return 0.85
    # token overlap
    ta, tb = set(ca.split()), set(cb.split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(len(ta), len(tb))


# Minimum interval between outbound API calls (politeness + avoid bursts)
_SS_MIN_INTERVAL = 1.1
_ADB_MIN_INTERVAL = 0.45
_STEAM_MIN_INTERVAL = 0.45
_ss_last_call = 0.0
_adb_last_call = 0.0
_steam_last_call = 0.0
_api_throttle_lock = threading.Lock()


def throttle_api(service):
    """Serialize and space calls per service (one logical client)."""
    global _ss_last_call, _adb_last_call, _steam_last_call
    with _api_throttle_lock:
        now = time.time()
        if service == "ss":
            wait = _SS_MIN_INTERVAL - (now - _ss_last_call)
            if wait > 0:
                time.sleep(wait)
            _ss_last_call = time.time()
        elif service == "steam":
            wait = _STEAM_MIN_INTERVAL - (now - _steam_last_call)
            if wait > 0:
                time.sleep(wait)
            _steam_last_call = time.time()
        else:
            wait = _ADB_MIN_INTERVAL - (now - _adb_last_call)
            if wait > 0:
                time.sleep(wait)
            _adb_last_call = time.time()
