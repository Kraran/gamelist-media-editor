# Gamelist Media Editor v1.8.0

Undo and redo over several steps, long scans with a progress bar and Stop, automatic updates of the Windows .exe (SHA-256 verified), and a 45-second demo in the README.

## Highlights

**Undo / Redo, several steps**
- ↶ / ↷ in the top bar (`Ctrl+Z` / `Ctrl+Y` / `Ctrl+Shift+Z`), a history menu that jumps to any step of the session or back to *Before these changes*.
- Up to 30 steps per open gamelist, one step per action (a save, a bulk edit, a whole batch scrape, an image edit…).
- Writes the gamelist back atomically, and only if nobody else changed it meanwhile. Files sent to the Recycle Bin are recovered there; image edits are undone with their originals.

**Background scans with progress and Stop**
- Solid images, ROM check and media check run in the background, with *X / Y*, the item being read and **Stop**.
- Stop changes nothing (scans only read). Apply reuses the reviewed scan when nothing changed on disk.

**Automatic updates** (Windows `.exe`)
- At start-up GME asks GitHub, at most once a day, whether a newer release exists (*Settings › General › Updates*; *Actions › Check for updates* asks now).
- *Update now* downloads the official zip, checks its SHA-256 against `SHA256SUMS.txt`, replaces only the `.exe`, restarts, and rolls back if the new version does not start. Settings, keys and backups are never touched.

**Other**
- A 45-second animated demo in the README.
- Pushing a tag `vX.Y.Z` now publishes the Windows zip and `SHA256SUMS.txt` on the GitHub release (needed by the in-app updater).

Full list: [CHANGELOG.md](https://github.com/Kraran/gamelist-media-editor/blob/v1.8.0/CHANGELOG.md)

## Downloads

| File | Description |
|------|-------------|
| `GamelistMediaEditor-Windows-v1.8.0.zip` | Standalone Windows `.exe` (no Python needed) |
| `SHA256SUMS.txt` | SHA-256 of the zip (required by the in-app updater) |
| Source code (zip / tar.gz) | Python 3.9+ (`pip install -r requirements.txt`) |

## Upgrade from 1.7.5

Replace the app files and keep `screenscraper_config.json`, `ui_settings.json`, `recent_gamelists.json`, `sources_config.json` and `network_credentials.json`. Nothing to migrate, and there is no new dependency.

The 1.7.5 `.exe` cannot update itself: this is the first version that can. From 1.8.0 onwards, later releases install themselves (SHA-256 verified). A `.gme-update\` folder may appear next to the app.
