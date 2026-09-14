<#
.SYNOPSIS
    Configure ngrok pour TradePilot : token, domaine reserve et fichier ngrok.yml.

.DESCRIPTION
    1. Localise le binaire ngrok (NGROK_BINARY, PATH, bridge\data\bin\ngrok.exe) ;
    2. enregistre le token avec "ngrok config add-authtoken" (le token n'est
       jamais affiche dans la console) ;
    3. ecrit NGROK_AUTHTOKEN, NGROK_DOMAIN et NGROK_ENABLED=true dans bridge\.env ;
    4. ecrit bridge\data\ngrok.yml (format version 3) avec un tunnel nomme
       "tradepilot" pointant sur le port du Bridge, en HTTPS uniquement ;
    5. rappelle comment reserver un domaine gratuit sur le tableau de bord ngrok ;
    6. avec -Test, ouvre le tunnel quelques secondes pour verifier qu'il monte.

.PARAMETER AuthToken
    Token ngrok (https://dashboard.ngrok.com/get-started/your-authtoken).

.PARAMETER Domain
    Domaine reserve, par exemple tradepilot-xyz.ngrok-free.app. Il doit
    correspondre EXACTEMENT au domaine reserve sur le tableau de bord ngrok.

.PARAMETER Port
    Port local du Bridge. Par defaut : la valeur BRIDGE_PORT de bridge\.env.

.PARAMETER Test
    Lance reellement le tunnel pendant quelques secondes puis l'arrete.

.EXAMPLE
    .\scripts\setup_ngrok.ps1 -AuthToken "2ab..." -Domain "tradepilot-xyz.ngrok-free.app"

.EXAMPLE
    .\scripts\setup_ngrok.ps1 -Domain "tradepilot-xyz.ngrok-free.app" -Test
#>
[CmdletBinding()]
param(
    [string]$AuthToken = "",
    [string]$Domain = "",
    [int]$Port = 0,
    [switch]$Test
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot   = Split-Path -Parent $ScriptDir
$BridgeDir  = Join-Path $RepoRoot  "bridge"
$EnvFile    = Join-Path $BridgeDir ".env"
$DataDir    = Join-Path $BridgeDir "data"
$BinDir     = Join-Path $DataDir   "bin"
$LocalNgrok = Join-Path $BinDir    "ngrok.exe"
$NgrokYml   = Join-Path $DataDir   "ngrok.yml"

function Write-Ok    { param([string]$Message) Write-Host ("[OK]        " + $Message) -ForegroundColor Green }
function Write-Info  { param([string]$Message) Write-Host ("[INFO]      " + $Message) -ForegroundColor Gray }
function Write-Warn  { param([string]$Message) Write-Host ("[ATTENTION] " + $Message) -ForegroundColor Yellow }
function Write-Fail  { param([string]$Message) Write-Host ("[ERREUR]    " + $Message) -ForegroundColor Red }

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

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  TradePilot - configuration de ngrok"                          -ForegroundColor White
Write-Host "==============================================================" -ForegroundColor White
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Localisation du binaire ngrok
# ---------------------------------------------------------------------------
$ngrokPath = $null
$configured = Get-EnvValue -Path $EnvFile -Key "NGROK_BINARY"
if ($configured -and (Test-Path -LiteralPath $configured)) {
    $ngrokPath = $configured
} else {
    $inPath = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($inPath) {
        $ngrokPath = $inPath.Source
    } elseif (Test-Path -LiteralPath $LocalNgrok) {
        $ngrokPath = $LocalNgrok
    }
}

if (-not $ngrokPath) {
    Write-Fail "ngrok est introuvable."
    Write-Host "         Installez-le avec :  .\scripts\install_bridge.ps1 -WithNgrok"   -ForegroundColor Yellow
    Write-Host "         ou telechargez-le sur https://ngrok.com/download et copiez"     -ForegroundColor Yellow
    Write-Host "         ngrok.exe dans bridge\data\bin\."                               -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$versionRes = Invoke-Capture -FilePath $ngrokPath -Arguments @("version")
Write-Ok ("ngrok trouve : " + $ngrokPath)
Write-Info ("Version : " + $versionRes.Output)

# ---------------------------------------------------------------------------
# 2. Port du Bridge
# ---------------------------------------------------------------------------
if ($Port -le 0) {
    $portValue = Get-EnvValue -Path $EnvFile -Key "BRIDGE_PORT"
    if ($portValue -and ($portValue -match "^\d+$")) { $Port = [int]$portValue } else { $Port = 8787 }
}
Write-Info ("Port local du Bridge : " + $Port)

# ---------------------------------------------------------------------------
# 3. Token
# ---------------------------------------------------------------------------
Write-Host ""
if (-not [string]::IsNullOrWhiteSpace($AuthToken)) {
    $tokenValue = $AuthToken.Trim()
    $addRes = Invoke-Capture -FilePath $ngrokPath -Arguments @("config", "add-authtoken", $tokenValue)
    if ($addRes.ExitCode -eq 0) {
        Write-Ok "Token enregistre dans la configuration ngrok (valeur jamais affichee)."
    } else {
        # On n'affiche pas la sortie brute : elle pourrait contenir le token.
        Write-Warn "ngrok a refuse le token. Verifiez-le sur https://dashboard.ngrok.com/get-started/your-authtoken"
    }
    if (Set-EnvValue -Path $EnvFile -Key "NGROK_AUTHTOKEN" -Value $tokenValue) {
        Write-Ok "NGROK_AUTHTOKEN ecrit dans bridge\.env (valeur jamais affichee)."
    }
} else {
    $existingToken = Get-EnvValue -Path $EnvFile -Key "NGROK_AUTHTOKEN"
    if ([string]::IsNullOrWhiteSpace($existingToken)) {
        Write-Warn "Aucun token fourni et NGROK_AUTHTOKEN est vide dans bridge\.env."
        Write-Host "            Recuperez-le sur https://dashboard.ngrok.com/get-started/your-authtoken" -ForegroundColor Yellow
        Write-Host "            puis relancez :  .\scripts\setup_ngrok.ps1 -AuthToken <votre-token>"      -ForegroundColor Yellow
    } else {
        Write-Info "NGROK_AUTHTOKEN deja renseigne dans bridge\.env : conserve."
    }
}

# ---------------------------------------------------------------------------
# 4. Domaine reserve
# ---------------------------------------------------------------------------
Write-Host ""
$finalDomain = $null
if (-not [string]::IsNullOrWhiteSpace($Domain)) {
    $finalDomain = $Domain.Trim().Replace("https://", "").Replace("http://", "").TrimEnd("/")
    if (Set-EnvValue -Path $EnvFile -Key "NGROK_DOMAIN" -Value $finalDomain) {
        Write-Ok ("NGROK_DOMAIN ecrit dans bridge\.env : " + $finalDomain)
    }
} else {
    $finalDomain = Get-EnvValue -Path $EnvFile -Key "NGROK_DOMAIN"
    if ([string]::IsNullOrWhiteSpace($finalDomain)) {
        $finalDomain = $null
        Write-Warn "Aucun domaine reserve n'est configure."
    } else {
        Write-Info ("Domaine deja configure : " + $finalDomain)
    }
}

if ($finalDomain) {
    $null = Set-EnvValue -Path $EnvFile -Key "NGROK_ENABLED" -Value "true"
    Write-Ok "NGROK_ENABLED=true : le tunnel s'ouvrira avec le Bridge."
}

Write-Host ""
Write-Host "  COMMENT RESERVER UN DOMAINE GRATUIT" -ForegroundColor Cyan
Write-Host "  ----------------------------------------------------------" -ForegroundColor Cyan
Write-Host "   1. Creez un compte gratuit sur https://ngrok.com"                     -ForegroundColor Gray
Write-Host "   2. Ouvrez https://dashboard.ngrok.com/domains"                        -ForegroundColor Gray
Write-Host "   3. Cliquez sur 'New Domain' : l'offre gratuite inclut UN domaine"     -ForegroundColor Gray
Write-Host "      statique du type  quelque-chose.ngrok-free.app"                    -ForegroundColor Gray
Write-Host "   4. Copiez ce domaine EXACTEMENT (sans https://, sans / final) et"     -ForegroundColor Gray
Write-Host "      relancez :  .\scripts\setup_ngrok.ps1 -Domain <votre-domaine>"     -ForegroundColor Gray
Write-Host ""
Write-Host "   IMPORTANT : la valeur NGROK_DOMAIN de bridge\.env doit correspondre"  -ForegroundColor Yellow
Write-Host "   caractere pour caractere au domaine reserve sur le tableau de bord."  -ForegroundColor Yellow
Write-Host "   Sinon ngrok refuse le tunnel (erreur ERR_NGROK_313 / 8012) et"        -ForegroundColor Yellow
Write-Host "   l'application mobile ne trouvera pas le Bridge."                      -ForegroundColor Yellow
Write-Host ""

# ---------------------------------------------------------------------------
# 5. Fichier de configuration ngrok.yml
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $DataDir)) { New-Item -ItemType Directory -Path $DataDir -Force | Out-Null }

$region = Get-EnvValue -Path $EnvFile -Key "NGROK_REGION"
if ([string]::IsNullOrWhiteSpace($region)) { $region = "eu" }

$domainLine = ""
if ($finalDomain) {
    $domainLine = "    domain: " + $finalDomain
} else {
    $domainLine = "    # domain: votre-domaine.ngrok-free.app   # a renseigner apres reservation"
}

$ymlLines = @(
    "# Configuration de l'agent ngrok pour TradePilot.",
    "# Fichier genere par scripts\setup_ngrok.ps1 - ne contient aucun secret.",
    "# Le token est stocke separement par 'ngrok config add-authtoken'.",
    "# Utilisation manuelle :",
    ("#   ngrok start --config " + [char]34 + $NgrokYml + [char]34 + " tradepilot"),
    'version: "3"',
    "agent:",
    ("  region: " + $region),
    "tunnels:",
    "  tradepilot:",
    "    proto: http",
    ("    addr: " + $Port),
    $domainLine,
    "    schemes:",
    "      - https"
)

Set-Content -LiteralPath $NgrokYml -Value $ymlLines -Encoding UTF8
Write-Ok ("Configuration ecrite : " + $NgrokYml)

# ---------------------------------------------------------------------------
# 6. Test optionnel du tunnel
# ---------------------------------------------------------------------------
if ($Test) {
    Write-Host ""
    if (-not $finalDomain) {
        Write-Fail "Test impossible : aucun domaine reserve configure."
        Write-Host "         Relancez avec -Domain <votre-domaine>." -ForegroundColor Yellow
        Write-Host ""
        exit 1
    }

    Write-Info ("Ouverture du tunnel de test vers le port " + $Port + " pendant 10 secondes...")
    $ngrokArgs = @("http", ("--domain=" + $finalDomain), $Port.ToString())
    $proc = $null
    try {
        $proc = Start-Process -FilePath $ngrokPath -ArgumentList $ngrokArgs -WindowStyle Hidden -PassThru
    } catch {
        Write-Fail ("Lancement de ngrok impossible : " + $_.Exception.Message)
        Write-Host ""
        exit 1
    }

    $publicUrl = $null
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        if ($proc.HasExited) { break }
        try {
            $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3 -ErrorAction Stop
            foreach ($tunnel in $tunnels.tunnels) {
                if ($tunnel.public_url) { $publicUrl = $tunnel.public_url; break }
            }
            if ($publicUrl) { break }
        } catch { }
    }

    if ($publicUrl) {
        Write-Ok ("Tunnel operationnel : " + $publicUrl)
        Write-Info "C'est l'adresse a saisir dans l'application mobile."
    } else {
        Write-Warn "Le tunnel n'a pas pu etre etabli en 10 secondes."
        Write-Host "            Causes frequentes :"                                            -ForegroundColor Yellow
        Write-Host "             - token absent ou invalide ;"                                  -ForegroundColor Yellow
        Write-Host "             - domaine non reserve sur votre compte ;"                      -ForegroundColor Yellow
        Write-Host "             - un autre agent ngrok tourne deja (ERR_NGROK_108) :"          -ForegroundColor Yellow
        Write-Host "               fermez-le avec  Stop-Process -Name ngrok -Force ;"           -ForegroundColor Yellow
        Write-Host "             - pare-feu ou proxy d'entreprise."                             -ForegroundColor Yellow
    }

    if ($proc -and -not $proc.HasExited) {
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
            Write-Info "Tunnel de test ferme."
        } catch {
            Write-Warn "Le processus ngrok de test n'a pas pu etre arrete automatiquement."
        }
    }
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  Configuration ngrok terminee." -ForegroundColor Green
if ($finalDomain) {
    Write-Host ("  URL publique du Bridge : https://" + $finalDomain) -ForegroundColor White
}
Write-Host "  Redemarrez le Bridge pour appliquer :"                        -ForegroundColor Gray
Write-Host "   .\scripts\stop_bridge.ps1"                                   -ForegroundColor Gray
Write-Host "   .\scripts\start_bridge_background.ps1"                       -ForegroundColor Gray
Write-Host "==============================================================" -ForegroundColor White
Write-Host ""
exit 0
