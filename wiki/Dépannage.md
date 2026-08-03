# Dépannage

## `ModuleNotFoundError: No module named 'flask'`

Les dépendances ne sont pas installées.

```bash
python -m pip install -r requirements.txt
```

ou :

```bash
python -m pip install flask lxml requests
```

---

## « Une tentative d’accès à un socket de manière interdite… »

Souvent lié au port **5000** réservé sous Windows.  
Ce projet utilise **5050**. Si le message apparaît encore :

1. Ferme les autres instances de l’éditeur  
2. Vérifie qu’aucun antivirus ne bloque Python  
3. En dernier recours, change le port à la fin de `app.py` (`port=5050`)

---

## Le navigateur ne s’ouvre pas / page blanche

1. Ouvre manuellement : [http://127.0.0.1:5050](http://127.0.0.1:5050)  
2. Vérifie que la fenêtre noire (`Lancer.bat`) est toujours ouverte  
3. Regarde s’il y a un message d’erreur dans cette fenêtre  

---

## Fichier `gamelist.xml` introuvable

- Vérifie le chemin (glisser-déposer évite les fautes de frappe)  
- Enlève les guillemets en trop si tu as collé le chemin à la main  
- Le fichier doit exister **avant** le lancement  

---

## Les images / vidéos ne s’affichent pas dans RetroBat après édition

1. Redémarre EmulationStation / RetroBat (ou « Update Gamelists »)  
2. Vérifie que les fichiers sont bien dans `images/` ou `videos/` à côté du XML  
3. Ouvre le `gamelist.xml` : le chemin doit ressembler à `./images/monjeu.png`  

---

## Suppression de jeu : certains fichiers restent

Permissions disque, fichier ouvert ailleurs, ou chemin hors du dossier XML (volontairement refusé par sécurité).  
Les fichiers refusés sont listés dans la réponse de l’outil ; supprime-les à la main si besoin.

---

## `Lancer.bat` affiche des erreurs bizarres (`'cho' n’est pas…`)

Ancien problème de fins de ligne (fichier modifié avec un éditeur qui casse le format Windows).  
Re-télécharge `Lancer.bat` depuis le dépôt GitHub.

---

## Toujours bloqué ?

1. Note le **message d’erreur exact** affiché dans le terminal  
2. Ouvre une [issue](https://github.com/Kraran/gamelist-media-editor/issues) sur GitHub avec :  
   - système (Windows 10/11, etc.)  
   - version de Python (`python --version`)  
   - message complet  
