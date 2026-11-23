# ES-DE

GME sait ouvrir les gamelists d’**ES-DE** (EmulationStation Desktop Edition), en plus de RetroBat, Batocera et Recalbox. ES-DE range ses fichiers autrement : GME le détecte tout seul et s’adapte, sans rien changer pour les autres.

## Comment ES-DE range ses fichiers

| Quoi | Où (installation classique) | Où (Windows portable) |
| --- | --- | --- |
| Réglages | `~/ES-DE/settings/es_settings.xml` | `ES-DE\ES-DE\settings\es_settings.xml` |
| Gamelists | `~/ES-DE/gamelists/<système>/gamelist.xml` | `ES-DE\ES-DE\gamelists\<système>\gamelist.xml` |
| Médias | `~/ES-DE/downloaded_media/<système>/<type>/` | `ES-DE\ES-DE\downloaded_media\<système>\<type>\` |
| ROMs | `~/ROMs/<système>/` | `ES-DE\ROMs\<système>\` |

- Le gamelist ne contient **aucune balise média** : ES-DE trouve un média par son **nom**, celui de la ROM sans extension, sous-dossiers compris. Pour `./Multidisk/Last Ninja 2/Last Ninja 2.m3u`, la vidéo est `downloaded_media/c64/videos/Multidisk/Last Ninja 2/Last Ninja 2.mp4`.
- Les réglages **ROMDirectory** (dossier des ROMs) et **MediaDirectory** (*Game media directory*) de `es_settings.xml` sont lus, avec `~` et `%ESPATH%`. Un chemin de système changé dans `custom_systems/es_systems.xml` est suivi aussi.
- Version portable : `portable.txt` à côté de `ES-DE.exe` place les données dans `ES-DE\ES-DE` ; `~` désigne alors le dossier `ES-DE` lui-même.

## Ouvrir ES-DE dans GME

- **Un système** : *Gamelist…* puis `ES-DE/gamelists/<système>/gamelist.xml`. Un badge **ES-DE** s’affiche à côté du nom du système (survole-le : dossier des médias et des ROMs).
- **Tous les systèmes** : dans *Gamelist…*, va dans le dossier `ES-DE` (ou le dossier portable, ou `settings`) : un bandeau *Installation ES-DE détectée* propose **Vue d’ensemble ES-DE**. *Vue multi-systèmes…* sur ce dossier fait pareil. Le dossier `CLEANUP` d’ES-DE (sauvegardes du nettoyage) est ignoré.
- Ouvrir `es_settings.xml` directement indique où sont les gamelists.

## Correspondance des médias

| Dossier ES-DE | Média dans GME | ScreenScraper |
| --- | --- | --- |
| `screenshots` | Image (capture) | `ss` |
| `titlescreens` | Écran titre | `sstitle` |
| `covers` | Miniature (boîte 2D) | `box-2D` |
| `3dboxes` | Boxart (boîte 3D) | `box-3D` |
| `backcovers` | Box back | `box-2D-back` |
| `marquees` | Marquee (logo) | `wheel-hd`, `wheel`, `marquee` |
| `physicalmedia` | Support | `support-2D` |
| `fanart` | Fanart | `fanart` |
| `miximages` | Mix | `mixrbv2` |
| `videos` | Vidéo | `video-normalized`, `video` |
| `manuals` | Manuel (PDF) | `manuel` |

ES-DE n’a pas de dossier pour **wheel, maps, bezel, musique** ni **Pad2Key** : ces médias ne sont pas proposés (éditeur, scrape, scrape par lot, statistiques ; *–* dans la vue d’ensemble). Le dossier `custom` d’ES-DE n’est pas touché.

Extensions : `.png`, `.jpg`, `.webp` pour les images, `.mp4`, `.mkv`, `.avi`, `.wmv`, `.mov`, `.webm`, `.m4v` pour les vidéos, `.pdf` pour les manuels. Si deux fichiers existent pour un même média, GME montre le `.png` d’abord, puis le `.jpg`.

## Ce qui change par rapport à RetroBat

- **Ajouter / remplacer** un média (fichier, glisser-déposer, URL, scrape, scrape par lot, actions sur plusieurs systèmes, sources de secours) écrit le fichier **au nom attendu par ES-DE** dans `downloaded_media`. Si le nouveau fichier change de format (`.jpg` → `.png`), l’ancien part à la corbeille, sinon ES-DE pourrait continuer à l’afficher.
- **Supprimer** un média met **son fichier à la corbeille** : sans balise, il n’y a rien d’autre à retirer. *Modifier en masse › Médias* et *Images unies* font de même.
- L’**éditeur d’images** remplace toujours le média (une copie *-edit* serait invisible pour ES-DE) ; *Annuler* le remet comme avant.
- Le `gamelist.xml` reste celui d’ES-DE : **aucune balise média n’est écrite**, les balises propres à ES-DE (`altemulator`, `sortname`, `playcount`, `<folder>`…) et les inconnues sont gardées. Des balises média venues d’un autre EmulationStation (ignorées par ES-DE) sont gardées telles quelles.
- *Vérifier les ROMs* et la suppression d’un jeu cherchent les ROMs dans le dossier ROMs d’ES-DE. *Vérifier les médias* parcourt `downloaded_media/<système>` ; le média d’une ROM présente mais absente du gamelist (ES-DE l’affiche quand même) n’est pas compté comme inutilisé.
- Les noms de systèmes d’ES-DE sont reconnus pour ScreenScraper (`genesis`, `sg-1000`, `tg-cd`, `megadrivejp`…).

## Limites

- Renommer une ROM ne renomme pas ses médias.
- Les systèmes sans `gamelist.xml` n’apparaissent pas dans la vue d’ensemble ES-DE, et *Créer un gamelist* n’est pas proposé : ES-DE crée lui-même ses gamelists. *Vérifier les ROMs › ajouter les ROMs absentes* complète un gamelist existant.
- Un chemin de ROM absolu hors du dossier ROMs est rangé par son seul nom de fichier.
- Les `<folder>` d’ES-DE sont gardés mais ne sont pas modifiables dans GME.
