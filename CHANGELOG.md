# Changelog

All notable changes to Gamelist Media Editor are documented in this file.

## [Unreleased]

### Added
- **Genre and favorite / hidden / kids filters** below the media filter: the genre menu lists the main genres of the gamelist (the part before ` / `, case-insensitive) plus *No genre*; the second menu shows *Favorites*, *Hidden*, *Not hidden* or *For kids*. Each menu counts the games its options would show with the search and the other filters; an active filter is outlined, and the three combine with the search, *Next incomplete*, the batch scrape and the CSV export.
- **Search in every field**: the toggle at the end of the search box also searches genre, developer, publisher, family, players, language, region, date, arcade system and rating (the description is not part of the list and is not searched). Off by default, so name and ROM path searches stay as fast as before on very large lists; the choice is kept in `ui_settings.json` (`search_all_fields`).
- **Downloaded image check** at scrape time (single and batch, all sources): an image that Pillow cannot decode (corrupt, truncated, an HTML error page), smaller than 16 px on a side or 32×32 px in area, or of a single colour / fully transparent is not written, the game keeps its previous file, and the field is reported as failed (*image: single-colour or empty image, not saved*) in the scrape toast and the batch report, where *Retry failures* can try it again. Thresholds are constants in `gme/media.py`; videos, manuals and images dropped by hand are not checked.
- **Export the list (CSV)** (Actions): the games shown in the list (search and filters applied), in its order, as `gamelist-<system>-<date>.csv`, UTF-8 with BOM for Excel, `;` separator (`,` in English). Columns: `path`, `name`, `genre`, `releasedate` (as `YYYY-MM-DD`), `developer`, `publisher`, `players`, `rating`, `favorite`, `hidden`, `kidgame`, `region`, `lang`, `media` (media tags filled), `required_media` (e.g. `3/4`) and `missing_required`. Cells starting with `=`, `+`, `-` or `@` are prefixed with `'` so a spreadsheet never runs them as formulas. New route `POST /api/export-csv` (same local-only checks as the other routes).
- **Copy the ROM paths of the ticked games**: a button in the selection bar and an item in the game ⋯ menu copy their full paths, one per line, in the order of the list.
- **Resizable game list**: drag the right edge of the list to show long game names in full. The media tiles and the stage shrink in real time to make room (the tiles keep their shape and get smaller before a column is dropped); the editor always keeps at least 600 px and the list at least 260 px, also when the window is made smaller. The edge also works with touch and pen, with the arrow keys once focused (`Shift`: bigger steps, `Home` / `End`: narrowest / widest), `Esc` cancels a drag and a double-click returns to the default width. The width is kept in `ui_settings.json` and applied before the page is drawn. Hovering a name in the list shows it in full.
- **Resume batch scrapes**: the plan, chosen fields and results are kept on disk for each gamelist. The *Last batch* button below the game list reopens its report; *Resume* continues the remaining games after a stop, page reload or app restart. A game checkpoints on the server before its response is sent, and repeated requests cannot accidentally advance the next game. Only one window controls a resumed lot at a time.
- **Retry failures** in a completed batch report: retries only failed games and failed fields of partial updates, including in *Replace all* mode. Successfully written fields are not selected again. A fresh XML backup is made before retrying.
- **Backups and restoration** (Actions): each manual or bulk-operation backup also keeps a dated copy next to the gamelist, under `.gme-backups/<XML filename>/` (latest 30). The existing `.bak` is preserved on first use and the compatible `.bak` copy continues to be updated. Restore confirms the selected date, keeps a snapshot of the current XML first, and invalidates older tabs. Only the XML is restored: ROMs and media are not backed up or recovered by this feature.
- **Parallel ScreenScraper batch scrape**: with a member login, the batch looks up and downloads several games at once, up to the `maxthreads` ScreenScraper reports for the account (1 without a login, or until ScreenScraper has answered). The limit is re-read from every answer (`response.ssuser`), and results are still applied, written to `gamelist.xml` and checkpointed one game at a time in list order, so resume, retry and the journal work as before. *Stop* stops every worker at once (a request already sent finishes; the game in progress is checkpointed only if it completed). The progress shows `Threads: 2/4` and the requests used today against the daily quota.
- **ScreenScraper limits shared by the whole app** (`gme/scrapers/ss_limits.py`): every ScreenScraper request — API calls, media downloads (`mediaJeu.php` / `mediaVideoJeu.php`, Pad2Key), previews, single-game scrapes, one or two batches — takes one slot of a single process-wide semaphore sized to `maxthreads`, and starts under one shared limiter: evenly spaced, at most `maxrequestspermin` (minus a 10 % margin) in any 60 seconds; unknown limit: one request every 1.1 s as before. Nothing is sent once `requeststoday` reaches `maxrequestsperday` or `requestskotoday` reaches `maxrequestskoperday`. HTTP 429 drops to 1 thread for 2 minutes and retries the request twice (3 s, 10 s); HTTP 430/431 (daily quotas), 423 (API closed), 426 (software refused) and 401 (server saturated) stop the batch with an explicit reason and refuse further requests locally for a while (30 min, 30 min, 10 min, 1 h, 2 min) instead of sending them.
- **Threads setting** (Settings › ScreenScraper): *Auto* (the account's `maxthreads`) or 1–16. It can only lower the number ScreenScraper allows; the server clamps it. The hint shows the account's maximum once known. Arcade Database and Steam keep their single, spaced requests.
- Batch checkpoints append small result records rather than rewriting the complete game plan after each game. Saved reports omit scraper URLs and credentials. A truncated final checkpoint after a crash is ignored and repaired when processing resumes; the interrupted game may be checked again.

### Fixed
- Gamelist operations now keep the same file and media folder from lookup through saving. Opening another gamelist waits for the operation to finish; requests from an older tab or batch are refused after the active gamelist changes, including when the ROM paths match.
- A file that remains locked after the save retries is left intact: the app reports the failed save instead of truncating and rewriting the original. Failed XML writes also discard the modified cache. Local media uploads use atomic writes.
- Typing while a save is pending remains marked as unsaved. An upload or media removal finishing after another game was selected updates its original game, without changing the new game's gallery.
- Returning to a game whose description was already loaded no longer leaves it read-only while another game's request is pending; refreshing the list preserves an unsaved description.
- Batch reports and their exports now show every download error for partially updated games, with an explicit warning instead of silently counting the game as a complete success. A batch stops if another tab changes the active gamelist, and its export keeps the original gamelist path.

## [1.6.0] - 2026-11-15

Batch scrape (ticked games or the games shown), light theme, every interface text translated in the 13 languages. Release notes: [docs/release-notes/RELEASE_NOTES_v1.6.0.md](docs/release-notes/RELEASE_NOTES_v1.6.0.md).

### Added
- **Light theme** (Settings › General): *Dark* (default), *Light* or *System*, which follows the light or dark setting of Windows, even while the app is open. Kept in `ui_settings.json` and applied before the page is drawn (no dark flash); the light colors keep the contrasts of the dark theme (text 4.5:1, outlines 3:1)
- **Batch scrape** (Actions › *Scrape in batch*, or *Scrape…* in the selection bar): scrapes the ticked games, or else every game shown in the list (search and filter, e.g. *Required media missing*), one after the other with the source of the system. Choose *Fill gaps* (only empty fields) or *Replace all*, and which media and information to write (the name and Pad2Key are off by default); a `.bak` is made first. A progress bar shows each game, *Stop* ends after the game in progress, and the report lists the games updated (with their fields), the **uncertain** ones (the source offers several games: nothing is written, *Choose…* opens the game's scrape to pick it), the errors, and can be exported. A refused ScreenScraper (quota, login, API closed) or a stopped server ends the run instead of failing every game
- **Tick games in the list** for the batch scrape: the box on a row's thumbnail, `Ctrl`+click, or `X` for the open game; `Shift`+click ticks every game shown in between; `Esc` unticks all. The ticks survive a reload of the list
- ScreenScraper answers that will not change with another game (quota, login, API closed) come back as `source_blocked` (HTTP 503) instead of "not found"

### Changed
- Removed the per-field routes `/api/name`, `/api/desc` and `/api/meta`, unused by the interface since 1.4.0 (`POST /api/game/<index>` saves any field in one write)
- Code clean-up: dead code and styles removed, outdated comments rewritten, early functions re-indented, one list of "come back later" messages for the error toasts and the batch scrape

### Fixed
- **About 270 texts were still in English** in the other languages (arcade systems menu and dialog, Steam messages, *Open gamelist* dialog, rating errors, `mame.xml` messages…); they are translated, and 16 texts no longer used are removed
- ScreenScraper and Arcade Database network errors (no answer in time, network down, unexpected answer) were always shown in French; the system tooltip said "dossier" in every language
- "Label: value" in error messages and exported reports used the French spacing (`Label : value`) in every language
- *About* used *vous* in French while the rest of the interface uses *tu*

## [1.5.0] - 2026-11-14

Check ROMs and Check media, required media per system, safer deletions (Recycle Bin, files shared between games kept), settings kept next to the app. Release notes: [docs/release-notes/RELEASE_NOTES_v1.5.0.md](docs/release-notes/RELEASE_NOTES_v1.5.0.md).

### Added
- **Required media per system** (Settings › Required media, or *Required media…* above a game's missing media): the media a game must have to be complete, by default image, video, marquee and box art (no box on arcade systems). The list count (`3/4`), the *Required media missing* filter and *Next incomplete* use them; a game's missing required media come first, the others under *Optional*. Each system keeps its own choice; the other customized systems are listed with a way back to the default
- **Thumbnail and Bezel in the editor**: the `<thumbnail>` and `<bezel>` tags written by the scrape can now be seen, replaced, removed and filtered like the other media
- **Scrape comparison**: *Media* / *Information* shortcuts jump to each section, and the bottom fades out while there is more below (the information was often hidden under the media)
- **Check media** (Actions menu): compares the media folders of the gamelist (`images/`, `videos/`, `manuals/` and their sub-folders) with what the games use, and reports the **unused media** (with a thumbnail, the size to free, a warning and nothing ticked when more than half look unused, e.g. a folder shared with another gamelist) and the **links to missing media** (a tag pointing to a file that is gone). *Clean up* moves the ticked files to the **Recycle Bin** (recoverable; or deletes them if unticked) and removes the ticked broken tags, `.bak` first. A file used by any tag of any game is never offered, Batocera tags (`<titleshot>`, `<wheel>`…) included; the server re-scans before deleting. *Export the report* saves it as text
- Check ROMs and Check media share one report dialog
- **Check ROMs** (Actions menu): compares the gamelist with the files of its folder and reports the ROMs missing from the gamelist, the entries whose ROM is gone and the games listed twice. Tick what to change, then *Update the gamelist*: missing ROMs are added (named after the file, ready to scrape), dead entries removed (optionally with their media, unless another game uses them), duplicates merged into the most complete entry. A `.bak` backup is made first (on by default); nothing is ticked when more than half of the games lack their ROM (wrong folder, disconnected drive). *Export the report* saves it as a text file. Media folders are skipped, disc tracks listed in a `.cue` / `.gdi` / `.m3u` are not counted as games, a folder named like `Game.ps3` is one game, a folder named like a ROM beside it (`kinst/` next to `kinst.zip`) holds that game's data; on arcade systems (MAME, FBNeo, Naomi…) `.chd` disks are never games; 30,000 files are checked in under a second

### Changed
- The **language**, the **scrape sources** and the required media are kept by the server in `ui_settings.json` next to the app, not in the browser storage of the app window, which could lose them (the choices of older versions are moved over once)
- **ScreenScraper settings** are saved as soon as they change, like the language; the *Save* button is gone
- **Preferred ScreenScraper region**: 24 regions (Germany, Spain, Italy, UK, Brazil, Korea…) instead of 5, named in the interface language

### Fixed
- **Tab left the open dialog** and moved through the page behind it; it now cycles inside the dialog
- **Enter in the scrape comparison** only applied when the *Apply* button had the focus, not after ticking a card or a row, although the shortcut list said so
- **About** did not mention the Steam source
- **Enter on *Cancel* confirmed the action** in every confirmation dialog (purge of `<region>`, deletion…), and Enter on *Don't save* saved. Enter now presses the focused button; a dialog that deletes something opens with the focus on *Cancel* and is only confirmed by its button
- **Replacing a media could delete another game's file**: the previous file was deleted for good even when another game (or another tag of the same game) pointed to it, e.g. a box art shared by a clone. It now goes to the Recycle Bin, and only if no other tag uses it; a new file whose name is already used by another tag gets another name (`…-image-2.png`) instead of overwriting it. Same for the scrape and Steam trailers
- **Delete this game** deleted every file of the game for good, files used by other games included, and its dialog listed fewer files than it deleted. The dialog now lists exactly what goes (the ROM with its `.cue` / `.gdi` / `.m3u` tracks and discs, the folder named like the ROM, the `.keys` file, the media) and what is kept because another game uses it (shared box art, ROM listed twice); everything goes to the Recycle Bin unless unticked. If the ROM cannot be deleted, nothing changes. Check ROMs also sends the media of removed entries to the Recycle Bin
- **A replaced picture still showed the old one** (gallery, list thumbnail) when the new file had the same name, until the app was restarted
- **Purge `<region>`**: the open game and the list kept showing the regions until reload
- **Media gallery: images were cut** when their shape differed from the usual one for their field (a round logo as marquee, a tall cabinet photo as boxart). Each tile now takes the shape of its image or video once loaded (between very tall and 4:1 wide) and the media always fits whole in its frame; the manual tile is no longer a tall empty box
- **Recent gamelists** (Open gamelist dialog): clicking a recent file only copied its path into the field, and long paths were cut at the end, so several recent files looked identical. A click now opens the file; each entry shows its system folder first and its path cut at the start; the file already open is not listed; a recent file that no longer exists is marked, removed when you try to open it, and any entry can be removed (×)
- **Recent gamelists were not remembered**: the list lived in the browser storage of the app window, which *Quit* stopped too abruptly to save it. The server now keeps the list in `recent_gamelists.json` next to the `.exe` / `app.py` (the 10 most recent are shown; the list of older versions is imported once). *Quit* also lets the app window close normally before stopping it, so the language and scrape-source choices are saved too

## [1.4.0] - 2026-10-24

New interface (dark theme), one Scrape button with a comparison before applying, much faster with large gamelists, safety fixes. Release notes: [docs/release-notes/RELEASE_NOTES_v1.4.0.md](docs/release-notes/RELEASE_NOTES_v1.4.0.md).

### Added
- **Settings** dialog (app bar, gear): General (language, applied at once), ScreenScraper (member login, region, media types, test), Scrape sources (the per-system choices made in the Scrape menu, with a way back to automatic), Keyboard shortcuts. Replaces the Tools dialog
- **Actions** menu (app bar ⋯) for the whole gamelist: `.bak` backup, arcade system names from `mame.xml`, purge `<region>`; disabled while no gamelist is open
- Game **⋯ menu**: *Copy the ROM path* and *Delete this game…* (moved out of the header, where it sat next to Scrape)
- **Next incomplete** button and `N`: next game in the list that is missing media, or that matches the media filter when one is set; wraps around, says so when none is left
- **Keyboard shortcuts**: `J`/`K` next/previous game, `N` next incomplete, `S` scrape, `?` shortcut list (`Ctrl+S`, `Ctrl+F` and `/` as before). Letters do nothing while typing in a field; the status bar shows them
- Menus work with the keyboard (arrows, Home/End, Enter, Escape) and close on a click outside
- **One "Scrape" button**: the source is picked for the system (Arcade Database for MAME, FBNeo, Neo-Geo, CPS, Naomi…; Steam for the `steam` folder; ScreenScraper for everything else). The ▾ menu forces another source, remembered per system, with a way back to the automatic choice. Replaces the three ScreenScraper / Arcade DB / Steam buttons
- **Scrape comparison**: each field shows the current value next to the proposed one, images side by side with their size in pixels, marked *New*, *Different* or *Replaces*. Only what the game is missing is ticked; *Fill gaps* / *Replace all* / *None* presets; identical fields and fields the source does not have are listed at the bottom; the apply button counts the selected fields and has the focus (Enter applies)
- Proposed images are downloaded once for the preview, kept for a day in `cache/remote/`, and reused when applied: no second ScreenScraper download (quota). Previews are addressed by a key, so ScreenScraper URLs, which carry the member login, never appear in an address or in the server log
- `preset` in the scrape apply routes (`"missing"` or `"all"` instead of a field list): the server selects the fields itself, ready for a future batch scrape
- **Game sheet**: media gallery where each media keeps its shape (masonry of columns, larger on big screens) with its size in pixels or video length; missing media grouped as small drop targets that also open a file picker on click; *Replace* button on each media
- **Single save bar** under the editor: lists the unsaved changes, *Save* (`Ctrl+S`) and *Discard changes*; changed fields are marked. Replaces the three separate Save buttons
- **Rating in stars** (half steps, keyboard arrows), **release date picker** (stored as `YYYYMMDDT000000`; a value it cannot show is kept and displayed), **language and region lists** named in the interface language (values outside the list such as `en,fr` are kept), **suggestions** for developer, publisher, family, players and arcade system from the values already in the gamelist
- `POST /api/game/<index>`: saves name, description and metadata together, validated first, in one write of `gamelist.xml`
- **Game list thumbnails**: screenshot (or box, mix, logo) of each game, generated once by the app and cached in `cache/thumbs/` (WebP, refreshed when the image changes)
- **Media count per game** (`4/10`, green when complete) with the list of missing media on hover, instead of the unlabeled dots
- **Single media filter** menu with the number of games missing each media, instead of twelve chips
- **New interface foundation** (dark theme): three areas (game list, media, description and metadata side panel), design tokens in `static/style.css` ready for a light theme, embedded SVG icons (Tabler) instead of emoji, embedded fonts (IBM Plex Sans with Cyrillic, Saira Condensed for titles) so the UI works offline
- Save buttons stay quiet and turn violet only when that part has unsaved changes; confirmation buttons name the action ("Delete", "Quit"…)
- Keyboard shortcuts shown in the status bar, translated
- Screenshot in the README; guard tests for icons, fonts and emoji
- **Unsaved changes are protected**: switching game, reloading, opening another gamelist, scraping or quitting with unsaved edits asks *Save / Don't save / Cancel*; closing the window asks too. Save buttons with pending changes are highlighted and the status bar lists the changed fields
- Browser tests (Playwright + Chromium, `python -m pytest -m e2e`), run by the CI
- `--no-browser` command-line option: start the server without opening a window
- CI builds the Windows `.exe`, starts it and checks the UI, assets and API; the `.exe` is attached to each run
- ScreenScraper system ids for all RetroBat folders (138 → 271 entries: CPS1/2/3, Cave, ST-V, Teknoparrot, MSX2+, FM Towns, ports…), built from RetroBat's `es_systems.cfg` and EmulationStation's ScreenScraper tables
- Tests (`tests/`, `pytest.ini`, pytest via `requirements-dev.txt`): ScreenScraper map, game identity, security, version, translations (13 languages, same keys and placeholders)
- GitHub Actions CI: tests on Windows and Linux, Python 3.9 and 3.13, plus `app.js` syntax check

### Changed
- Scrape apply: ScreenScraper, Arcade Database and Steam share one implementation (`gme/scrapers/apply.py`, `compare.py`); metadata go through the same validation as a manual edit (a rating from a source is normalized, an invalid one is reported)
- Downloaded media are written atomically, and a Steam trailer is downloaded to a temporary file first: an interrupted download no longer leaves a truncated file in place of the previous one
- **Much faster with large gamelists**: on a realistic 30,000-game MAME list the app now opens in 1 s instead of 14 s and opens a game in 0.17 s instead of 1.4 s. The game list is virtualized (about 40 rows in the page instead of 420,000 elements), the server builds it in one pass (2.0 s → 0.3 s) and sends 3 times less data: only filled fields, descriptions loaded when a game is opened
- "Delete this game" moved from the app bar to the game header; the window adapts below 1280 px (icon-only bar buttons) and 1100 px (metadata under the media)
- Text, field outlines and focus rings meet WCAG AA contrast
- `app.py` (3,850 lines) split into the `gme/` package: `editor`, `scrapers/ss|adb|steam|common`, `xml_store`, `media`, `systems`, `arcade`, `security`, `i18n`, `window`, `server`, `main`… Code moved verbatim (152 of 161 definitions identical by AST comparison, the 9 others are the intended edits), Flask blueprints per area, no behaviour change; `app.py` stays the entry point (`python app.py`, `Lancer.bat`, PyInstaller)
- README rewritten for the current version: removed the obsolete Setup installer (v1.1.3) and the duplicated "Option B", added Steam, Pillow, safety notes and a Development section
- Release notes moved from the repository root to `docs/release-notes/`

### Removed
- Language flags loaded from flagcdn.com (an outside website): languages and regions are now named lists, everything works offline
- Repository cleanup: `PUBLISH_v1.1.3.bat` (one-off publish script), `generate_icons.py` with `icon_data/` and `icons_*.json` (base64 copies of icons already in `static/`), unused root `icon.png`

### Fixed
- Scrape applied fields the user had not ticked: the ScreenScraper thumbnail, bezel and Pad2Key were always downloaded (replacing existing files), and Arcade Database always wrote the arcade system name. They are now rows of the comparison like the others
- A field ticked while the source had no value for it erased the game's value; a scrape now never erases anything
- An invalid rating rejected by the metadata route left the other submitted fields changed in memory, so the next save of anything wrote them too. Values are now all validated before anything is changed
- Media messages showed the internal field name (`boxart`) instead of its translated label
- **`gamelist.xml` could be seen empty, or lost, during a save**: the file was truncated then rewritten, so a program reading it at that moment (EmulationStation, another editor) got an empty file, and a crash or power cut mid-write destroyed it. Saves now write a temporary file next to it and swap it in atomically; `screenscraper_config.json` too. On Windows, if another program holds the file open, the save retries briefly then writes in place as before
- Metadata labels were hard-coded in English or French ("Releasedate", "Developer", "Genre principal"…): they now follow the interface language
- The backup checkbox of confirmation dialogs showed its French text twice
- **Saving metadata erased the genre** when it was not in the built-in French list (e.g. `Platform` from ScreenScraper EN or another scraper). Such a genre is now shown and kept as-is
- Saving now sends only the fields you changed: an untouched field (genre, `kidgame` = `1`, `lang` = `en,fr`…) is never rewritten
- Escape now closes the "Open gamelist" dialog
- Header showed **v1.2.0** instead of 1.3.0: the version is now rendered from `APP_VERSION` / `APP_RELEASE_DATE` in `app.py` (header + About), no hard-coded copy left in the UI
- Per-game actions (edit, upload, clear, scrape/apply, **delete**) could hit **another game** when `gamelist.xml` changed after the list was loaded (games are addressed by XML position). The UI now sends the game `<path>`; the server re-targets the request if the game moved, or answers 409 and the UI reloads the list. Selection is kept by path on reload
- ScreenScraper system map: 14 wrong ids pointed at other systems and degraded matching (hash and search fell back to "no system"): Naomi 142→56 (was Neo-Geo), Atomiswave 148→53 (Irem), Model 2 149→54 (Seta), Model 3 150→55 (Midway), VIC-20 118→73, PET 120→240, Plus/4 119→99, PC-88 121→221, PC-98 122→208, Pico-8 211→234, WASM-4 0→262, Naomi 2 →75, C128 →66 (as RetroBat); duplicate keys removed; `trsdos` removed (100 is Super A'Can)

### Security
- Reject cross-site requests (CSRF) and non-local `Host` headers (DNS rebinding): a web page open in the browser could previously trigger delete / purge / upload / shutdown on the local server

## [1.3.0] - 2026-09-01

### Added
- Media fields **support** (`cartridge`), **boxart**, **fanart**, **mix**, **maps** (drag-and-drop + ScreenScraper)
- Persistent ScreenScraper media-type prefs in **Outils** (image ss/sstitle, boxart box-2D/box-3D, mix v1/v2)
- RetroBat-aligned extras: auto **thumbnail**, **bezel**, **Pad2Key** (`.keys`), **family**, **region**, flags favorite / hidden / kidgame
- **Steam** trailer scraper (FR when available, 720p if ≤ 50 MB else 480p)
- **Arcade system** metadata (`arcadesystemname`) from MAME driver (CPS1, Neo-Geo, …) via Arcade DB page + optional `mame.xml`
- Lightbox preview when clicking an image
- Select all / Deselect all in SS, Arcade DB and Steam apply modals
- Application window (Chromium `--app=`) when Edge/Chrome/Brave is available

### Changed
- Arcade DB media map: **PCB → Support**, **Cabinet → Boxart**, **Flyer → Boxback**, **Decal → Marquee**
- Arcade DB uses `query_mame_media` to fetch PCB / Decal
- `arcadesystemname` left empty when the driver is named after the single game
- Kidgame is no longer inferred automatically from PEGI/ESRB
- Arcade DB cabinet is no longer written to fanart
- Version **1.3.0**

### Fixed
- ScreenScraper boxback solid-green placeholders are ignored (no file, no XML path)
- Image downloads use a real extension (magic bytes), not `.php`
- Strict ScreenScraper types: no unwanted fallbacks (e.g. support-texture)

## [1.2.0] - 2026-08-24

### Added
- **Windows standalone `.exe`** (PyInstaller) — double-click, no Python install required for end users
- **Start without a gamelist** — open any `gamelist.xml` from the **Gamelist…** menu (auto-prompt on first launch)
- Optional CLI / drag-and-drop of a gamelist onto the `.exe` still supported
- Browser opens automatically on startup
- Empty-state CTA when no gamelist is loaded

### Changed
- App no longer blocks on console path input
- PyInstaller-aware paths: templates/static from bundle; config (`screenscraper_config.json`) next to the `.exe`
- Version **1.2.0**

### Build (developers)
- `BUILD_EXE.bat` / `GamelistMediaEditor.spec` on Windows with Python + PyInstaller

## [1.1.3] - 2026-08-16

### Added
- **About** dialog (click the logo / title in the header) — same layout as RomSet Verifier
  - Author portrait, version, release date, license, repository, stack
  - Links to GitHub profile and repository
- Header **brand button** uses the app favicon as logo

### Changed
- Version constant **1.1.3** (UI About, console banner, User-Agent)

## [1.1.2] - 2026-08-16

### Added
- **Open another gamelist.xml** without restarting the app (header button **Gamelist…**)
- **In-app file browser**: folders, `.xml` files, parent navigation, Windows drive roots
- Browser opens by default on the **parent folder** of the current gamelist
- **Recent gamelists** list (stored in the browser)
- Paste full path still supported; double-click a `gamelist.xml` to open it immediately
- API: `GET /api/browse`, `POST /api/open-gamelist`, `GET /api/session`

### Changed
- `APP_DIR` separated from media `BASE_DIR` so switching systems is safe
- `/api/games` also returns `xml_path` / `base_dir`

## [1.1.1] - 2026-08-08

### Added
- **Internationalization (i18n)** for the full UI and server API messages
- **13 languages**: Français, English, Español, Deutsch, Italiano, Português, Nederlands, Polski, Türkçe, Svenska, Norsk, Dansk, Русский
- Language selector in **Tools** with explicit **Apply language** action (choice stored in the browser)
- Client sends `X-Locale` so error / quota messages from the server match the selected language
- Locale files under `static/locales/*.json` (easy to extend)

### Changed
- Unified app version constant **`APP_VERSION = 1.1.1`** (User-Agent, console banner, Arcade DB UA)
- Remaining hard-coded French status / toast / scrape strings moved into locale files

### Fixed
- Language change now applies reliably after using the Apply button
- Server messages (invalid index, missing fields, file not found, scrape errors) follow the UI language

## [1.1.0] - 2026-08-06

### Added
- **ScreenScraper** integration: per-field scrape, candidate picker, zip-inner ROM hashing, optional member boost (Tools)
- **Arcade Database** (Arcade Italia) scrape button for MAME/FBNeo-style romsets
- Loading spinner during scraper requests
- System name badge in the header bar
- Clearer API error handling (network, HTTP, login, **quota / rate limits**)
- Client-side throttling for ScreenScraper and Arcade Database requests

### Changed
- Tools panel: ScreenScraper member credentials only (developer credentials are built into the app)
- Unified scrape apply modal for both scrapers

### Fixed
- Wrong ScreenScraper developer password encoding (`O` vs `0`)
- `amiga500` and many other RetroBat folder names mapped to ScreenScraper system IDs
- Scrape button passing a pointer event as `gameid`

## [1.0.2] - 2026-08-06

### Added
- **Reload** button — re-read `gamelist.xml` from disk while keeping the current selection when possible
- Client-side **upload size limit** (50 MB), aligned with the server
- Process-level **XML write lock** to serialize saves and backups
- Auto-delete of the **previous media file** when replacing with a different path/extension (e.g. `.png` → `.jpg`)
- Genres loaded from **`static/genres.json`** (easier to maintain)
- Accessibility basics: `aria-*` on list, filters, dialogs; focus-visible styles

### Changed
- Safer path resolution for `/media/` (no path traversal; fixed `lstrip("./")` edge case)
- URL downloads: hard **50 MB** cap with streaming
- `Ctrl+S` stops the save chain on the first failure (name → desc → meta)
- Confirmation modals unified (clear field / quit / destructive actions)
- UI polish: no inline styles, CSS helpers, shutdown screen as a proper class
- XML parse **cache** (mtime-based) + `get_game_elem` helper

### Fixed
- Path sanitization that could turn `../x` into a relative path under the media root
- Filter / list logic consolidated (`getFilteredGames`)
- Debounced search to avoid re-rendering on every keystroke

## [1.0.1] - 2026-08-05

### Added
- **Missing media filters** with live counts (no image / video / marquee / manual / boxback, or any missing)
- **Keyboard navigation** in the game list (Up/Down, Page Up/Down, Home/End)
- Shortcuts: **Ctrl+S** (save), **Ctrl+F** or **/** (search)
- **Tools** panel for global actions
- Manual **gamelist.xml.bak** backup
- Optional backup checkbox before purge regions / delete game
- **Quit** button (stops Flask server; console closes when using Lancer.bat)
- **Windows Setup** installer (`Installer.bat` + `Install.ps1`): choose folder, install Python if needed, dependencies, shortcuts

### Changed
- Header cleaned up (region purge moved into Tools)
- Status bar shows keyboard hints
- Safer confirmation dialogs for destructive actions

### Fixed
- JavaScript `escapeHtml` syntax error that prevented the game list from loading
- Windows batch files line endings (CRLF) for reliable launchers
- PowerShell installer encoding issues on French Windows

## [1.0.0] - 2026-08-02

### Added
- Initial public release
- Drag-and-drop media editor for image, video, marquee, manual, boxback
- Metadata editing (name, desc, genre, rating, dates, publisher, lang flags, etc.)
- Purge all `<region>` tags
- Delete game (ROM + media + XML)
- Favicon / app icon, Lancer.bat, bilingual README
