# Gamelist Media Editor v1.1.2

Switch systems without restarting.

## Highlights

### Open another gamelist.xml
- Header button **📂 Gamelist…**
- In-app **file browser** (folders, `.xml`, parent folder, Windows drives)
- Opens by default on the **parent** of the current gamelist (e.g. `roms/`)
- **Recent** paths remembered in the browser
- Double-click a `gamelist.xml` to open it immediately
- Paste full path still works

### Technical
- `GET /api/browse`, `POST /api/open-gamelist`, `GET /api/session`
- `APP_DIR` vs media `BASE_DIR` separation
- Version **1.1.2**

## Downloads

| File | Description |
|------|-------------|
| `gamelist-media-editor-v1.1.2-source.zip` | Manual install (Python + `pip install -r requirements.txt`) |
| `GamelistMediaEditor-Windows-Setup-v1.1.2.zip` | Windows installer (`Installer.bat`) |

## Upgrade from 1.1.1

Replace the app files or re-run the Windows setup. No `gamelist.xml` migration needed.
