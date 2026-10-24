# Fonctionnalités

Version documentée : **1.4.0**

## Médias

- Glisser-déposer (fichier ou image d’une page web) ou clic pour choisir : image, video, marquee, manual, boxback, **support**, **boxart**, **fanart**, **mix**, **maps**
- Galerie : chaque média dans sa forme, avec sa taille en pixels ou la durée de la vidéo ; médias manquants regroupés
- Clic image → agrandissement
- Extensions réelles (PNG/JPG/MP4…), jamais `.php` ; écritures atomiques (jamais de fichier à moitié écrit)
- Extras RetroBat au scrape ScreenScraper : miniature, bezel 16:9, Pad2Key (`.keys`)

## Métadonnées

- name, desc, genre, rating (**étoiles**), releasedate (**sélecteur de date**), developer, publisher, family, players, lang, region (**listes nommées**), **arcadesystemname**
- Suggestions tirées des valeurs du gamelist
- Flags RetroBat : favorite, hidden, kidgame
- **Une barre d’enregistrement** : champs modifiés marqués, `Ctrl+S`, *Annuler les modifications* ; une seule écriture du XML ; rien n’est perdu en changeant de jeu

## Scrapers

- **Un bouton Scraper**, source choisie par système (Arcade Database pour l’arcade, Steam pour `steam`, ScreenScraper sinon), menu pour en forcer une autre (retenue par système)
- **Comparaison** actuel / proposé avec images ; seul ce qui manque est coché ; préréglages *Compléter*, *Tout remplacer*, *Rien*
- Aperçus téléchargés une fois et réutilisés à l’application (quota ScreenScraper)
- ScreenScraper (hash + nom, types configurables, boost membre, tous les systèmes RetroBat)
- Arcade Database (PCB / Cabinet / Flyer / Decal, système arcade)
- Steam (trailer FR, 720p / 480p, limite 50 Mo)

## Liste

- **Miniatures** et **compteur de médias** par jeu (survol : ce qui manque)
- Recherche, **filtre** par média manquant avec compteurs
- **Suivant incomplet** (`N`)
- Rapide sur de très grosses listes (30 000 jeux MAME s’ouvrent en une seconde environ)
- Badge système dans l’en-tête

## Session

- Démarre **sans** gamelist
- Ouvrir un autre XML (explorateur + récents), recharger depuis le disque
- **Actions** : `.bak` manuel, systèmes arcade depuis `mame.xml`, purge globale `<region>`
- Supprimer un jeu (menu ⋯ du jeu), copier le chemin de la ROM
- Fenêtre Chromium `--app=` (pas de barre d’adresse)

## Interface

- Thème sombre, polices et icônes intégrées (fonctionne hors ligne)
- **Réglages** : langue, ScreenScraper, sources de scrape, raccourcis
- **Clavier** : `J`/`K`, `N`, `S`, `Ctrl+S`, `Ctrl+F`, `?`
- 13 langues
- À propos (clic logo), Quitter

## Technique

- `127.0.0.1:5050` uniquement ; requêtes d’autres sites (CSRF) et en-têtes `Host` étrangers refusés
- Chaque action vise le jeu par son `<path>` : si le XML a changé entre-temps, elle atteint le bon jeu ou est refusée
- Limite 50 Mo, écritures du XML sérialisées et atomiques
- Tests automatiques (Windows / Linux, navigateur) et exe construit par la CI ; exe sur la [release](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.4.0)

**Gamelist Media Editor** · v1.4.0
