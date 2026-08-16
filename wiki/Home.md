# Gamelist Media Editor — Wiki

Bienvenue sur la documentation de **Gamelist Media Editor** (version **1.1.1**), un outil local pour éditer les médias et métadonnées d’un fichier `gamelist.xml` (RetroBat / EmulationStation).

## En deux mots

Application web **locale** (sur ton PC uniquement) qui te permet de :

- glisser-déposer images, vidéos, marquees, manuels et jaquettes ;
- **scraper** un jeu via **ScreenScraper** ou **Arcade Database** (champ par champ) ;
- filtrer les jeux **sans média** (image, vidéo, etc.) ;
- renommer un jeu, éditer sa description et ses métadonnées ;
- modifier genre, note, développeur, langue (avec drapeau), etc. ;
- sauvegarder un `.bak`, purger les balises `<region>`, supprimer un jeu (ROM + médias + XML) ;
- quitter proprement serveur + navigateur.

Tout est sauvegardé **directement** dans ton `gamelist.xml`. Aucun cloud obligatoire.

## Installation rapide (Windows)

1. Télécharge **`GamelistMediaEditor-Windows-Setup-v1.1.1.zip`** sur la [page Releases](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.1.1)
2. Dézippe → double-clic sur **`Installer.bat`**
3. Choisis le dossier d’installation
4. Lance le raccourci **Gamelist Media Editor**
5. Indique (ou glisse) ton `gamelist.xml`
6. Ouvre [http://127.0.0.1:5050](http://127.0.0.1:5050)

## Navigation

| Page | Contenu |
|------|---------|
| [Installation](Installation) | Setup Windows, install manuelle, structure des médias |
| [Utilisation](Utilisation) | Interface, filtres, médias, métadonnées, outils, raccourcis |
| [Scrapers](Scrapers) | ScreenScraper et Arcade Database (nouveauté 1.1.0) |
| [Fonctionnalités](Fonctionnalités) | Liste détaillée (v1.1.1) |
| [FAQ](FAQ) | Questions fréquentes |
| [Dépannage](Dépannage) | Erreurs courantes et solutions |

## Liens utiles

- **Code source** : [github.com/Kraran/gamelist-media-editor](https://github.com/Kraran/gamelist-media-editor)
- **Releases** : [v1.1.0](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.1.1)
- **Licence** : MIT
- **Interface** : [http://127.0.0.1:5050](http://127.0.0.1:5050) (après démarrage)

## Pour qui ?

Conçu pour les collectionneurs **RetroBat** / **EmulationStation** qui veulent finaliser proprement les jeux mal scrapés, sans éditer le XML à la main.

Accessible aux débutants : double-clic sur le raccourci (ou `Lancer.bat`), puis glisser-déposer ou scrape dans le navigateur.
