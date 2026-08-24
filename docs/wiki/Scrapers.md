# Scrapers

Version documentée : **1.2.0**

## ScreenScraper

- Fonctionne **sans configuration** (identifiants développeur de l’application intégrés)
- Optionnel : compte **membre** dans **Outils** pour un meilleur quota (boost)
- Correspondance : CRC/MD5 de la ROM (y compris fichier *intérieur* d’un `.zip`), puis recherche par nom avec liste de candidats
- Tu choisis les champs à appliquer (médias + métadonnées)
- Indicateur de chargement pendant l’attente (l’API peut être lente)

### Conseils

- Le dossier parent du `gamelist.xml` (ex. `snes`, `amiga500`) aide à identifier le système
- En cas d’ambiguïté, choisis le bon jeu dans la liste de candidats
- Respecte les quotas : l’app espace déjà les requêtes

## Arcade Database (Arcade Italia)

- Bouton **Arcade DB** à côté de ScreenScraper
- Idéal pour **arcade / mame / fbneo** (noms de romset MAME)
- Même interface de sélection de champs que ScreenScraper
- **Aucun compte** requis

Utilise-le sur les bons systèmes ; sur une console home, préfère ScreenScraper.

## Appliquer les résultats

1. Lance le scrape sur le jeu sélectionné
2. Si besoin, choisis un candidat
3. Coche les champs à importer
4. Valide : téléchargement des médias + écriture XML

**Gamelist Media Editor** · v1.2.0
