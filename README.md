# Gamelist Media Editor

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-green.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#)

**English** | [Français](#français)

Local web application to edit **EmulationStation / RetroBat `gamelist.xml`** media files and metadata.

Drag & drop screenshots, videos, marquees, manuals and box art from your disk or from the web. Edit names, descriptions, genres, ratings and more — with instant save to the XML.

---

## Features

- **Drag & drop media**: `image`, `video`, `marquee`, `manual`, `boxback`
  - From the file explorer or by dragging an image from a browser tab
- **Rename games** (`name`) and edit **descriptions** (`desc`)
- **Metadata editor**: rating (0–1), releasedate, developer, publisher, family, players, lang, genre
- **Hierarchical genre picker** (main genre + sub-genre)
- **Country flags** for the `lang` field (fr, en, eu, wr, …)
- **Alphabetical game list** with search
- **Purge all `<region>` tags** from the whole XML (with confirmation)
- **Delete a game completely**: ROM + media files on disk + XML entry (with confirmation)
- **Favicon & app icon** included
- **Windows launcher** (`Lancer.bat`) and desktop shortcut script

## Requirements

- Python **3.8+**
- Packages: `flask`, `lxml`, `requests`

```bash
python -m pip install flask lxml requests
```

## Quick start

### Windows

1. Double-click **`Lancer.bat`**
2. Paste or drag-and-drop the path to your `gamelist.xml`
3. Your browser opens at [http://127.0.0.1:5050](http://127.0.0.1:5050)

Optional — create a desktop shortcut with the app icon:

```powershell
powershell -ExecutionPolicy Bypass -File .\Creer-Raccourci.ps1
```

### Command line (Windows / Linux / macOS)

```bash
python app.py
# or with an explicit path:
python app.py "/path/to/roms/system/gamelist.xml"
```

The app uses the **folder that contains the XML** as the media root (`images/`, `videos/`, `manuals/`).

## Project layout

```
gamelist-media-editor/
├── app.py                 # Flask backend
├── templates/index.html   # Web UI
├── static/                # Favicon & icons
├── Lancer.bat             # Windows launcher
├── Creer-Raccourci.ps1    # Creates a desktop shortcut (Windows)
├── icon.ico / icon.png    # Application icon
├── requirements.txt
└── README.md
```

## Safety notes

- Deleting a game **removes files from disk** (ROM + media). Confirm carefully.
- Only paths under the XML directory are deleted (path traversal is blocked).
- The development server binds to `127.0.0.1:5050` (local only).

## License

MIT — see [LICENSE](LICENSE).

---

## Français

Application web **locale** pour éditer les médias et métadonnées d'un fichier **`gamelist.xml`** (EmulationStation / RetroBat).

Glisse-dépose captures, vidéos, marquees, manuels et jaquettes depuis le disque ou le web. Modifie noms, descriptions, genres, notes, etc. — sauvegarde immédiate dans le XML.

### Fonctionnalités

- **Glisser-déposer** : image, vidéo, marquee, manuel, boxback (fichiers locaux ou depuis un navigateur)
- **Renommage** des jeux et édition des **descriptions**
- **Métadonnées** : rating, releasedate, developer, publisher, family, players, lang, genre
- **Genre hiérarchique** (genre principal + sous-genre)
- **Drapeaux** pour le champ `lang`
- **Liste alphabétique** avec recherche
- **Suppression de toutes les balises `<region>`**
- **Suppression complète d'un jeu** (ROM + médias + entrée XML)
- **Favicon** et **icône d'application**
- Lanceur Windows (`Lancer.bat`) et script de raccourci Bureau

### Prérequis

```bash
python -m pip install flask lxml requests
```

### Démarrage rapide (Windows)

1. Double-clique sur **`Lancer.bat`**
2. Indique ou glisse-dépose ton `gamelist.xml`
3. Le navigateur s'ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050)

Raccourci Bureau avec icône :

```powershell
powershell -ExecutionPolicy Bypass -File .\Creer-Raccourci.ps1
```

### Ligne de commande

```bash
python app.py
python app.py "D:\RetroBat\roms\amstradcpc\gamelist.xml"
```

Les dossiers `images/`, `videos/` et `manuals/` sont ceux **à côté** du fichier XML.

### Avertissements

- La suppression d'un jeu **efface des fichiers sur le disque**. Confirme bien.
- Seuls les chemins situés sous le dossier du XML sont touchés.
- Serveur de développement uniquement (`127.0.0.1:5050`).

### Licence

MIT — voir [LICENSE](LICENSE).
