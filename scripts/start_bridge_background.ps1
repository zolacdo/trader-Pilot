<#
.SYNOPSIS
    Demarre le Bridge TradePilot en arriere-plan, sans aucune fenetre visible.

.DESCRIPTION
    Utilise bridge\.venv\Scripts\pythonw.exe (interpreteur sans console) s'il
    existe, sinon python.exe avec une fenetre masquee. Le PID est ecrit dans
    bridge\data\bridge.pid et les sorties sont redirigees vers
    bridge\data\logs\bridge-stdout.log et bridge-stderr.log.

    Le script est idempotent : si le PID enregistre correspond a un processus
    encore vivant, aucun second Bridge n'est lance.

    Apres le demarrage, il attend jusqu'a 30 secondes que
    http://127.0.0.1:<port>/api/v1/health reponde, puis affiche l'URL locale et,
    si le tunnel est actif, l'URL publique reelle lue depuis l'API locale de
    ngrok (http://127.0.0.1:4040/api/tunnels).

    C'est ce script qui est appele par la tache planifiee TradePilotBridge
    (voir scripts\install_autostart.ps1).

.PARAMETER NoNgrok
    Force NGROK_ENABLED=false pour ce lancement uniquement (bridge\.env intact).

.PARAMETER TimeoutSeconds
    Duree d'attente maximale de la reponse de /api/v1/health (30 par defaut).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_bridge_background.ps1

.EXAMPLE
    .\scripts\start_bridge_background.ps1 -NoNgrok
#>
[CmdletBinding()]
param(
    [switch]$NoNgrok,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot    = Split-Path -Parent $ScriptDir
$BridgeDir   = Join-Path $RepoRoot  "bridge"
$VenvDir     = Join-Path $BridgeDir ".venv"
$VenvPython  = Join-Path $VenvDir   "Scripts\python.exe"
$VenvPythonW = Join-Path $VenvDir   "Scripts\pythonw.exe"
$EnvFile     = Join-Path $BridgeDir ".env"
$DataDir     = Join-Path $BridgeDir "data"
$LogDir      = Join-Path $DataDir   "logs"
$PidFile     = Join-Path $DataDir   "bridge.pid"
$StdoutLog   = Join-Path $LogDir    "bridge-stdout.log"
$StderrLog   = Join-Path $LogDir    "bridge-stderr.log"

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

# Renvoie le processus du Bridge si le fichier PID pointe sur un processus vivant.
function Get-RunningBridge {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $raw = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $raw) { return $null }
    $raw = $raw.Trim()
    if ($raw -notmatch "^\d+$") { return $null }
    $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    # Le PID pourrait avoir ete recycle par un tout autre programme.
    if ($proc.ProcessName -notmatch "^pythonw?$") { return $null }
    return $proc
}

# Evite des journaux qui grossissent indefiniment.
function Rotate-LogFile {
    param([string]$Path, [int]$MaxBytes = 5242880)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -lt $MaxBytes) { return }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archive = [IO.Path]::ChangeExtension($Path, $null) + "." + $stamp + ".log"
    try { Move-Item -LiteralPath $Path -Destination $archive -Force } catch { }
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  TradePilot Bridge - demarrage en arriere-plan"                -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor White

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host ""
    Write-Host "[ERREUR] Environnement virtuel introuvable : $VenvPython"   -ForegroundColor Red
    Write-Host "         Lancez d'abord : .\scripts\install_bridge.ps1"      -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

foreach ($dir in @($DataDir, $LogDir)) {
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
}

$bridgeHost = Get-EnvValue -Path $EnvFile -Key "BRIDGE_HOST"
$portValue  = Get-EnvValue -Path $EnvFile -Key "BRIDGE_PORT"
if ([string]::IsNullOrWhiteSpace($bridgeHost)) { $bridgeHost = "127.0.0.1" }
$bridgePort = 8787
if ($portValue -and ($portValue -match "^\d+$")) { $bridgePort = [int]$portValue }

$healthUrl = "http://127.0.0.1:" + $bridgePort + "/api/v1/health"

# ---------------------------------------------------------------------------
# Deja demarre ?
# ---------------------------------------------------------------------------
$existing = Get-RunningBridge
if ($existing) {
    Write-Host ""
    Write-Host ("[INFO] Le Bridge tourne deja (PID " + $existing.Id + ") : aucun nouveau demarrage.") -ForegroundColor Green
    Write-Host ("       Demarre depuis : " + $existing.StartTime)                                     -ForegroundColor Gray
    Write-Host ("       API locale     : http://" + $bridgeHost + ":" + $bridgePort)                  -ForegroundColor Gray
    try {
        $null = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5 -ErrorAction Stop
        Write-Host "       Etat de sante  : l'API repond correctement." -ForegroundColor Green
    } catch {
        Write-Host "       Etat de sante  : le processus vit mais l'API ne repond pas encore." -ForegroundColor Yellow
    }
    Write-Host "       Pour l'arreter : .\scripts\stop_bridge.ps1"       -ForegroundColor Gray
    Write-Host ""
    exit 0
}

if (Test-Path -LiteralPath $PidFile) {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# Lancement
# ---------------------------------------------------------------------------
Rotate-LogFile -Path $StdoutLog
Rotate-LogFile -Path $StderrLog

# pythonw.exe n'ouvre aucune console : c'est le choix ideal pour l'arriere-plan.
$useWindowless = Test-Path -LiteralPath $VenvPythonW
if ($useWindowless) {
    $exePath = $VenvPythonW
} else {
    $exePath = $VenvPython
}

$env:PYTHONUNBUFFERED = "1"
if ($NoNgrok) {
    $env:NGROK_ENABLED = "false"
    Write-Host "[INFO] Tunnel ngrok desactive pour ce lancement (-NoNgrok)." -ForegroundColor Gray
}

$startArgs = @{
    FilePath               = $exePath
    ArgumentList           = @("-m", "app.main")
    WorkingDirectory       = $BridgeDir
    RedirectStandardOutput = $StdoutLog
    RedirectStandardError  = $StderrLog
    PassThru               = $true
}
if (-not $useWindowless) {
    # python.exe ouvrirait une console : on la masque.
    $startArgs["WindowStyle"] = "Hidden"
}

$process = $null
try {
    $process = Start-Process @startArgs
} catch {
    Write-Host ""
    Write-Host ("[ERREUR] Impossible de demarrer le Bridge : " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "         Verifiez que le Bridge n'est pas deja lance et que les fichiers" -ForegroundColor Yellow
    Write-Host "         de log ne sont pas verrouilles par un autre programme."          -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

if (-not $process) {
    Write-Host "[ERREUR] Le processus n'a pas pu etre cree." -ForegroundColor Red
    exit 1
}

Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ASCII

Write-Host ""
Write-Host ("[OK]   Bridge lance en arriere-plan (PID " + $process.Id + ")") -ForegroundColor Green
Write-Host ("       Interpreteur : " + $exePath)   -ForegroundColor Gray
Write-Host ("       Fichier PID  : " + $PidFile)   -ForegroundColor Gray
Write-Host ("       Journal      : " + $StdoutLog) -ForegroundColor Gray
Write-Host ("       Erreurs      : " + $StderrLog) -ForegroundColor Gray

# ---------------------------------------------------------------------------
# Attente de la disponibilite de l'API
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host ("[INFO] Attente de la reponse de " + $healthUrl + " (max " + $TimeoutSeconds + " s)...") -ForegroundColor Gray

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$healthy  = $false
while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) { break }
    try {
        $null = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3 -ErrorAction Stop
        $healthy = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($process.HasExited) {
    Write-Host ""
    Write-Host ("[ERREUR] Le Bridge s'est arrete immediatement (code " + $process.ExitCode + ").") -ForegroundColor Red
    Write-Host  "         Derniere lignes de bridge-stderr.log :" -ForegroundColor Yellow
    if (Test-Path -LiteralPath $StderrLog) {
        Get-Content -LiteralPath $StderrLog -Tail 20 | ForEach-Object { Write-Host ("         " + $_) -ForegroundColor DarkGray }
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host ""
    exit 1
}

Write-Host ""
if ($healthy) {
    Write-Host "[OK]   Le Bridge repond." -ForegroundColor Green
} else {
    Write-Host ("[ATTENTION] Pas de reponse sur /api/v1/health apres " + $TimeoutSeconds + " s.") -ForegroundColor Yellow
    Write-Host  "            Le processus tourne toujours : consultez les journaux ci-dessus."   -ForegroundColor Yellow
}

Write-Host ""
Write-Host ("       URL locale  : http://" + $bridgeHost + ":" + $bridgePort) -ForegroundColor White

# URL publique reelle : l'agent ngrok l'expose sur son API locale (port 4040).
$publicUrl = $null
try {
    $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 5 -ErrorAction Stop
    foreach ($tunnel in $tunnels.tunnels) {
        if ($tunnel.public_url -and $tunnel.public_url.StartsWith("https://")) {
            $publicUrl = $tunnel.public_url
            break
        }
    }
    if (-not $publicUrl -and $tunnels.tunnels) {
        $publicUrl = $tunnels.tunnels[0].public_url
    }
} catch {
    $publicUrl = $null
}

if ($publicUrl) {
    Write-Host ("       URL publique : " + $publicUrl) -ForegroundColor White
    Write-Host  "       C'est cette adresse que l'application mobile doit utiliser." -ForegroundColor Gray
} else {
    $configuredDomain = Get-EnvValue -Path $EnvFile -Key "NGROK_DOMAIN"
    $ngrokEnabled     = Get-EnvValue -Path $EnvFile -Key "NGROK_ENABLED"
    if ($NoNgrok) {
        Write-Host "       URL publique : desactivee pour ce lancement (-NoNgrok)." -ForegroundColor Gray
    } elseif ($ngrokEnabled -and $ngrokEnabled.ToLower() -eq "true") {
        Write-Host "       URL publique : tunnel non detecte (l'agent ngrok n'a pas repondu)." -ForegroundColor Yellow
        if ($configuredDomain) {
            Write-Host ("       Domaine configure : https://" + $configuredDomain) -ForegroundColor Gray
        }
        Write-Host "       Verifiez bridge\data\logs\ et .\scripts\setup_ngrok.ps1." -ForegroundColor Yellow
    } else {
        Write-Host "       URL publique : aucune (NGROK_ENABLED=false, acces local uniquement)." -ForegroundColor Gray
        Write-Host "       Pour activer l'acces distant : .\scripts\setup_ngrok.ps1"             -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "       Arret du Bridge : .\scripts\stop_bridge.ps1" -ForegroundColor Gray
Write-Host ""
exit 0
