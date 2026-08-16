# FAQ

## C’est accessible sans être informaticien ?

Oui. Sous Windows, le **Setup** installe Python si besoin. Ensuite : raccourci → chemin du `gamelist.xml` → navigateur → glisser-déposer ou boutons scrape.

## Faut-il un compte ScreenScraper ?

**Non** pour scraper. Un compte **membre** est **optionnel** (Outils) pour augmenter les quotas (boost).

## Arcade DB, c’est pour tous les systèmes ?

Non. C’est optimisé pour l’**arcade** (noms de ROM MAME). Pour SNES, Amiga, etc., utilise **ScreenScraper**.

## Les scrapers modifient-ils mes ROMs ?

Non. Ils téléchargent des **médias** et mettent à jour le **XML**. La ROM n’est pas réécrite (sauf si tu utilises « Supprimer ce jeu »).

## Où sont stockés mon login / mot de passe membre SS ?

En local dans `screenscraper_config.json` (à côté de l’appli), **jamais** envoyé sur GitHub. Les identifiants *développeur* du logiciel sont intégrés dans le code (obfusqués).

## Puis-je travailler hors ligne ?

Oui pour l’édition manuelle. Les boutons ScreenScraper / Arcade DB nécessitent Internet.

## Ça marche avec Batocera / Recalbox ?

Le format `gamelist.xml` EmulationStation est le même principe. L’outil est validé surtout avec **RetroBat** sous Windows ; sur d’autres OS, lance `python app.py` en pointant le XML.

## Le port 5050 est déjà pris ?

Ferme une autre instance de l’éditeur, ou change `port=5050` à la fin de `app.py`.

## Comment revenir en arrière après une erreur ?

Utilise un **`gamelist.xml.bak`** (Outils → Sauvegarder, ou case à cocher avant purge / suppression). Restaure en renommant le `.bak`.
