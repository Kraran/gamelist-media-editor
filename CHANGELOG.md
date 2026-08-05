# Changelog

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
