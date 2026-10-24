# Changelog

All notable changes to Gamelist Media Editor are documented in this file.

## [Unreleased]

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
