# Changelog

## [1.0.2] - 2026-08-06

### Added
- **Reload** button — re-read `gamelist.xml` from disk while keeping the current selection when possible
- Client-side **upload size limit** (50 MB), aligned with the server
- Process-level **XML write lock** to serialize saves and backups
- Auto-delete of the **previous media file** when replacing with a different path/extension (e.g. `.png` → `.jpg`)
- Genres loaded from **`static/genres.json`** (easier to maintain)
- Accessibility basics: `aria-*` on list, filters, dialogs; focus-visible styles

### Changed
- Safer path resolution for `/media/` (no path traversal; fixed `lstrip("./" )` edge case)
- URL downloads: hard **50 MB** cap with streaming
- `Ctrl+S` stops the save chain on the first failure (name → desc → meta)
- Confirmation modals unified (clear field / quit / destructive actions)
- UI polish: no inline styles, CSS helpers, shutdown screen as a proper class
- XML parse **cache** (mtime-based) + `get_game_elem` helper

### Fixed
- Path sanitization that could turn `../x` into a relative path under the media root
- Filter / list logic consolidated (`getFilteredGames`)
- Debounced search to avoid re-rendering on every keystroke

## [1.0.1] - 2026-08-05

### Added
- **Missing media filters** with live counts (no image / video / marquee / manual / boxback, or any missing)
- **Keyboard navigation** in the game list (Up/Down, Page Up/Down, Home/End)
- Shortcuts: **Ctrl+S** (save), **Ctrl+F** or **/** (search)
- **Tools** panel for global actions
- Manual **gamelist.xml.bak** backup
- Optional backup checkbox before purge regions / delete game
- **Quit** button (stops Flask server; console closes when using Lancer.bat)
- **Windows Setup** installer (`Installer.bat` + `Install.ps1`): choose folder, install Python if needed, dependencies, shortcuts

### Changed
- Header cleaned up (region purge moved into Tools)
- Status bar shows keyboard hints
- Safer confirmation dialogs for destructive actions

### Fixed
- JavaScript `escapeHtml` syntax error that prevented the game list from loading
- Windows batch files line endings (CRLF) for reliable launchers
- PowerShell installer encoding issues on French Windows

## [1.0.0] - 2026-08-02

### Added
- Initial public release
- Drag-and-drop media editor for image, video, marquee, manual, boxback
- Metadata editing (name, desc, genre, rating, dates, publisher, lang flags, etc.)
- Purge all `<region>` tags
- Delete game (ROM + media + XML)
- Favicon / app icon, Lancer.bat, bilingual README
