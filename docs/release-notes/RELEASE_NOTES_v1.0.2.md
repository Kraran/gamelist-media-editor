# Gamelist Media Editor v1.0.2

## Nouveautés (FR)

- Bouton **Recharger** la liste depuis le disque (sans redémarrer)
- Limite de taille **50 Mo** pour les uploads (fichier local + URL)
- Verrou d'écriture XML (sauvegardes / enregistrements sérialisés)
- Suppression de l'**ancien média** lors d'un remplacement (ex. `.png` → `.jpg`)
- Genres externalisés dans `static/genres.json`
- Sécurité des chemins `/media/` renforcée
- `Ctrl+S` s'arrête à la première erreur
- Confirmations unifiées, accessibilité de base, polish UI

## What's new (EN)

- **Reload** button (re-read XML from disk)
- **50 MB** upload size limit (local file + URL)
- XML write lock
- Delete previous media file on path/extension change
- Genres in `static/genres.json`
- Hardened `/media/` path resolution
- `Ctrl+S` stops on first save failure
- Unified confirmations, basic a11y, UI polish

## Installation

### A — Windows Setup
1. Download `GamelistMediaEditor-Windows-Setup.zip`
2. Extract → run `Installer.bat`
3. Choose folder → done

### B — Manual
1. Download `gamelist-media-editor-v1.0.2-source.zip`
2. `python -m pip install -r requirements.txt`
3. Run `Lancer.bat` or `python app.py path\to\gamelist.xml`
4. Open http://127.0.0.1:5050
