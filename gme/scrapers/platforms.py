"""Platforms of the fallback sources, keyed by the ScreenScraper system id.

``gme.systems.SS_SYSTEM_MAP`` already turns every RetroBat / Batocera folder
into a ScreenScraper system id; this table turns that id into the platform(s)
of LaunchBox Games Database (platform names of its ``Platforms.xml``),
TheGamesDB (platform ids, comma list for its ``filter[platform]``) and IGDB
(platform ids). ``None``: the source has no such platform, so it is not asked.
Sources (facts, cross-checked): LaunchBox ``Metadata.zip`` › ``Platforms.xml``,
TheGamesDB ``/v1/Platforms``, IGDB ``/v4/platforms``.
"""

# ss id: (LaunchBox platforms, TheGamesDB ids, IGDB ids)
PLATFORMS = {
    1: (("Sega Genesis",), "18,36", (29,)),                 # Mega Drive / Genesis
    2: (("Sega Master System",), "35", (64,)),
    3: (("Nintendo Entertainment System",), "7", (18, 99)),  # NES / Famicom
    4: (("Super Nintendo Entertainment System",), "6", (19, 58)),
    9: (("Nintendo Game Boy",), "4", (33,)),
    10: (("Nintendo Game Boy Color",), "41", (22,)),
    11: (("Nintendo Virtual Boy",), "4918", (87,)),
    12: (("Nintendo Game Boy Advance",), "5", (24,)),
    13: (("Nintendo GameCube",), "2", (21,)),
    14: (("Nintendo 64",), "3", (4,)),
    15: (("Nintendo DS",), "8", (20,)),
    16: (("Nintendo Wii",), "9", (5,)),
    17: (("Nintendo 3DS",), "4912", (37,)),
    18: (("Nintendo Wii U",), "38", (41,)),
    19: (("Sega 32X",), "33", (30,)),
    20: (("Sega CD",), "21", (78,)),
    21: (("Sega Game Gear",), "20", (35,)),
    22: (("Sega Saturn",), "17", (32,)),
    23: (("Sega Dreamcast",), "16", (23,)),
    25: (("SNK Neo Geo Pocket",), "4922", (119,)),
    26: (("Atari 2600",), "22", (59,)),
    27: (("Atari Jaguar",), "28", (62,)),
    28: (("Atari Lynx",), "4924", (61,)),
    29: (("3DO Interactive Multiplayer",), "25", (50,)),
    31: (("NEC TurboGrafx-16",), "34", (86,)),
    32: (("Microsoft Xbox",), "14", (11,)),
    33: (("Microsoft Xbox 360",), "15", (12,)),
    40: (("Atari 5200",), "26", (66,)),
    41: (("Atari 7800",), "27", (60,)),
    42: (("Atari ST",), "4937", (63,)),
    43: (("Atari 800", "Atari XEGS"), "4943,30", (65,)),
    45: (("WonderSwan",), "4925", (57,)),
    46: (("WonderSwan Color",), "4926", (123,)),
    48: (("ColecoVision",), "31", (68,)),
    52: (("Nintendo Game & Watch",), "4950", (307,)),
    53: (("Sammy Atomiswave",), "23", (52,)),
    56: (("Sega Naomi",), "23", (52,)),
    57: (("Sony Playstation",), "10", (7,)),
    58: (("Sony Playstation 2",), "11", (8,)),
    59: (("Sony Playstation 3",), "12", (9,)),
    60: (("Sony Playstation 4",), "4919", (48,)),
    61: (("Sony PSP",), "13", (38,)),
    62: (("Sony Playstation Vita",), "39", (46,)),
    64: (("Commodore Amiga",), "4911", (16,)),
    65: (("Amstrad CPC",), "4914", (25,)),
    66: (("Commodore 64",), "40", (15,)),
    70: (("SNK Neo Geo CD",), "4956", (136,)),
    72: (("NEC PC-FX",), "4930", (274,)),
    73: (("Commodore VIC-20",), "4945", (71,)),
    75: (("Arcade",), "23", (52,)),
    76: (("Sinclair ZX Spectrum",), "4913", (26,)),
    77: (("Sinclair ZX-81",), "5010", (373,)),
    79: (("Sharp X68000",), "4931", (121,)),
    80: (("Fairchild Channel F",), None, (127,)),
    82: (("SNK Neo Geo Pocket Color",), "4923", (120,)),
    86: (("Apple II",), "4942", (75,)),
    94: (("Emerson Arcadia 2001",), "4963", (473,)),
    99: (("Commodore Plus 4",), "5007", (94,)),
    102: (("GCE Vectrex",), "4939", (70,)),
    104: (("Magnavox Odyssey 2",), "4927", (133,)),
    105: (("PC Engine SuperGrafx",), "34", (128,)),
    106: (("Nintendo Famicom Disk System",), "4936", (51,)),
    109: (("Sega SG-1000",), "4949", (84,)),
    113: (("Microsoft MSX",), "4929", (27,)),
    114: (("NEC TurboGrafx-CD",), "4955", (150,)),
    115: (("Mattel Intellivision",), "32", (67,)),
    116: (("Microsoft MSX2",), "4929", (53,)),
    130: (("Commodore Amiga CD32",), "4947", (114,)),
    133: (("Philips CD-i",), "4917", (117,)),
    135: (("MS-DOS",), "1", (13,)),
    138: (("Windows",), "1", (6,)),
    142: (("SNK Neo Geo AES", "SNK Neo Geo MVS"), "24", (80, 79)),
    146: (("Apple Mac OS",), "37", (14,)),
    207: (("Watara Supervision",), "4959", (415,)),
    211: (("Nintendo Pokemon Mini",), "4957", (166,)),
    225: (("Nintendo Switch",), "4971", (130,)),
    281: (("Interton VC 4000",), None, (138,)),
    # Arcade boards and their LaunchBox platforms
    6: (("Arcade",), "23", (52,)),                           # CPS-1
    7: (("Arcade",), "23", (52,)),                           # CPS-2
    8: (("Arcade",), "23", (52,)),                           # CPS-3
    47: (("Arcade",), "23", (52,)),                          # Cave
    54: (("Sega Model 2",), "23", (52,)),
    55: (("Sega Model 3",), "23", (52,)),
    69: (("Sega ST-V",), "23", (52,)),
    # Consoles, handhelds and computers
    30: (("Nokia N-Gage",), "4938", (42,)),
    34: (("Microsoft Xbox One",), None, (49,)),
    36: (("Acorn Atom",), None, None),
    37: (("BBC Microcomputer System",), "5013", (69,)),
    44: (("Bally Astrocade",), "4968", (91,)),
    67: (("Epoch Super Cassette Vision",), None, None),
    74: (("Casio PV-1000",), "4964", None),
    78: (("Entex Adventure Vision",), None, None),
    84: (("Acorn Archimedes",), "4944", (116,)),
    85: (("Acorn Electron",), "4954", (134,)),
    87: (("Amstrad GX4000",), "4914", (506,)),
    88: (("Camputers Lynx",), None, None),
    89: (("Coleco ADAM",), None, None),
    90: (("Mega Duck",), "4948", (408,)),
    91: (("Dragon 32/64",), "4952", (153,)),
    93: (("Elektronika BK",), None, None),
    95: (("Epoch Game Pocket Computer",), None, None),
    97: (("Fujitsu FM-7",), "4978", (152,)),
    98: (("Casio Loopy",), None, (380,)),
    100: (("Funtech Super Acan",), None, (480,)),
    101: (("GamePark GP32",), None, None),
    103: (("Hartung Game Master",), None, None),
    107: (("Nintendo Satellaview",), "6", (306,)),
    108: (("Super Nintendo Entertainment System",), "6", (19, 58)),  # Sufami Turbo
    117: (("Microsoft MSX2+",), "4929", (53,)),
    120: (("VTech V.Smile",), "4988", (439,)),
    121: (("Tiger Game.com",), "4940", (379,)),
    122: (("Nintendo 64DD",), "3", (416,)),
    123: (("ScummVM",), None, None),
    127: (("Super Nintendo Entertainment System",), "6", (19,)),  # Super Game Boy
    129: (("Commodore CDTV",), None, (158,)),
    131: (("Oric Atmos",), "4986", None),
    144: (("TRS-80 Color Computer",), "4941", (151,)),
    171: (("Atari Jaguar CD",), "29", (410,)),
    205: (("Texas Instruments TI 99/4A",), "4953", (129,)),
    208: (("NEC PC-9801",), "4934", (149,)),
    210: (("Super Nintendo Entertainment System",), "6", (19, 58)),  # MSU-1
    213: (("SAM Coupé",), "4979", None),
    214: (("OpenBOR",), None, None),
    216: (("Uzebox",), None, (504,)),
    217: (("Apple IIGS",), "4942", (115,)),
    218: (("Spectravideo",), None, None),
    220: (("Sharp X1",), "4977", (77,)),
    221: (("NEC PC-8801",), "4933", (125,)),
    234: (("PICO-8",), None, None),
    240: (("Commodore PET",), None, (90,)),
    241: (("VTech CreatiVision",), "5005", None),
    253: (("Fujitsu FM Towns Marty",), "4932", (118,)),
    262: (("WASM-4",), None, None),
    263: (("Arduboy",), None, (438,)),
    266: ((), "5004", (378,)),                               # Gamate
}


def for_source(source, system_id):
    """The platform(s) of ``source`` for a ScreenScraper system id, or None."""
    entry = PLATFORMS.get(system_id) if system_id else None
    if not entry:
        return None
    return {"launchbox": entry[0], "thegamesdb": entry[1], "igdb": entry[2]}.get(source)
