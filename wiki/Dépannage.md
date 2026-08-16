# Dépannage

## `ModuleNotFoundError: No module named 'flask'`

```bash
python -m pip install -r requirements.txt
```

ou : `python -m pip install flask lxml requests`

---

## « Une tentative d’accès à un socket de manière interdite… »

Souvent le port **5000** sous Windows. Ce projet utilise **5050**. Sinon :

1. Ferme les autres instances  
2. Vérifie l’antivirus  
3. Change le port dans `app.py` en dernier recours  

---

## Page blanche / navigateur ne s’ouvre pas

1. Ouvre [http://127.0.0.1:5050](http://127.0.0.1:5050) à la main  
2. Garde la fenêtre `Lancer.bat` ouverte  
3. Lis l’éventuelle erreur dans la console  

---

## ScreenScraper / Arcade DB : « Aucun jeu trouvé »

- Vérifie que la ROM est bien indiquée dans le XML (`path`)  
- **Arcade DB** : le nom de fichier doit être un romset MAME (`mslug`, pas « Metal Slug »)  
- **ScreenScraper** : hash parfois impossible (format rare) → le fallback nom propose des candidats  
- Vérifie le **dossier système** (badge en haut) : un mauvais mapping peut limiter les résultats SS  

---

## Message quota / threads / « trop de requêtes »

Les APIs limitent le débit. L’outil affiche un toast **orange** et espace déjà les appels.

- Attends 30–60 secondes  
- Pour ScreenScraper : renseigne un **compte membre** dans Outils (boost)  
- Évite de lancer 50 scrapes d’affilée  

---

## « Impossible de contacter le serveur local »

Le process Python est arrêté. Relance `Lancer.bat` / `app.py`.

---

## Médias OK dans l’outil, absents dans RetroBat

1. Redémarre ES / « Update Gamelists »  
2. Vérifie `./images/…` à côté du XML  
3. Contrôle le chemin dans le `gamelist.xml`  

---

## Toujours bloqué ?

1. Note le message exact (terminal + toast)  
2. Ouvre une [issue](https://github.com/Kraran/gamelist-media-editor/issues) avec OS, version Python, version de l’outil (1.1.1)
