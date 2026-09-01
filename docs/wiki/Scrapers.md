# Scrapers

Version documentée : **1.3.0**

Trois boutons sur la fiche jeu : **ScreenScraper**, **Arcade DB**, **Steam**.  
Tu coches les champs à appliquer. **Tout sélectionner** / **Tout désélectionner** sont disponibles.

## ScreenScraper

- Fonctionne **sans compte** (identifiants développeur de l’app)
- Compte **membre** optionnel dans **Outils** (meilleur quota)
- Types d’images configurables dans **Outils** (choix unique, pas de repli) :
  - Image : Screenshot (`ss`) ou Screenshot titre (`sstitle`)
  - Boxart : Boîtier 2D (`box-2D`) ou 3D (`box-3D`, défaut)
  - Mix : Recalbox v1 ou v2 (défaut v2)
- Autres types fixes : marquee `wheel-hd`, boxback `box-2D-back`, support `support-2D`, fanart, maps, vidéo normalisée, manuel
- En plus, sans case à cocher : **thumbnail** (`box-2D`), **bezel** 16:9, **Pad2Key** (fichier `.keys` à côté de la ROM)
- Correspondance : hash de la ROM (fichier *intérieur* d’un `.zip`), puis nom + liste de candidats
- Un boxback **entièrement vert** (image factice SS) est **ignoré** : rien n’est écrit

### Conseils

- Le dossier parent (`snes`, `mame`, `amiga500`…) aide à trouver le système
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

**Système arcade** : lu sur la page du jeu (`Driver source: cps1.cpp` → `CPS1`).  
Si le driver a le **même nom** que le romset (`gauntlet.cpp` / `gauntlet`), le champ reste vide.

## Steam

Télécharge une **bande-annonce** (pas une capture SS).

- Recherche par nom, AppID ou URL boutique
- Textes boutique en **français** si disponibles
- Trailer FR nommé comme tel en priorité, sinon le plus récent
- `movie_max.mp4` si ≤ 50 Mo, sinon 480p
- Les URL CDN 404 / pages HTML d’erreur sont ignorées

Utile surtout pour les jeux PC / Steam, pas pour une ROM arcade.

## Appliquer

1. Scrape du jeu sélectionné  
2. Candidat si besoin  
3. Cases à cocher (+ tout / rien)  
4. Valider → téléchargement + XML

**Gamelist Media Editor** · v1.3.0
