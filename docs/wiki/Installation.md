# Installation

Version documentée : **1.3.0**

## Option A — Exécutable Windows (recommandé)

1. Ouvre la [release v1.3.0](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.3.0)
2. Télécharge **`GamelistMediaEditor-Windows-v1.3.0.zip`**
3. Décompresse où tu veux
4. Lance **`GamelistMediaEditor.exe`**

**Aucun Python à installer.**  
Fenêtre dédiée (mode application) si Edge / Chrome / Brave est le navigateur par défaut ou installé. Sinon, le navigateur habituel s’ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050).

Au premier lancement : **📂 Gamelist…** pour choisir le XML.

### Compiler l’exe (développeurs)

Windows + Python 3.9+ :

```bat
BUILD_EXE.bat
```

Sortie : `dist\GamelistMediaEditor.exe` (dossier ignoré par Git — normal).

## Option B — Source Python

1. Télécharge le **source** de la [release](https://github.com/Kraran/gamelist-media-editor/releases/latest) ou clone le dépôt
2. Installe **Python 3.9+** ([python.org](https://www.python.org/downloads/), *Add to PATH*)
3. Dans le dossier de l’app :

```bat
python -m pip install -r requirements.txt
```

Dépendances : Flask, lxml, requests, **Pillow**.

4. `Lancer.bat` ou `python app.py`  
   Optionnel : `python app.py "C:\chemin\vers\gamelist.xml"`

5. [http://127.0.0.1:5050](http://127.0.0.1:5050)

## Structure des médias

```
roms\snes\
  gamelist.xml
  images\
  videos\
  manuals\
  *.sfc / *.zip …
```

Les chemins écrits dans le XML sont relatifs (`./images/…`, `./videos/…`).  
Les fichiers **Pad2Key** (`.keys`) vont **à côté de la ROM**, pas dans `images/`.

## Mise à jour 1.2.0 → 1.3.0

- Remplace les fichiers de l’app (garde `screenscraper_config.json` à côté de l’exe / de `app.py`)
- En source : `python -m pip install -r requirements.txt` (Pillow ajouté)
- Aucune migration du `gamelist.xml`

**Gamelist Media Editor** · v1.3.0
