"""Read ROM DAT files: Logiqx XML (No-Intro, Redump, FBNeo…), MAME -listxml
and the older ClrMamePro text format.

Only what GME needs is kept: per game its name, description, parent (clone
of), BIOS flag, playability and the ROMs (name, size, CRC32, SHA1) with their
DAT status. Devices (MAME ``isdevice="yes"``) are not games and are skipped.

``read_dat(path, progress)`` streams XML with ``iterparse`` so a full MAME
listxml (hundreds of MB) fits; ``progress(done_bytes, total_bytes)`` is called
now and then.
"""

import os
import re

from lxml import etree


class DatError(ValueError):
    """Not a DAT GME can read."""


class Rom(object):
    __slots__ = ("name", "size", "crc", "sha1", "required", "baddump")

    def __init__(self, name, size=None, crc=None, sha1=None, required=True, baddump=False):
        self.name, self.size, self.crc, self.sha1 = name, size, crc, sha1
        self.required, self.baddump = required, baddump


class Game(object):
    __slots__ = ("name", "desc", "cloneof", "bios", "playable", "roms", "disks")

    def __init__(self, name):
        self.name, self.desc, self.cloneof = name, "", ""
        self.bios, self.playable = False, True
        self.roms, self.disks = [], []


class Dat(object):
    """A parsed DAT: ``games`` (name → Game) plus a few header facts."""

    def __init__(self, title, fmt, source):
        self.title, self.fmt, self.source = title, fmt, source
        self.games = {}
        self._by_rom = None
        self._by_crc = None
        self._by_sha1 = None

    def add(self, game):
        if game.name and game.name.lower() not in self.games:
            self.games[game.name.lower()] = game

    # --- indexes (built on first use) ---------------------------------------
    def _index(self):
        by_rom, by_crc, by_sha1 = {}, {}, {}
        for game in self.games.values():
            for rom in game.roms:
                by_rom.setdefault(os.path.basename(rom.name).lower(), []).append(game)
                if rom.crc:
                    by_crc.setdefault(rom.crc, []).append((game, rom))
                if rom.sha1:
                    by_sha1.setdefault(rom.sha1, []).append((game, rom))
        self._by_rom, self._by_crc, self._by_sha1 = by_rom, by_crc, by_sha1

    def by_rom_name(self, name):
        if self._by_rom is None:
            self._index()
        return self._by_rom.get(name.lower(), [])

    def by_crc(self, crc):
        if self._by_crc is None:
            self._index()
        return self._by_crc.get(crc, [])

    def by_sha1(self, sha1):
        if self._by_sha1 is None:
            self._index()
        return self._by_sha1.get(sha1, [])

    def find(self, file_name):
        """The game a file name designates: its stem is the game name (zip of a
        romset, No-Intro archive) or its full name is a ROM name (loose ROM)."""
        stem = os.path.splitext(file_name)[0].lower()
        game = self.games.get(stem) or self.games.get(file_name.lower())
        if game is not None:
            return game
        hits = self.by_rom_name(file_name)
        return hits[0] if len(hits) == 1 else None

    def info(self):
        clones = sum(1 for g in self.games.values() if g.cloneof)
        bios = sum(1 for g in self.games.values() if g.bios)
        return {"title": self.title, "format": self.fmt, "source": os.path.basename(self.source),
                "games": len(self.games), "clones": clones, "bios": bios}


def _int(value):
    try:
        return int(str(value).strip(), 0) if str(value).strip().lower().startswith("0x") else int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _hex(value, length):
    value = (value or "").strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{%d}" % length, value) else None


def _yes(value):
    return (value or "").strip().lower() in ("yes", "true", "1")


# --- XML: Logiqx datafile and MAME listxml -----------------------------------------

class _Counter(object):
    """File wrapper reporting how far the parser got."""

    def __init__(self, stream, total, progress):
        self.stream, self.total, self.progress, self.done = stream, total, progress, 0

    def read(self, size=-1):
        data = self.stream.read(size if size and size > 0 else 1 << 20)
        self.done += len(data)
        if self.progress:
            self.progress(self.done, self.total)
        return data


def _read_xml(path, progress):
    total = os.path.getsize(path)
    title, fmt, dat = "", "", None
    with open(path, "rb") as raw:
        stream = _Counter(raw, total, progress)
        context = etree.iterparse(stream, events=("start", "end"), huge_tree=True, recover=False,
                                  resolve_entities=False, no_network=True)
        depth = 0
        try:
            for event, elem in context:
                tag = elem.tag if isinstance(elem.tag, str) else ""
                if event == "start":
                    depth += 1
                    if depth == 1:
                        fmt = "listxml" if tag in ("mame", "m1") else "logiqx"
                        if tag not in ("datafile", "mame", "m1"):
                            raise DatError("root")
                        dat = Dat(elem.get("build") or "", fmt, path)
                    continue
                depth -= 1
                if depth == 1 and tag == "header":
                    title = (elem.findtext("name") or elem.findtext("description") or "").strip()
                    elem.clear()
                elif depth == 1 and tag in ("game", "machine"):
                    _xml_game(dat, elem)
                    elem.clear()
                    while elem.getprevious() is not None:
                        del elem.getparent()[0]
        except etree.XMLSyntaxError as e:
            raise DatError(str(e))
    if dat is None:
        raise DatError("empty")
    if title:
        dat.title = title
    elif fmt == "listxml":
        dat.title = ("MAME " + dat.title).strip()
    return dat


def _xml_game(dat, elem):
    if _yes(elem.get("isdevice")):
        return
    game = Game((elem.get("name") or "").strip())
    if not game.name:
        return
    game.desc = (elem.findtext("description") or "").strip()
    game.cloneof = (elem.get("cloneof") or "").strip()
    game.bios = _yes(elem.get("isbios"))
    if (elem.get("runnable") or "").strip().lower() == "no":
        game.playable = False
    driver = elem.find("driver")
    if driver is not None and (driver.get("status") or "").strip().lower() == "preliminary":
        game.playable = False
    for rom in elem.findall("rom"):
        name = (rom.get("name") or "").strip()
        if not name:
            continue
        status = (rom.get("status") or "").strip().lower()
        game.roms.append(Rom(name, _int(rom.get("size")), _hex(rom.get("crc"), 8), _hex(rom.get("sha1"), 40),
                             required=not rom.get("merge") and status != "nodump", baddump=status == "baddump"))
    for disk in elem.findall("disk"):
        name = (disk.get("name") or "").strip()
        status = (disk.get("status") or "").strip().lower()
        if name and not disk.get("merge") and status != "nodump":
            game.disks.append(name)
    dat.add(game)


# --- ClrMamePro text -----------------------------------------------------------------

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([()])|([^\s()"]+)')


def _tokens(text):
    for m in _TOKEN.finditer(text):
        if m.group(1) is not None:
            yield ("s", m.group(1).replace('\\"', '"'))
        elif m.group(2):
            yield (m.group(2), m.group(2))
        else:
            yield ("s", m.group(3))


def _block(tokens):
    """``key value key ( … )`` up to the closing parenthesis → [(key, value)]."""
    out = []
    for kind, value in tokens:
        if kind == ")":
            return out
        if kind != "s":
            raise DatError("syntax")
        key = value.lower()
        nxt = next(tokens, None)
        if nxt is None:
            break
        if nxt[0] == "(":
            out.append((key, _block(tokens)))
        elif nxt[0] == "s":
            out.append((key, nxt[1]))
        else:
            break
    return out


def _read_cmp(path, progress):
    total = os.path.getsize(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if progress:
        progress(total // 2, total)
    tokens = _tokens(text)
    dat = Dat("", "clrmamepro", path)
    seen_block = False
    for kind, value in tokens:
        if kind != "s":
            raise DatError("syntax")
        key = value.lower()
        nxt = next(tokens, None)
        if nxt is None or nxt[0] != "(":
            raise DatError("syntax")
        body = _block(tokens)
        seen_block = True
        if key in ("clrmamepro", "header"):
            fields = dict((k, v) for k, v in body if isinstance(v, str))
            dat.title = (fields.get("name") or fields.get("description") or "").strip()
        elif key in ("game", "machine", "resource"):
            fields = dict((k, v) for k, v in body if isinstance(v, str))
            game = Game((fields.get("name") or "").strip())
            if not game.name:
                continue
            game.desc = (fields.get("description") or "").strip()
            game.cloneof = (fields.get("cloneof") or "").strip()
            game.bios = key == "resource" or _yes(fields.get("isbios"))
            for sub_key, sub in body:
                if not isinstance(sub, list):
                    continue
                rf = dict((k, v) for k, v in sub if isinstance(v, str))
                name = (rf.get("name") or "").strip()
                if not name:
                    continue
                if sub_key == "rom":
                    flags = (rf.get("flags") or rf.get("status") or "").lower()
                    game.roms.append(Rom(name, _int(rf.get("size")), _hex(rf.get("crc"), 8), _hex(rf.get("sha1"), 40),
                                         required=not rf.get("merge") and flags != "nodump",
                                         baddump=flags == "baddump"))
                elif sub_key == "disk" and not rf.get("merge"):
                    game.disks.append(name)
            dat.add(game)
    if not seen_block:
        raise DatError("empty")
    if progress:
        progress(total, total)
    return dat


def read_dat(path, progress=None):
    """Parse ``path`` (format detected from its first bytes)."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if head.startswith(b"PK") or head.startswith(b"7z"):
        raise DatError("archive")
    start = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if start.startswith(b"<"):
        return _read_xml(path, progress)
    return _read_cmp(path, progress)
