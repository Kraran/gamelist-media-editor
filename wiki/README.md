# Publier ce contenu sur le Wiki GitHub

L’API connectée ne peut pas créer les pages du Wiki automatiquement.
Procédure en **2 minutes** :

1. Va sur https://github.com/Kraran/gamelist-media-editor/wiki
2. Si demandé, clique **Create the first page** (cela active le Wiki)
3. Pour chaque fichier de ce dossier `wiki/` (sauf ce README) :
   - **New page**
   - **Title** = nom du fichier **sans** `.md` (ex. `Home`, `Installation`, `Utilisation`, `Fonctionnalités`, `FAQ`, `Dépannage`)
   - Colle tout le contenu Markdown de la page
   - **Save page**
4. Pages spéciales GitHub Wiki :
   - titre `_Sidebar` → menu latéral
   - titre `_Footer` → pied de page

**Ordre conseillé :** Home → Installation → Utilisation → Fonctionnalités → FAQ → Dépannage → `_Sidebar` → `_Footer`.

Les fichiers restent versionnés dans le dépôt (`wiki/`) en secours.
