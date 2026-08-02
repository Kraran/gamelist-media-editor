# Cree un raccourci sur le Bureau avec l'icone de l'application
# Usage : clic droit > Executer avec PowerShell
#    ou : powershell -ExecutionPolicy Bypass -File .\Creer-Raccourci.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$batPath = Join-Path $scriptDir "Lancer.bat"
$iconPath = Join-Path $scriptDir "icon.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Gamelist Media Editor.lnk"

Write-Host ""
Write-Host "  Gamelist Media Editor - Creation du raccourci" -ForegroundColor Cyan
Write-Host "  ----------------------------------------------" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $batPath)) {
    Write-Host "  [ERREUR] Lancer.bat introuvable dans :" -ForegroundColor Red
    Write-Host "    $scriptDir"
    exit 1
}

$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut($shortcutPath)
$sc.TargetPath = $batPath
$sc.WorkingDirectory = $scriptDir
$sc.Description = "Editeur de medias pour gamelist.xml (EmulationStation / RetroBat)"
$sc.WindowStyle = 1
if (Test-Path $iconPath) {
    $sc.IconLocation = "$iconPath,0"
    Write-Host "  Icone    : $iconPath" -ForegroundColor DarkGray
} else {
    Write-Host "  [INFO] icon.ico absent - raccourci sans icone personnalisee" -ForegroundColor Yellow
}
$sc.Save()

Write-Host "  Raccourci : $shortcutPath" -ForegroundColor Green
Write-Host ""
Write-Host "  Double-clique sur le raccourci du Bureau pour lancer l'app." -ForegroundColor White
Write-Host ""
