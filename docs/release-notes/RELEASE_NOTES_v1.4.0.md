# Gamelist Media Editor v1.4.0

New interface, one Scrape button with a comparison before applying, much faster with large gamelists.

![The editor](https://raw.githubusercontent.com/Kraran/gamelist-media-editor/v1.4.0/docs/screenshots/editor.png)

## Highlights

**New interface (dark theme)**
- Three areas: game list, media of the selected game, description and metadata
- Game list with **thumbnails** and a **media count** per game (`4/10`, hover to see what is missing); one **missing-media filter** with counts
- **Media gallery**: each media in its own shape with its size in pixels; missing media grouped as drop targets (drop or click)
- **Stars** for the rating, a **date picker**, **named language and region lists**, suggestions from your gamelist
- **One save bar** (`Ctrl+S`) for all changes, with the changed fields marked; the app asks before unsaved changes could be lost
- Embedded icons and fonts: everything works offline

**Scrape**
- **One Scrape button**: Arcade Database for arcade folders, Steam for `steam`, ScreenScraper for everything else; the ▾ menu forces another source, remembered per system
- **Comparison before applying**: current and proposed values side by side, images with their size. Only what the game is missing is ticked; nothing is replaced unless you tick it (*Fill gaps* / *Replace all* / *None*)
- Proposed images are downloaded once and reused when applied: no second ScreenScraper download
- ScreenScraper system ids for **all RetroBat folders** (14 wrong ids fixed)

**Workflow**
- **Next incomplete** (`N`) and keyboard shortcuts: `J`/`K` next/previous, `S` scrape then Enter to apply, `?` for the list
- **Settings** (language, ScreenScraper, scrape sources, shortcuts) and an **Actions** menu (backup, arcade system names, purge `<region>`); *Delete this game* moved to the game's ⋯ menu
- **Much faster**: a 30,000-game MAME list opens in about 1 s (was 14 s), a game in 0.17 s (was 1.4 s)

## Fixes

- `gamelist.xml` is now written atomically: it can no longer be seen empty or lost during a save
- Actions on a game could hit **another game** if `gamelist.xml` changed meanwhile; they now reach the right game or are refused
- Scrape applied fields you had not ticked (thumbnail, bezel, Pad2Key, arcade system name), and a ticked field the source did not have erased your value
- Saving metadata could erase a genre outside the built-in list; only changed fields are written now
- An invalid rating no longer leaves other fields half-changed

## Security

- Requests from other websites (CSRF) and foreign `Host` headers (DNS rebinding) are rejected: a web page open in your browser could previously trigger delete, purge, upload or shutdown

Full list: [CHANGELOG.md](https://github.com/Kraran/gamelist-media-editor/blob/v1.4.0/CHANGELOG.md)

## Downloads

| File | Description |
|------|-------------|
| `GamelistMediaEditor-Windows-v1.4.0.zip` | Standalone Windows `.exe` (no Python needed) |
| Source code (zip / tar.gz) | Python 3.9+ (`pip install -r requirements.txt`) |

## Upgrade from 1.3.0

Replace the app files and keep your `screenscraper_config.json`. Nothing to migrate in `gamelist.xml`.  
**Tools** is now split into **Settings** (gear) and **Actions** (⋯). A `cache` folder (list thumbnails, scrape previews) is created next to the `.exe`; it can be deleted at any time.
