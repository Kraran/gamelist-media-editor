# Changelog

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
- Security hardening and robustness improvements
- Reload list button
- Upload size limits
- Genre hierarchy polish

### Fixed
- Path sanitization issues
- Filter / list logic
- Debounced search

## [1.0.1] - 2026-08-05

### Added
- Missing media filters with live counts
- Keyboard navigation and shortcuts
- Tools panel, Quit button, Windows Setup

### Fixed
- JavaScript escapeHtml syntax error
- Windows batch CRLF / installer encoding

## [1.0.0] - 2026-08-02

### Added
- Initial public release
