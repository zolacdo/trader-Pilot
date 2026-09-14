<#
.SYNOPSIS
    Affiche un nouveau code d'appairage pour connecter un telephone au Bridge.

.DESCRIPTION
    Un code d'appairage est valable 15 minutes et ne sert qu'une seule fois.
    Le Bridge en affiche un a son demarrage, mais lorsqu'il tourne en
    permanence (demarrage automatique), ce code est depuis longtemps expire.

    Ce script en demande un nouveau au Bridge. La demande n'est acceptee que
    depuis la machine ou tourne le Bridge : impossible de reclamer un code a
    distance.

.EXAMPLE
    .\scripts\pairing_code.ps1

.EXAMPLE
    .\scripts\pairing_code.ps1 -Port 8787
#>

[CmdletBinding()]
param(
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvFile  = Join-Path $RepoRoot "bridge\.env"

function Get-EnvValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path $Path)) { return $null }
    foreach ($line in Get-Content $Path) {
        if ($line -match ("^\s*" + [regex]::Escape($Key) + "\s*=\s*(.*)$")) {
            return $matches[1].Trim()
        }
    }
    return $null
}

if ($Port -le 0) {
    $configured = Get-EnvValue -Path $EnvFile -Key "BRIDGE_PORT"
    if ($configured) { $Port = [int]$configured } else { $Port = 8787 }
}

$baseUrl = "http://127.0.0.1:$Port/api/v1"

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  TradePilot - code d'appairage" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

try {
    $null = Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 5 -ErrorAction Stop
} catch {
    Write-Host "[ERREUR]    Le Bridge ne repond pas sur le port $Port." -ForegroundColor Red
    Write-Host "            Demarrez-le avec : .\scripts\start_bridge_background.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

try {
    $response = Invoke-RestMethod -Uri "$baseUrl/pairing/renew" -Method Post -TimeoutSec 15 -ErrorAction Stop
} catch {
    Write-Host "[ERREUR]    Le Bridge a refuse la demande : $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    exit 1
}

$minutes = [int]($response.expiresInSeconds / 60)

Write-Host "       Code d'appairage : " -NoNewline -ForegroundColor Gray
Write-Host $response.code -ForegroundColor Green
Write-Host "       Valable          : $minutes minutes, une seule utilisation" -ForegroundColor Gray
Write-Host ""

if ($response.publicUrl) {
    Write-Host "       Adresse a saisir dans l'application :" -ForegroundColor Gray
    Write-Host ("       " + $response.publicUrl) -ForegroundColor White
} else {
    Write-Host "       Adresse a saisir dans l'application (reseau local) :" -ForegroundColor Gray
    Write-Host ("       http://" + (Get-EnvValue -Path $EnvFile -Key "BRIDGE_HOST") + ":$Port") -ForegroundColor White
    Write-Host "       (aucun tunnel ngrok actif)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""
