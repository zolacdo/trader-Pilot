<#
.SYNOPSIS
    Arrete le Bridge TradePilot demarre en arriere-plan.

.DESCRIPTION
    Lit bridge\data\bridge.pid, demande d'abord un arret courtois au processus,
    puis force l'arret s'il ne repond pas. Termine egalement les agents ngrok.exe
    lances par le Bridge (processus enfants ou binaire situe dans le dossier du
    projet), puis supprime le fichier PID.

    Le script est sans danger si le Bridge est deja arrete : il le signale
    simplement et rend la main avec le code 0.

.PARAMETER TimeoutSeconds
    Duree d'attente de l'arret courtois avant l'arret force (10 s par defaut).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_bridge.ps1

.EXAMPLE
    .\scripts\stop_bridge.ps1 -TimeoutSeconds 20
#>
[CmdletBinding()]
param(
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot  = Split-Path -Parent $ScriptDir
$BridgeDir = Join-Path $RepoRoot  "bridge"
$DataDir   = Join-Path $BridgeDir "data"
$PidFile   = Join-Path $DataDir   "bridge.pid"

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  TradePilot Bridge - arret"                                    -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor White
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Lecture du fichier PID
# ---------------------------------------------------------------------------
$bridgePid = 0
if (Test-Path -LiteralPath $PidFile) {
    $raw = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($raw) { $raw = $raw.Trim() }
    if ($raw -match "^\d+$") {
        $bridgePid = [int]$raw
    } else {
        Write-Host "[ATTENTION] Le fichier PID est illisible : il sera supprime." -ForegroundColor Yellow
    }
} else {
    Write-Host ("[INFO] Aucun fichier PID (" + $PidFile + ") : le Bridge n'a pas ete demarre en arriere-plan.") -ForegroundColor Gray
}

$bridgeProcess = $null
if ($bridgePid -gt 0) {
    $candidate = Get-Process -Id $bridgePid -ErrorAction SilentlyContinue
    if ($candidate) {
        if ($candidate.ProcessName -match "^pythonw?$") {
            $bridgeProcess = $candidate
        } else {
            Write-Host ("[ATTENTION] Le PID " + $bridgePid + " appartient a '" + $candidate.ProcessName + "' et non au Bridge.") -ForegroundColor Yellow
            Write-Host  "            Aucun processus ne sera arrete (PID recycle par Windows)."                                  -ForegroundColor Yellow
        }
    } else {
        Write-Host ("[INFO] Le processus " + $bridgePid + " n'existe plus : le Bridge etait deja arrete.") -ForegroundColor Gray
    }
}

# ---------------------------------------------------------------------------
# 2. Recherche des agents ngrok lances par le Bridge (avant de tuer le parent)
# ---------------------------------------------------------------------------
$ngrokTargets = New-Object System.Collections.ArrayList
try {
    $ngrokProcesses = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'ngrok.exe'" -ErrorAction SilentlyContinue)
    foreach ($proc in $ngrokProcesses) {
        $isChild  = ($bridgePid -gt 0 -and $proc.ParentProcessId -eq $bridgePid)
        $fromRepo = $false
        if ($proc.ExecutablePath) {
            $fromRepo = $proc.ExecutablePath.ToLower().StartsWith($RepoRoot.ToLower())
        }
        if ($isChild -or $fromRepo) { [void]$ngrokTargets.Add($proc.ProcessId) }
    }
} catch {
    Write-Host ("[ATTENTION] Recherche des agents ngrok impossible : " + $_.Exception.Message) -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 3. Arret du Bridge
# ---------------------------------------------------------------------------
if ($bridgeProcess) {
    Write-Host ("[INFO] Arret du Bridge (PID " + $bridgeProcess.Id + ")...") -ForegroundColor Gray

    # Tentative d'arret courtois : fermeture de la fenetre principale si elle
    # existe (python.exe avec console), sinon on passe directement a l'etape
    # suivante. pythonw.exe n'a pas de fenetre : l'arret force sera necessaire.
    try {
        $null = $bridgeProcess.CloseMainWindow()
    } catch { }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $bridgeProcess.Refresh()
        if ($bridgeProcess.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }

    $bridgeProcess.Refresh()
    if (-not $bridgeProcess.HasExited) {
        Write-Host "[INFO] Pas de reponse a la demande d'arret : arret force." -ForegroundColor Gray
        try {
            Stop-Process -Id $bridgeProcess.Id -Force -ErrorAction Stop
        } catch {
            Write-Host ("[ERREUR] Arret impossible : " + $_.Exception.Message)                       -ForegroundColor Red
            Write-Host  "         Relancez ce script depuis une console PowerShell administrateur."  -ForegroundColor Yellow
            Write-Host ""
            exit 1
        }
    }

    Start-Sleep -Milliseconds 300
    if (Get-Process -Id $bridgeProcess.Id -ErrorAction SilentlyContinue) {
        Write-Host ("[ERREUR] Le processus " + $bridgeProcess.Id + " est toujours actif.") -ForegroundColor Red
        Write-Host ""
        exit 1
    }
    Write-Host ("[OK]   Bridge arrete (PID " + $bridgePid + ").") -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 4. Arret des agents ngrok du Bridge
# ---------------------------------------------------------------------------
if ($ngrokTargets.Count -gt 0) {
    foreach ($ngrokPid in $ngrokTargets) {
        try {
            Stop-Process -Id $ngrokPid -Force -ErrorAction Stop
            Write-Host ("[OK]   Agent ngrok arrete (PID " + $ngrokPid + ").") -ForegroundColor Green
        } catch {
            Write-Host ("[ATTENTION] Agent ngrok " + $ngrokPid + " non arrete : " + $_.Exception.Message) -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "[INFO] Aucun agent ngrok lance par le Bridge n'a ete trouve." -ForegroundColor Gray
}

# ---------------------------------------------------------------------------
# 5. Nettoyage du fichier PID
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $PidFile) {
    try {
        Remove-Item -LiteralPath $PidFile -Force
        Write-Host "[OK]   Fichier PID supprime." -ForegroundColor Green
    } catch {
        Write-Host ("[ATTENTION] Suppression du fichier PID impossible : " + $_.Exception.Message) -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "[INFO] Pour redemarrer : .\scripts\start_bridge_background.ps1" -ForegroundColor Gray
Write-Host ""
exit 0
