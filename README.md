# Gamelist Media Editor

Local web app to edit EmulationStation / **RetroBat** `gamelist.xml` media and metadata with drag-and-drop.

**Version 1.1.3** · [Documentation (Wiki)](https://github.com/Kraran/gamelist-media-editor/wiki) · [Releases](https://github.com/Kraran/gamelist-media-editor/releases)

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
- **Tools** panel: language, ScreenScraper member login, manual `.bak` backup, purge all `<region>` tags
- **Reload** list from disk without restarting the app
- **Open another gamelist.xml** mid-session (file browser + recent files) without restarting
- **About** dialog (click the header logo) — version, author, license, links
- Delete a game (ROM + media + XML entry) with optional backup
- **Quit** button stops the server (and closes the console when launched via `Lancer.bat`)
- Clear API error / quota messages, request throttling
- Safe media paths, upload size limits (50 MB), XML write lock
- **Multilingual UI** (13 languages) — change language in Tools

---

## Installation

### Option A — Windows Setup (recommended)

1. Download **GamelistMediaEditor-Windows-Setup-v1.1.3.zip** from the [latest release](https://github.com/Kraran/gamelist-media-editor/releases/latest)
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

## Usage (quick)

1. Select a game in the list
2. Drop media onto the zones, or use **ScreenScraper** / **Arcade DB**
3. Edit metadata and save (`Ctrl+S`)
4. To switch system: **📂 Gamelist…** → browse or paste path → Open
5. Click the **header logo** for About (version, author, links)
6. **Tools** for language, ScreenScraper boost, backup, region purge

Full guide: [Wiki](https://github.com/Kraran/gamelist-media-editor/wiki)

---

## License

MIT — see [LICENSE](LICENSE)
