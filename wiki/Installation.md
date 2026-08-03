# Installation

## Prérequis

- **Python 3.8** ou plus récent  
  - Windows : [python.org/downloads](https://www.python.org/downloads/) — coche **« Add python.exe to PATH »**
  - Linux : `sudo apt install python3 python3-pip` (ou équivalent)
  - macOS : [python.org](https://www.python.org/downloads/) ou Homebrew

## 1. Télécharger le projet

### Option A — ZIP (simple)

1. Va sur [la page du dépôt](https://github.com/Kraran/gamelist-media-editor)
2. Clique **Code** → **Download ZIP**
3. Dézippe le dossier où tu veux (ex. `Documents\gamelist-media-editor`)

### Option B — Git

```bash
git clone https://github.com/Kraran/gamelist-media-editor.git
cd gamelist-media-editor
```

## 2. Installer les dépendances

Ouvre un terminal **dans le dossier du projet** :

```bash
python -m pip install -r requirements.txt
```

Paquets installés : `flask`, `lxml`, `requests`.

## 3. (Optionnel) Générer les icônes

```bash
python generate_icons.py
```

Crée le favicon et `icon.ico` pour le raccourci Windows. Le favicon SVG fonctionne déjà sans cette étape.

## 4. Lancer l’application

### Windows (recommandé)

1. Double-clique sur **`Lancer.bat`**
2. Indique le chemin de ton `gamelist.xml`  
   (tu peux **glisser-déposer** le fichier dans la fenêtre noire, puis Entrée)
3. Le navigateur s’ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050)

### Ligne de commande (Windows / Linux / macOS)

```bash
python app.py
```

Le programme demande le chemin du `gamelist.xml`. Tu peux aussi le passer en argument :

```bash
python app.py "D:\RetroBat\roms\amstradcpc\gamelist.xml"
```

## Raccourci Bureau (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File .\Creer-Raccourci.ps1
```

Crée un raccourci avec l’icône de l’application (après `generate_icons.py`).

## Structure attendue des médias

Les dossiers médias sont **à côté** du `gamelist.xml` (arborescence RetroBat classique) :

```
roms/systeme/
├── gamelist.xml
├── images/          ← captures, marquees, boxback
├── videos/          ← vidéos de preview
├── manuals/         ← manuels PDF
└── *.zip / *.dsk …  ← les ROMs
```

L’outil crée les sous-dossiers manquants si besoin lors d’un upload.

## Arrêter le serveur

Ferme la fenêtre du terminal, ou appuie sur **Ctrl+C**.
