# Gamelist Media Editor

Local web app to edit EmulationStation / **RetroBat** `gamelist.xml` media and metadata with drag-and-drop.

**Version 1.1.0** · [Documentation (Wiki)](https://github.com/Kraran/gamelist-media-editor/wiki) · [Releases](https://github.com/Kraran/gamelist-media-editor/releases)

---

## Features

- Drag-and-drop for **image**, **video**, **marquee**, **manual**, **boxback** (local files or URLs)
- Edit **name**, **description**, **genre** (hierarchical), **rating**, **releasedate**, **developer**, **publisher**, **family**, **players**, **lang** (with flags)
- **ScreenScraper** scrape per field (hash / name match, candidate picker, optional member boost)
- **Arcade Database** (Arcade Italia) scrape for MAME/FBNeo romsets
- Filter games by **missing media** (with live counts)
- Current **system name** in the header (folder of the gamelist)
- Keyboard navigation (arrows, Page Up/Down, Home/End)
- Shortcuts: `Ctrl+S` save, `Ctrl+F` search
- **Tools** panel: manual `.bak` backup, purge all `<region>` tags, ScreenScraper member login
- **Reload** list from disk without restarting the app
- Delete a game (ROM + media + XML entry) with optional backup
- **Quit** button stops the server (and closes the console when launched via `Lancer.bat`)
- Clear API error / quota messages, request throttling
- Safe media paths, upload size limits (50 MB), XML write lock

---

## Installation

### Option A — Windows Setup (recommended)

1. Download **GamelistMediaEditor-Windows-Setup-v1.1.0.zip** from the [latest release](https://github.com/Kraran/gamelist-media-editor/releases/latest)
2. Extract and run **`Installer.bat`**
3. Choose an install folder
4. The installer will:
   - copy the app
   - install **Python** if needed (system, winget, or portable)
   - install `flask`, `lxml`, `requests`
   - create Desktop + Start Menu shortcuts

### Option B — Manual

1. Download the **source** zip from the [latest release](https://github.com/Kraran/gamelist-media-editor/releases/latest) (or clone this repo)
2. Install Python 3.9+ from [python.org](https://www.python.org/downloads/) (check *Add to PATH*)
3. In the app folder:

```bash
python -m pip install -r requirements.txt
```

4. Run **`Lancer.bat`** (Windows) or:

```bash
python app.py "C:\\path\\to\\gamelist.xml"
```

5. Open [http://127.0.0.1:5050](http://127.0.0.1:5050)

---

## Scrapers

### ScreenScraper

- Works out of the box (software developer credentials are built in)
- Optional **member account** in **Tools** for higher quotas (boost)
- Matching: ROM hashes (including files inside `.zip`), then name search with candidate list
- You choose which fields to apply (media + metadata)

### Arcade Database (Arcade Italia)

- Button **Arcade DB** next to ScreenScraper
- Best for **arcade / mame / fbneo** (MAME romset names)
- Same field-picker UI as ScreenScraper
- No account required

Please use scrapers responsibly (built-in throttling; avoid hammering the APIs).

---

## Usage

1. Point the launcher at your system `gamelist.xml` (media folders `images/`, `videos/`, `manuals/` are expected next to it)
2. Select a game → drop media into the zones, or use **ScreenScraper** / **Arcade DB**
3. Edit metadata and save (`Ctrl+S`)
4. Use **Tools** for global actions (backup, purge regions, SS boost login)
5. Use **Reload** if you edited the XML outside the app

---

## Requirements

- Python **3.9+**
- `flask`, `lxml`, `requests` (see `requirements.txt`)
- Modern browser (Chrome / Edge / Firefox)
- Internet access only if you use the scrapers

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) and [Releases](https://github.com/Kraran/gamelist-media-editor/releases).

---

## License

MIT — see [LICENSE](LICENSE)
