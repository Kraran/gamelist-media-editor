@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo  Build Gamelist Media Editor Windows .exe (PyInstaller)
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  pause
  exit /b 1
)

echo [1/3] Installing build dependencies...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

echo [2/3] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] Running PyInstaller...
python -m PyInstaller --noconfirm GamelistMediaEditor.spec
if errorlevel 1 (
  echo [ERROR] PyInstaller failed.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  OK - Executable:
echo    %cd%\dist\GamelistMediaEditor.exe
echo.
echo  Double-click the .exe - no gamelist required at start.
echo  Use the "Gamelist..." button to open a file.
echo  Optional: drag a gamelist.xml onto the .exe to open it.
echo ============================================================
explorer dist
pause
