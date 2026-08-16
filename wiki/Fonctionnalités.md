# Fonctionnalités

Version documentée : **1.1.1**

## Médias

- Glisser-déposer **image**, **vidéo**, **marquee**, **manuel (PDF)**, **boxback**
- Fichiers locaux ou URL `http(s)`
- Limite **50 Mo**
- Création auto des dossiers `images/`, `videos/`, `manuals/`
- Remplacement : suppression de l’ancien fichier si le chemin change
- Retrait de balise XML sans effacer le fichier disque

## Métadonnées

- `name`, `desc`
- `rating` (0–1), `releasedate`, `developer`, `publisher`, `family`, `players`
- `lang` avec **drapeau** (pays, EU, World…)
- `genre` hiérarchique (liste guidée)

## Scrapers (1.1.0)

- **ScreenScraper** : hash ROM (y compris zip), recherche nom, candidats, boost membre optionnel
- **Arcade Database** : romsets MAME / FBNeo, même UI de sélection de champs
- Spinner de chargement, messages quota / erreur clairs
- Espacement automatique des requêtes API

## Liste et navigation

- Tri alphabétique par `name`
- Recherche texte
- Filtres **médias manquants** + pastilles de comptage
- Flèches, Page Up/Down, Home/End
- **Ctrl+S**, **Ctrl+F** / **/**

## Outils & sécurité

- Sauvegarde manuelle `gamelist.xml.bak`
- Purge de toutes les balises `<region>`
- Suppression complète d’un jeu (ROM + médias + XML) avec confirmation
- Case « créer un .bak » avant actions destructives
- Chemins médias sécurisés (pas de sortie du dossier système)
- Serveur local uniquement (`127.0.0.1:5050`)
- Verrou d’écriture XML, cache de parse

## Interface

- Badge **nom du système** (dossier du gamelist) dans la barre
- Panneau **Outils**
- Bouton **Recharger** la liste
- Bouton **Quitter** (arrête le serveur)
- Favicon / icônes application

## Interface multilingue (1.1.1)

13 langues pour l’interface et les messages serveur.  
**Outils → Langue** → choisir → **Appliquer la langue**.

Fichiers : `static/locales/*.json`.

