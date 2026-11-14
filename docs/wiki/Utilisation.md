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
| Liste (gauche) | Recherche, filtre par média manquant (avec le nombre de jeux), jeux avec **miniature** et **compteur de médias requis** (`3/4`, vert si complet ; survole-le pour voir ce qui manque) |
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
| Miniature | `<thumbnail>` | `images/` |
| Bezel | `<bezel>` | `images/` |

- **Ajouter** : glisse un fichier (ou une image d’une page web) sur un média manquant, ou clique dessus pour choisir un fichier
- **Remplacer** : glisse sur le média, ou bouton *Remplacer le fichier*
  L’ancien fichier, s’il avait un autre nom, va à la **Corbeille**. Un fichier qu’un autre jeu utilise (ou une autre balise du même jeu) n’est jamais effacé ni écrasé : le nouveau prend un autre nom (`…-image-2.png`).
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

Le bouton **Suivant incomplet** (ou `N`) passe au prochain jeu de la liste auquel il manque au moins un **média requis**. Si un filtre est actif (ex. « sans boxart »), il passe au prochain jeu qui correspond au filtre. Il reprend en haut de la liste et prévient quand il n’en reste plus.

## Médias requis

Chaque système a sa liste de **médias requis** : ceux qu’un jeu doit avoir pour être complet. Par défaut : image, vidéo, marquee et boxart (sans boxart pour les systèmes arcade). Change-la dans **Réglages › Médias requis**, ou avec **Médias requis…** au-dessus des médias manquants d’un jeu.

Elle sert au compteur de la liste (`3/4`), au filtre **Média requis manquant** et à **Suivant incomplet**. Dans la fiche, les médias requis manquants viennent en premier, les autres sous **Facultatifs**.

## Menu ⋯ du jeu

- **Copier le chemin de la ROM** (chemin complet)
- **Supprimer ce jeu…** : la fenêtre liste exactement ce qui part :
  - les **fichiers du jeu** : la ROM, ses pistes ou disques (`.cue`, `.gdi`, `.m3u`), le dossier du même nom à côté (MAME : `kinst/` de `kinst.zip`), son fichier Pad2Key `.keys` ;
  - ses **médias** ;
  - son entrée dans `gamelist.xml`.

  Ce qu’un autre jeu utilise encore (boxart partagé, ROM listée deux fois) est **gardé** et listé à part. Tout va à la **Corbeille** (décoche l’option pour supprimer définitivement) ; sauvegarde `.bak` optionnelle. Si la ROM ne peut pas être supprimée (fichier verrouillé, lecteur réseau sans Corbeille), rien n’est modifié.

## Actions (⋯ dans la barre du haut)

Pour tout le gamelist :

- **Sauvegarder (.bak)** : copie `gamelist.xml.bak` à côté du fichier
- **Vérifier les ROMs** : compare le gamelist aux fichiers du dossier et liste
  - les **ROMs absentes du gamelist** (à ajouter : nom du fichier, prêtes à scraper avec `S` puis `N`),
  - les **entrées sans ROM** (le fichier de `<path>` n’existe plus : à retirer, avec leurs médias si tu le coches),
  - les **jeux en double** (même ROM listée plusieurs fois : fusion dans l’entrée la plus complète).

  Coche ce que tu veux changer puis **Mettre à jour le gamelist** (sauvegarde `.bak` avant, cochée par défaut). **Exporter le rapport** l’enregistre en texte. Si plus de la moitié des jeux n’ont pas leur ROM (mauvais dossier, disque débranché), rien n’est coché.
  Pour l’arcade (MAME, FBNeo, Naomi…), les disques `.chd` et le dossier d’un romset (`kinst\` à côté de `kinst.zip`) ne sont jamais proposés comme jeux.
- **Vérifier les médias** : compare les dossiers `images`, `videos`, `manuals` aux médias utilisés par les jeux et liste
  - les **médias inutilisés** (miniature, taille à libérer),
  - les **liens vers des médias absents** (balise qui pointe vers un fichier disparu).

  **Nettoyer** met les fichiers cochés à la **Corbeille** (récupérables ; décoche l’option pour les supprimer définitivement) et retire les balises cassées cochées (sauvegarde `.bak` avant). Un fichier utilisé par n’importe quelle balise d’un jeu n’est jamais proposé. Si plus de la moitié des médias semblent inutilisés (dossier partagé avec un autre gamelist ?), rien n’est coché.
- **Remplir les systèmes arcade** depuis un dump MAME `mame.xml` (`mame.exe -listxml`) ; les jeux qui ont déjà une valeur sont laissés tels quels
- **Supprimer toutes les balises `<region>`** (confirmation, sauvegarde optionnelle)

## Réglages (roue dentée)

| Onglet | Contenu |
|---|---|
| Général | Langue de l’interface (appliquée immédiatement) |
| ScreenScraper | Compte membre (boost), région préférée, types d’images, test de connexion ; chaque réglage est enregistré dès qu’il change |
| Sources de scrape | Les sources forcées par système depuis le menu ▾ du bouton Scraper, avec retour à l’automatique |
| Médias requis | Les médias qu’un jeu du système ouvert doit avoir, et les autres systèmes personnalisés |
| Raccourcis clavier | La liste ci-dessous |

Ces réglages (et la langue) sont gardés dans `ui_settings.json`, à côté de l’exe.

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
