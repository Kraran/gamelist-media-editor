# Fonctionnalités

Version documentée : **1.7.5**

## Médias

- Glisser-déposer (fichier ou image d’une page web) ou clic pour choisir : image, video, marquee, manual, boxback, **support**, **boxart**, **fanart**, **mix**, **maps**, **miniature**, **bezel**, **wheel**, **titleshot**, **musique** (lecteur audio)
- **Éditeur d’images** : recadrage (libre ou ratio), pivoter / miroir, fond transparent (depuis les bords ou une couleur), rognage automatique, taille maximale, PNG / JPG / WebP ; aperçu en direct, copie de l’original, **Annuler**
- Galerie : chaque média dans sa forme, avec sa taille en pixels ou la durée de la vidéo ; médias manquants regroupés
- Clic image → agrandissement
- Extensions réelles (PNG/JPG/MP4…), jamais `.php` ; écritures atomiques (jamais de fichier à moitié écrit)
- Extra RetroBat au scrape ScreenScraper : Pad2Key (`.keys`)
- Un fichier remplacé va à la **Corbeille** ; un fichier qu’un autre jeu utilise n’est jamais effacé ni écrasé

## Métadonnées

- name, desc, genre, rating (**étoiles**), releasedate (**sélecteur de date**), developer, publisher, family, players, lang, region (**listes nommées**), **arcadesystemname**
- Suggestions tirées des valeurs du gamelist
- Flags RetroBat : favorite, hidden, kidgame
- **Une barre d’enregistrement** : champs modifiés marqués, `Ctrl+S`, *Annuler les modifications* ; une seule écriture du XML ; rien n’est perdu en changeant de jeu

## Scrapers

- **Un bouton Scraper**, source choisie par système (Arcade Database pour l’arcade, Steam pour `steam`, ScreenScraper sinon), menu pour en forcer une autre (retenue par système)
- **Comparaison** actuel / proposé avec images ; seul ce qui manque est coché ; préréglages *Compléter*, *Tout remplacer*, *Rien*
- Aperçus téléchargés une fois et réutilisés à l’application (quota ScreenScraper)
- **Scrape par lot** : jeux cochés (case, `Ctrl`/`Maj`+clic, `X`) ou affichés ; compléter ou remplacer, champs au choix, progression avec arrêt, rapport (mis à jour, incertains à choisir ensuite, erreurs) ; **reprise** après un arrêt et **réessai des erreurs**
- **En parallèle** avec un compte membre, jamais plus que son `maxthreads` ; requêtes par minute et quota du jour respectés par toute l’app ; réglage *Threads* pour en faire moins
- **Cache des réponses ScreenScraper** (30 jours, réglable) : rescraper ne consomme pas de quota
- **Type ScreenScraper, région et activation par média** (Réglages › Médias ScreenScraper) ; images téléchargées vérifiées (illisibles, minuscules ou unies refusées)
- ScreenScraper (hash + nom, tous les systèmes RetroBat)
- **Sources de secours** : LaunchBox Games Database (sans clé, base téléchargée une fois par jour), TheGamesDB (ta clé API), IGDB (ton application Twitch) complètent ScreenScraper champ par champ (jeu absent, champ ou média manquant, quota atteint) dans l’ordre choisi ; pastille de source dans la comparaison ; scrape d’un jeu, par lot et sur plusieurs systèmes
- Arcade Database (PCB / Cabinet / Flyer / Decal, système arcade)
- Steam (trailer FR, 720p / 480p, limite 50 Mo)

## Liste

- **Miniatures** et **compteur de médias requis** par jeu (survol : ce qui manque)
- Recherche (option : dans tous les champs), **filtres** par média manquant, par genre, favoris / cachés / enfants, et **filtre par colonne**, avec compteurs
- Liste **redimensionnable** à la souris (les vignettes rétrécissent en direct)
- `Ctrl+A` coche tous les jeux affichés ; copie des chemins des jeux cochés ; **export CSV** de la liste
- **Médias requis par système** : le compteur de la liste, le filtre et **Suivant incomplet** (`N`) s’en servent
- Rapide sur de très grosses listes (30 000 jeux MAME s’ouvrent en une seconde environ)
- Badge système dans l’en-tête

## Session

- Démarre **sans** gamelist
- Ouvrir un autre XML (explorateur + récents), recharger depuis le disque
- **Vue multi-systèmes** : tout un dossier `roms` (RetroBat, Batocera, Recalbox) en un tableau trié par système — jeux, ROM absentes ou hors gamelist, couverture image / miniature / marquee / wheel / vidéo, métadonnées manquantes, totaux ; un clic ouvre le système, le sélecteur ▾ passe d’un système à l’autre ; analyse en arrière-plan avec cache, lecture seule
- **Actions sur plusieurs systèmes** : sur les systèmes cochés de la vue d’ensemble, un par un — vérification des ROMs et des médias, images unies, suppression de champs, scraping avec la source de chaque système dans les limites ScreenScraper du compte (toute la série s’arrête au quota du jour) ; sauvegarde datée avant chaque modification, progression, **Arrêter**, rapport final ; suppression de fichiers seulement sur option et confirmation
- **Actions** : `.bak` manuel, systèmes arcade depuis `mame.xml`, **Vérifier les ROMs** (ROMs absentes du gamelist, entrées sans ROM, doublons ; mise à jour et rapport), **Vérifier les médias** (médias inutilisés à la Corbeille, liens cassés retirés ; rapport)
- Supprimer un jeu (menu ⋯ du jeu) : la fenêtre liste les fichiers qui partent (ROM, pistes et disques, médias) et ceux gardés car un autre jeu les utilise ; tout va à la Corbeille
- Copier le chemin de la ROM
- **Modifier en masse** : champ, supprimer des champs entiers (région, genre…), rechercher / remplacer (regex), noms d’après le fichier ou un DAT / une liste MAME, images (rogner, réduire, convertir), images unies (balises retirées, fichiers à la Corbeille en option), retirer des médias ou des jeux ; aperçu avant → après, sauvegarde datée et **Annuler**
- **Outil DAT** (No-Intro, Redump, FBNeo, MAME) : comparaison par nom, CRC32 ou SHA1, rapport filtrable et export CSV ; ROMs jamais modifiées
- **Créer un gamelist ici…** à partir d’un dossier de ROMs (extensions du système)
- **Statistiques** et **Sauvegardes** (30 copies datées, restaurables)
- **Annuler / Rétablir sur plusieurs niveaux** : boutons ↶ ↷ en haut (l’infobulle dit ce qui sera annulé), menu **Historique** (les étapes de la session, saut direct à l’une d’elles ou *Avant ces modifications*), `Ctrl+Z` / `Ctrl+Y` / `Ctrl+Maj+Z` hors des champs de saisie ; 30 étapes par gamelist, une par action (un enregistrement, une modification en masse, un scrap par lot entier…) ; une nouvelle modification efface ce qui pouvait être rétabli ; un gamelist modifié hors de GME remet l’historique à zéro au lieu d’écraser ce changement ; les fichiers mis à la Corbeille ne reviennent pas (sauf les retouches d’image)
- **Barre de progression et Arrêter** sur les analyses longues (images unies, vérification des ROMs et des médias) : *X / Y*, élément en cours ; affichée seulement après un court délai ; arrêter ne modifie rien
- Fenêtre Chromium `--app=` (pas de barre d’adresse)

## Interface

- Thème **sombre** (par défaut), **clair** ou **comme le système** (Réglages › Général) ; polices et icônes intégrées (fonctionne hors ligne)
- **Réglages** : langue, ScreenScraper, sources de scrape, médias requis, raccourcis ; gardés dans `ui_settings.json` à côté de l’exe
- **Clavier** : `J`/`K`, `N`, `S`, `Ctrl+S`, `Ctrl+Z` / `Ctrl+Y`, `Ctrl+F`, `?`
- 13 langues
- À propos (clic logo), Quitter

## Technique

- `127.0.0.1:5050` uniquement ; requêtes d’autres sites (CSRF) et en-têtes `Host` étrangers refusés
- Chaque action vise le jeu par son `<path>` : si le XML a changé entre-temps, elle atteint le bon jeu ou est refusée
- Limite 50 Mo, écritures du XML sérialisées et atomiques
- Tests automatiques (Windows / Linux, navigateur) et exe construit par la CI ; exe sur la [release](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.7.5)

**Gamelist Media Editor** · v1.7.5
