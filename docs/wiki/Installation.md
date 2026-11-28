# Installation

Version documentée : **1.7.5**

## Option A — Exécutable Windows (recommandé)

1. Ouvre la [release v1.7.5](https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.7.5)
2. Télécharge **`GamelistMediaEditor-Windows-v1.7.5.zip`**
3. Décompresse où tu veux
4. Lance **`GamelistMediaEditor.exe`**

**Aucun Python à installer.** L’interface fonctionne hors ligne (polices et icônes intégrées).  
Fenêtre dédiée (mode application) si Edge / Chrome / Brave est installé. Sinon, le navigateur habituel s’ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050).

Au premier lancement : **Gamelist…** pour choisir le XML.

### Mises à jour automatiques

À partir de la prochaine version, l’exe se met à jour tout seul :

- Au démarrage, GME demande à GitHub (sans compte, **au plus une fois par jour**, rien si tu es hors ligne) s’il existe une version plus récente. **Réglages › Général › Mises à jour** désactive cette vérification ; **Actions › Vérifier les mises à jour** la lance quand tu veux.
- Une nouvelle version ouvre une fenêtre avec ses nouveautés : **Mettre à jour maintenant**, **Plus tard** ou **Ignorer cette version**.
- *Mettre à jour maintenant* télécharge le zip de la release (barre de progression, *Arrêter*), vérifie son empreinte **SHA-256** avec le fichier `SHA256SUMS.txt` de la release (absent ou différent : refusé), puis GME se ferme, remplace son `.exe` et redémarre sur le même gamelist. Si la nouvelle version ne démarre pas, l’ancienne est remise en place.
- Seuls les fichiers des releases du dépôt officiel sont téléchargés, en HTTPS. Tes réglages, clés, mots de passe réseau, listes récentes, caches et sauvegardes ne sont pas touchés : seul `GamelistMediaEditor.exe` est remplacé.
- Revenir à la version précédente : ferme GME et recopie `.gme-update\previous\GamelistMediaEditor.exe` à la place de `GamelistMediaEditor.exe`. Le journal de la mise à jour est dans `.gme-update\update.log`.
- Si l’exe est dans un dossier protégé (par exemple `C:\Program Files`), la mise à jour est refusée : place GME dans un dossier à toi.

### Compiler l’exe (développeurs)

Windows + Python 3.9+ :

```bat
BUILD_EXE.bat
```

Sortie : `dist\GamelistMediaEditor.exe` (dossier ignoré par Git — normal).  
La CI GitHub construit aussi l’exe à chaque push et le joint au run (14 jours).

Publier une version : pousser un tag `vX.Y.Z` (identique à `gme/version.py`). Le workflow *Release* construit l’exe, le zippe avec `tools/release_assets.py` et joint à la release **`GamelistMediaEditor-Windows-vX.Y.Z.zip` et `SHA256SUMS.txt`** (la mise à jour automatique refuse une release sans ce fichier).

## Option B — Source Python

1. Télécharge le **source** de la [release](https://github.com/Kraran/gamelist-media-editor/releases/latest) ou clone le dépôt
2. Installe **Python 3.9+** ([python.org](https://www.python.org/downloads/), *Add to PATH*)
3. Dans le dossier de l’app :

```bat
python -m pip install -r requirements.txt
```

Dépendances : Flask, lxml, requests, Pillow, Send2Trash.

4. `Lancer.bat` ou `python app.py`  
   Optionnel : `python app.py "C:\chemin\vers\gamelist.xml"`  
   `python app.py --no-browser` démarre le serveur sans ouvrir de fenêtre.

5. [http://127.0.0.1:5050](http://127.0.0.1:5050)

## Structure des médias

```
roms\snes\
  gamelist.xml
  images\
  videos\
  manuals\
  *.sfc / *.zip …
```

Les chemins écrits dans le XML sont relatifs (`./images/…`, `./videos/…`).  
Les fichiers **Pad2Key** (`.keys`) vont **à côté de la ROM**, pas dans `images/`.

## Fichiers créés à côté de l’exe / de `app.py`

| Fichier / dossier | Rôle |
|---|---|
| `screenscraper_config.json` | Compte membre ScreenScraper, région, types de médias |
| `recent_gamelists.json` | Les derniers gamelists ouverts (fenêtre Gamelist…) |
| `ui_settings.json` | Thème, langue, sources de scrape et médias requis par système |
| `cache\thumbs\` | Miniatures de la liste (recréées à la demande) |
| `cache\remote\` | Images proposées par un scrape, gardées un jour (pas de second téléchargement) |
| `cache\ss-api\` | Réponses ScreenScraper gardées (30 jours par défaut) : rescraper ne consomme pas de quota |
| `state\batches\` | Lots de scrape à reprendre (*Dernier lot*) |
| `update_state.json` | Dernière vérification des mises à jour et version ignorée |
| `.gme-update\` | Mise à jour automatique : nouvelle version téléchargée, version précédente (`previous\`), journal `update.log` |

À côté de chaque gamelist, `.gme-backups\` garde les sauvegardes datées et les originaux des images modifiées.

Le dossier `cache` peut être supprimé sans risque.

## Mise à jour vers 1.7.5

- Remplace les fichiers de l’app (garde `screenscraper_config.json`, `ui_settings.json` et `recent_gamelists.json`)
- Aucune migration du `gamelist.xml` ; aucune nouvelle dépendance depuis la 1.5.0
- Les types de médias ScreenScraper gardent les valeurs de la 1.6.0 : **wheel** et **titleshot** restent désactivés tant que tu ne les coches pas dans **Réglages › Médias ScreenScraper**

Depuis une version antérieure à la 1.5.0 :
- En source : `python -m pip install -r requirements.txt` (dépendance **Send2Trash**, pour la Corbeille)
- Au premier lancement, la langue et les sources de scrape choisies avant sont reprises dans `ui_settings.json`
- Le compteur de la liste compte les **médias requis** du système (`3/4`) : choisis-les dans **Réglages › Médias requis**

Depuis la 1.3.0 : les **Outils** sont devenus **Réglages** (roue dentée) et **Actions** (⋯), voir [Utilisation](Utilisation).

**Gamelist Media Editor** · v1.7.5
