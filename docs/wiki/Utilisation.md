# Utilisation

Version documentée : **1.2.0**

## Démarrage

1. Lance **`GamelistMediaEditor.exe`** (ou `Lancer.bat` / `python app.py`)
2. Le navigateur s’ouvre sur [http://127.0.0.1:5050](http://127.0.0.1:5050)
3. Si aucun gamelist n’est chargé, l’écran invite à ouvrir un fichier et le dialogue **📂 Gamelist…** peut s’ouvrir tout seul

### Ouvrir un gamelist.xml

- Bouton **📂 Gamelist…** dans l’en-tête
- Explorateur de dossiers intégré (dossiers, fichiers `.xml`, lecteur Windows, dossier parent)
- Liste des **fichiers récents**
- Double-clic sur un `gamelist.xml` pour l’ouvrir
- Ou colle le chemin complet dans le champ texte

Tu peux **changer de système** (autre `gamelist.xml`) à tout moment sans redémarrer l’application.

## Interface

| Zone | Rôle |
|------|------|
| En-tête | Logo / **À propos**, nom du système, compteur de jeux, Gamelist…, Outils, Recharger, Supprimer le jeu, **⏻ Quitter** |
| Liste gauche | Recherche, filtres « médias manquants », liste alphabétique |
| Zone centrale | Éditeur du jeu sélectionné : médias + métadonnées |

## Médias (glisser-déposer)

Pour chaque champ (**image**, **vidéo**, **marquee**, **manuel**, **boxback**) :

- glisse un fichier local, **ou**
- glisse une URL image/vidéo depuis le navigateur

Les fichiers sont copiés sous `images/`, `videos/` ou `manuals/` avec un nom basé sur la ROM.

## Métadonnées

- **Nom** : champ + bouton Enregistrer
- **Description** : zone de texte
- **Genre** : liste principale + sous-genre
- **Note** (0–1), date de sortie, développeur, éditeur, famille, joueurs, langue (code + drapeau)

Raccourci **Ctrl+S** pour enregistrer les métadonnées courantes.

## Filtres « médias manquants »

Pastilles sous la recherche : Tous / sans image / sans vidéo / etc.  
Le chiffre indique combien de jeux matchent le filtre.

## Outils (⚙)

- **Langue** de l’interface (13 langues) → Appliquer
- Identifiants **ScreenScraper** (boost membre optionnel)
- Sauvegarde manuelle **`.bak`**
- Purge de toutes les balises `<region>`

## Raccourcis clavier

| Touche | Action |
|--------|--------|
| ↑ / ↓ | Naviguer dans la liste |
| Page Up / Down | Sauter dans la liste |
| Home / End | Premier / dernier jeu |
| Ctrl+F | Focus recherche |
| Ctrl+S | Enregistrer métadonnées |

## Quitter

Bouton **⏻ Quitter** (rouge) : arrête le serveur local. Tu peux ensuite fermer l’onglet du navigateur.

**Gamelist Media Editor** · v1.2.0
