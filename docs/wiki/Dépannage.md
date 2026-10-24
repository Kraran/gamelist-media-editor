# Dépannage

Version documentée : **1.4.0**

### « ModuleNotFoundError: flask » ou « Pillow »

Sources sans dépendances :

```bat
python -m pip install -r requirements.txt
```

Ou utilise l’exe de la release.

### Port 5050 / socket refusé

Une instance tourne déjà : **Quitter** ou Task Manager. Une seule à la fois.

### Aucun jeu dans la liste

Ouvre un `gamelist.xml` valide via **Gamelist…**, vérifie les balises `<game>`, clique **Recharger**.

### Scrape ScreenScraper introuvable / 404 / quota

- Dossier système (`roms\snes`, `roms\mame`…)
- Autre candidat
- Boost membre dans **Réglages › ScreenScraper**
- API parfois saturée : réessaie plus tard

### Arcade DB : pas de PCB / Decal / système arcade

- Le romset doit être un nom MAME (`mslug`, pas `Metal Slug.zip` fantaisiste)
- PCB / Decal viennent de `query_mame_media` ; s’ils n’existent pas chez ADB, le champ reste vide
- Driver = nom du jeu → `arcadesystemname` volontairement vide

### Steam : trailer en erreur

Certaines bandes-annonces n’ont plus de MP4 CDN. L’app passe à 480p ou signale l’absence. Réessaie un autre AppID.

### Images en `.php`

Corrigé en 1.3.0 (signature du fichier). Re-scrape le média pour remplacer l’ancien fichier.

### Interface pas traduite / pas à jour

`static/locales/` doit contenir les 13 JSON. **Réglages › Général › Langue**, puis **Ctrl+F5**.

### L’exe ne démarre pas

Autorise-le dans l’antivirus (PyInstaller). Relance `BUILD_EXE.bat` si tu compiles.

### « Ce jeu a changé dans gamelist.xml »

Le `gamelist.xml` a été modifié par un autre programme pendant que l’app était ouverte. L’action est refusée pour ne pas toucher un autre jeu ; la liste se recharge. Refais l’action.

### Les miniatures de la liste ne s’affichent pas

Elles sont créées au premier affichage dans `cache\thumbs\` à côté de l’exe. Supprimer le dossier `cache` les régénère.

**Gamelist Media Editor** · v1.4.0
