# FAQ

## C’est accessible à un débutant en informatique ?

Oui. Sous Windows : double-clic sur `Lancer.bat`, tu indiques (ou glisses) ton `gamelist.xml`, le navigateur s’ouvre. Ensuite c’est du glisser-déposer et des champs à remplir. Pas besoin de savoir coder ni d’éditer le XML à la main.

## Est-ce que je peux ajouter des vidéos ?

Oui. Zone **Vidéo** sur la fiche du jeu : glisse un fichier (MP4, etc.) ou une source web. Le fichier est placé dans `videos/` et la balise `<video>` est mise à jour.

## Mes données partent-elles sur Internet ?

Non. L’application tourne en local (`127.0.0.1`). Seul cas de connexion sortante : si **tu** glisses une image depuis une page web, l’outil la télécharge une fois pour l’enregistrer sur ton disque.

## Où sont enregistrés les fichiers médias ?

Dans les dossiers **à côté** du `gamelist.xml` que tu as indiqué au démarrage (`images/`, `videos/`, `manuals/`).

## Je peux l’utiliser avec RetroBat / Batocera / Recalbox ?

Oui pour tout système qui utilise un `gamelist.xml` au format EmulationStation. Testé surtout dans l’esprit **RetroBat** (chemins relatifs, dossiers images/videos/manuals).

## Comment revenir en arrière après une suppression de jeu ?

La suppression est définitive sur le disque. Garde une sauvegarde (copie du dossier système ou du XML + médias) avant d’utiliser cette fonction.

## Le port 5000 est bloqué / erreur de socket sous Windows

L’appli utilise le port **5050** par défaut pour éviter ce problème fréquent sur Windows.

## Python n’est pas reconnu

Réinstalle Python en cochant **Add python.exe to PATH**, ferme toutes les fenêtres de terminal, puis relance `Lancer.bat`.

## Puis-je modifier le code / le redistribuer ?

Oui, licence **MIT**. Crédite le projet si tu le repartages.
