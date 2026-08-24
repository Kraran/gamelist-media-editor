# Gamelist Media Editor v1.2.0

Standalone Windows release: start without a gamelist, open via the in-app browser.

## Highlights

- **GamelistMediaEditor.exe** — no Python required for end users (build with `BUILD_EXE.bat`)
- Starts with **no gamelist loaded**; use **📂 Gamelist…** (opens automatically on first launch)
- Drag-and-drop a `gamelist.xml` onto the `.exe` still works
- Browser opens on http://127.0.0.1:5050
- **About** dialog (click header logo)
- Quit button style aligned with RomSet Verifier (⏻, solid red)
- Full **i18n** pass (13 languages, including About / open gamelist / no-gamelist messages)
- ScreenScraper config is saved next to the executable

## Downloads

| File | Description |
|------|-------------|
| `gamelist-media-editor-v1.2.0.zip` | Package with the Windows executable (recommended) |
| Source zipball from the tag | Full source + `BUILD_EXE.bat` |

## Build the .exe yourself

On Windows with Python 3.9+:

```bat
BUILD_EXE.bat
```

Output: `dist\GamelistMediaEditor.exe`
