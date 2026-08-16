@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo  Publish Gamelist Media Editor v1.1.3 to GitHub
echo ============================================================
set REPO=C:\Users\ffc59\Documents\gamelist-media-editor
if not exist "%REPO%\.git" (
  echo Clone not found at %REPO% - edit REPO= in this script.
  pause
  exit /b 1
)
cd /d "%REPO%"
git fetch origin
git pull --rebase origin main
echo.
echo Extract gamelist-media-editor-v1.1.3-source.zip then copy over the clone.
echo Press a key when files are copied...
pause
git add -A
git status
git commit -m "v1.1.3: About dialog + header brand icon"
git push origin main
git tag -a v1.1.3 -m "v1.1.3 About dialog + header brand"
git push origin v1.1.3
gh release create v1.1.3 --title "v1.1.3 — About dialog + header brand" --notes-file RELEASE_NOTES_v1.1.3.md "%~dp0gamelist-media-editor-v1.1.3-source.zip" "%~dp0GamelistMediaEditor-Windows-Setup-v1.1.3.zip"
echo Done: https://github.com/Kraran/gamelist-media-editor/releases/tag/v1.1.3
pause
