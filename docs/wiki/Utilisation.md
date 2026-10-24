# Utilisation

Version documentée : **1.4.0**

## Démarrage

1. Lance l’exe (ou `Lancer.bat` / `python app.py`)
2. Une fenêtre application s’ouvre si possible, sinon le navigateur
3. **Gamelist…** si aucun XML n’est chargé (navigateur de fichiers, ou un clic sur l’un des 10 derniers fichiers ouverts)

Tu peux changer de système à tout moment sans redémarrer.

## Interface

| Zone | Rôle |
|------|------|
| Barre du haut | Logo / À propos, système, nombre de jeux, **Gamelist…**, **Recharger**, **Actions** (⋯), **Réglages**, **Quitter** |
| Liste (gauche) | Recherche, filtre par média manquant (avec le nombre de jeux), jeux avec **miniature** et **compteur de médias** (`4/10`, vert si complet ; survole-le pour voir ce qui manque) |
| Centre | Nom du jeu, **Scraper**, **Suivant incomplet**, menu ⋯ du jeu, médias présents, médias manquants |
| Droite | Description, métadonnées, favori / caché / jeu enfant |
| Bas | Barre d’enregistrement (quand quelque chose a changé), barre d’état et raccourcis |

En dessous de 1100 px de large, les métadonnées passent sous les médias.

## Médias

Les médias présents s’affichent **dans leur forme** (boîte verticale, logo large…) avec leur taille en pixels ou la durée de la vidéo. Clic sur une image → **agrandissement**.

| Média | Balise XML | Dossier |
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

- **Ajouter** : glisse un fichier (ou une image d’une page web) sur un média manquant, ou clique dessus pour choisir un fichier
- **Remplacer** : glisse sur le média, ou bouton *Remplacer le fichier*
- **Retirer** : la corbeille retire la balise du XML (le fichier reste sur le disque)

Limite : 50 Mo par fichier.

## Métadonnées

- Nom, description, genre (liste + sous-genre)
- **Note en étoiles** (demi-étoiles ; clic, flèches, Début / Fin, Suppr)
- **Date de sortie** avec un sélecteur de date (stockée `AAAAMMJJT000000` ; une valeur non reconnue est gardée telle quelle)
- Développeur, éditeur, famille, joueurs : **suggestions** tirées du gamelist
- **Langue** et **région** en listes nommées dans la langue de l’interface (une valeur comme `en,fr` est conservée)
- **Système arcade** (`<arcadesystemname>`, ex. CPS1, Neo-Geo)
- **Favori**, **Caché**, **Jeu enfant**

Les champs modifiés sont marqués et la **barre d’enregistrement** les liste : **Enregistrer** (`Ctrl+S`) écrit tout en une fois, **Annuler les modifications** revient à l’état du disque.  
Changer de jeu, recharger, scraper ou quitter avec des modifications en cours demande *Enregistrer / Ne pas enregistrer / Annuler*.

## Suivant incomplet

Le bouton **Suivant incomplet** (ou `N`) passe au prochain jeu de la liste auquel il manque au moins un média. Si un filtre est actif (ex. « sans boxart »), il passe au prochain jeu qui correspond au filtre. Il reprend en haut de la liste et prévient quand il n’en reste plus.

## Menu ⋯ du jeu

- **Copier le chemin de la ROM** (chemin complet)
- **Supprimer ce jeu…** : ROM + médias + entrée XML, avec sauvegarde `.bak` optionnelle (irréversible)

## Actions (⋯ dans la barre du haut)

Pour tout le gamelist :

- **Sauvegarder (.bak)** : copie `gamelist.xml.bak` à côté du fichier
- **Remplir les systèmes arcade** depuis un dump MAME `mame.xml` (`mame.exe -listxml`) ; les jeux qui ont déjà une valeur sont laissés tels quels
- **Supprimer toutes les balises `<region>`** (confirmation, sauvegarde optionnelle)

## Réglages (roue dentée)

| Onglet | Contenu |
|---|---|
| Général | Langue de l’interface (appliquée immédiatement, mémorisée par le navigateur) |
| ScreenScraper | Compte membre (boost), région préférée, types d’images, test de connexion |
| Sources de scrape | Les sources forcées par système depuis le menu ▾ du bouton Scraper, avec retour à l’automatique |
| Raccourcis clavier | La liste ci-dessous |

## Raccourcis

| Touche | Action |
|--------|--------|
| `J` / `↓` | Jeu suivant |
| `K` / `↑` | Jeu précédent |
| Page préc. / Page suiv. | 10 jeux plus haut / plus bas |
| Début / Fin | Premier / dernier jeu de la liste |
| `N` | Jeu incomplet suivant |
| `S` | Scraper le jeu |
| Entrée | Appliquer le scrape (fenêtre de comparaison) |
| `Ctrl+S` | Enregistrer |
| `Ctrl+F` ou `/` | Rechercher |
| Échap | Fermer une fenêtre ou un menu |
| `?` | Liste des raccourcis |

Les lettres ne font rien pendant la saisie dans un champ.

## Quitter

**Quitter** arrête le serveur. Fermer la fenêtre application l’arrête aussi.

**Gamelist Media Editor** · v1.4.0
