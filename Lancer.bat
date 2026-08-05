@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title Gamelist Media Editor
cd /d "%~dp0"

REM Couleurs console (vert clair sur fond noir)
color 0A

echo.
echo  ============================================================
echo            Gamelist Media Editor
echo            Editeur de medias pour gamelist.xml
echo  ============================================================
echo.

REM --- Verification de Python ---
where python >nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo.
    echo  Solutions :
    echo    1. Installe Python depuis https://www.python.org/downloads/
    echo    2. Coche "Add python.exe to PATH" pendant l'installation
    echo    3. Redemarre ce script apres installation
    echo.
    pause
    exit /b 1
)

REM --- Chemin du gamelist.xml (argument ou saisie) ---
if not "%~1"=="" (
    set "XML_PATH=%~1"
    goto :check_file
)

echo  Indique le chemin complet vers ton fichier gamelist.xml
echo  Astuce : tu peux glisser-deposer le fichier dans cette fenetre
echo           puis appuyer sur Entree.
echo.
set /p "XML_PATH=  Chemin du gamelist.xml : "

if "%XML_PATH%"=="" (
    color 0E
    echo.
    echo  [ANNULE] Aucun fichier indique.
    echo.
    pause
    exit /b 1
)

REM Enlever les guillemets eventuels (glisser-deposer)
set "XML_PATH=%XML_PATH:"=%"

:check_file
if not exist "%XML_PATH%" (
    color 0C
    echo.
    echo  [ERREUR] Fichier introuvable :
    echo    %XML_PATH%
    echo.
    echo  Verifie le chemin et reessaie.
    echo.
    pause
    exit /b 1
)

echo.
echo  ------------------------------------------------------------
echo   XML      : %XML_PATH%
echo   Dossier  : %~dp0
echo   URL      : http://127.0.0.1:5050
echo  ------------------------------------------------------------
echo.
echo  Demarrage du serveur...
echo  Le navigateur va s'ouvrir automatiquement.
echo  Pour arreter : ferme cette fenetre ou appuie sur Ctrl+C
echo.

REM Ouvre le navigateur apres 2 secondes
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5050"

python app.py "%XML_PATH%"
set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
    color 0A
    echo  Serveur arrete proprement. Fermeture...
    timeout /t 1 /nobreak >nul
    endlocal
    exit /b 0
)

color 0C
echo  [ERREUR] Le programme s'est arrete avec le code %EXITCODE%.
echo  Verifie que les paquets Python sont installes :
echo    python -m pip install flask lxml requests
echo.
pause
endlocal
