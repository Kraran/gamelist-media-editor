"""ScreenScraper system detected from the gamelist folder (RetroBat folder names)."""

import os

from gme import xml_store


# RetroBat / ES folder name → ScreenScraper systemeid (unknown folder → None).
# Source: RetroBat's es_systems.cfg (folder → platform) and the ScreenScraper
# id tables of RetroBat/Batocera EmulationStation (ScreenScraper.cpp,
# PlatformId.cpp), cross-checked with ES-DE. Rule: the exact SS system when one
# exists (naomi 56, cps1 6, pet 240…), else the id RetroBat itself scrapes with
# (c128 → C64, ports → PC…). Keep keys unique: tests/test_ss_system_map.py.
SS_SYSTEM_MAP = {
    "2ship": 14, "32x": 19, "3do": 29, "3ds": 17, "actionmax": 81, "adam": 89,
    "advision": 78, "amazon": 138, "amiga": 64, "amiga1000": 64, "amiga1200": 64,
    "amiga3000": 64, "amiga4000": 64, "amiga500": 64, "amiga600": 64, "amigacd32": 130,
    "amigacdtv": 129, "amstradcpc": 65, "apple2": 86, "apple2gs": 217, "arcade": 75,
    "arcadia": 94, "archimedes": 84, "arduboy": 263, "astrocade": 44, "atari2600": 26,
    "atari5200": 40, "atari7800": 41, "atari800": 43, "atarijaguar": 27, "atarilynx": 28,
    "atarist": 42, "atarixe": 43, "atom": 36, "atomiswave": 53, "bbcmicro": 37,
    "bennugd": 138, "bk": 93, "bstone": 138, "bsyndrome": 135, "c128": 66, "c16": 99,
    "c20": 73, "c64": 66, "camplynx": 88, "cannonball": 135, "casloopy": 98,
    "cassettevision": 300, "cave": 47, "cavestory": 135, "cd32": 130, "cdi": 133,
    "cdogs": 135, "cgenius": 135, "channelf": 80, "chihiro": 75, "coco": 144,
    "colecovision": 48, "commodore64": 66, "corsixth": 135, "cpc": 65, "cplus4": 99,
    "cps1": 6, "cps2": 7, "cps3": 8, "crvision": 241, "daphne": 49, "devilutionx": 135,
    "dice": 75, "dinothawr": 135, "doom": 135, "doom3": 138, "dos": 135, "dragon32": 91,
    "dreamcast": 23, "dusklight": 13, "eagames": 138, "easyrpg": 231, "ecwolf": 135,
    "eduke32": 135, "electron": 85, "epic": 138, "exodos": 135, "exowin3x": 135,
    "exowin9x": 135, "famicom": 3, "fba": 75, "fbneo": 75, "fds": 106, "fm7": 97,
    "fmtowns": 253, "fpinball": 199, "gaelco": 194, "gamate": 266, "gameandwatch": 52,
    "gamecom": 121, "gamecube": 13, "gamegear": 21, "gamepock": 95, "gb": 9,
    "gb2players": 9, "gba": 12, "gba2players": 12, "gbc": 10, "gbc2players": 10, "gc": 13,
    "gemrb": 135, "genesis": 1, "gg": 21, "gmaster": 103, "gog": 138, "gp32": 101, "gw": 52,
    "gx4000": 87, "halflife": 138, "hbmame": 75, "hikaru": 75, "ikemen": 135,
    "intellivision": 115, "j2me": 302, "jaguar": 27, "jaguarcd": 171, "lcdgames": 75,
    "lindbergh": 75, "love": 206, "lowresnx": 244, "lutro": 206, "lynx": 28, "mac": 146,
    "macintosh": 146, "mame": 75, "mame2003": 75, "mame2010": 75, "mastersystem": 2,
    "megacd": 20, "megadrive": 1, "megadrive-msu": 1, "megaduck": 90, "mess": 135,
    "mo5": 141, "model2": 54, "model3": 55, "msx": 113, "msx1": 113, "msx2": 116,
    "msx2+": 117, "msxturbor": 118, "mugen": 135, "multivision": 109, "n3ds": 17, "n64": 14,
    "n64dd": 122, "namco2x6": 75, "namco3xx": 75, "naomi": 56, "naomi2": 75, "nds": 15,
    "neogeo": 142, "neogeo64": 75, "neogeocd": 70, "nes": 3, "ngage": 30, "ngp": 25,
    "ngpc": 82, "odyssey2": 104, "openbor": 214, "opengoal": 135, "openjazz": 135,
    "openlara": 138, "oric": 131, "oricatmos": 131, "pc": 135, "pc88": 221, "pc98": 208,
    "pcengine": 31, "pcenginecd": 114, "pcfx": 72, "pdark": 14, "pet": 240, "pico8": 234,
    "pinballfx": 138, "pinballfx2": 138, "pinballfx3": 138, "pinballm": 138, "plus4": 99,
    "pokemini": 211, "ports": 135, "powerbomberman": 138, "ps1": 57, "ps2": 58, "ps3": 59,
    "ps4": 60, "psp": 61, "psvita": 62, "psx": 57, "pv1000": 74, "quake": 135,
    "quake2": 138, "raze": 135, "recomp": 135, "reminiscence": 135, "rtcw": 138,
    "samcoupe": 213, "satellaview": 107, "saturn": 22, "scummvm": 123, "scv": 67,
    "sega32x": 19, "segacd": 20, "segastv": 69, "sfc": 4, "sg1000": 109, "sgb": 127,
    "sgb-msu1": 9, "singe": 49, "sms": 2, "snes": 4, "snes-msu1": 210, "soh": 14,
    "solarus": 223, "sonic-mania": 135, "sonic3-air": 135, "sonicretro": 135,
    "spectravideo": 218, "spectrum": 76, "starship": 14, "steam": 138, "sufami": 108,
    "superbroswar": 135, "supergrafx": 105, "supernes": 4, "supervision": 207,
    "supracan": 100, "switch": 225, "teknoparrot": 269, "tg16": 31, "tg16cd": 114,
    "theforceengine": 135, "thomson": 141, "ti99": 205, "tic80": 222, "to7": 141,
    "triforce": 75, "uzebox": 216, "vc4000": 281, "vectrex": 102, "vic20": 73,
    "vircon32": 272, "virtualboy": 11, "vita": 62, "vpinball": 198, "vsmile": 120,
    "wasm4": 262, "wii": 16, "wiiu": 18, "windows": 138, "wonderswan": 45,
    "wonderswancolor": 46, "wswan": 45, "wswanc": 46, "x1": 220, "x68000": 79, "xbox": 32,
    "xbox360": 33, "xboxone": 34, "xegs": 43, "zaccariapinball": 138, "zeldaclassic": 135,
    "zinc": 75, "zx81": 77, "zxspectrum": 76,
}


def detect_system_id():
    """Guess ScreenScraper systemeid from parent folder of gamelist.xml."""
    folder = os.path.basename(os.path.normpath(xml_store.BASE_DIR)).lower().strip()
    if folder in SS_SYSTEM_MAP:
        sid = SS_SYSTEM_MAP[folder]
        return (sid if sid else None), folder
    # strip common prefixes
    for prefix in ("roms-", "rom-", "sys-"):
        if folder.startswith(prefix):
            key = folder[len(prefix):]
            if key in SS_SYSTEM_MAP:
                sid = SS_SYSTEM_MAP[key]
                return (sid if sid else None), key
    # Heuristics: amiga500 → amiga, megadrive_* etc.
    prefixes = (
        ("amiga", 64), ("c64", 66), ("nes", 3), ("snes", 4), ("mame", 75),
        ("fbneo", 75), ("psx", 57), ("ps1", 57), ("ps2", 58), ("psp", 61),
        ("megadrive", 1), ("genesis", 1), ("n64", 14), ("gba", 12),
        ("dos", 135), ("pc", 135), ("zx", 76), ("msx", 113),
    )
    for pref, sid in prefixes:
        if folder.startswith(pref):
            return sid, folder
    return None, folder


def get_system_info():
    """Human-readable system label from the gamelist parent folder."""
    sid, folder = detect_system_id()
    # Prefer original folder casing from BASE_DIR
    display = os.path.basename(os.path.normpath(xml_store.BASE_DIR)) or folder or "—"
    return {
        "folder": folder or display.lower(),
        "label": display,
        "id": sid,
    }
