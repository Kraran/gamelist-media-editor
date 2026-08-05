@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title Installation - Gamelist Media Editor
cd /d "%~dp0"

echo.
echo  ============================================================
echo    Gamelist Media Editor - Installateur Windows
echo  ============================================================
echo.
echo  Cet assistant va :
echo    - te demander un dossier d'installation
echo    - copier l'application
echo    - installer Python si necessaire (systeme ou portable)
echo    - installer flask, lxml, requests
echo    - creer des raccourcis Bureau et Menu Demarrer
echo.
echo  Une connexion Internet peut etre necessaire
echo  (Python / dependances).
echo.
pause

where powershell >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] PowerShell introuvable.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"
set "EC=%ERRORLEVEL%"

if not "%EC%"=="0" (
    echo.
    echo  [ERREUR] L'installation s'est terminee avec le code %EC%.
    pause
)
endlocal
exit /b %EC%
