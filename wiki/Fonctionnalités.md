# Fonctionnalités

## Médias

| Fonction | Description |
|----------|-------------|
| Glisser-déposer fichier | Depuis l’Explorateur Windows / Finder / gestionnaire de fichiers |
| Glisser-déposer web | Image tirée d’un onglet navigateur → téléchargement auto |
| Champs supportés | `image`, `video`, `marquee`, `manual`, `boxback` |
| Création des dossiers | `images/`, `videos/`, `manuals/` créés si absents |
| Chemins relatifs | Écriture en `./images/...` pour rester portable |

## Édition texte & métadonnées

| Fonction | Description |
|----------|-------------|
| Renommage | Champ `name` — liste retriée alphabétiquement |
| Description | Éditeur de texte pour `desc` |
| Rating | 0 à 1 |
| Releasedate, developer, publisher, family, players | Champs libres |
| Lang | Codes ISO 2 lettres + `eu` / `wr` avec **drapeaux** colorés |
| Genre | Sélection guidée (genre + sous-genre) parmi une liste fixe adaptée au rétrogaming |

## Maintenance du gamelist

| Fonction | Description |
|----------|-------------|
| Purge `<region>` | Supprime toutes les balises region du XML (confirmation) |
| Suppression de jeu | ROM + tous les médias + entrée XML (confirmation) |
| Sécurité chemins | Interdiction de sortir du dossier du XML (`..` bloqué) |

## Confort d’usage

| Fonction | Description |
|----------|-------------|
| Liste alphabétique | Tri par `name` |
| Recherche | Filtre rapide dans la liste des jeux |
| Serveur local | `127.0.0.1:5050` uniquement (pas exposé sur le réseau) |
| Lanceur Windows | `Lancer.bat` coloré, messages d’erreur clairs |
| Raccourci Bureau | Script PowerShell `Creer-Raccourci.ps1` |
| Favicon / icône | SVG + génération PNG/ICO via `generate_icons.py` |

## Ce que l’outil ne fait pas

- Il ne **télécharge pas** les ROMs ni ne scrappe ScreenScraper / autres bases.  
- Il ne gère pas plusieurs `gamelist.xml` en même temps (un lancement = un fichier).  
- Ce n’est **pas** un serveur public : reste sur ta machine.
