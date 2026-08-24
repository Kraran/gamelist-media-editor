# Installation

Version documentée : **1.2.0**

Trois méthodes : **exécutable Windows** (recommandé), **source Python**, ou ancien **Setup Windows** (versions ≤ 1.1.x).

## Option A — Exécutable Windows (recommandé)

1. Va sur la [release v1.2.0](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.2.0)
2. Télécharge **`gamelist-media-editor-v1.2.0.zip`**
3. Décompresse le zip où tu veux
4. Lance **`GamelistMediaEditor.exe`**

Le navigateur s’ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050).  
**Aucun Python à installer.** Aucun chemin à saisir dans la console.

Au premier lancement, l’app propose d’ouvrir un `gamelist.xml` via **📂 Gamelist…**.

### Compiler l’exe toi-même (développeurs)

Sur Windows avec Python 3.9+ :

```bat
BUILD_EXE.bat
```

Sortie : `dist\GamelistMediaEditor.exe`

## Option B — Installation manuelle (Python)

1. Télécharge le **source** depuis la [release](https://github.com/Kraran/gamelist-media-editor/releases/latest) ou clone le dépôt
2. Installe **Python 3.9+** depuis [python.org](https://www.python.org/downloads/) (coche *Add to PATH*)
3. Dans le dossier de l’app :

```bat
python -m pip install -r requirements.txt
```

4. Lance **`Lancer.bat`** (Windows) ou :

```bat
python app.py
```

Optionnel : `python app.py "C:\chemin\vers\gamelist.xml"` pour ouvrir un fichier tout de suite.

5. Ouvre [http://127.0.0.1:5050](http://127.0.0.1:5050)

## Structure des médias attendue

Le `gamelist.xml` et les dossiers médias sont dans le **même dossier système** RetroBat, par exemple :

```
roms\snes\
  gamelist.xml
  images\
  videos\
  manuals\
  *.sfc / *.zip …
```

L’outil lit le XML et écrit les fichiers relatifs (`./images/…`, `./videos/…`, etc.).

## Mise à jour vers 1.2.0

- Remplace l’ancien dossier par le contenu du zip **v1.2.0**, **ou**
- Relance `BUILD_EXE.bat` si tu compiles toi-même

Conserve éventuellement ton fichier local `screenscraper_config.json` (identifiants membre SS) s’il est à côté de l’exe / de `app.py`.

Aucune migration de `gamelist.xml` n’est nécessaire.

**Gamelist Media Editor** · v1.2.0
