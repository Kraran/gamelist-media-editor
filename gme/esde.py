"""ES-DE (EmulationStation Desktop Edition) layout.

ES-DE keeps its data apart from the games (see its INSTALL.md / USERGUIDE.md)::

    <ES-DE>/settings/es_settings.xml                 ROMDirectory, MediaDirectory
    <ES-DE>/gamelists/<system>/gamelist.xml          metadata only, no media tag
    <MediaDirectory or ES-DE/downloaded_media>/<system>/<type>/<rom path minus ext>.<ext>
    <ROMDirectory or ~/ROMs>/<system>/...            the games (<path> is relative to it)

``<ES-DE>`` is ``~/ES-DE`` (installer) or ``ES-DE\\ES-DE`` (Windows portable
release, ``portable.txt`` next to ES-DE.exe). ``~`` and ``%ESPATH%`` in the
settings expand to the folder that holds ``<ES-DE>`` (the user's home, or the
portable folder).

A media is found by its name, never through a tag: when an ES-DE gamelist is
open, GME adds in memory one tag per media found (value ``@media/<type>/<name>``,
resolved by ``xml_store.resolve_under_base``) so the editor, the scrapers and
the batch actions work as usual. These tags are never written: ``strip_for_save``
removes them from the copy that goes to disk. Media tags already present in the
file (a gamelist copied from another EmulationStation, ignored by ES-DE) are
kept aside on load and written back unchanged.
"""

import html
import os
import re

from lxml import etree

# GME field -> ES-DE media folder
FOLDERS = {
    "image": "screenshots",
    "titleshot": "titlescreens",
    "thumbnail": "covers",
    "boxart": "3dboxes",
    "boxback": "backcovers",
    "marquee": "marquees",
    "cartridge": "physicalmedia",
    "fanart": "fanart",
    "mix": "miximages",
    "video": "videos",
    "manual": "manuals",
}
FIELDS = tuple(FOLDERS)
IMAGE_EXTS = (".png", ".jpg", ".webp")
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".wmv", ".mov", ".webm", ".m4v")
MANUAL_EXTS = (".pdf",)
PREFIX = "@media/"
LEGACY_ATTR = "gme-legacy-media"          # media tags of the file itself, kept aside in memory
NOT_SYSTEMS = {"CLEANUP"}                 # ES-DE's orphaned data cleanup backups

_SETTING = re.compile(r'<string\s+name="(ROMDirectory|MediaDirectory)"\s+value="([^"]*)"')


def exts_for(field):
    if field == "video":
        return VIDEO_EXTS
    if field == "manual":
        return MANUAL_EXTS
    return IMAGE_EXTS


class Layout:
    """One ES-DE installation, and the system of the open gamelist."""

    def __init__(self, home, system=None):
        self.home = os.path.normpath(home)               # the ES-DE application data folder
        self.system = system
        self.settings_file = os.path.join(self.home, "settings", "es_settings.xml")
        settings = read_settings(self.settings_file)
        self.parent = os.path.dirname(self.home)          # what ~ and %ESPATH% expand to
        self.rom_root = self._expand(settings.get("ROMDirectory")) or os.path.join(self.parent, "ROMs")
        self.media_root = self._expand(settings.get("MediaDirectory")) or os.path.join(self.home, "downloaded_media")
        self.gamelists = os.path.join(self.home, "gamelists")
        self.portable = os.path.isfile(os.path.join(self.parent, "portable.txt"))
        self.rom_dir = self._rom_dir()

    def _expand(self, value):
        value = (value or "").strip()
        if not value:
            return None
        value = value.replace("%ESPATH%", self.parent).replace("%ROMPATH%", "")
        if value == "~" or value.startswith(("~/", "~\\")):
            value = self.parent + value[1:]
        if not os.path.isabs(value):
            value = os.path.join(self.parent, value)
        return os.path.normpath(value)

    def _rom_dir(self):
        """Folder the ``<path>`` tags of this system are relative to."""
        custom = system_rom_path(self.home, self.system)
        if custom:
            custom = custom.replace("%ROMPATH%", self.rom_root)
            return os.path.normpath(self._expand(custom) or custom)
        return os.path.normpath(os.path.join(self.rom_root, self.system or ""))

    @property
    def media_dir(self):
        return os.path.join(self.media_root, self.system or "")

    def info(self):
        return {"kind": "esde", "home": self.home, "rom_dir": self.rom_dir,
                "media_dir": self.media_dir, "portable": self.portable, "fields": list(FIELDS),
                "folders": dict(FOLDERS)}


def read_settings(path):
    """ROMDirectory / MediaDirectory of ``es_settings.xml`` (a file without a root element)."""
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return {}
    return {m.group(1): html.unescape(m.group(2)) for m in _SETTING.finditer(text)}


def system_rom_path(home, system):
    """A system's ``<path>`` from ``custom_systems/es_systems.xml``, if the user changed it."""
    if not system:
        return None
    path = os.path.join(home, "custom_systems", "es_systems.xml")
    if not os.path.isfile(path):
        return None
    try:
        root = etree.parse(path, etree.XMLParser(remove_blank_text=True, resolve_entities=False)).getroot()
    except (etree.XMLSyntaxError, OSError):
        return None
    for sys_elem in root.iter("system"):
        if (sys_elem.findtext("name") or "").strip() == system:
            value = (sys_elem.findtext("path") or "").strip()
            return value or None
    return None


def is_home(path):
    """``path`` is an ES-DE application data folder."""
    return bool(path) and os.path.isfile(os.path.join(path, "settings", "es_settings.xml")) \
        and os.path.isdir(os.path.join(path, "gamelists"))


def find_home(path):
    """The ES-DE folder for a path given by the user: the ES-DE folder itself,
    the portable install folder (holding ``ES-DE/``), ``es_settings.xml``,
    ``gamelists/``, a system's gamelist folder or its gamelist.xml. Else None."""
    if not path:
        return None
    full = os.path.abspath(str(path))
    if os.path.isfile(full):
        full = os.path.dirname(full)
    candidates = [full, os.path.join(full, "ES-DE")]
    up = full
    for _ in range(3):
        up = os.path.dirname(up)
        candidates.append(up)
    for cand in candidates:
        if is_home(cand):
            return os.path.normpath(cand)
    return None


def layout_for_gamelist(xml_path):
    """Layout when ``xml_path`` is ``<ES-DE>/gamelists/<system>/gamelist.xml``, else None."""
    if not xml_path:
        return None
    folder = os.path.dirname(os.path.abspath(xml_path))
    gamelists = os.path.dirname(folder)
    if os.path.basename(gamelists).lower() != "gamelists":
        return None
    home = os.path.dirname(gamelists)
    if not is_home(home):
        return None
    return Layout(home, os.path.basename(folder))


# --- media by name ------------------------------------------------------------

def rom_stem(layout, rom_path):
    """``Multidisk/Last Ninja 2/Last Ninja 2`` for ``./Multidisk/Last Ninja 2/Last Ninja 2.m3u``
    (the media name: the ROM path under the system folder minus its extension)."""
    value = (rom_path or "").strip().replace("\\", "/")
    if not value:
        return None
    if os.path.isabs(value) or re.match(r"^[A-Za-z]:/", value):
        base = os.path.normpath(layout.rom_dir)
        full = os.path.normpath(value)
        try:
            inside = os.path.commonpath([base, full]) == base
        except ValueError:
            inside = False
        value = os.path.relpath(full, base).replace(os.sep, "/") if inside else os.path.basename(full)
    while value.startswith("./"):
        value = value[2:]
    value = value.strip("/")
    parts = [p for p in value.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    full = os.path.join(layout.rom_dir, *parts)
    name = parts[-1]
    if not os.path.isdir(full):                 # "directories interpreted as files" keep their dot
        name = os.path.splitext(name)[0] or name
    return "/".join(parts[:-1] + [name])


class MediaIndex:
    """Files of every media folder of a system, listed once: field -> {stem key: [names]}."""

    def __init__(self, layout):
        self.layout = layout
        self._found = {}
        for field, folder in FOLDERS.items():
            top = os.path.join(layout.media_dir, folder)
            found = {}
            exts = exts_for(field)
            for dirpath, _dirs, files in os.walk(top):
                rel_dir = os.path.relpath(dirpath, top).replace(os.sep, "/")
                rel_dir = "" if rel_dir == "." else rel_dir + "/"
                for name in files:
                    stem, ext = os.path.splitext(name)
                    if ext.lower() not in exts or name.startswith("."):
                        continue
                    found.setdefault(_key(rel_dir + stem), []).append(rel_dir + name)
            self._found[field] = found

    def lookup(self, field, stem):
        """``@media/<folder>/<name>`` of the media of ``field`` for ``stem``, or None."""
        names = self._found.get(field, {}).get(_key(stem))
        if not names:
            return None
        order = {e: i for i, e in enumerate(exts_for(field))}
        names = sorted(names, key=lambda n: order.get(os.path.splitext(n)[1].lower(), 99))
        return f"{PREFIX}{FOLDERS[field]}/{names[0]}"


def _key(stem):
    return os.path.normcase(stem)


def media_value(field, stem, ext):
    return f"{PREFIX}{FOLDERS[field]}/{stem}{ext}"


def resolve(layout, value):
    """Absolute path of an ``@media/...`` value under the system's media folder, or None."""
    clean = str(value or "").replace("\\", "/")
    if not clean.startswith(PREFIX):
        return None
    clean = clean[len(PREFIX):].strip("/")
    parts = clean.split("/")
    if not clean or ".." in parts or parts[0] not in FOLDERS.values():
        return None
    base = os.path.normpath(layout.media_dir)
    full = os.path.normpath(os.path.join(base, clean))
    try:
        if os.path.commonpath([base, full]) != base:
            return None
    except ValueError:
        return None
    return full


def to_value(layout, full):
    """``@media/...`` value of a file under the system's media folder, or None."""
    base = os.path.normpath(layout.media_dir)
    full = os.path.normpath(full)
    try:
        if os.path.commonpath([base, full]) != base:
            return None
    except ValueError:
        return None
    return PREFIX + os.path.relpath(full, base).replace(os.sep, "/")


def siblings(full, field):
    """Other files of the same media (same name, another supported extension)."""
    stem = os.path.splitext(full)[0]
    out = []
    for ext in exts_for(field):
        for cand in (stem + ext, stem + ext.upper()):
            if os.path.normcase(cand) != os.path.normcase(full) and os.path.isfile(cand):
                out.append(cand)
    return out


# --- in-memory tags -----------------------------------------------------------------

def inject(tree, layout, media_tags):
    """Set aside the file's own media tags and add one ``@media/`` tag per media found."""
    index = MediaIndex(layout)
    for game in tree.getroot().iterchildren("game"):
        legacy = [c for c in game if isinstance(c.tag, str) and c.tag in media_tags]
        if legacy:
            game.set(LEGACY_ATTR, "".join(etree.tostring(c, encoding="unicode", with_tail=False) for c in legacy))
            for c in legacy:
                game.remove(c)
        stem = rom_stem(layout, game.findtext("path", ""))
        if not stem:
            continue
        for field in FIELDS:
            value = index.lookup(field, stem)
            if value:
                etree.SubElement(game, field).text = value


def strip_for_save(tree, media_tags):
    """Copy of ``tree`` as ES-DE wants it on disk: no ``@media`` tag, the file's own tags back."""
    import copy
    out = copy.deepcopy(tree)
    for game in out.getroot().iterchildren("game"):
        for c in [c for c in game if isinstance(c.tag, str) and c.tag in media_tags]:
            game.remove(c)
        legacy = game.attrib.pop(LEGACY_ATTR, None)
        if legacy:
            try:
                wrapper = etree.fromstring("<x>" + legacy + "</x>")
                for c in list(wrapper):
                    game.append(c)
            except etree.XMLSyntaxError:
                pass
    return out


def target(layout, game, field, ext):
    """(absolute path, ``@media`` value) of ``field``'s file for ``game`` with ``ext``."""
    stem = rom_stem(layout, game.findtext("path", "")) or _safe(game.findtext("name", "") or "unknown")
    value = media_value(field, stem, ext)
    return resolve(layout, value), value


def _safe(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name or "unknown"
