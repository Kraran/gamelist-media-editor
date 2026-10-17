# Gamelist Media Editor v1.3.0

Scrapers, RetroBat media fields and arcade hardware names.

## Highlights

- New media: **Support**, **Boxart**, **Fanart**, **Mix**, **Maps**
- ScreenScraper media types configurable in **Tools**
- **Steam** trailers (French when available)
- Arcade Database: PCB / Cabinet / Flyer / Decal mapped like a cabinet scrap
- `<arcadesystemname>` from MAME driver (`cps1.cpp` → CPS1)
- Solid-green ScreenScraper boxbacks are skipped
- Image lightbox, Select all / Deselect all on scrape apply

## Downloads

| File | Description |
|------|-------------|
| `gamelist-media-editor-v1.3.0-source.zip` | Source (Python) |
| `GamelistMediaEditor-Windows-v1.3.0.zip` | Standalone `.exe` (build with `BUILD_EXE.bat` if you ship it) |

## Upgrade from 1.2.0

Replace the app files (keep your `screenscraper_config.json`).  
`pip install -r requirements.txt` (Pillow added).
