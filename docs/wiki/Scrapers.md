# Scrapers

Version documentée : **1.4.0**

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

Chaque image proposée est téléchargée **une seule fois**, pour l’aperçu, et gardée un jour dans `cache\remote\`. L’application réutilise ce fichier : ScreenScraper n’est pas sollicité deux fois. Les adresses ScreenScraper (qui contiennent ton identifiant) n’apparaissent ni dans la page ni dans la console.

## ScreenScraper

- Fonctionne **sans compte** (identifiants développeur de l’app)
- Compte **membre** optionnel dans **Réglages › ScreenScraper** (meilleur quota), avec **Tester la connexion**
- Types d’images configurables au même endroit (choix unique, pas de repli) :
  - Image : Screenshot (`ss`) ou Screenshot titre (`sstitle`)
  - Boxart : Boîtier 2D (`box-2D`) ou 3D (`box-3D`, défaut)
  - Mix : Recalbox v1 ou v2 (défaut v2)
- Autres types fixes : marquee `wheel-hd`, boxback `box-2D-back`, support `support-2D`, fanart, maps, vidéo normalisée, manuel
- Extras RetroBat proposés comme les autres champs : **miniature** (`box-2D`), **bezel** 16:9, **Pad2Key** (fichier `.keys` à côté de la ROM)
- Correspondance : hash de la ROM (fichier *intérieur* d’un `.zip`), puis nom + liste de candidats
- Un boxback **entièrement vert** (image factice SS) est **ignoré** : rien n’est écrit

### Conseils

- Le dossier parent (`snes`, `mame`, `amiga500`…) donne le système ; tous les dossiers RetroBat sont reconnus
- En cas d’ambiguïté, choisis le bon candidat
- L’app espace les requêtes ; en cas de quota, attends ou active le boost

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

**Gamelist Media Editor** · v1.4.0
