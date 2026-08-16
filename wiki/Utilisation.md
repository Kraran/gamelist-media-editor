# Utilisation

Version documentée : **1.1.1**

## Interface

Après le lancement :

1. **Barre du haut** : titre, nombre de jeux, **nom du système** (dossier du gamelist), boutons Recharger / Outils / Quitter  
2. **Liste à gauche** : recherche + filtres « médias manquants »  
3. **Éditeur à droite** : nom, médias, description, métadonnées, boutons **ScreenScraper** et **Arcade DB**

Sélectionne un jeu dans la liste pour l’éditer.

## Filtres « médias manquants »

Au-dessus de la liste : **Tous**, **Sans image**, **Sans vidéo**, **Sans marquee**, **Sans manuel**, **Sans boxback**, **Un média manquant**.

La pastille indique le **nombre** de jeux concernés (en tenant compte de la recherche).

## Médias (glisser-déposer)

Zones : **Image**, **Vidéo**, **Marquee**, **Manuel (PDF)**, **Box Back**.

- Fichier depuis l’explorateur → glisser sur la zone  
- Depuis le web → glisser une image ou fournir une URL `http(s)`

L’outil copie le fichier dans le bon dossier, met à jour le XML, et **supprime l’ancien fichier** si le chemin change (ex. `.png` → `.jpg`).

Limite : **50 Mo**.

Le bouton **✕** retire la balise du XML **sans** supprimer le fichier sur le disque.

## Scrapers (1.1.0)

Voir la page dédiée **[Scrapers](Scrapers)**.

En résumé :

1. Sélectionne un jeu  
2. Clique **ScreenScraper** (multi-système) ou **Arcade DB** (arcade / MAME)  
3. Attends le spinner  
4. Coche les champs à importer  
5. **Appliquer la sélection**

## Nom et description

- Champ **name** + Enregistrer (ou Entrée)  
- Zone **desc** + Enregistrer (ou **Ctrl+S**)

## Métadonnées

| Champ | Notes |
|-------|--------|
| `rating` | Entre 0 et 1 |
| `releasedate` | Date de sortie |
| `developer` / `publisher` | Texte libre |
| `family` / `players` | Texte libre |
| `lang` | Code 2 lettres + `eu`, `wr` — drapeau à côté |
| `genre` | Liste guidée (genre + sous-genre) |

## Panneau Outils

Bouton **Outils** :

1. **Sauvegarder le gamelist.xml** → `gamelist.xml.bak`  
2. **Supprimer toutes les balises `<region>`** → confirmation + case `.bak` optionnelle  
3. **ScreenScraper — compte membre** (optionnel) : ssid + mot de passe pour le **boost** de quotas  

Les identifiants **développeur** (logiciel) sont déjà intégrés : tu n’as rien à saisir pour scraper.

## Supprimer un jeu

Bouton **Supprimer ce jeu** :

- confirmation  
- case **sauvegarde .bak** (recommandée)  
- efface ROM + médias liés + entrée XML  

Irréversible (sauf restauration du `.bak`).

## Recharger la liste

Bouton **Recharger** : relit le XML depuis le disque sans redémarrer le serveur.

## Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| **↑** / **↓** | Jeu précédent / suivant |
| **PageUp** / **PageDown** | Saut ~10 jeux |
| **Home** / **End** | Premier / dernier jeu visible |
| **Ctrl+S** | Enregistrer |
| **Ctrl+F** ou **/** | Focus recherche |
| **Échap** | Fermer panneau / annuler |

## Quitter

Bouton **Quitter** → confirmation → arrêt du serveur (la console se ferme avec `Lancer.bat`).

## Changer de langue (1.1.1)

1. Ouvre **Outils**
2. Section **Langue de l’interface**
3. Choisis la langue
4. Clique **Appliquer la langue**

Le choix est mémorisé dans le navigateur.

