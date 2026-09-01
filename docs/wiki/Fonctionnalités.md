# Fonctionnalités

Version documentée : **1.3.0**

## Médias

- Glisser-déposer : image, video, marquee, manual, boxback, **support**, **boxart**, **fanart**, **mix**, **maps**
- Clic image → lightbox
- Extensions réelles (PNG/JPG/MP4…), jamais `.php`
- Thumbnail RetroBat automatique au scrape SS
- Bezel 16:9 et Pad2Key (`.keys`) au scrape SS

## Métadonnées

- name, desc, genre, rating, releasedate, developer, publisher, family, players, lang, **region**
- **arcadesystemname** (CPS1, Neo-Geo, System 16…)
- Flags RetroBat : favorite, hidden, kidgame (pas d’inférence automatique « jeu enfant »)

## Scrapers

- ScreenScraper (hash + nom, types configurables, boost membre)
- Arcade Database (PCB / Cabinet / Flyer / Decal)
- Steam (trailer FR, 720p / 480p, limite 50 Mo)
- Tout sélectionner / tout désélectionner

## Liste

- Tri alphabétique, recherche, filtres médias manquants + compteurs
- Flèches, Page Up/Down, Home/End
- Badge système dans l’en-tête

## Session

- Démarre **sans** gamelist
- Ouvrir un autre XML (explorateur + récents)
- Recharger depuis le disque
- `.bak` manuel ; option backup avant purge / suppression
- Purge globale `<region>`
- Fenêtre Chromium `--app=` (pas de barre d’adresse)

## Interface

- 13 langues
- À propos (clic logo)
- ⏻ Quitter

## Technique

- `127.0.0.1:5050` uniquement
- Limite 50 Mo, verrou d’écriture XML
- `build/` et `dist/` ignorés par Git ; exe sur la [release](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.3.0)

**Gamelist Media Editor** · v1.3.0
