# Utilisation

Version documentée : **1.3.0**

## Démarrage

1. Lance l’exe (ou `Lancer.bat` / `python app.py`)
2. Une fenêtre application s’ouvre si possible, sinon le navigateur
3. **📂 Gamelist…** si aucun XML n’est chargé

Tu peux changer de système à tout moment sans redémarrer.

## Interface

| Zone | Rôle |
|------|------|
| En-tête | Logo / À propos, nom du système, compteur, Gamelist…, Outils, Recharger, Supprimer, ⏻ Quitter |
| Liste | Recherche, filtres médias manquants, jeux par nom |
| Centre | Médias + métadonnées du jeu sélectionné |

Clic sur une image → **agrandissement** (lightbox). Échap ou clic pour fermer.

## Médias (glisser-déposer)

Champs éditables à l’écran :

| Zone | Balise XML | Dossier |
|------|------------|---------|
| Image | `<image>` | `images/` |
| Vidéo | `<video>` | `videos/` |
| Marquee | `<marquee>` | `images/` |
| Manuel | `<manual>` | `manuals/` |
| Boxback | `<boxback>` | `images/` |
| Support | `<cartridge>` | `images/` |
| Boxart | `<boxart>` | `images/` |
| Fanart | `<fanart>` | `images/` |
| Mix | `<mix>` | `images/` |
| Maps | `<map>` | `images/` |

Glisse un fichier local ou une URL.  
Le **thumbnail** RetroBat (miniature menu) est téléchargé automatiquement au scrape SS s’il existe, sans zone supplémentaire.

## Métadonnées

- Nom, description, genre (liste + sous-genre)
- Note (0–1), date, développeur, éditeur, famille, joueurs
- Langue (code + drapeau), **région**
- **Système arcade** (`<arcadesystemname>`, ex. CPS1, Neo-Geo)
- Cases RetroBat : **Favori**, **Caché**, **Jeu enfant**

**Ctrl+S** enregistre nom + description + métadonnées.

## Filtres

Pastilles sous la recherche (sans image, sans vidéo, sans support, etc.) avec le nombre de jeux.

## Outils (⚙)

- Langue de l’interface → **Appliquer**
- Compte membre **ScreenScraper** (boost)
- Types d’images ScreenScraper (screenshot / titre, box 2D / 3D, mix v1 / v2)
- Sauvegarde manuelle `.bak`
- Purge de toutes les balises `<region>`
- Remplir `arcadesystemname` depuis un dump MAME `mame.xml` (optionnel)

## Raccourcis

| Touche | Action |
|--------|--------|
| ↑ / ↓ | Liste |
| Page Up / Down | Sauter |
| Home / End | Premier / dernier |
| Ctrl+F | Recherche |
| Ctrl+S | Enregistrer |
| Échap | Fermer lightbox / dialogue |

## Quitter

**⏻ Quitter** arrête le serveur. Fermer la fenêtre application arrête aussi le serveur.

**Gamelist Media Editor** · v1.3.0
