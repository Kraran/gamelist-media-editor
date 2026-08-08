# Changelog

All notable changes to Gamelist Media Editor are documented in this file.

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

