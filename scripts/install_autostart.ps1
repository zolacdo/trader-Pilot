<#
.SYNOPSIS
    Installe la tache planifiee Windows qui demarre le Bridge TradePilot
    automatiquement, en arriere-plan, avec le tunnel ngrok.

.DESCRIPTION
    Cree une tache planifiee nommee "TradePilotBridge" qui execute
    scripts\start_bridge_background.ps1 sans fenetre visible.

    POURQUOI UN DECLENCHEUR "A L'OUVERTURE DE SESSION" ET NON "AU DEMARRAGE" ?
    ------------------------------------------------------------------------
    Le Bridge pilote MetaTrader 5 via le paquet Python MetaTrader5, qui dialogue
    avec le terminal MT5 Desktop (terminal64.exe). Ce terminal est une
    application graphique : il n'existe que dans une session utilisateur
    interactive et ne peut pas fonctionner dans la session 0 (session de
    service, sans bureau). Une tache declenchee "au demarrage du systeme"
    s'executerait avant toute ouverture de session : MT5 ne serait pas lance,
    le Bridge ne pourrait ni lire le compte ni passer d'ordre.
    On declenche donc a l'ouverture de session de l'utilisateur courant, avec
    un delai de 60 secondes qui laisse le temps au reseau de monter et a
    MetaTrader 5 de demarrer.

    La tache est configuree pour :
      - s'executer avec les privileges les plus eleves (-RunLevel Highest) ;
      - demarrer meme si l'heure prevue a ete manquee (-StartWhenAvailable) ;
      - ne jamais etre interrompue pour cause de duree (ExecutionTimeLimit = 0) ;
      - redemarrer automatiquement 3 fois, a 1 minute d'intervalle, en cas d'echec ;
      - fonctionner sur batterie et ne pas s'arreter au passage sur batterie.

.PARAMETER NgrokDomain
    Domaine reserve ngrok a ecrire dans bridge\.env (active NGROK_ENABLED=true).

.PARAMETER NgrokAuthToken
    Token ngrok a ecrire dans bridge\.env. Il n'est jamais affiche.

.PARAMETER Remove
    Desinstalle la tache planifiee TradePilotBridge.

.PARAMETER Status
    Affiche l'etat de la tache sans rien modifier (ne demande pas les droits
    administrateur).

.EXAMPLE
    # Console PowerShell ADMINISTRATEUR
    .\scripts\install_autostart.ps1 -NgrokDomain "tradepilot-xyz.ngrok-free.app" -NgrokAuthToken "2ab..."

.EXAMPLE
    .\scripts\install_autostart.ps1 -Status

.EXAMPLE
    # Console PowerShell ADMINISTRATEUR
    .\scripts\install_autostart.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$NgrokDomain = "",
    [string]$NgrokAuthToken = "",
    [switch]$Remove,
    [switch]$Status
)

$ErrorActionPreference = "Stop"

$TaskName = "TradePilotBridge"

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot   = Split-Path -Parent $ScriptDir
$BridgeDir  = Join-Path $RepoRoot  "bridge"
$EnvFile    = Join-Path $BridgeDir ".env"
$StartScript = Join-Path $ScriptDir "start_bridge_background.ps1"

function Write-Ok    { param([string]$Message) Write-Host ("[OK]        " + $Message) -ForegroundColor Green }
function Write-Info  { param([string]$Message) Write-Host ("[INFO]      " + $Message) -ForegroundColor Gray }
function Write-Warn  { param([string]$Message) Write-Host ("[ATTENTION] " + $Message) -ForegroundColor Yellow }
function Write-Fail  { param([string]$Message) Write-Host ("[ERREUR]    " + $Message) -ForegroundColor Red }

function Test-Administrator {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Ecrit ou met a jour une cle du .env sans afficher sa valeur.
function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warn "bridge\.env est absent : lancez d'abord .\scripts\install_bridge.ps1"
        return $false
    }
    $lines = @(Get-Content -LiteralPath $Path)
    $updated = $false
    $result = New-Object System.Collections.ArrayList
    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ($trimmed -ne "" -and -not $trimmed.StartsWith("#")) {
            $idx = $trimmed.IndexOf("=")
            if ($idx -ge 1 -and $trimmed.Substring(0, $idx).Trim() -eq $Key) {
                [void]$result.Add($Key + "=" + $Value)
                $updated = $true
                continue
            }
        }
        [void]$result.Add($line)
    }
    if (-not $updated) { [void]$result.Add($Key + "=" + $Value) }
    Set-Content -LiteralPath $Path -Value $result -Encoding UTF8
    return $true
}

function Get-BridgeTask {
    try {
        return Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    } catch {
        return $null
    }
}

function Show-TaskStatus {
    $task = Get-BridgeTask
    if (-not $task) {
        Write-Host ""
        Write-Info ("La tache planifiee '" + $TaskName + "' n'est pas installee.")
        Write-Info "Pour l'installer : ouvrez PowerShell en administrateur puis lancez"
        Write-Info "  .\scripts\install_autostart.ps1"
        Write-Host ""
        return $false
    }

    Write-Host ""
    Write-Ok ("Tache '" + $TaskName + "' installee.")
    Write-Host ("            Etat            : " + $task.State) -ForegroundColor Gray
    foreach ($action in $task.Actions) {
        Write-Host ("            Programme       : " + $action.Execute) -ForegroundColor Gray
        if ($action.Arguments) {
            Write-Host ("            Arguments       : " + $action.Arguments) -ForegroundColor DarkGray
        }
    }
    try {
        $principal = $task.Principal
        Write-Host ("            Compte          : " + $principal.UserId + " (" + $principal.RunLevel + ")") -ForegroundColor Gray
    } catch { }

    try {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
        $lastRun = $info.LastRunTime
        if (-not $lastRun -or $lastRun.Year -lt 2000) { $lastRun = "jamais" }
        $nextRun = $info.NextRunTime
        if (-not $nextRun) { $nextRun = "a la prochaine ouverture de session" }
        Write-Host ("            Derniere execution : " + $lastRun) -ForegroundColor Gray
        Write-Host ("            Prochaine execution: " + $nextRun) -ForegroundColor Gray
        Write-Host ("            Dernier resultat   : " + $info.LastTaskResult + " (0 = succes)") -ForegroundColor Gray
    } catch {
        Write-Warn ("Informations d'execution indisponibles : " + $_.Exception.Message)
    }
    Write-Host ""
    return $true
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  TradePilot Bridge - demarrage automatique (tache planifiee)"  -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor White

# ---------------------------------------------------------------------------
# Mode -Status : lecture seule, pas besoin d'etre administrateur
# ---------------------------------------------------------------------------
if ($Status) {
    $null = Show-TaskStatus
    exit 0
}

# ---------------------------------------------------------------------------
# Les modes installation et desinstallation exigent les droits administrateur
# ---------------------------------------------------------------------------
# Les droits administrateur ne sont PAS obligatoires : la tache tourne sous le
# compte de l'utilisateur, a son ouverture de session. Sans elevation, on
# enregistre simplement la tache avec des privileges standards, ce qui suffit
# au Bridge et a ngrok.
$IsElevated = Test-Administrator
if ($IsElevated) {
    $TaskRunLevel = "Highest"
} else {
    $TaskRunLevel = "Limited"
    Write-Host ""
    Write-Info "Console non administrateur : la tache sera creee avec des privileges standards."
    Write-Host "       C'est suffisant pour demarrer le Bridge et le tunnel ngrok."          -ForegroundColor Gray
    Write-Host "       Pour des privileges eleves, relancez ce script depuis une console"    -ForegroundColor Gray
    Write-Host "       PowerShell ouverte en tant qu'administrateur."                        -ForegroundColor Gray
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Desinstallation
# ---------------------------------------------------------------------------
if ($Remove) {
    $task = Get-BridgeTask
    if (-not $task) {
        Write-Host ""
        Write-Info ("La tache '" + $TaskName + "' n'existe pas : rien a desinstaller.")
        Write-Host ""
        exit 0
    }
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host ""
        Write-Ok ("Tache '" + $TaskName + "' supprimee.")
        Write-Info "Le Bridge ne demarrera plus automatiquement a l'ouverture de session."
        Write-Info "S'il tourne encore : .\scripts\stop_bridge.ps1"
        Write-Host ""
        exit 0
    } catch {
        Write-Host ""
        Write-Fail ("Suppression impossible : " + $_.Exception.Message)
        Write-Host ""
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Verifications prealables
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $StartScript)) {
    Write-Host ""
    Write-Fail ("Script de demarrage introuvable : " + $StartScript)
    Write-Host  "         Le depot semble incomplet." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Warn "bridge\.env est absent : lancez d'abord .\scripts\install_bridge.ps1"
}

# ---------------------------------------------------------------------------
# Ecriture des parametres ngrok
# ---------------------------------------------------------------------------
$ngrokChanged = $false

if (-not [string]::IsNullOrWhiteSpace($NgrokAuthToken)) {
    if (Set-EnvValue -Path $EnvFile -Key "NGROK_AUTHTOKEN" -Value $NgrokAuthToken.Trim()) {
        Write-Ok "NGROK_AUTHTOKEN ecrit dans bridge\.env (valeur jamais affichee)."
        $ngrokChanged = $true
    }
}

if (-not [string]::IsNullOrWhiteSpace($NgrokDomain)) {
    $domain = $NgrokDomain.Trim().Replace("https://", "").Replace("http://", "").TrimEnd("/")
    if (Set-EnvValue -Path $EnvFile -Key "NGROK_DOMAIN" -Value $domain) {
        Write-Ok ("NGROK_DOMAIN ecrit dans bridge\.env : " + $domain)
        $ngrokChanged = $true
    }
}

if ($ngrokChanged) {
    if (Set-EnvValue -Path $EnvFile -Key "NGROK_ENABLED" -Value "true") {
        Write-Ok "NGROK_ENABLED=true : le tunnel sera ouvert a chaque demarrage automatique."
    }
}

# ---------------------------------------------------------------------------
# Construction de la tache planifiee
# ---------------------------------------------------------------------------
Write-Host ""
Write-Info "Creation de la tache planifiee..."

$argumentLine = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " + [char]34 + $StartScript + [char]34

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumentLine -WorkingDirectory $RepoRoot

# Declencheur : ouverture de session de l'utilisateur courant (voir l'explication
# detaillee dans le bloc .DESCRIPTION ci-dessus : MT5 exige une session
# interactive).
$currentUser = $env:USERNAME
if ($env:USERDOMAIN) { $currentUser = $env:USERDOMAIN + "\" + $env:USERNAME }

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser

# Delai de 60 secondes : laisse le reseau et MetaTrader 5 se lancer avant le Bridge.
try {
    $trigger.Delay = "PT60S"
} catch {
    Write-Warn "Delai de demarrage non applicable sur ce systeme : la tache demarrera immediatement."
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

# Aucune limite de duree d'execution : le Bridge doit tourner en continu.
$settings.ExecutionTimeLimit = "PT0S"
$settings.DisallowStartIfOnBatteries = $false
$settings.StopIfGoingOnBatteries = $false

$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel $TaskRunLevel

try {
    $null = Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Demarre le Bridge TradePilot en arriere-plan a l'ouverture de session (MetaTrader 5 exige une session interactive)." `
        -Force `
        -ErrorAction Stop
} catch {
    Write-Host ""
    Write-Fail ("Enregistrement de la tache impossible : " + $_.Exception.Message)
    Write-Host  "         Verifiez que le service 'Planificateur de taches' est demarre" -ForegroundColor Yellow
    Write-Host  "         et que votre compte est bien administrateur de la machine."    -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------------------
# Verification finale
# ---------------------------------------------------------------------------
$installed = Show-TaskStatus
if (-not $installed) {
    Write-Fail "La tache a ete creee mais reste introuvable : verifiez le Planificateur de taches."
    exit 1
}

Write-Host "==============================================================" -ForegroundColor White
Write-Host "  Demarrage automatique installe." -ForegroundColor Green
Write-Host ""
Write-Host "  A chaque ouverture de session Windows, apres 60 secondes :"    -ForegroundColor White
Write-Host "   - le Bridge demarre en arriere-plan, sans fenetre ;"          -ForegroundColor Gray
Write-Host "   - le tunnel ngrok s'ouvre sur votre domaine reserve"          -ForegroundColor Gray
Write-Host "     (si NGROK_ENABLED=true et NGROK_DOMAIN renseigne)."         -ForegroundColor Gray
Write-Host ""
Write-Host "  Pensez a mettre MetaTrader 5 en demarrage automatique lui aussi" -ForegroundColor Yellow
Write-Host "  (raccourci dans le dossier Demarrage : touche Windows + R, puis"  -ForegroundColor Yellow
Write-Host "  shell:startup)."                                                  -ForegroundColor Yellow
Write-Host ""
Write-Host "  Tester sans redemarrer : Start-ScheduledTask -TaskName $TaskName" -ForegroundColor Gray
Write-Host "  Voir l'etat            : .\scripts\install_autostart.ps1 -Status" -ForegroundColor Gray
Write-Host "  Desinstaller           : .\scripts\install_autostart.ps1 -Remove" -ForegroundColor Gray
Write-Host "==============================================================" -ForegroundColor White
Write-Host ""
exit 0
