# FAQ

Version documentée : **1.7.5**

### Faut-il Python ?

Non avec **`GamelistMediaEditor.exe`**.  
Oui seulement depuis les sources (`pip install -r requirements.txt`, dont Pillow).

### Dois-je indiquer le gamelist au démarrage ?

Non. **📂 Gamelist…**, ou glisse le XML sur l’exe.

### Est-ce que ça marche avec ES-DE ?

Oui. Ouvre `ES-DE/gamelists/<système>/gamelist.xml` (ou le dossier `ES-DE` pour la vue d’ensemble) : les médias sont lus et écrits dans `downloaded_media`, au nom de la ROM, sans balise dans le gamelist. Détails et correspondance des dossiers : [ES-DE](ES-DE).

### Puis-je modifier directement le gamelist de ma Batocera ou de ma Recalbox ?

Oui, par le réseau : *Gamelist…* › bloc **Réseau** › **Rechercher**, ou tape `\\BATOCERA\share\roms\<système>` dans le chemin. Les sauvegardes restent sur ce PC, et GME peut recharger les listes sur Batocera après l'enregistrement. Détails, mot de passe et précautions : [Réseau](Réseau).

### Est-ce que ça vérifie les ROM Batocera / RetroBat ?

Non. L’outil édite le XML et les médias, il ne teste pas les cores.

### Puis-je ajouter des vidéos ?

Oui : glisser-déposer, scrape ScreenScraper / Arcade DB, ou bande-annonce **Steam** (bouton Scraper, menu ▾).

### Qu’est-ce que le « Support » ?

La balise RetroBat `<cartridge>` (PCB arcade côté Arcade DB, `support-2D` côté ScreenScraper).

### Pourquoi un boxback n’est pas téléchargé ?

ScreenScraper envoie parfois une image **entièrement verte** à la place du dos de boîte. L’app l’ignore volontairement.

### Où sont les identifiants ScreenScraper ?

Clés développeur **intégrées**. Login membre (boost) + types d’images : **Réglages › ScreenScraper**, fichier `screenscraper_config.json` à côté de l’exe.

### Les données partent-elles sur Internet ?

Seulement pendant un scrape (SS, Arcade DB ou Steam). Sinon tout reste en local.

### Pourquoi Edge / Chrome et pas Firefox en fenêtre appli ?

Le mode `--app=` (sans barre d’adresse) est une option Chromium. Firefox s’ouvre en navigateur normal.

### Le scrape va-t-il écraser mes médias ?

Non, sauf si tu le demandes. La fenêtre de comparaison ne coche que ce qui manque ; un média existant n’est remplacé que si tu coches sa carte (badge **Remplace**).

### Pourquoi Arcade Database s’ouvre au lieu de ScreenScraper ?

Le bouton Scraper choisit la source selon le dossier du système (arcade → Arcade Database). Le menu ▾ force une autre source, retenue pour ce système.

### Comment aller vite sur toute une liste ?

Filtre sur un média manquant, puis `N` (jeu incomplet suivant), `S` (scraper), Entrée (appliquer), et ainsi de suite.

### Comment mettre GME à jour ?

L’exe le propose tout seul au démarrage (une fois par jour au plus) ou via **Actions › Vérifier les mises à jour** : *Mettre à jour maintenant* télécharge la release officielle, vérifie son empreinte SHA-256, remplace l’exe et redémarre. Tes réglages et sauvegardes restent. L’ancienne version est gardée dans `.gme-update\previous`. Voir [Installation](Installation#mises-à-jour-automatiques).

### Puis-je annuler plusieurs modifications ?

Oui : **↶ Annuler** / **↷ Rétablir** en haut (ou `Ctrl+Z` / `Ctrl+Y` hors des champs de saisie), et le bouton **Historique** pour revenir directement à une étape. 30 étapes par gamelist pendant la session ; le gamelist.xml revient octet pour octet. Les fichiers mis à la Corbeille se récupèrent depuis la Corbeille. Pour revenir plus loin ou après avoir relancé GME : *Actions › Sauvegardes*.

**Gamelist Media Editor** · v1.7.5
