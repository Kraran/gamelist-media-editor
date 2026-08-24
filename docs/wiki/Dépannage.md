# Dépannage

Version documentée : **1.2.0**

### « ModuleNotFoundError: flask »

Tu lances les **sources** sans dépendances :

```bat
python -m pip install -r requirements.txt
```

Ou utilise l’**exe** de la release 1.2.0 (pas besoin de Python).

### Le port 5050 est déjà utilisé / accès socket refusé

Ferme une ancienne instance (bouton **Quitter** ou Task Manager), ou redémarre le PC. Une seule instance à la fois.

### Aucun jeu dans la liste

1. Ouvre un `gamelist.xml` valide via **📂 Gamelist…**
2. Vérifie que le fichier contient bien des balises `<game>`
3. Clique **Recharger**

### Scrape ScreenScraper « jeu non trouvé » / 404

- Vérifie le dossier système (ex. `amiga500` sous `roms\`)
- Essaie un autre candidat dans la liste
- Vérifie le quota / login membre dans **Outils**
- L’API SS est parfois lente ou saturée : réessaie plus tard

### L’interface reste en anglais / français partiel

Vérifie que le dossier **`static/locales/`** est présent (13 fichiers `.json`).  
**Outils → Langue → Appliquer**, puis Ctrl+F5.

### L’exe ne démarre pas

- Antivirus : autorise l’exe (PyInstaller)
- Lance depuis une console pour voir les messages d’erreur
- Rebuild avec `BUILD_EXE.bat` si tu as modifié le code

### Après une mise à jour, ancien comportement

Vide le cache navigateur (**Ctrl+F5**) ou ouvre une fenêtre privée.

**Gamelist Media Editor** · v1.2.0
