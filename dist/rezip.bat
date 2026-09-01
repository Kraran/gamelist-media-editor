@echo off
chcp 65001 >nul
setlocal

rem Chemin complet vers 7z.exe
set "SEVENZIP=C:\Program Files\7-Zip\7z.exe"

rem Dossier temporaire unique
set "TMPDIR=%TEMP%\tmp_zip"
if exist "%TMPDIR%" rd /s /q "%TMPDIR%"

rem Boucle sur tous les fichiers .zip
for %%F in (*.zip) do (
    setlocal DisableDelayedExpansion
    echo.
    echo Traitement de "%%F"

    rem Nettoyer et recréer le dossier temporaire
    rd /s /q "%TMPDIR%" >nul 2>&1
    mkdir "%TMPDIR%"

    rem Extraction du contenu avec guillemets
    "%SEVENZIP%" x "%%F" -o"%TMPDIR%" -y >nul

    rem Suppression de l'archive originale
    del "%%F"

    rem Recompression avec compression maximale
    "%SEVENZIP%" a -tzip -mx=9 "%%F" "%TMPDIR%\*" >nul

    rem Nettoyage temporaire
    rd /s /q "%TMPDIR%"

    echo Fichier "%%F" recompressé avec succès
    endlocal
)

echo.
echo Tous les fichiers ont été traités.
pause
