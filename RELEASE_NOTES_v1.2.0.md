# Gamelist Media Editor v1.2.0

Standalone Windows release: start without a gamelist, open via the in-app browser.

## Highlights

<<<<<<< HEAD
- **GamelistMediaEditor.exe** — no Python required for end users (build with `BUILD_EXE.bat`)
- Starts with **no gamelist loaded**; use **📂 Gamelist…** (opens automatically on first launch)
- Drag-and-drop a `gamelist.xml` onto the `.exe` still works
- Browser opens on http://127.0.0.1:5050
- **About** dialog (click header logo)
- Quit button style aligned with RomSet Verifier (⏻, solid red)
- Full **i18n** pass (13 languages, including About / open gamelist / no-gamelist messages)
=======
- **GamelistMediaEditor.exe** — no Python required for end users
- Starts with **no gamelist loaded**; use **📂 Gamelist…** (opens automatically on first launch)
- Drag-and-drop a `gamelist.xml` onto the `.exe` still works
- Browser opens on http://127.0.0.1:5050
>>>>>>> f05aa51 (v1.2.0: standalone exe, start without gamelist, About, i18n complete)
- ScreenScraper config is saved next to the executable

## Downloads

| File | Description |
|------|-------------|
<<<<<<< HEAD
| `GamelistMediaEditor-Windows-v1.2.0.zip` | Folder with `GamelistMediaEditor.exe` (recommended) |
=======
| `GamelistMediaEditor-Windows-v1.2.0.zip` | Folder with `GamelistMediaEditor.exe` + icon (recommended) |
>>>>>>> f05aa51 (v1.2.0: standalone exe, start without gamelist, About, i18n complete)
| `gamelist-media-editor-v1.2.0-source.zip` | Source (Python) + `BUILD_EXE.bat` |

## Build the .exe yourself

On Windows with Python 3.9+:

```bat
BUILD_EXE.bat
```

Output: `dist\GamelistMediaEditor.exe`
