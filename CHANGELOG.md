# Changelog

All notable changes to Gamelist Media Editor are documented in this file.

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
- Auto-delete of the **previous media file** when replacing with a different path/extension
- Genres loaded from **`static/genres.json`**
- Accessibility basics: `aria-*` on list, filters, dialogs; focus-visible styles

### Changed
- Safer path resolution for `/media/`
- URL downloads: hard **50 MB** cap with streaming
- Confirmation modals unified
- XML parse **cache** (mtime-based)

### Fixed
- Path sanitization edge cases
- Filter / list logic consolidated
- Debounced search

## [1.0.1] - 2026-08-05

### Added
- **Missing media filters** with live counts
- **Keyboard navigation** and shortcuts
- **Tools** panel, manual backup, optional backup before destructive actions
- **Quit** button
- **Windows Setup** installer

### Fixed
- JavaScript `escapeHtml` syntax error
- Windows batch / PowerShell encoding issues

## [1.0.0] - 2026-08-02

### Added
- Initial public release
