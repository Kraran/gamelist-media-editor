# Scrapers (ScreenScraper & Arcade Database)

Nouveauté de la **v1.1.1**.

Les deux scrapers partagent la **même interface** : recherche → éventuelle liste de candidats → cases à cocher par champ → application (téléchargement des médias + mise à jour du XML).

Une **connexion Internet** est requise. L’outil espace les requêtes pour respecter les serveurs distants.

---

## ScreenScraper

Bouton **📡 ScreenScraper** dans l’éditeur du jeu.

### Ce qu’il fait

- Identifie le jeu par **hash de la ROM** (CRC / MD5 / SHA1), y compris le contenu **à l’intérieur d’un `.zip`**  
- Sinon recherche par **nom**, avec liste de **candidats** si plusieurs résultats  
- Propose médias + métadonnées : image, vidéo, marquee, manuel, boxback, name, desc, genre, rating, dates, developer, publisher, players, lang…

### Compte utilisateur

- **Aucun compte obligatoire** pour commencer (identifiants *logiciel* intégrés)  
- **Optionnel** : ton compte **membre** ScreenScraper dans **Outils** → boost de quotas (plus de requêtes / threads)  

### Conseils

- Fonctionne sur la plupart des systèmes RetroBat (SNES, Amiga, PlayStation, etc.)  
- Si le jeu trouvé est faux → choisis un autre candidat dans la liste  
- En cas de message **quota / threads** : attends un peu, ou active le boost membre  

---

## Arcade Database (Arcade Italia)

Bouton **🕹️ Arcade DB** à côté de ScreenScraper.

### Ce qu’il fait

- Recherche par **nom de romset MAME** (ex. `mslug`, `sf2`, `pacman`) = nom du fichier ROM **sans extension**  
- Sur les **clones**, peut reprendre les infos du **parent**  
- Médias adaptés arcade : snapshot, marquee, flyer/box, vidéo shortplay, historique, etc.

### Quand l’utiliser

- Idéal pour **`arcade`**, **`mame`**, **`fbneo`**, et dossiers au nommage MAME  
- Sur une console (SNES, etc.), les résultats seront souvent vides ou peu pertinents — c’est normal  

Aucun compte requis.

---

## Parcours commun

1. Sélectionne un jeu dans la liste  
2. Clique **ScreenScraper** ou **Arcade DB**  
3. Un **spinner** s’affiche pendant l’appel API (peut être lent)  
4. **Cas A** — un seul jeu : fenêtre avec cases à cocher  
5. **Cas B** — plusieurs résultats : choisis le bon, puis les cases  
6. Coche uniquement ce que tu veux importer (champs déjà remplis restent cochés ou non selon le contenu)  
7. **Appliquer la sélection**  

Les médias sont téléchargés dans `images/`, `videos/`, `manuals/` et les balises XML sont mises à jour.

---

## Messages d’erreur fréquents

| Message | Signification |
|---------|----------------|
| Quota / threads / 429 | Limite API atteinte → patiente ou boost SS |
| API fermée / 503 | Service distant en maintenance |
| Aucun jeu trouvé | Hash/nom/romset non reconnu |
| Serveur local injoignable | `Lancer.bat` / `app.py` arrêté |

Voir aussi [Dépannage](Dépannage).

---

## Bonnes pratiques

- Ne pas enchaîner des dizaines de scrapes à la seconde (l’outil bride déjà les appels)  
- Préférer un `.bak` (Outils) avant une grosse session  
- Arcade DB = arcade ; ScreenScraper = le reste (et aussi l’arcade en secours)
