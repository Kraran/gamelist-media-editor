#Requires -Version 5.1
# Gamelist Media Editor - Windows installer

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$Host.UI.RawUI.WindowTitle = "Installation - Gamelist Media Editor"

$AppName      = "Gamelist Media Editor"
$AppVersion   = "1.0.2"
$PythonVer    = "3.12.8"
$PythonEmbed  = "https://www.python.org/ftp/python/$PythonVer/python-$PythonVer-embed-amd64.zip"
$GetPipUrl    = "https://bootstrap.pypa.io/get-pip.py"
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$PayloadDir   = Join-Path $ScriptDir "payload"

function Write-Step($msg)  { Write-Host ""; Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "   OK  $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "   !   $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "   ERR $msg" -ForegroundColor Red }
function Write-Info($msg)  { Write-Host "   $msg" -ForegroundColor Gray }

Clear-Host
Write-Host ""
Write-Host " ============================================================" -ForegroundColor Magenta
Write-Host "   $AppName  v$AppVersion" -ForegroundColor Magenta
Write-Host "   Installateur Windows" -ForegroundColor Magenta
Write-Host " ============================================================" -ForegroundColor Magenta
Write-Host ""

if (-not (Test-Path $PayloadDir)) {
    Write-Err "Dossier payload introuvable a cote de Install.ps1."
    Write-Info "Re-telecharge l'archive d'installation complete."
    Read-Host "Entree pour quitter"
    exit 1
}

Write-Step "Choix du dossier d'installation"

Add-Type -AssemblyName System.Windows.Forms | Out-Null
$browser = New-Object System.Windows.Forms.FolderBrowserDialog
$browser.Description = "Choisis le dossier d'installation de $AppName"
$browser.ShowNewFolderButton = $true
$defaultPath = Join-Path $env:LOCALAPPDATA "GamelistMediaEditor"
if (Test-Path $defaultPath) { $browser.SelectedPath = $defaultPath } else { $browser.SelectedPath = $env:LOCALAPPDATA }

$dialogResult = $browser.ShowDialog()
if ($dialogResult -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Warn "Installation annulee."
    Start-Sleep -Seconds 2
    exit 0
}

$InstallDir = $browser.SelectedPath.TrimEnd('\')
if ((Split-Path $InstallDir -Leaf) -ne "GamelistMediaEditor") {
    $candidate = Join-Path $InstallDir "GamelistMediaEditor"
    $useSub = Read-Host "Installer dans '$candidate' ? (O/n)"
    if ($useSub -eq "" -or $useSub -match '^[oOyY]') { $InstallDir = $candidate }
}

Write-Ok "Dossier : $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Step "Copie des fichiers de l'application"
Get-ChildItem -Path $PayloadDir -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($PayloadDir.Length).TrimStart('\')
    $dest = Join-Path $InstallDir $rel
    $destParent = Split-Path $dest -Parent
    if (-not (Test-Path $destParent)) { New-Item -ItemType Directory -Force -Path $destParent | Out-Null }
    Copy-Item -Path $_.FullName -Destination $dest -Force
}
Write-Ok "Fichiers copies"

Write-Step "Verification de Python"

function Test-PythonCmd($cmd) {
    try {
        $out = & $cmd -c "import sys; print(sys.version_info[0], sys.version_info[1], sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $parts = ($out | Out-String).Trim() -split '\s+'
            if ($parts.Count -ge 3) {
                $major = [int]$parts[0]; $minor = [int]$parts[1]
                if ($major -ge 3 -and $minor -ge 9) {
                    return @{ Cmd = $cmd; Exe = $parts[2]; Version = "$major.$minor" }
                }
            }
        }
    } catch {}
    return $null
}

$PythonInfo = $null
$PortablePythonDir = Join-Path $InstallDir "python"
$portableExe = Join-Path $PortablePythonDir "python.exe"

if (Test-Path $portableExe) {
    $PythonInfo = Test-PythonCmd $portableExe
    if ($PythonInfo) { Write-Ok "Python portable trouve : $($PythonInfo.Version)" }
}

if (-not $PythonInfo) {
    foreach ($c in @("python", "py")) {
        $PythonInfo = Test-PythonCmd $c
        if ($PythonInfo) {
            Write-Ok "Python systeme trouve : $($PythonInfo.Version) ($($PythonInfo.Exe))"
            break
        }
    }
}

if (-not $PythonInfo) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Info "Installation de Python via winget..."
        try {
            & winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
            Start-Sleep -Seconds 2
            foreach ($c in @("python", "py")) {
                $PythonInfo = Test-PythonCmd $c
                if ($PythonInfo) { Write-Ok "Python installe via winget : $($PythonInfo.Version)"; break }
            }
        } catch { Write-Warn "winget a echoue : $_" }
    }
}

if (-not $PythonInfo) {
    Write-Info "Telechargement de Python $PythonVer portable (embeddable)..."
    $zipPath = Join-Path $env:TEMP "python-embed-$PythonVer.zip"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $PythonEmbed -OutFile $zipPath -UseBasicParsing
        if (Test-Path $PortablePythonDir) { Remove-Item $PortablePythonDir -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $PortablePythonDir | Out-Null
        Expand-Archive -Path $zipPath -DestinationPath $PortablePythonDir -Force
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

        $pth = Get-ChildItem $PortablePythonDir -Filter "python*._pth" | Select-Object -First 1
        if ($pth) {
            $content = Get-Content $pth.FullName
            $newContent = @()
            foreach ($line in $content) {
                if ($line -match '^\s*#\s*import\s+site') { $newContent += "import site" }
                else { $newContent += $line }
            }
            if ($newContent -notcontains "import site") { $newContent += "import site" }
            if ($newContent -notcontains "Lib\site-packages") { $newContent += "Lib\site-packages" }
            Set-Content -Path $pth.FullName -Value $newContent -Encoding ASCII
        }

        Write-Info "Installation de pip..."
        $getPip = Join-Path $env:TEMP "get-pip.py"
        Invoke-WebRequest -Uri $GetPipUrl -OutFile $getPip -UseBasicParsing
        & $portableExe $getPip --no-warn-script-location 2>&1 | Out-Null
        Remove-Item $getPip -Force -ErrorAction SilentlyContinue

        $PythonInfo = Test-PythonCmd $portableExe
        if ($PythonInfo) { Write-Ok "Python portable installe : $($PythonInfo.Version)" }
        else { throw "Python portable non fonctionnel apres installation" }
    } catch {
        Write-Err "Impossible d'installer Python automatiquement : $_"
        Write-Info "Installe Python manuellement depuis https://www.python.org/downloads/"
        Write-Info "Coche Add python.exe to PATH, puis relance cet installateur."
        Read-Host "Entree pour quitter"
        exit 1
    }
}

$PythonExe = $PythonInfo.Exe
$PythonCmd = $PythonInfo.Cmd

Write-Step "Installation des dependances Python (flask, lxml, requests)"
$reqFile = Join-Path $InstallDir "requirements.txt"
try {
    & $PythonCmd -m pip install --upgrade pip --disable-pip-version-check 2>&1 | Out-Null
    & $PythonCmd -m pip install -r $reqFile --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "pip a renvoye le code $LASTEXITCODE" }
    Write-Ok "Dependances installees"
} catch {
    Write-Err "Echec pip : $_"
    Write-Info "Essaie manuellement :"
    Write-Info "  `"$PythonExe`" -m pip install flask lxml requests"
    Read-Host "Entree pour continuer quand meme"
}

try {
    & $PythonCmd -c "import flask, lxml, requests; print('ok')" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Ok "Import flask / lxml / requests OK" }
    else { Write-Warn "Les modules ne s'importent pas encore - verifie pip" }
} catch { Write-Warn "Verification imports echouee" }

$pyPathFile = Join-Path $InstallDir "python_path.txt"
Set-Content -Path $pyPathFile -Value $PythonExe -Encoding ASCII

Write-Step "Configuration du lanceur"
$launcher = Join-Path $InstallDir "Lancer.bat"

$bat = @"
@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title Gamelist Media Editor
cd /d "%~dp0"

color 0A
echo.
echo  ============================================================
echo            Gamelist Media Editor
echo            Editeur de medias pour gamelist.xml
echo  ============================================================
echo.

set "PYEXE="
if exist "%~dp0python_path.txt" (
    set /p PYEXE=<"%~dp0python_path.txt"
)
if not defined PYEXE if exist "%~dp0python\python.exe" set "PYEXE=%~dp0python\python.exe"
if not defined PYEXE set "PYEXE=python"

"%PYEXE%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [ERREUR] Python introuvable.
    echo  Relance Installer.bat ou installe Python depuis python.org
    echo.
    pause
    exit /b 1
)

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

set "XML_PATH=%XML_PATH:"=%"

:check_file
if not exist "%XML_PATH%" (
    color 0C
    echo.
    echo  [ERREUR] Fichier introuvable :
    echo    %XML_PATH%
    echo.
    pause
    exit /b 1
)

echo.
echo  ------------------------------------------------------------
echo   XML      : %XML_PATH%
echo   Python   : %PYEXE%
echo   URL      : http://127.0.0.1:5050
echo  ------------------------------------------------------------
echo.
echo  Demarrage du serveur...
echo  Le navigateur va s'ouvrir automatiquement.
echo  Pour arreter : bouton Quitter dans l'app, ou Ctrl+C ici
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5050"

"%PYEXE%" "%~dp0app.py" "%XML_PATH%"
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
echo  [ERREUR] Code de sortie %EXITCODE%.
echo  Verifie les dependances : "%PYEXE%" -m pip install flask lxml requests
echo.
pause
endlocal
"@
$bat = $bat -replace "`n", "`r`n"
[System.IO.File]::WriteAllText($launcher, $bat, [System.Text.Encoding]::ASCII)
Write-Ok "Lancer.bat configure"

Write-Step "Creation des raccourcis"

function New-Shortcut($Path, $Target, $Args, $WorkDir, $Icon, $Desc) {
    $w = New-Object -ComObject WScript.Shell
    $s = $w.CreateShortcut($Path)
    $s.TargetPath = $Target
    if ($Args) { $s.Arguments = $Args }
    $s.WorkingDirectory = $WorkDir
    if ($Icon -and (Test-Path $Icon)) { $s.IconLocation = $Icon }
    $s.Description = $Desc
    $s.Save()
}

$iconPath = Join-Path $InstallDir "icon.ico"
$desk = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Gamelist Media Editor"
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null

New-Shortcut (Join-Path $desk "$AppName.lnk") "cmd.exe" "/c `"$launcher`"" $InstallDir $iconPath $AppName
New-Shortcut (Join-Path $startMenu "$AppName.lnk") "cmd.exe" "/c `"$launcher`"" $InstallDir $iconPath $AppName

$uninst = Join-Path $InstallDir "Uninstall.ps1"
$u = @"
# Desinstallation - Gamelist Media Editor
$ErrorActionPreference = 'Continue'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Suppression des raccourcis..."
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Gamelist Media Editor.lnk') -Force -ErrorAction SilentlyContinue
$sm = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\Gamelist Media Editor'
Remove-Item $sm -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Ferme ce script, puis supprime manuellement le dossier :"
Write-Host "  $dir"
Read-Host 'Entree pour quitter'
"@
$utf8BOM = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText($uninst, $u, $utf8BOM)

New-Shortcut (Join-Path $startMenu "Desinstaller.lnk") "powershell.exe" "-ExecutionPolicy Bypass -File `"$uninst`"" $InstallDir $null "Desinstaller $AppName"
Write-Ok "Raccourcis Bureau + Menu Demarrer"

$info = @"
Application : $AppName
Version     : $AppVersion
Installe le : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Dossier     : $InstallDir
Python      : $PythonExe
"@
[System.IO.File]::WriteAllText((Join-Path $InstallDir "install_info.txt"), $info, $utf8BOM)

Write-Host ""
Write-Host " ============================================================" -ForegroundColor Green
Write-Host "   Installation terminee !" -ForegroundColor Green
Write-Host " ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dossier   : $InstallDir" -ForegroundColor White
Write-Host "  Python    : $PythonExe" -ForegroundColor White
Write-Host "  Lancer    : double-clic sur le raccourci Bureau" -ForegroundColor White
Write-Host "              ou sur Lancer.bat dans le dossier" -ForegroundColor White
Write-Host ""
Write-Host "  Au demarrage, indique le chemin de ton gamelist.xml" -ForegroundColor Gray
Write-Host "  (glisser-deposer dans la fenetre de commande)." -ForegroundColor Gray
Write-Host ""

$open = Read-Host "Ouvrir le dossier d'installation maintenant ? (O/n)"
if ($open -eq "" -or $open -match '^[oOyY]') { Start-Process explorer.exe $InstallDir }

Write-Host ""
Read-Host "Entree pour fermer l'installateur"
