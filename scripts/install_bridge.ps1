<#
.SYNOPSIS
    Installation complete et idempotente du Bridge TradePilot sous Windows.

.DESCRIPTION
    Le script peut etre relance autant de fois que necessaire sans rien casser :
      1. verifie Python 3.11+ ;
      2. cree bridge\.venv s'il n'existe pas et met pip a jour ;
      3. installe bridge\requirements.txt ;
      4. cree bridge\.env a partir de .env.example s'il est absent ;
      5. genere une MASTER_KEY Fernet si la ligne MASTER_KEY est vide ;
      6. cree les dossiers data, data\logs, data\sessions, data\bin ;
      7. telecharge ngrok pour Windows amd64 (uniquement avec -WithNgrok ou sur reponse "oui") ;
      8. lance le diagnostic scripts\check_environment.ps1.

    Aucun secret (token, cle, mot de passe) n'est affiche dans la console.

.PARAMETER WithNgrok
    Telecharge ngrok sans poser de question.

.PARAMETER NgrokAuthToken
    Token ngrok a ecrire dans bridge\.env (jamais affiche). Active NGROK_ENABLED=true.

.PARAMETER NgrokDomain
    Domaine reserve ngrok a ecrire dans bridge\.env. Active NGROK_ENABLED=true.

.PARAMETER Force
    Recree l'environnement virtuel de zero, reinstalle les dependances,
    retelecharge ngrok et ecrase les valeurs ngrok deja presentes dans bridge\.env.
    La MASTER_KEY existante n'est JAMAIS ecrasee (elle chiffre vos donnees).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_bridge.ps1

.EXAMPLE
    .\scripts\install_bridge.ps1 -WithNgrok -NgrokDomain "tradepilot-xyz.ngrok-free.app" -NgrokAuthToken "2ab...."

.EXAMPLE
    .\scripts\install_bridge.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$WithNgrok,
    [string]$NgrokAuthToken = "",
    [string]$NgrokDomain = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$NGROK_URL = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot    = Split-Path -Parent $ScriptDir
$BridgeDir   = Join-Path $RepoRoot   "bridge"
$VenvDir     = Join-Path $BridgeDir  ".venv"
$VenvPython  = Join-Path $VenvDir    "Scripts\python.exe"
$EnvFile     = Join-Path $BridgeDir  ".env"
$EnvExample  = Join-Path $RepoRoot   ".env.example"
$Requirements = Join-Path $BridgeDir "requirements.txt"
$DataDir     = Join-Path $BridgeDir  "data"
$BinDir      = Join-Path $DataDir    "bin"
$LocalNgrok  = Join-Path $BinDir     "ngrok.exe"

# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------
function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ("==> " + $Message) -ForegroundColor Cyan
}
function Write-Ok    { param([string]$Message) Write-Host ("    [OK]    " + $Message) -ForegroundColor Green }
function Write-Info  { param([string]$Message) Write-Host ("    [INFO]  " + $Message) -ForegroundColor Gray }
function Write-Warn  { param([string]$Message) Write-Host ("    [ATTENTION] " + $Message) -ForegroundColor Yellow }
function Write-Fail  { param([string]$Message) Write-Host ("    [ERREUR] " + $Message) -ForegroundColor Red }

function Stop-WithMessage {
    param([string]$Message, [string]$Aide = "")
    Write-Host ""
    Write-Fail $Message
    if ($Aide) { Write-Host ("    " + $Aide) -ForegroundColor Yellow }
    Write-Host ""
    exit 1
}

# Execute un programme externe sans que la redirection 2>&1 ne fasse echouer
# le script (comportement specifique a PowerShell 5.1).
function Invoke-Capture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    $ErrorActionPreference = "Continue"
    $out = ""
    $code = -1
    try {
        $raw  = & $FilePath @Arguments 2>&1
        $code = $LASTEXITCODE
        $out  = ($raw | Out-String).Trim()
    } catch {
        $out  = $_.Exception.Message
        $code = -1
    }
    return [pscustomobject]@{ ExitCode = $code; Output = $out }
}

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

# Ecrit ou met a jour une cle dans le .env en preservant le reste du fichier.
# La valeur n'est jamais affichee dans la console.
function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @(Get-Content -LiteralPath $Path)
    }
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
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  TradePilot - installation du Bridge (Windows)"                -ForegroundColor White
Write-Host "  Projet : $RepoRoot"                                           -ForegroundColor DarkGray
Write-Host "==============================================================" -ForegroundColor White

if (-not (Test-Path -LiteralPath $BridgeDir)) {
    Stop-WithMessage "Le dossier 'bridge' est introuvable dans $RepoRoot." "Lancez ce script depuis le depot TradePilot (dossier scripts\)."
}

# ---------------------------------------------------------------------------
# 1. Python
# ---------------------------------------------------------------------------
Write-Step "1/8 Verification de Python"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Stop-WithMessage "Python n'est pas installe (ou pas dans le PATH)." "Telechargez Python 3.11 ou plus recent ici : https://www.python.org/downloads/windows/ - cochez 'Add python.exe to PATH' pendant l'installation, puis relancez ce script."
}

$versionRes = Invoke-Capture -FilePath $pythonCmd.Source -Arguments @("--version")
if ($versionRes.Output -notmatch "(\d+)\.(\d+)\.(\d+)") {
    Stop-WithMessage "Impossible de lire la version de Python ($($versionRes.Output))." "Reinstallez Python 3.11+ : https://www.python.org/downloads/windows/"
}
$pyMajor = [int]$Matches[1]
$pyMinor = [int]$Matches[2]
if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
    Stop-WithMessage "Python $pyMajor.$pyMinor detecte : le Bridge exige Python 3.11 minimum." "Telechargez une version recente ici : https://www.python.org/downloads/windows/"
}
Write-Ok "$($versionRes.Output) - $($pythonCmd.Source)"

# ---------------------------------------------------------------------------
# 2. Environnement virtuel
# ---------------------------------------------------------------------------
Write-Step "2/8 Environnement virtuel bridge\.venv"

if ($Force -and (Test-Path -LiteralPath $VenvDir)) {
    Write-Warn "-Force : suppression de l'environnement virtuel existant."
    try {
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    } catch {
        Stop-WithMessage "Impossible de supprimer $VenvDir." "Fermez tout programme utilisant cet environnement (Bridge en cours, editeur de code) puis relancez."
    }
}

if (Test-Path -LiteralPath $VenvPython) {
    Write-Ok "Environnement deja present : $VenvDir"
} else {
    Write-Info "Creation de l'environnement virtuel (quelques secondes)..."
    $venvRes = Invoke-Capture -FilePath $pythonCmd.Source -Arguments @("-m", "venv", $VenvDir)
    if ($venvRes.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
        Stop-WithMessage "La creation de l'environnement virtuel a echoue." ("Detail : " + $venvRes.Output)
    }
    Write-Ok "Environnement cree : $VenvDir"
}

# ---------------------------------------------------------------------------
# 3. Dependances
# ---------------------------------------------------------------------------
Write-Step "3/8 Installation des dependances Python"

Write-Info "Mise a jour de pip..."
$pipUp = Invoke-Capture -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check", "--quiet")
if ($pipUp.ExitCode -ne 0) {
    Write-Warn "La mise a jour de pip a echoue, on continue avec la version actuelle."
} else {
    Write-Ok "pip a jour."
}

if (-not (Test-Path -LiteralPath $Requirements)) {
    Stop-WithMessage "Fichier introuvable : $Requirements" "Le depot semble incomplet. Recuperez le projet complet puis relancez."
}

Write-Info "Installation de bridge\requirements.txt (peut prendre 1 a 3 minutes)..."
$pipArgs = @("-m", "pip", "install", "-r", $Requirements, "--disable-pip-version-check")
if ($Force) { $pipArgs += "--upgrade" }
$pipRes = Invoke-Capture -FilePath $VenvPython -Arguments $pipArgs
if ($pipRes.ExitCode -ne 0) {
    Write-Host $pipRes.Output -ForegroundColor DarkGray
    Stop-WithMessage "L'installation des dependances a echoue." "Verifiez votre connexion Internet puis relancez le script. Si l'erreur concerne MetaTrader5, verifiez que vous utilisez un Python 64 bits."
}
Write-Ok "Dependances installees."

# ---------------------------------------------------------------------------
# 4. Fichier de configuration
# ---------------------------------------------------------------------------
Write-Step "4/8 Fichier de configuration bridge\.env"

if (Test-Path -LiteralPath $EnvFile) {
    Write-Ok "bridge\.env deja present : il n'est pas ecrase."
} else {
    if (-not (Test-Path -LiteralPath $EnvExample)) {
        Stop-WithMessage "Modele introuvable : $EnvExample" "Impossible de creer bridge\.env automatiquement."
    }
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
    Write-Ok "bridge\.env cree a partir de .env.example."
    Write-Info "Pensez a y renseigner TELEGRAM_API_ID, TELEGRAM_API_HASH et OPENROUTER_API_KEY."
}

# ---------------------------------------------------------------------------
# 5. Cle maitre de chiffrement
# ---------------------------------------------------------------------------
Write-Step "5/8 Cle maitre de chiffrement (MASTER_KEY)"

$currentKey = Get-EnvValue -Path $EnvFile -Key "MASTER_KEY"
if (-not [string]::IsNullOrWhiteSpace($currentKey)) {
    Write-Ok "MASTER_KEY deja renseignee (valeur jamais affichee)."
} else {
    $keyRes = Invoke-Capture -FilePath $VenvPython -Arguments @("-c", "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    if ($keyRes.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($keyRes.Output)) {
        Stop-WithMessage "Generation de la MASTER_KEY impossible." ("Detail : " + $keyRes.Output)
    }
    Set-EnvValue -Path $EnvFile -Key "MASTER_KEY" -Value ($keyRes.Output.Trim())
    Write-Ok "MASTER_KEY generee et ecrite dans bridge\.env (valeur jamais affichee)."
    Write-Host ""
    Write-Host "    ***********************************************************" -ForegroundColor Yellow
    Write-Host "    AVERTISSEMENT IMPORTANT" -ForegroundColor Yellow
    Write-Host "    Cette cle chiffre TOUS vos secrets (session Telegram, cles API)." -ForegroundColor Yellow
    Write-Host "    Sauvegardez le fichier bridge\.env dans un endroit sur." -ForegroundColor Yellow
    Write-Host "    Si vous le perdez, il faudra tout reconfigurer depuis zero." -ForegroundColor Yellow
    Write-Host "    Ne le partagez jamais et ne le mettez jamais sur Git." -ForegroundColor Yellow
    Write-Host "    ***********************************************************" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 6. Dossiers de donnees
# ---------------------------------------------------------------------------
Write-Step "6/8 Dossiers de donnees"

foreach ($dir in @($DataDir, (Join-Path $DataDir "logs"), (Join-Path $DataDir "sessions"), $BinDir)) {
    if (Test-Path -LiteralPath $dir) {
        Write-Info ("Deja present : " + $dir)
    } else {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Ok ("Cree : " + $dir)
    }
}

# ---------------------------------------------------------------------------
# 7. ngrok
# ---------------------------------------------------------------------------
Write-Step "7/8 ngrok (acces distant depuis le telephone)"

$ngrokInPath = Get-Command ngrok -ErrorAction SilentlyContinue
$ngrokReady  = $false
if ($ngrokInPath) {
    Write-Ok ("ngrok deja disponible dans le PATH : " + $ngrokInPath.Source)
    $ngrokReady = $true
} elseif ((Test-Path -LiteralPath $LocalNgrok) -and (-not $Force)) {
    Write-Ok ("ngrok deja present : " + $LocalNgrok)
    $ngrokReady = $true
}

$doDownload = $false
if (-not $ngrokReady) {
    if ($WithNgrok) {
        $doDownload = $true
    } elseif ([Environment]::UserInteractive) {
        Write-Host ""
        Write-Host "    ngrok permet d'atteindre le Bridge depuis votre telephone hors du Wi-Fi." -ForegroundColor Gray
        Write-Host "    Le Bridge fonctionne sans ngrok (acces reseau local uniquement)."         -ForegroundColor Gray
        $answer = Read-Host "    Telecharger ngrok maintenant ? (o/N)"
        if ($answer -match "^(o|oui|y|yes)$") { $doDownload = $true }
    } else {
        Write-Info "Mode non interactif : telechargement de ngrok ignore (utilisez -WithNgrok)."
    }
}

if ($doDownload) {
    $tempZip = Join-Path $env:TEMP ("ngrok-" + [Guid]::NewGuid().ToString("N") + ".zip")
    $tempDir = Join-Path $env:TEMP ("ngrok-" + [Guid]::NewGuid().ToString("N"))
    try {
        # PowerShell 5.1 negocie TLS 1.0 par defaut : forcer TLS 1.2 pour le CDN.
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Info "Telechargement de ngrok (Windows amd64)..."
        Invoke-WebRequest -Uri $NGROK_URL -OutFile $tempZip -UseBasicParsing
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
        Expand-Archive -LiteralPath $tempZip -DestinationPath $tempDir -Force
        $extracted = Get-ChildItem -LiteralPath $tempDir -Filter "ngrok.exe" -Recurse | Select-Object -First 1
        if (-not $extracted) {
            throw "ngrok.exe absent de l'archive telechargee."
        }
        Copy-Item -LiteralPath $extracted.FullName -Destination $LocalNgrok -Force
        Write-Ok ("ngrok installe : " + $LocalNgrok)
        $ngrokReady = $true
    } catch {
        Write-Warn ("Telechargement de ngrok impossible : " + $_.Exception.Message)
        Write-Warn "Vous pouvez l'installer manuellement depuis https://ngrok.com/download et copier ngrok.exe dans bridge\data\bin\."
    } finally {
        if (Test-Path -LiteralPath $tempZip) { Remove-Item -LiteralPath $tempZip -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $tempDir) { Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

if (-not $ngrokReady) {
    Write-Info "Le Bridge restera utilisable en reseau local, sans acces distant."
}

# Ecriture des parametres ngrok fournis en ligne de commande.
$ngrokConfigured = $false

if (-not [string]::IsNullOrWhiteSpace($NgrokAuthToken)) {
    $existingToken = Get-EnvValue -Path $EnvFile -Key "NGROK_AUTHTOKEN"
    if ((-not [string]::IsNullOrWhiteSpace($existingToken)) -and (-not $Force)) {
        Write-Info "NGROK_AUTHTOKEN deja renseigne : conserve (utilisez -Force pour l'ecraser)."
    } else {
        Set-EnvValue -Path $EnvFile -Key "NGROK_AUTHTOKEN" -Value $NgrokAuthToken.Trim()
        Write-Ok "NGROK_AUTHTOKEN ecrit dans bridge\.env (valeur jamais affichee)."
    }
    $ngrokConfigured = $true
}

if (-not [string]::IsNullOrWhiteSpace($NgrokDomain)) {
    $domain = $NgrokDomain.Trim().Replace("https://", "").Replace("http://", "").TrimEnd("/")
    Set-EnvValue -Path $EnvFile -Key "NGROK_DOMAIN" -Value $domain
    Write-Ok ("NGROK_DOMAIN ecrit dans bridge\.env : " + $domain)
    $ngrokConfigured = $true
}

if ($ngrokConfigured) {
    Set-EnvValue -Path $EnvFile -Key "NGROK_ENABLED" -Value "true"
    Write-Ok "NGROK_ENABLED=true : le tunnel demarrera avec le Bridge."
}

if ($ngrokReady -and (-not $ngrokConfigured)) {
    $existingDomain = Get-EnvValue -Path $EnvFile -Key "NGROK_DOMAIN"
    if ([string]::IsNullOrWhiteSpace($existingDomain)) {
        Write-Info "Pour finir la configuration du tunnel : .\scripts\setup_ngrok.ps1 -AuthToken <token> -Domain <votre-domaine>"
    }
}

# ---------------------------------------------------------------------------
# 8. Diagnostic final
# ---------------------------------------------------------------------------
Write-Step "8/8 Diagnostic de l'environnement"

$checkScript = Join-Path $ScriptDir "check_environment.ps1"
if (Test-Path -LiteralPath $checkScript) {
    & $checkScript
    $checkCode = $LASTEXITCODE
} else {
    Write-Warn "check_environment.ps1 introuvable : diagnostic ignore."
    $checkCode = 0
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  Installation terminee." -ForegroundColor Green
Write-Host "  Etapes suivantes :" -ForegroundColor White
Write-Host "   1. Ouvrez bridge\.env et renseignez vos identifiants Telegram / OpenRouter." -ForegroundColor Gray
Write-Host "   2. Lancez MetaTrader 5 Desktop et connectez-vous a votre compte demo."       -ForegroundColor Gray
Write-Host "   3. Demarrage manuel   : .\scripts\start_bridge.ps1"                           -ForegroundColor Gray
Write-Host "   4. Demarrage au boot  : console admin puis .\scripts\install_autostart.ps1"   -ForegroundColor Gray
Write-Host "==============================================================" -ForegroundColor White
Write-Host ""

if ($checkCode -ne 0) { exit 1 }
exit 0
