# Changelog

All notable changes to Gamelist Media Editor are documented in this file.

## [1.2.0] - 2026-08-24

### Added
- **Windows standalone `.exe`** (PyInstaller) — double-click, no Python install required for end users
- **Start without a gamelist** — open any `gamelist.xml` from the **Gamelist…** menu (auto-prompt on first launch)
- Optional CLI / drag-and-drop of a gamelist onto the `.exe` still supported
- Browser opens automatically on startup
- Empty-state CTA when no gamelist is loaded
- **About** dialog (header logo)
- `BUILD_EXE.bat` + `GamelistMediaEditor.spec`

### Changed
- App no longer blocks on console path input
- PyInstaller-aware paths: templates/static from bundle; config (`screenscraper_config.json`) next to the `.exe`
- Quit button: ⏻ + solid red (RomSet Verifier style)
- Complete i18n for new strings (13 languages)
- Version **1.2.0**

### Build (developers)
- `BUILD_EXE.bat` / `GamelistMediaEditor.spec` on Windows with Python + PyInstaller

## [1.1.3] - 2026-08-16

### Added
- **About** dialog (click the logo / title in the header)
- Header **brand button** uses the app favicon as logo

### Changed
- Version constant **1.1.3**

## [1.1.2] - 2026-08-16

### Added
- **Open another gamelist.xml** without restarting
- In-app file browser + recent files

## [1.1.1] - 2026-08-08

### Added
- Multilingual UI (13 languages)

## [1.1.0] - 2026-08-06

### Added
- ScreenScraper + Arcade Database scrapers

## [1.0.2] - 2026-08-06

### Added
- Reload, upload limits, XML write lock, genres.json

## [1.0.1] - 2026-08-05

### Added
- Missing media filters, Tools panel, Windows Setup

## [1.0.0] - 2026-08-02

### Added
- Initial public release
