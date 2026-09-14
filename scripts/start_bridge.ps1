<#
.SYNOPSIS
    Demarre le Bridge TradePilot au premier plan (usage manuel, fenetre visible).

.DESCRIPTION
    Active l'environnement virtuel bridge\.venv, se place dans bridge\ puis lance
    "python -m app.main". Les journaux s'affichent directement dans la console.
    Ctrl+C arrete proprement le Bridge et le code de sortie de Python est propage.

    Pour un demarrage sans fenetre (arriere-plan), utiliser plutot
    scripts\start_bridge_background.ps1.

.PARAMETER NoNgrok
    Desactive le tunnel ngrok pour CE lancement uniquement, en forcant la
    variable d'environnement NGROK_ENABLED=false. Le fichier bridge\.env
    n'est pas modifie.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_bridge.ps1

.EXAMPLE
    .\scripts\start_bridge.ps1 -NoNgrok
    Demarre le Bridge en local uniquement, sans ouvrir de tunnel ngrok.
#>
[CmdletBinding()]
param(
    [switch]$NoNgrok
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot   = Split-Path -Parent $ScriptDir
$BridgeDir  = Join-Path $RepoRoot  "bridge"
$VenvDir    = Join-Path $BridgeDir ".venv"
$VenvPython = Join-Path $VenvDir   "Scripts\python.exe"
$EnvFile    = Join-Path $BridgeDir ".env"

function Get-EnvValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        if ($trimmed.Substring(0, $idx).Trim() -eq $Key) {
            return $trimmed.Substring($idx + 1).Trim()
        }
    }
    return $null
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  TradePilot Bridge - demarrage manuel"                         -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor White

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host ""
    Write-Host "[ERREUR] L'environnement virtuel est introuvable :" -ForegroundColor Red
    Write-Host "         $VenvPython"                               -ForegroundColor Red
    Write-Host "         Lancez d'abord : .\scripts\install_bridge.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $BridgeDir "app"))) {
    Write-Host ""
    Write-Host "[ERREUR] Le module 'app' est introuvable dans $BridgeDir." -ForegroundColor Red
    Write-Host "         Le depot semble incomplet."                       -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Host "[ATTENTION] bridge\.env est absent : les valeurs par defaut seront utilisees." -ForegroundColor Yellow
    Write-Host "            Lancez .\scripts\install_bridge.ps1 pour le creer."                -ForegroundColor Yellow
}

$bridgeHost = Get-EnvValue -Path $EnvFile -Key "BRIDGE_HOST"
$bridgePort = Get-EnvValue -Path $EnvFile -Key "BRIDGE_PORT"
if ([string]::IsNullOrWhiteSpace($bridgeHost)) { $bridgeHost = "127.0.0.1" }
if ([string]::IsNullOrWhiteSpace($bridgePort)) { $bridgePort = "8787" }

# Activation de l'environnement virtuel pour le processus courant : on prefixe
# le PATH et on positionne VIRTUAL_ENV, ce que fait Activate.ps1.
$env:VIRTUAL_ENV = $VenvDir
$env:PATH = (Join-Path $VenvDir "Scripts") + ";" + $env:PATH
# Sorties Python non bufferisees : les journaux apparaissent immediatement.
$env:PYTHONUNBUFFERED = "1"

if ($NoNgrok) {
    $env:NGROK_ENABLED = "false"
    Write-Host "[INFO] Tunnel ngrok desactive pour ce lancement (-NoNgrok)." -ForegroundColor Gray
}

Write-Host ("[INFO] Interpreteur : " + $VenvPython)                       -ForegroundColor Gray
Write-Host ("[INFO] Dossier      : " + $BridgeDir)                        -ForegroundColor Gray
Write-Host ("[INFO] API locale   : http://" + $bridgeHost + ":" + $bridgePort) -ForegroundColor Gray
Write-Host "[INFO] Arreter le Bridge : Ctrl+C"                            -ForegroundColor Gray
Write-Host ""

$exitCode = 0
Push-Location -LiteralPath $BridgeDir
try {
    # Ctrl+C est transmis tel quel au processus Python enfant (meme groupe de
    # console) : uvicorn effectue alors son arret propre.
    $ErrorActionPreference = "Continue"
    & $VenvPython -m app.main
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { $exitCode = 0 }
} catch {
    Write-Host ""
    Write-Host ("[ERREUR] Le Bridge s'est arrete sur une erreur : " + $_.Exception.Message) -ForegroundColor Red
    $exitCode = 1
} finally {
    Pop-Location
}

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "[INFO] Bridge arrete normalement." -ForegroundColor Gray
} else {
    Write-Host ("[ATTENTION] Bridge arrete avec le code " + $exitCode + ".") -ForegroundColor Yellow
    Write-Host "            Consultez bridge\data\logs\ pour le detail."     -ForegroundColor Yellow
}
Write-Host ""

exit $exitCode
