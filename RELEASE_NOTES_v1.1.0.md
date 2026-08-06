# Gamelist Media Editor v1.1.0

Major feature release: online scrapers.

## Highlights

### ScreenScraper
- Scrape metadata and media **field by field**
- ROM identification via CRC/MD5/SHA1 (including files inside `.zip`)
- Candidate list when several games match
- Optional **member login** in Tools for quota boost
- Built-in software developer credentials (no setup for end users)

### Arcade Database (Arcade Italia)
- **Arcade DB** button next to ScreenScraper
- Ideal for **MAME / FBNeo / arcade** romsets
- Same apply UI (checkboxes per field)

### UX & robustness
- System name in the top bar
- Loading spinner while APIs work
- Clear messages for quota / rate limits / offline server
- Polite request spacing toward both APIs

## Downloads

| File | Description |
|------|-------------|
| `gamelist-media-editor-v1.1.0-source.zip` | Manual install (Python + `pip install -r requirements.txt`) |
| `GamelistMediaEditor-Windows-Setup-v1.1.0.zip` | Windows installer (`Installer.bat`) |

## Upgrade from 1.0.x

Replace the app files (or re-run the Windows setup). No migration of `gamelist.xml` is required.

Optional: open **Tools** and enter your ScreenScraper **member** login for higher quotas.

## Notes

- Scrapers need internet access
- Arcade DB is most useful on arcade systems (MAME-style ROM names)
- Please do not flood the remote APIs; the app already throttles requests
