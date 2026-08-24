@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Gamelist Media Editor
echo.
echo  Gamelist Media Editor
echo  --------------------
echo  Demarrage du serveur local (http://127.0.0.1:5050)
echo  Le navigateur va s'ouvrir automatiquement.
echo  Ouvre un gamelist.xml via le bouton "Gamelist..." si besoin.
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python introuvable. Installe Python 3 ou utilise GamelistMediaEditor.exe
  pause
  exit /b 1
)

if "%~1"=="" (
  python app.py
) else (
  python app.py "%~1"
)
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo.
  echo [ERREUR] Code %ERR%
  pause
)
exit /b %ERR%
