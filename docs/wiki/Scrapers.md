# Scrapers

Version documentée : **1.7.0**

## Le bouton Scraper

Un seul bouton sur la fiche du jeu (ou la touche `S`). La source est choisie selon le **dossier du système** :

| Système (dossier) | Source automatique |
|---|---|
| `mame`, `fbneo`, `fba`, `arcade`, `neogeo`, `cps1/2/3`, `naomi`, `atomiswave`, `cave`, `segastv`, `model2/3`… | Arcade Database |
| `steam` | Steam |
| Tous les autres | ScreenScraper |

Le menu **▾** à côté du bouton force une autre source et lance le scrape. Ce choix est **retenu pour ce système** sur ce navigateur ; *Revenir au choix automatique* l’annule (aussi dans **Réglages › Sources de scrape**).

## La comparaison

Après le scrape (et le choix du bon jeu si plusieurs correspondent), une fenêtre montre **ce qui va changer** :

- **Médias** : l’actuel et le proposé côte à côte, avec leur taille en pixels. Un média absent de la fiche n’affiche que le proposé. Vidéo, manuel et Pad2Key sont décrits en texte (type, qualité, taille).
- **Informations** : valeur actuelle → valeur proposée, au format de la fiche (étoiles, date, langue et région nommées).
- Chaque champ porte un badge **Nouveau** (la fiche n’a rien), **Différent** (texte différent) ou **Remplace** (un fichier existe déjà).
- En bas : les champs **identiques** et ceux que la source **ne propose pas**.

**Seul ce qui manque est coché.** Rien n’est remplacé sans que tu le coches. Préréglages : **Compléter** (ce qui manque), **Tout remplacer**, **Rien**. Un clic n’importe où sur une ligne ou une carte la coche.

Le bouton **Appliquer (n)** a le focus : `S` puis Entrée remplit les manques du jeu.  
Un scrape n’**efface** jamais une valeur : un champ que la source n’a pas reste tel quel.

### Quota ScreenScraper

**Cache des réponses** : les recherches de jeux sont gardées sur le disque (`cache\ss-api\`, 30 jours par défaut, *Jeu non trouvé* 1 jour, jamais les erreurs). Rescraper un jeu n’envoie alors aucune requête et ne consomme rien de ton quota. Les identifiants ne sont jamais enregistrés. **Réglages › ScreenScraper** le désactive, règle sa durée et le vide ; la fenêtre de scrape (*Actualiser depuis ScreenScraper*) et le lot (*Ignorer le cache*) peuvent redemander à ScreenScraper.

Chaque image proposée est téléchargée **une seule fois**, pour l’aperçu, et gardée un jour dans `cache\remote\`. L’application réutilise ce fichier : ScreenScraper n’est pas sollicité deux fois. Les adresses ScreenScraper (qui contiennent ton identifiant) n’apparaissent ni dans la page ni dans la console.

## Scraper par lot

Pour scraper beaucoup de jeux d’un coup : **Actions › Scraper par lot**, ou **Scraper…** dans la barre de sélection.

**Quels jeux ?** Les jeux **cochés** dans la liste ; si aucun ne l’est, **tous les jeux affichés** (avec la recherche et le filtre en cours : par exemple le filtre *Média requis manquant* donne tous les jeux incomplets).

Pour cocher : la case qui apparaît sur la miniature d’une ligne, `Ctrl`+clic sur la ligne, ou `X` pour le jeu ouvert. `Maj`+clic coche tous les jeux affichés jusqu’à celui-là. `Échap` (ou ×) décoche tout.

**Quoi écrire ?**
- **Compléter** : seuls les champs vides sont remplis, rien n’est remplacé.
- **Tout remplacer** : les champs cochés sont aussi remplacés quand la source a une autre valeur.
- Coche les **médias** et les **informations** à écrire. Le **nom** et **Pad2Key** sont décochés par défaut.
- Une sauvegarde `.bak` est faite avant (option).

**Pendant le lot**, une barre montre le jeu en cours ; **Arrêter** s’arrête après ce jeu (et arrête tous les jeux en cours en parallèle).

**En parallèle, sans dépasser tes limites ScreenScraper** : avec un compte membre (celui saisi dans **Réglages › ScreenScraper**), plusieurs jeux sont traités en même temps, jamais plus que le `maxthreads` que ScreenScraper donne à ce compte ; sans compte, un seul à la fois. Toute l’application partage les limites du compte (requêtes par minute, quota du jour, réponses 429 / 430 / 431) et les résultats sont écrits dans l’ordre de la liste. **Réglages › ScreenScraper › Threads** peut baisser ce nombre, jamais le dépasser ; la fenêtre du lot affiche *Threads : x/y*.

**Reprendre / réessayer** : le lot est gardé sur le disque. **Dernier lot**, sous la liste des jeux, rouvre son rapport ; **Reprendre** continue les jeux restants après un arrêt ou un redémarrage ; **Réessayer les erreurs** ne refait que les jeux et champs en erreur. La source est celle du système (bouton Scraper). Si ScreenScraper refuse (quota, identifiants, API fermée), le lot s’interrompt au lieu d’échouer jeu après jeu.

**Le rapport** donne les jeux **mis à jour** (avec les champs écrits), ceux **sans rien de nouveau**, les **incertains** et les **erreurs**. Un jeu est incertain quand la source ne reconnaît pas la ROM et propose plusieurs jeux par le nom : rien n’est écrit, et **Choisir…** ouvre son scrape pour que tu choisisses le bon. **Exporter le rapport** l’enregistre en texte.

## ScreenScraper

- Fonctionne **sans compte** (identifiants développeur de l’app)
- Compte **membre** optionnel dans **Réglages › ScreenScraper** (meilleur quota), avec **Tester la connexion**
- **Réglages › Médias ScreenScraper** : pour chaque média, activé ou non, le type ScreenScraper (par exemple image `ss` ou `sstitle`, boxart `box-2D` ou `box-3D`, marquee `wheel-hd`, `wheel` ou `screenmarquee`, mix `mixrbv1` / `mixrbv2`, bezel 16:9 ou 4:3, vidéo normalisée ou originale) et la région essayée en premier. Les valeurs par défaut sont celles de la 1.6.0
- **Wheel** (`<wheel>`) et **titleshot** (`<titleshot>`) sont proposés quand tu les actives (désactivés par défaut) ; ScreenScraper n’a pas de **musique** de jeu : ajoute-la à la main
- Les images téléchargées sont **vérifiées** : un fichier illisible, minuscule ou d’une seule couleur n’est pas écrit et le champ est signalé en erreur
- Extras RetroBat proposés comme les autres champs : **miniature** (`box-2D`), **bezel** 16:9, **Pad2Key** (fichier `.keys` à côté de la ROM)
- Correspondance : hash de la ROM (fichier *intérieur* d’un `.zip`), puis nom + liste de candidats
- Un boxback **entièrement vert** (image factice SS) est **ignoré** : rien n’est écrit

### Conseils

- Le dossier parent (`snes`, `mame`, `amiga500`…) donne le système ; tous les dossiers RetroBat sont reconnus
- En cas d’ambiguïté, choisis le bon candidat
- L’app respecte les limites du compte (requêtes par minute, quota du jour, `maxthreads`) ; en cas de quota atteint, attends le lendemain

## Arcade Database (Arcade Italia)

Idéal pour **MAME / FBNeo / Neo-Geo / Atomiswave**, etc. Aucun compte.

Mapping images arcade :

| Arcade DB | Champ dans l’éditeur |
|-----------|----------------------|
| In-game / title | Image |
| PCB | Support |
| Cabinet | Boxart |
| Flyer | Boxback |
| Decal | Marquee |
| Vidéo shortplay | Vidéo |
| Manuel PDF | Manuel |

Le **fanart n’est pas remplacé** par le cabinet.

**Système arcade** : lu sur la page du jeu (`Driver source: cps1.cpp` → `CPS1`), proposé dans la comparaison comme les autres champs.  
Si le driver a le **même nom** que le romset (`gauntlet.cpp` / `gauntlet`), le champ reste vide.

## Steam

Télécharge une **bande-annonce** (pas une capture SS).

- Recherche par nom, AppID ou URL boutique
- Textes boutique en **français** si disponibles
- Trailer FR nommé comme tel en priorité, sinon le plus récent
- `movie_max.mp4` si ≤ 50 Mo, sinon 480p
- Les URL CDN 404 / pages HTML d’erreur sont ignorées

Utile surtout pour les jeux PC / Steam, pas pour une ROM arcade.

**Gamelist Media Editor** · v1.7.0
