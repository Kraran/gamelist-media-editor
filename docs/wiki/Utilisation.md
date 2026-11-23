# Utilisation

Version documentée : **1.7.0**

## Démarrage

1. Lance l’exe (ou `Lancer.bat` / `python app.py`)
2. Une fenêtre application s’ouvre si possible, sinon le navigateur
3. **Gamelist…** si aucun XML n’est chargé (navigateur de fichiers, ou un clic sur l’un des 10 derniers fichiers ouverts)

Tu peux changer de système à tout moment sans redémarrer.

## Vue multi-systèmes

Dans **Gamelist…**, va dans ton dossier `roms` (RetroBat `roms`, Batocera `/userdata/roms`, Recalbox `/recalbox/share/roms`, ou le dossier au-dessus) puis clique **Vue multi-systèmes…**. Les 6 derniers dossiers roms ouverts sont listés sous les récents.

- Une ligne par dossier de système (un `gamelist.xml` ou des ROMs ; `bios/`, `saves/`… sont ignorés), avec son nom complet (*Super Nintendo* pour `snes`)
- Colonnes : jeux, **ROM absentes** (entrées dont le fichier n’existe plus), **hors gamelist** (fichiers ROM non listés), part des jeux avec **image, miniature, marquee, wheel, vidéo** présents sur le disque (survole la case : présents / liens cassés / manquants), jeux **sans description, genre ou date**
- Totaux de la collection en haut ; clic sur un en-tête pour trier (deux sens)
- Clic sur un système : il s’ouvre dans l’éditeur (les modifications non enregistrées sont demandées avant). La flèche ▾ à côté du nom du système passe à un autre système ou revient à la vue d’ensemble
- Un dossier sans gamelist propose **Créer un gamelist…** ; un `gamelist.xml` illisible est signalé
- L’analyse tourne en arrière-plan (barre de progression, **Arrêter**) et reste en mémoire tant que le gamelist et les dossiers de médias ne changent pas ; **Actualiser** relit tout
- Lecture seule : l’analyse n’écrit rien

### Actions sur plusieurs systèmes

Coche des systèmes dans la vue d’ensemble (la case de l’en-tête coche tout), puis **Actions sur les systèmes cochés…**. Coche les actions voulues ; elles s’enchaînent **un système à la fois**, dans cet ordre :

1. **Vérifier les ROMs** : ajouter les ROMs absentes du gamelist ; retirer les entrées sans ROM (décoché par défaut, jamais si plus de la moitié manque) et, en option, leurs médias inutilisés
2. **Vérifier les médias** : retirer les liens vers des fichiers absents ; en option, supprimer les médias inutilisés (jamais si plus de la moitié semble inutilisée : dossier partagé ?)
3. **Images unies** : les champs à vérifier, et en option la suppression des fichiers
4. **Supprimer des champs** : les mêmes balises que *Modifier en masse › Supprimer des champs*
5. **Scraper** avec la source du système (ScreenScraper, ou Arcade Database / Steam) : *Compléter* (seulement les jeux auxquels il manque un champ coché, pour économiser le quota) ou *Remplacer* (tous les jeux)

- Chaque action passe par l’outil d’un seul système : mêmes contrôles et **sauvegarde datée** avant chaque modification (*Sauvegardes › Historique*)
- ScreenScraper : jamais plus de requêtes à la fois que le `maxthreads` de ton compte, ses requêtes par minute sont respectées et le quota du jour est vérifié avant chaque système. Quota atteint, bannissement ou source bloquée : **toute la série s’arrête** et dit pourquoi ; les systèmes restants sont *non traités* (le lot du système arrêté se reprend depuis l’éditeur)
- Un système dont un lot de scraping n’est pas fini est ignoré plutôt que remplacé
- Barre de progression (système, action, jeux), **Arrêter** termine l’étape en cours, puis un **rapport** par système et par action ; **Retour à la vue d’ensemble** relit les compteurs
- Supprimer des fichiers (toujours vers la Corbeille) demande sa propre case **et** une confirmation en rouge qui les liste. Les ROMs ne sont jamais supprimées
- Un système en erreur (gamelist illisible…) n’arrête pas les autres ; à la fin, le gamelist ouvert avant est rouvert

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
| Wheel | `<wheel>` | `images/` |
| Titleshot | `<titleshot>` | `images/` |
| Musique | `<music>` | `music/` |

- **Ajouter** : glisse un fichier (ou une image d’une page web) sur un média manquant, ou clique dessus pour choisir un fichier
- **Remplacer** : glisse sur le média, ou bouton *Remplacer le fichier*
  L’ancien fichier, s’il avait un autre nom, va à la **Corbeille**. Un fichier qu’un autre jeu utilise (ou une autre balise du même jeu) n’est jamais effacé ni écrasé : le nouveau prend un autre nom (`…-image-2.png`).
- **Retirer** : la corbeille retire la balise du XML (le fichier reste sur le disque)

Limite : 50 Mo par fichier.

### Éditeur d’images

Le bouton **Éditer l’image** d’une vignette d’image (pas les vidéos, manuels ni musiques) ouvre l’original et le résultat, sur un damier :

- **Recadrage** : trace un rectangle sur l’original et déplace-le ; libre ou en 1:1, 4:3, 3:4, 16:9, 9:16, 2:1, 3:1 ou aux proportions d’origine
- **Pivoter** de 90° et **miroir** horizontal / vertical
- **Fond transparent** : *Depuis les bords* (la couleur des coins qui touche les bords, l’intérieur d’un logo reste opaque) ou *Cette couleur partout*, avec une tolérance
- **Rognage automatique** des bords transparents ou d’une seule couleur
- **Taille maximale** (proportions gardées) et **format** PNG / JPG / WebP avec la qualité

L’aperçu suit chaque réglage et n’écrit rien. **Enregistrer** remplace le fichier (une copie de l’original est gardée ; un nouveau format prend la nouvelle extension et le chemin du gamelist suit) ou crée un nouveau fichier `…-edit`. Un fichier qu’une autre balise utilise n’est jamais écrasé. **Annuler** dans la notification remet l’original (20 dernières modifications).

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

- **Scraper par lot** : les jeux cochés dans la liste, sinon tous ceux affichés ; voir [Scrapers](Scrapers#scraper-par-lot)
- **Modifier en masse** (aussi le crayon de la barre de sélection) : sur les jeux cochés, affichés ou tous, avec un **aperçu** avant → après obligatoire, une sauvegarde datée avant d’appliquer et **Annuler** dans la notification :
  - *Champ* : une valeur pour genre, développeur, éditeur, date, note, joueurs, langue, région, famille, système arcade, favori / caché / enfant
  - *Supprimer des champs* : retire entièrement les balises cochées (`<region>`, `<genre>`, `<desc>`, `<sortname>`, `<playcount>`, `<cheevosId>`…, même vides). Chaque balise affiche le nombre de jeux qui l’ont ; une confirmation rappelle les champs et le nombre de jeux. `<name>`, `<path>` et les médias ne sont pas proposés (les médias ont leur onglet). Pour retirer toutes les régions : coche *Région* sur « Toute la gamelist »
  - *Rechercher / remplacer* dans le nom, la description ou un champ texte (texte simple ou expression régulière)
  - *Noms* : d’après le nom du fichier ROM, ou d’après un DAT / une liste MAME (`pacman.zip` → `Pac-Man (Midway)`), avec ou sans les mentions `(Europe)`, `[!]`…
  - *Images* : rogner, réduire ou convertir un média de tous ces jeux (copie des originaux, **Annuler**)
  - *Images unies* : repère les images d’une seule couleur ou entièrement transparentes (fausses images, téléchargements vides) parmi les types de médias cochés, avec un aperçu (miniature, couleur, fichier), et retire leurs balises. Une petite variation due à la compression JPEG est tolérée. La case *Supprimer aussi les fichiers du disque* (décochée par défaut) les envoie à la **Corbeille** après confirmation, mais seulement les fichiers du dossier du gamelist qu’aucune autre balise n’utilise (les autres sont gardés et listés) ; les ROMs ne sont jamais supprimées. **Annuler** restaure le gamelist, pas les fichiers : récupère-les dans la Corbeille
  - *Médias* : retirer des balises (les fichiers restent) ; *Retirer* : sortir des jeux du gamelist (leurs médias à la Corbeille en option) ; **les ROMs ne sont jamais supprimées**
- **Outil DAT** : charge un DAT No-Intro, Redump, FBNeo ou MAME que tu as et compare tes ROMs par nom ou, si tu le demandes, par CRC32 / SHA1 : OK, mal nommé, mauvais dump, incomplet, inconnu, manquant ; filtres et export CSV. Les ROMs ne sont jamais renommées, déplacées ni supprimées
- **Statistiques** : jeux scrapés, complets, médias présents / cassés / manquants par type (avec *Afficher*), genres
- **Exporter la liste (CSV)** : les jeux affichés, dans l’ordre de la liste
- **Sauvegardes** : les 30 dernières copies datées du gamelist, restaurables
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

## Réglages (roue dentée)

| Onglet | Contenu |
|---|---|
| Général | Thème (sombre, clair ou comme le système) et langue de l’interface, appliqués immédiatement |
| ScreenScraper | Compte membre, région préférée, **threads** (Auto ou moins), **cache** des réponses, test de connexion ; chaque réglage est enregistré dès qu’il change |
| Médias ScreenScraper | Pour chaque média : activé ou non, type ScreenScraper et région essayée en premier |
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
| `X` | Cocher / décocher le jeu ouvert pour le scrape par lot (`Maj`+clic : tous jusqu’à ce jeu, `Échap` : tout décocher) |
| Entrée | Appliquer le scrape (fenêtre de comparaison) |
| `Ctrl+S` | Enregistrer |
| `Ctrl+F` ou `/` | Rechercher |
| Échap | Fermer une fenêtre ou un menu |
| `?` | Liste des raccourcis |

Les lettres ne font rien pendant la saisie dans un champ.

## Quitter

**Quitter** arrête le serveur. Fermer la fenêtre application l’arrête aussi.

**Gamelist Media Editor** · v1.7.0
