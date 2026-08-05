# Gamelist Media Editor v1.0.1

## Nouveautés (FR)

- Filtres médias manquants avec compteurs en direct
- Navigation clavier dans la liste (flèches, Page Up/Down, Home/End)
- Raccourcis : Ctrl+S (enregistrer), Ctrl+F (recherche)
- Panneau **Outils** : sauvegarde manuelle `.bak`, purge des balises `<region>`
- Case à cocher backup avant actions destructives
- Bouton **Quitter** (arrête le serveur Flask)
- **Installateur Windows** (dossier au choix, Python auto, dépendances, raccourcis)
- Correctifs : liste de jeux vide (`escapeHtml`), CRLF des `.bat`, encodage PowerShell

## What's new (EN)

- Missing-media filters with live counts
- Keyboard navigation and shortcuts
- Tools panel (manual backup, region purge)
- Quit button
- Windows Setup installer
- Bug fixes (game list, batch line endings, PowerShell encoding)

## Installation

### A — Windows Setup
1. Download `GamelistMediaEditor-Windows-Setup.zip`
2. Extract → run `Installer.bat`
3. Choose folder → done

### B — Manual
1. Download `gamelist-media-editor-v1.0.1-source.zip`
2. `python -m pip install -r requirements.txt`
3. Run `Lancer.bat` or `python app.py path\\to\\gamelist.xml`
4. Open http://127.0.0.1:5050
