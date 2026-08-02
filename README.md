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
python -m pip install -r requirements.txt
```

## Icons

After cloning, generate the PNG/ICO files (favicon + Windows shortcut icon):

```bash
python generate_icons.py
```

This creates `static/favicon.ico`, `static/favicon-16.png`, `static/favicon-32.png`, `static/app-icon.png`, `icon.ico`, and `icon.png`.
An SVG favicon (`static/favicon.svg`) is already in the repo and works without this step.

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
├── icon_data/             # Embedded icon payloads
├── generate_icons.py      # Writes PNG/ICO from icon_data
├── Lancer.bat             # Windows launcher
├── Creer-Raccourci.ps1    # Desktop shortcut (Windows)
├── requirements.txt
└── README.md
```

## Safety notes

- **Deleting a game removes files from disk** (ROM + media). Always confirm carefully.
- Only files under the XML’s folder are touched (path traversal protected).
- Development server only — bound to `127.0.0.1:5050` (not exposed to the network by default).

## License

MIT — see [LICENSE](LICENSE).

---

<a id="français"></a>

## Français

Application web **locale** pour éditer les **médias et métadonnées** d’un fichier `gamelist.xml` (EmulationStation / RetroBat).

Glisse-dépose captures, vidéos, marquees, manuels et jaquettes depuis le disque ou le web. Modifie noms, descriptions, genres, notes — sauvegarde immédiate dans le XML.

### Fonctionnalités

- **Glisser-déposer** : `image`, `video`, `marquee`, `manual`, `boxback`
- **Renommer** un jeu (`name`) et éditer la **description** (`desc`)
- **Métadonnées** : rating, releasedate, developer, publisher, family, players, lang, genre
- **Genre hiérarchique**, **drapeaux** lang, **liste alphabétique**
- **Suppression** des `<region>` et suppression complète d’un jeu
- Lanceur Windows et raccourci Bureau

### Prérequis

```bash
python -m pip install -r requirements.txt
```

### Icônes

Après le clone, génère les fichiers PNG/ICO :

```bash
python generate_icons.py
```

Cela crée le favicon, l’icône d’application et `icon.ico` pour le raccourci Windows.
Le favicon SVG (`static/favicon.svg`) est déjà dans le dépôt.

### Démarrage rapide (Windows)

1. Double-clique sur **`Lancer.bat`**
2. Indique ou glisse-dépose ton `gamelist.xml`
3. Le navigateur s’ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050)

```powershell
powershell -ExecutionPolicy Bypass -File .\Creer-Raccourci.ps1
```

### Ligne de commande

```bash
python app.py
python app.py "D:\RetroBat\roms\amstradcpc\gamelist.xml"
```

### Licence

MIT — voir [LICENSE](LICENSE).
