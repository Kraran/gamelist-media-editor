# Gamelist Media Editor v1.0.0

**English** | [Français](#français)

First stable release of the local web app to edit EmulationStation / RetroBat `gamelist.xml` media and metadata.

## Highlights

- **Drag & drop media**: `image`, `video`, `marquee`, `manual`, `boxback` (from disk or browser)
- **Rename games** (`name`) and edit **descriptions** (`desc`)
- **Metadata**: rating (0–1), releasedate, developer, publisher, family, players, lang, genre
- **Hierarchical genre** picker (main + sub-genre)
- **Country / region flags** for `lang` (including EU and World)
- **Alphabetical** game list with search
- **Purge all `<region>` tags** (with confirmation)
- **Delete a game completely**: ROM + media on disk + XML entry (with confirmation)
- **Windows launcher** (`Lancer.bat`) and desktop shortcut script
- **Favicon & app icons** (run `python generate_icons.py` after clone, or use the release ZIP)

## Requirements

- Python 3.8+
- `pip install -r requirements.txt` (flask, lxml, requests)

## Quick start

```bash
# From source
python generate_icons.py   # optional if using the release ZIP
python app.py
# or
python app.py "/path/to/gamelist.xml"
```

**Windows:** double-click `Lancer.bat`, then open http://127.0.0.1:5050

## Safety

- Deleting a game **removes files from disk**. Confirm carefully.
- Bound to `127.0.0.1:5050` only (not exposed to the network by default).

## License

MIT

---

<a id="français"></a>

## Français

Première version stable de l’éditeur local de médias et métadonnées pour `gamelist.xml` (EmulationStation / RetroBat).

### Points clés

- **Glisser-déposer** : `image`, `video`, `marquee`, `manual`, `boxback`
- **Renommage** et édition de la **description**
- **Métadonnées** : rating, releasedate, developer, publisher, family, players, lang, genre
- **Genre hiérarchique**, **drapeaux** pour `lang`
- **Liste alphabétique** avec recherche
- **Purge des balises `<region>`** et **suppression complète d’un jeu**
- Lanceur Windows et raccourci Bureau
- Icônes : `python generate_icons.py` après clone, ou ZIP de release déjà généré

### Démarrage

```bash
python generate_icons.py
python app.py
```

**Windows :** double-clic sur `Lancer.bat` → http://127.0.0.1:5050

### Licence

MIT
