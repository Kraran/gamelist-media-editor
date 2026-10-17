# Gamelist Media Editor v1.1.1

Maintenance and internationalization release.

## Highlights

### Multilingual interface
- **13 languages** for the UI and API error messages
- Selector in **Tools** + **Apply language** button
- Preference stored in the browser; client sends `X-Locale` on API calls

Supported: Français, English, Español, Deutsch, Italiano, Português, Nederlands, Polski, Türkçe, Svenska, Norsk, Dansk, Русский.

### Consistency
- Single **`APP_VERSION = 1.1.1`** used for console banner and all HTTP User-Agents (ScreenScraper, downloads, Arcade Database)
- Remaining hard-coded French strings in status/toasts/scrape UI moved to locale JSON files

## Downloads

| File | Description |
|------|-------------|
| `gamelist-media-editor-v1.1.1-source.zip` | Manual install (Python + `pip install -r requirements.txt`) |
| `GamelistMediaEditor-Windows-Setup-v1.1.1.zip` | Windows installer (`Installer.bat`) |

## Upgrade from 1.1.0

Replace the app files (or re-run the Windows setup). No migration of `gamelist.xml` is required.

New files to keep: the whole `static/locales/` folder.

## Notes

- Genre names in the picker remain as stored in `genres.json` (French RetroBat-style labels)
- Console / `Lancer.bat` prompts stay in French
- Scrapers still need internet access (unchanged from 1.1.0)
