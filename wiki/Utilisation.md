# Utilisation

Une fois le serveur démarré, ouvre [http://127.0.0.1:5050](http://127.0.0.1:5050) dans ton navigateur.

## Interface

- **À gauche** : liste des jeux (ordre alphabétique) + barre de recherche  
- **À droite** : fiche du jeu sélectionné (médias + métadonnées)

Clique sur un jeu dans la liste pour l’éditer.

---

## Médias (glisser-déposer)

Zones disponibles pour chaque jeu :

| Zone | Balise XML | Dossier cible |
|------|------------|---------------|
| Image (capture) | `<image>` | `images/` |
| Vidéo | `<video>` | `videos/` |
| Marquee | `<marquee>` | `images/` |
| Manuel | `<manual>` | `manuals/` |
| Box back (dos de boîte) | `<boxback>` | `images/` |

### Depuis le disque

1. Ouvre l’Explorateur de fichiers  
2. Glisse un fichier (PNG, JPG, MP4, PDF…) sur la zone voulue  
3. Le fichier est copié et le XML est mis à jour tout de suite

### Depuis le web

1. Ouvre une image (ou une page) dans un onglet du navigateur  
2. Glisse l’image vers la zone de l’éditeur  
3. L’outil télécharge le fichier et l’enregistre localement

Tu peux aussi coller une **URL** si l’interface le propose pour ce champ.

---

## Nom et description

- **Name** : renomme le jeu (la liste se reclasse automatiquement par ordre alphabétique)
- **Desc** : grand champ texte pour la description (`<desc>`)

Pense à **enregistrer** (bouton Enregistrer / Ctrl+S selon l’interface) après modification du texte.

---

## Métadonnées

Champs modifiables en bas de la fiche :

| Champ | Détail |
|-------|--------|
| **rating** | Note entre `0` et `1` (ex. `0.85`) |
| **releasedate** | Date de sortie (format EmulationStation, ex. `19901225T000000`) |
| **developer** | Développeur |
| **publisher** | Éditeur |
| **family** | Famille / série |
| **players** | Nombre de joueurs (ex. `1-2`) |
| **lang** | Code langue sur 2 lettres (`fr`, `en`, `de`…) + `eu` (Europe) et `wr` (World). Un **drapeau** s’affiche à côté. |
| **genre** | Liste déroulante **hiérarchique** : genre principal, puis sous-genre filtré |

---

## Actions globales / dangereuses

### Purger toutes les balises `<region>`

Bouton en bas de page. **Demande confirmation.**  
Supprime toutes les lignes `<region>...</region>` du fichier XML entier (utile si le scraper a rempli des régions inutiles).

### Supprimer un jeu complètement

Bouton à côté de la purge, **sur le jeu sélectionné**.  
Après confirmation forte, l’outil :

1. supprime la **ROM** sur le disque ;  
2. supprime les **médias** liés (image, vidéo, manuel, etc.) ;  
3. retire l’entrée `<game>` du `gamelist.xml`.

> ⚠️ **Irréversible.** Vérifie bien le jeu avant de confirmer.

---

## Bonnes pratiques

1. Fais une **copie de sauvegarde** de ton dossier système (ou au moins du `gamelist.xml`) avant les suppressions en masse.  
2. Garde le terminal ouvert tant que tu édites.  
3. Après de grosses modifications, relance EmulationStation / RetroBat pour rafraîchir la liste.  
4. Les chemins dans le XML restent **relatifs** (`./images/...`) : compatible RetroBat.
