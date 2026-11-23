"""A generated ES-DE installation for the tests (never real ROMs: a few bytes each).

Desktop layout (``portable=False``)::

    <tmp>/home/ES-DE/settings/es_settings.xml        ROMDirectory ~/Games/ROMs
    <tmp>/home/ES-DE/gamelists/{snes,megadrive,CLEANUP}/gamelist.xml
    <tmp>/home/ES-DE/downloaded_media/snes/<type>/...
    <tmp>/home/Games/ROMs/{snes,megadrive}/...

Windows portable layout (``portable=True``): ``<tmp>/ES-DE/portable.txt``, the
data in ``<tmp>/ES-DE/ES-DE`` and the ROMs in ``<tmp>/ES-DE/ROMs`` (empty
ROMDirectory setting, ES-DE's default).
"""
import os

SNES = """<?xml version="1.0"?>
<gameList>
  <folder><path>./Multi</path><name>Multi-disc</name></folder>
  <game>
    <path>./Alpha (Europe).sfc</path>
    <name>Alpha</name>
    <desc>First game.</desc>
    <altemulator>Snes9x - Current</altemulator>
    <playcount>3</playcount>
  </game>
  <game>
    <path>./Multi/Bravo/Bravo.m3u</path>
    <name>Bravo</name>
    <image>./images/bravo-legacy.png</image>
  </game>
  <game>
    <path>./Charlie.zip</path>
    <name>Charlie</name>
  </game>
</gameList>
"""
MEGADRIVE = """<?xml version="1.0"?>
<gameList>
  <game><path>./Sonic.md</path><name>Sonic</name><genre>Platform</genre></game>
</gameList>
"""
SETTINGS = """<?xml version="1.0"?>
<bool name="ScraperRegionFallback" value="true" />
<string name="MediaDirectory" value="{media}" />
<string name="ROMDirectory" value="{roms}" />
<string name="ThemeSet" value="linear-es-de" />
"""


def picture(color=(40, 120, 200), fmt="PNG"):
    from tests.conftest import picture as pic
    return pic((64, 48), color, fmt)


def write(path, data):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def make_esde(tmp_path, portable=False, media_setting="", rom_setting=None):
    """Build the tree; returns a dict of its main paths."""
    tmp_path = str(tmp_path)
    if portable:
        parent = os.path.join(tmp_path, "ES-DE")
        write(os.path.join(parent, "portable.txt"), "")
        write(os.path.join(parent, "ES-DE.exe"), b"MZ")
        rom_setting = "" if rom_setting is None else rom_setting
    else:
        parent = os.path.join(tmp_path, "home")
        rom_setting = "~/Games/ROMs" if rom_setting is None else rom_setting
    home = os.path.join(parent, "ES-DE")
    write(os.path.join(home, "settings", "es_settings.xml"), SETTINGS.format(media=media_setting, roms=rom_setting))
    roms = os.path.join(parent, "ROMs") if not rom_setting else os.path.join(parent, "Games", "ROMs")
    media = os.path.join(home, "downloaded_media")
    if media_setting:
        media = os.path.normpath(media_setting.replace("%ESPATH%", parent).replace("~", parent))
    write(os.path.join(home, "gamelists", "snes", "gamelist.xml"), SNES)
    write(os.path.join(home, "gamelists", "megadrive", "gamelist.xml"), MEGADRIVE)
    write(os.path.join(home, "gamelists", "CLEANUP", "gamelist.xml"), "<gameList/>")
    for rel in ("snes/Alpha (Europe).sfc", "snes/Multi/Bravo/Bravo (Disc 1).chd",
                "snes/Charlie.zip", "snes/Delta.sfc", "megadrive/Sonic.md"):
        write(os.path.join(roms, *rel.split("/")), b"rom")
    write(os.path.join(roms, "snes", "Multi", "Bravo", "Bravo.m3u"), "Bravo (Disc 1).chd\n")
    snes = os.path.join(media, "snes")
    write(os.path.join(snes, "covers", "Alpha (Europe).png"), picture((200, 40, 40)))
    write(os.path.join(snes, "screenshots", "Alpha (Europe).jpg"), picture((40, 200, 40), "JPEG"))
    write(os.path.join(snes, "marquees", "Alpha (Europe).png"), picture((40, 40, 200)))
    write(os.path.join(snes, "videos", "Multi", "Bravo", "Bravo.mp4"), b"\x00\x00\x00\x18ftypmp42")
    write(os.path.join(snes, "miximages", "Delta.png"), picture((90, 90, 90)))   # a ROM not in the gamelist
    write(os.path.join(snes, "covers", "Ghost.png"), picture((10, 10, 10)))      # no ROM at all: orphan
    write(os.path.join(snes, "custom", "Alpha (Europe).png"), picture((5, 5, 5)))  # ES-DE's custom folder
    write(os.path.join(media, "megadrive", "covers", "Sonic.png"), picture((0, 0, 200)))
    return {"parent": parent, "home": home, "roms": roms, "media": media, "snes_media": snes,
            "snes_xml": os.path.join(home, "gamelists", "snes", "gamelist.xml"),
            "md_xml": os.path.join(home, "gamelists", "megadrive", "gamelist.xml")}
