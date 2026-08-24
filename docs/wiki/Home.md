# Gamelist Media Editor — Wiki

**Version documentée : 1.2.0**

## En deux mots

Application web **locale** (sur ton PC uniquement) qui te permet de :

- glisser-déposer images, vidéos, marquees, manuels et jaquettes ;
- **scraper** un jeu via **ScreenScraper** ou **Arcade Database** (champ par champ) ;
- filtrer les jeux **sans média** (image, vidéo, etc.) ;
- renommer un jeu, éditer sa description et ses métadonnées ;
- modifier genre, note, développeur, langue (avec drapeau), etc. ;
- **changer la langue de l’interface** (13 langues) ;
- **ouvrir un autre `gamelist.xml`** sans redémarrer (explorateur intégré) ;
- sauvegarder un `.bak`, purger les balises `<region>`, supprimer un jeu (ROM + médias + XML) ;
- consulter l’**À propos** (logo en haut à gauche) ;
- quitter proprement serveur + navigateur (**⏻ Quitter**).

Tout est sauvegardé **directement** dans ton `gamelist.xml`. Aucun cloud obligatoire.

## Installation rapide (Windows)

### Recommandé — exécutable autonome

1. Télécharge **`gamelist-media-editor-v1.2.0.zip`** sur la [page Releases](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.2.0)
2. Dézippe → double-clic sur **`GamelistMediaEditor.exe`**
3. Le navigateur s’ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050)
4. Utilise **📂 Gamelist…** pour ouvrir ton `gamelist.xml` (proposé automatiquement au premier lancement)

Optionnel : glisse un `gamelist.xml` sur le `.exe` pour l’ouvrir tout de suite.

### Alternative — source Python

Voir [Installation](Installation).

## Navigation

| Page | Contenu |
| --- | --- |
| [Installation](Installation) | Exe Windows, source Python, structure des médias |
| [Utilisation](Utilisation) | Interface, ouvrir un gamelist, filtres, médias, outils, raccourcis |
| [Scrapers](Scrapers) | ScreenScraper et Arcade Database |
| [Fonctionnalités](Fonctionnalités) | Liste détaillée (v1.2.0) |
| [FAQ](FAQ) | Questions fréquentes |
| [Dépannage](Dépannage) | Erreurs courantes et solutions |

## Liens utiles

- **Code source** : [github.com/Kraran/gamelist-media-editor](https://github.com/Kraran/gamelist-media-editor)
- **Releases** : [v1.2.0](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.2.0)
- **Licence** : MIT
- **Interface** : [http://127.0.0.1:5050](http://127.0.0.1:5050) (après démarrage)

## Pour qui ?

Conçu pour les collectionneurs **RetroBat** / **EmulationStation** qui veulent finaliser proprement les jeux mal scrapés, sans éditer le XML à la main.

Accessible aux débutants : double-clic sur l’exe, puis **Gamelist…** et glisser-déposer / scrape dans le navigateur.

**Gamelist Media Editor** · v1.2.0
