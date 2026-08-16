# Installation

Version documentée : **1.1.1**

Deux méthodes : **Setup Windows** (recommandé) ou **installation manuelle**.

---

## A — Setup Windows (recommandé)

Aucun Python à installer à la main : l’installateur s’en charge si besoin.

1. Va sur la [release v1.1.0](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.1.1)
2. Télécharge **`GamelistMediaEditor-Windows-Setup-v1.1.1.zip`**
3. Dézippe l’archive (dossier temporaire OK)
4. Double-clique sur **`Installer.bat`**
5. Choisis le dossier d’installation  
   (ex. `C:\Users\Toi\AppData\Local\GamelistMediaEditor`)
6. Attends la fin (copie des fichiers, Python système ou portable, dépendances)
7. Un raccourci **Gamelist Media Editor** est créé sur le Bureau et dans le Menu Démarrer

### Premier lancement

1. Double-clic sur le raccourci (ou `Lancer.bat` dans le dossier d’install)
2. Indique le chemin de ton `gamelist.xml`  
   (tu peux **glisser-déposer** le fichier dans la fenêtre noire, puis Entrée)
3. Le navigateur s’ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050)

### Python géré par l’installateur

Ordre de recherche :

1. Python déjà présent dans le dossier d’install (portable)
2. Python système (PATH)
3. Installation via **winget** (Windows 10/11)
4. Téléchargement d’un **Python portable** (embeddable) dans le dossier d’install — sans droits admin

Versions : **Python 3.9+**. Dépendances : `flask`, `lxml`, `requests`.

### Désinstallation

Menu Démarrer → **Gamelist Media Editor** → **Désinstaller**, puis supprimer le dossier d’installation si besoin.

---

## B — Installation manuelle

### Prérequis

- **Python 3.9** ou plus récent  
  - Windows : [python.org/downloads](https://www.python.org/downloads/) — coche **« Add python.exe to PATH »**
  - Linux : `sudo apt install python3 python3-pip` (ou équivalent)
  - macOS : [python.org](https://www.python.org/downloads/) ou Homebrew

### 1. Télécharger le code

**Option A — ZIP source (release)**

1. [Release v1.1.0](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.1.1)
2. Télécharge **`gamelist-media-editor-v1.1.1-source.zip`**
3. Dézippe où tu veux

**Option B — Git**

```bash
git clone https://github.com/Kraran/gamelist-media-editor.git
cd gamelist-media-editor
```

### 2. Installer les dépendances

Dans le dossier du projet :

```bash
python -m pip install -r requirements.txt
```

Paquets : `flask`, `lxml`, `requests`.

### 3. Lancer

**Windows** : double-clic sur **`Lancer.bat`**, puis chemin du `gamelist.xml`.

**Tous OS** :

```bash
python app.py "C:\chemin\vers\gamelist.xml"
```

Ouvre [http://127.0.0.1:5050](http://127.0.0.1:5050).

---

## Structure des médias

Le fichier `gamelist.xml` est dans un dossier système (ex. `roms\snes\`). À côté, l’outil attend :

```
snes/
  gamelist.xml
  images/     ← image, marquee, boxback…
  videos/
  manuals/
  *.zip / ROMs
```

Les chemins enregistrés dans le XML sont relatifs (`./images/monjeu-image.png`).

---

## Connexion Internet

- **Pas nécessaire** pour éditer médias / métadonnées à la main  
- **Nécessaire** uniquement pour les boutons **ScreenScraper** et **Arcade DB**
