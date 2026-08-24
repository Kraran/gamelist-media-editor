# Fonctionnalités

Version documentée : **1.2.0**

## Médias & métadonnées

- Glisser-déposer **image**, **video**, **marquee**, **manual**, **boxback** (fichier ou URL)
- Édition **name**, **desc**, **genre** (hiérarchique), **rating**, **releasedate**, **developer**, **publisher**, **family**, **players**, **lang** (drapeaux)
- Suppression du tag média XML (fichier disque conservé) ou suppression complète du jeu

## Scrapers

- **ScreenScraper** (hash + nom + candidats + boost membre optionnel)
- **Arcade Database** (romsets MAME)
- Throttle et messages de quota localisés

## Liste & navigation

- Tri alphabétique par nom
- Filtres « médias manquants » avec compteurs
- Recherche, flèches clavier, Page Up/Down, Home/End
- Badge **système** (dossier du gamelist) dans l’en-tête

## Session & fichiers

- Démarrage **sans** gamelist obligatoire
- **Ouvrir un autre gamelist.xml** sans redémarrer (explorateur + récents)
- **Recharger** la liste depuis le disque
- Sauvegarde **`.bak`** manuelle ; option backup avant purge / suppression
- Purge globale des balises `<region>`

## Interface

- **13 langues** (FR, EN, ES, DE, IT, PT, NL, PL, TR, SV, NO, DA, RU)
- Dialogue **À propos** (logo en-tête)
- Bouton **⏻ Quitter** (style rouge plein)
- Favicon / icône application

## Technique

- Écoute **127.0.0.1:5050** uniquement
- Chemins médias sécurisés (pas de path traversal)
- Limite upload 50 Mo, verrou d’écriture XML
- Build Windows : **PyInstaller** (`BUILD_EXE.bat`)

**Gamelist Media Editor** · v1.2.0
