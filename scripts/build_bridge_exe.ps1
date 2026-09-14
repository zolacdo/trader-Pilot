<#
.SYNOPSIS
    Construit un executable Windows autonome du Bridge TradePilot.

.DESCRIPTION
    Utilise PyInstaller et le fichier bridge/tradepilot.spec. Le resultat est
    un dossier complet, copiable sur une machine qui n'a ni Python ni les
    dependances installes.

    MetaTrader 5 n'est PAS embarque : il reste a installer separement, comme
    n'importe quel terminal de courtier.

    Aucun secret n'est inclus dans l'executable. Le fichier .env doit etre
    place a cote de TradePilotBridge.exe sur la machine cible.

.PARAMETER Clean
    Supprime les dossiers build/ et dist/ avant de reconstruire.

.EXAMPLE
    .\scripts\build_bridge_exe.ps1

.EXAMPLE
    .\scripts\build_bridge_exe.ps1 -Clean
#>

[CmdletBinding()]
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$BridgeDir = Join-Path $RepoRoot "bridge"
$Python    = Join-Path $BridgeDir ".venv\Scripts\python.exe"
$SpecFile  = Join-Path $BridgeDir "tradepilot.spec"

function Write-Ok   { param([string]$m) Write-Host ("[OK]        " + $m) -ForegroundColor Green }
function Write-Info { param([string]$m) Write-Host ("[INFO]      " + $m) -ForegroundColor Gray }
function Write-Fail { param([string]$m) Write-Host ("[ERREUR]    " + $m) -ForegroundColor Red }

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  TradePilot Bridge - construction de l'executable" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $Python)) {
    Write-Fail "Environnement Python introuvable."
    Write-Host "            Lancez d'abord : .\scripts\install_bridge.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

if (-not (Test-Path $SpecFile)) {
    Write-Fail "Fichier tradepilot.spec introuvable dans bridge\."
    Write-Host ""
    exit 1
}

Set-Location $BridgeDir

# Les executables natifs ecrivent sur la sortie d'erreur sans que ce soit un
# echec : on repasse en mode non bloquant et on lit le code de retour.
$ErrorActionPreference = "Continue"

Write-Info "Verification de PyInstaller..."
& $Python -c "import PyInstaller" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Info "Installation de PyInstaller dans l'environnement du Bridge..."
    & $Python -m pip install --quiet pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Installation de PyInstaller impossible."
        exit 1
    }
}
$pyinstallerVersion = (& $Python -m PyInstaller --version 2>$null | Select-Object -First 1)
Write-Ok "PyInstaller $pyinstallerVersion"

if ($Clean) {
    foreach ($folder in @("build", "dist")) {
        $path = Join-Path $BridgeDir $folder
        if (Test-Path $path) {
            Remove-Item $path -Recurse -Force
            Write-Info "Supprime : $folder\"
        }
    }
}

Write-Host ""
Write-Info "Construction en cours (plusieurs minutes au premier passage)..."
Write-Host ""

& $Python -m PyInstaller --noconfirm --clean tradepilot.spec
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Fail "La construction a echoue. Lisez les messages ci-dessus."
    Write-Host ""
    exit 1
}

$exePath = Join-Path $BridgeDir "dist\TradePilotBridge\TradePilotBridge.exe"
if (-not (Test-Path $exePath)) {
    Write-Fail "Executable absent apres la construction : $exePath"
    exit 1
}

$sizeMb = [math]::Round(((Get-ChildItem (Split-Path $exePath) -Recurse |
    Measure-Object -Property Length -Sum).Sum / 1MB), 1)

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Ok "Executable construit."
Write-Host ""
Write-Host ("       Dossier : " + (Split-Path $exePath))          -ForegroundColor White
Write-Host ("       Taille  : " + $sizeMb + " Mo")                 -ForegroundColor Gray
Write-Host ""
Write-Host "  Pour l'utiliser sur une autre machine :" -ForegroundColor Yellow
Write-Host "   1. Copiez tout le dossier TradePilotBridge\"       -ForegroundColor Yellow
Write-Host "   2. Placez votre fichier .env a cote de l'executable" -ForegroundColor Yellow
Write-Host "   3. Installez MetaTrader 5 et connectez-vous"         -ForegroundColor Yellow
Write-Host "   4. Lancez TradePilotBridge.exe"                      -ForegroundColor Yellow
Write-Host ""
Write-Host "  Le code d'appairage s'affiche dans la console." -ForegroundColor Gray
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
