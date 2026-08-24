# FAQ

Version documentée : **1.2.0**

### Faut-il Python ?

Non si tu utilises **`GamelistMediaEditor.exe`** (release 1.2.0).  
Oui seulement pour lancer depuis les sources (`pip install -r requirements.txt`).

### Dois-je indiquer le gamelist au démarrage ?

Non. L’app démarre vide : ouvre un fichier via **📂 Gamelist…**.  
Tu peux aussi glisser un `gamelist.xml` sur l’exe, ou passer le chemin en argument.

### Est-ce que ça vérifie les ROM avec Batocera / RetroBat ?

Non. L’outil édite le **`gamelist.xml` et les médias** ; il ne valide pas la compatibilité des ROM avec un core d’émulateur.

### Puis-je ajouter des vidéos ?

Oui : glisser-déposer un fichier vidéo (ou une URL) dans la zone **Vidéo**, ou via le scrape ScreenScraper / Arcade DB.

### Où sont les identifiants ScreenScraper ?

Les clés **développeur** (application) sont intégrées.  
Ton login **membre** (boost) se configure dans **Outils** et est stocké localement dans `screenscraper_config.json` à côté de l’exe.

### L’app est-elle multilingue ?

Oui, **13 langues**. **Outils → Langue → Appliquer**.

### Les données partent-elles sur Internet ?

Seulement si tu lances un **scrape** (ScreenScraper ou Arcade Database). Sinon, tout reste sur ta machine (`127.0.0.1`).

**Gamelist Media Editor** · v1.2.0
