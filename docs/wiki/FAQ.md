# FAQ

Version documentée : **1.3.0**

### Faut-il Python ?

Non avec **`GamelistMediaEditor.exe`**.  
Oui seulement depuis les sources (`pip install -r requirements.txt`, dont Pillow).

### Dois-je indiquer le gamelist au démarrage ?

Non. **📂 Gamelist…**, ou glisse le XML sur l’exe.

### Est-ce que ça vérifie les ROM Batocera / RetroBat ?

Non. L’outil édite le XML et les médias, il ne teste pas les cores.

### Puis-je ajouter des vidéos ?

Oui : glisser-déposer, scrape ScreenScraper / Arcade DB, ou bande-annonce **Steam**.

### Qu’est-ce que le « Support » ?

La balise RetroBat `<cartridge>` (PCB arcade côté Arcade DB, `support-2D` côté ScreenScraper).

### Pourquoi un boxback n’est pas téléchargé ?

ScreenScraper envoie parfois une image **entièrement verte** à la place du dos de boîte. L’app l’ignore volontairement.

### Où sont les identifiants ScreenScraper ?

Clés développeur **intégrées**. Login membre (boost) + types d’images : **Outils**, fichier `screenscraper_config.json` à côté de l’exe.

### Les données partent-elles sur Internet ?

Seulement pendant un scrape (SS, Arcade DB ou Steam). Sinon tout reste en local.

### Pourquoi Edge / Chrome et pas Firefox en fenêtre appli ?

Le mode `--app=` (sans barre d’adresse) est une option Chromium. Firefox s’ouvre en navigateur normal.

**Gamelist Media Editor** · v1.3.0
