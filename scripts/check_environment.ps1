<#
.SYNOPSIS
    Diagnostic complet de l'environnement TradePilot Bridge (lecture seule).

.DESCRIPTION
    Ce script ne modifie RIEN. Il verifie et affiche un tableau lisible :
      - Python 3.11+ et presence du venv bridge\.venv
      - Paquets Python indispensables (fastapi, telethon, MetaTrader5, cryptography, uvicorn)
      - Installation de MetaTrader 5 (terminal64.exe) et si le terminal tourne
      - Presence du fichier bridge\.env et si MASTER_KEY / NGROK_DOMAIN sont renseignes
        (la VALEUR n'est jamais affichee : seulement "renseigne" ou "vide")
      - Presence de ngrok (PATH ou bridge\data\bin\ngrok.exe) et sa version
      - Occupation du port BRIDGE_PORT
      - Connectivite Internet vers api.telegram.org et openrouter.ai

    Code de sortie : 0 si tout l'essentiel est OK, 1 s'il manque quelque chose d'essentiel.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_environment.ps1

.EXAMPLE
    .\scripts\check_environment.ps1
    Puis consulter $LASTEXITCODE : 0 = environnement pret, 1 = action requise.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Chemins de base
# ---------------------------------------------------------------------------
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot   = Split-Path -Parent $ScriptDir
$BridgeDir  = Join-Path $RepoRoot  "bridge"
$VenvDir    = Join-Path $BridgeDir ".venv"
$VenvPython = Join-Path $VenvDir   "Scripts\python.exe"
$EnvFile    = Join-Path $BridgeDir ".env"
$DataDir    = Join-Path $BridgeDir "data"
$LocalNgrok = Join-Path $DataDir   "bin\ngrok.exe"

$script:Problems = 0
$script:Warnings = 0

# ---------------------------------------------------------------------------
# Fonctions d'affichage
# ---------------------------------------------------------------------------
function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host ("-- " + $Title + " " + ("-" * [Math]::Max(4, 62 - $Title.Length))) -ForegroundColor Cyan
}

function Write-Result {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][ValidateSet("OK", "MANQUANT", "ATTENTION", "INFO")][string]$Status,
        [string]$Detail = ""
    )
    switch ($Status) {
        "OK"        { $tag = "[OK]        "; $color = "Green" }
        "MANQUANT"  { $tag = "[MANQUANT]  "; $color = "Red";    $script:Problems++ }
        "ATTENTION" { $tag = "[ATTENTION] "; $color = "Yellow"; $script:Warnings++ }
        default     { $tag = "[INFO]      "; $color = "Gray" }
    }
    $line = $tag + $Label.PadRight(34)
    if ($Detail) { $line = $line + " " + $Detail }
    Write-Host $line -ForegroundColor $color
}

# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------

# Execute un programme externe sans faire echouer le script. Sous PowerShell 5.1,
# rediriger la sortie d'erreur d'un .exe (2>&1) leve une NativeCommandError quand
# $ErrorActionPreference vaut "Stop" : on le neutralise localement.
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

# Lit une valeur dans un fichier .env. La valeur n'est jamais journalisee ici.
function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        if ($trimmed.Substring(0, $idx).Trim() -eq $Key) {
            $value = $trimmed.Substring($idx + 1).Trim()
            return $value.Trim([char]34).Trim([char]39)
        }
    }
    return $null
}

# Renvoie "renseigne" ou "vide" : ne revele JAMAIS le contenu d'un secret.
function Get-SecretState {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return "vide" }
    return "renseigne"
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
Write-Host "  TradePilot - diagnostic de l'environnement Windows"           -ForegroundColor White
Write-Host "  Dossier du projet : $RepoRoot"                                -ForegroundColor DarkGray
Write-Host "  Date : $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')"             -ForegroundColor DarkGray
Write-Host "==============================================================" -ForegroundColor White

# ---------------------------------------------------------------------------
# 1. Python et environnement virtuel
# ---------------------------------------------------------------------------
Write-Section "Python et environnement virtuel"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Result "Python installe" "MANQUANT" "commande 'python' introuvable - https://www.python.org/downloads/windows/"
} else {
    $res = Invoke-Capture -FilePath $pythonCmd.Source -Arguments @("--version")
    $versionText = $res.Output
    if ($versionText -match "(\d+)\.(\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
            Write-Result "Python 3.11+" "OK" "$versionText ($($pythonCmd.Source))"
        } else {
            Write-Result "Python 3.11+" "MANQUANT" "$versionText detecte - version 3.11 minimum requise"
        }
    } else {
        Write-Result "Python 3.11+" "ATTENTION" "version illisible : $versionText"
    }
}

if (Test-Path -LiteralPath $VenvPython) {
    $venvRes = Invoke-Capture -FilePath $VenvPython -Arguments @("--version")
    Write-Result "Environnement virtuel bridge\.venv" "OK" $venvRes.Output
} else {
    Write-Result "Environnement virtuel bridge\.venv" "MANQUANT" "lancer scripts\install_bridge.ps1"
}

# ---------------------------------------------------------------------------
# 2. Paquets Python
# ---------------------------------------------------------------------------
Write-Section "Paquets Python du venv"

# MetaTrader5 est optionnel au demarrage : le Bridge se lance sans lui mais ne
# peut pas trader. On le signale donc en ATTENTION et non en MANQUANT.
$packages = @(
    @{ Module = "fastapi";      Essential = $true  },
    @{ Module = "uvicorn";      Essential = $true  },
    @{ Module = "telethon";     Essential = $true  },
    @{ Module = "cryptography"; Essential = $true  },
    @{ Module = "MetaTrader5";  Essential = $false }
)

if (Test-Path -LiteralPath $VenvPython) {
    foreach ($pkg in $packages) {
        $module = $pkg.Module
        $check  = Invoke-Capture -FilePath $VenvPython -Arguments @("-c", "import $module")
        if ($check.ExitCode -eq 0) {
            $verCheck = Invoke-Capture -FilePath $VenvPython -Arguments @("-c", "import $module,sys; sys.stdout.write(str(getattr($module,'__version__','?')))")
            $ver = ""
            if ($verCheck.ExitCode -eq 0 -and $verCheck.Output) { $ver = "version " + $verCheck.Output }
            Write-Result ("Paquet " + $module) "OK" $ver
        } else {
            if ($pkg.Essential) {
                Write-Result ("Paquet " + $module) "MANQUANT" "relancer scripts\install_bridge.ps1"
            } else {
                Write-Result ("Paquet " + $module) "ATTENTION" "le Bridge demarrera mais ne pourra pas piloter MT5"
            }
        }
    }
} else {
    Write-Result "Paquets Python" "MANQUANT" "venv absent : verification impossible"
}

# ---------------------------------------------------------------------------
# 3. MetaTrader 5
# ---------------------------------------------------------------------------
Write-Section "MetaTrader 5"

$mt5SearchRoots = @(
    "C:\Program Files\MetaTrader 5*",
    "C:\Program Files\*MetaTrader*",
    "C:\Program Files (x86)\*MetaTrader*",
    (Join-Path $env:APPDATA "MetaQuotes\Terminal\*")
)

$foundTerminals = New-Object System.Collections.ArrayList
foreach ($pattern in $mt5SearchRoots) {
    $roots = @()
    try { $roots = @(Get-Item -Path $pattern -ErrorAction SilentlyContinue) } catch { $roots = @() }
    foreach ($root in $roots) {
        if (-not $root.PSIsContainer) { continue }
        $hits = @()
        try {
            $hits = @(Get-ChildItem -LiteralPath $root.FullName -Filter "terminal64.exe" -Recurse -Depth 2 -File -ErrorAction SilentlyContinue)
        } catch {
            $hits = @()
        }
        foreach ($hit in $hits) {
            if (-not $foundTerminals.Contains($hit.FullName)) { [void]$foundTerminals.Add($hit.FullName) }
        }
    }
}

if ($foundTerminals.Count -gt 0) {
    Write-Result "Terminal MetaTrader 5" "OK" ("$($foundTerminals.Count) installation(s) trouvee(s)")
    foreach ($terminal in $foundTerminals) {
        Write-Host ("             -> " + $terminal) -ForegroundColor DarkGray
    }
} else {
    Write-Result "Terminal MetaTrader 5" "ATTENTION" "terminal64.exe introuvable - installez MT5 Desktop (Exness)"
}

$mt5Process = @(Get-Process -Name "terminal64" -ErrorAction SilentlyContinue)
if ($mt5Process.Count -gt 0) {
    Write-Result "Processus terminal64 en cours" "OK" ("PID " + (($mt5Process | ForEach-Object { $_.Id }) -join ", "))
} else {
    Write-Result "Processus terminal64 en cours" "ATTENTION" "MT5 n'est pas lance : le Bridge ne pourra pas trader"
}

# ---------------------------------------------------------------------------
# 4. Configuration bridge\.env
# ---------------------------------------------------------------------------
Write-Section "Configuration bridge\.env"

$bridgePort = 8787
if (Test-Path -LiteralPath $EnvFile) {
    Write-Result "Fichier bridge\.env" "OK" $EnvFile

    $masterKey   = Get-EnvValue -Path $EnvFile -Key "MASTER_KEY"
    $ngrokDomain = Get-EnvValue -Path $EnvFile -Key "NGROK_DOMAIN"
    $ngrokToken  = Get-EnvValue -Path $EnvFile -Key "NGROK_AUTHTOKEN"
    $ngrokOn     = Get-EnvValue -Path $EnvFile -Key "NGROK_ENABLED"
    $portValue   = Get-EnvValue -Path $EnvFile -Key "BRIDGE_PORT"
    $hostValue   = Get-EnvValue -Path $EnvFile -Key "BRIDGE_HOST"
    $dataValue   = Get-EnvValue -Path $EnvFile -Key "DATA_DIR"

    if ((Get-SecretState $masterKey) -eq "renseigne") {
        Write-Result "MASTER_KEY" "OK" "renseigne (valeur jamais affichee)"
    } else {
        Write-Result "MASTER_KEY" "ATTENTION" "vide - une cle sera generee dans data\master.key au demarrage"
    }

    if ((Get-SecretState $ngrokDomain) -eq "renseigne") {
        Write-Result "NGROK_DOMAIN" "OK" "renseigne"
    } else {
        Write-Result "NGROK_DOMAIN" "ATTENTION" "vide - pas d'URL publique stable pour le telephone"
    }

    Write-Result "NGROK_AUTHTOKEN" "INFO" (Get-SecretState $ngrokToken)
    if ([string]::IsNullOrWhiteSpace($ngrokOn)) { $ngrokOn = "false" }
    Write-Result "NGROK_ENABLED" "INFO" $ngrokOn

    if ($portValue -and ($portValue -match "^\d+$")) { $bridgePort = [int]$portValue }
    if ([string]::IsNullOrWhiteSpace($hostValue)) { $hostValue = "127.0.0.1" }
    if ([string]::IsNullOrWhiteSpace($dataValue)) { $dataValue = "./data" }
    Write-Result "Ecoute prevue" "INFO" ($hostValue + ":" + $bridgePort)
    Write-Result "DATA_DIR" "INFO" $dataValue
} else {
    Write-Result "Fichier bridge\.env" "MANQUANT" "lancer scripts\install_bridge.ps1 (copie de .env.example)"
}

foreach ($dir in @($DataDir, (Join-Path $DataDir "logs"), (Join-Path $DataDir "sessions"), (Join-Path $DataDir "bin"))) {
    $short = $dir.Replace($RepoRoot + "\", "")
    if (Test-Path -LiteralPath $dir) {
        Write-Result ("Dossier " + $short) "OK" ""
    } else {
        Write-Result ("Dossier " + $short) "ATTENTION" "sera cree au premier demarrage"
    }
}

# ---------------------------------------------------------------------------
# 5. ngrok
# ---------------------------------------------------------------------------
Write-Section "ngrok (acces distant)"

$ngrokPath = $null
$configuredNgrok = $null
if (Test-Path -LiteralPath $EnvFile) { $configuredNgrok = Get-EnvValue -Path $EnvFile -Key "NGROK_BINARY" }

if ($configuredNgrok -and (Test-Path -LiteralPath $configuredNgrok)) {
    $ngrokPath = $configuredNgrok
} else {
    $ngrokCmd = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($ngrokCmd) {
        $ngrokPath = $ngrokCmd.Source
    } elseif (Test-Path -LiteralPath $LocalNgrok) {
        $ngrokPath = $LocalNgrok
    }
}

if ($ngrokPath) {
    $ngrokVersion = Invoke-Capture -FilePath $ngrokPath -Arguments @("version")
    Write-Result "Binaire ngrok" "OK" ($ngrokPath + " - " + $ngrokVersion.Output)
} else {
    Write-Result "Binaire ngrok" "ATTENTION" "absent du PATH et de bridge\data\bin - lancer install_bridge.ps1 -WithNgrok"
}

# L'agent ngrok expose une API locale sur le port 4040 quand il tourne.
try {
    $tunnels = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -TimeoutSec 3 -ErrorAction Stop
    $publicUrls = @()
    foreach ($tunnel in $tunnels.tunnels) { $publicUrls += $tunnel.public_url }
    if ($publicUrls.Count -gt 0) {
        Write-Result "Tunnel ngrok actif" "OK" ($publicUrls -join ", ")
    } else {
        Write-Result "Tunnel ngrok actif" "INFO" "agent demarre mais aucun tunnel ouvert"
    }
} catch {
    Write-Result "Tunnel ngrok actif" "INFO" "aucun agent ngrok en cours (normal si le Bridge est arrete)"
}

# ---------------------------------------------------------------------------
# 6. Port du Bridge
# ---------------------------------------------------------------------------
Write-Section "Port reseau du Bridge"

$portBusy = $false
try {
    $listeners = @(Get-NetTCPConnection -LocalPort $bridgePort -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $portBusy = $true
        $owners = @()
        foreach ($listener in $listeners) {
            $proc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
            if ($proc) {
                $owners += ($proc.ProcessName + " (PID " + $proc.Id + ")")
            } else {
                $owners += ("PID " + $listener.OwningProcess)
            }
        }
        Write-Result "Port $bridgePort" "ATTENTION" ("deja utilise par : " + (($owners | Select-Object -Unique) -join ", "))
    } else {
        Write-Result "Port $bridgePort" "OK" "libre"
    }
} catch {
    Write-Result "Port $bridgePort" "INFO" ("verification impossible : " + $_.Exception.Message)
}

if ($portBusy) {
    # Le Bridge repond-il deja sur ce port ?
    try {
        $null = Invoke-RestMethod -Uri ("http://127.0.0.1:" + $bridgePort + "/api/v1/health") -TimeoutSec 3 -ErrorAction Stop
        Write-Result "Bridge deja demarre" "OK" "l'API repond sur /api/v1/health"
    } catch {
        Write-Result "Bridge deja demarre" "ATTENTION" "le port est pris par un autre programme (voir ci-dessus)"
    }
}

# ---------------------------------------------------------------------------
# 7. Connectivite Internet
# ---------------------------------------------------------------------------
Write-Section "Connectivite Internet"

foreach ($target in @("api.telegram.org", "openrouter.ai")) {
    try {
        $reachable = Test-NetConnection -ComputerName $target -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue -ErrorAction Stop
        if ($reachable) {
            Write-Result ("HTTPS vers " + $target) "OK" "port 443 joignable"
        } else {
            Write-Result ("HTTPS vers " + $target) "ATTENTION" "injoignable (pare-feu, proxy ou coupure reseau)"
        }
    } catch {
        Write-Result ("HTTPS vers " + $target) "ATTENTION" ("test impossible : " + $_.Exception.Message)
    }
}

# ---------------------------------------------------------------------------
# Bilan
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "==============================================================" -ForegroundColor White
if ($script:Problems -eq 0) {
    Write-Host "  RESULTAT : environnement pret." -ForegroundColor Green
    if ($script:Warnings -gt 0) {
        Write-Host "  $($script:Warnings) point(s) d'attention ci-dessus, non bloquant(s)." -ForegroundColor Yellow
    }
    Write-Host "  Demarrage manuel  : .\scripts\start_bridge.ps1"            -ForegroundColor Gray
    Write-Host "  Demarrage en fond : .\scripts\start_bridge_background.ps1" -ForegroundColor Gray
    Write-Host "==============================================================" -ForegroundColor White
    Write-Host ""
    exit 0
} else {
    Write-Host "  RESULTAT : $($script:Problems) element(s) essentiel(s) manquant(s)." -ForegroundColor Red
    Write-Host "  Corrigez les lignes [MANQUANT] puis relancez ce diagnostic."         -ForegroundColor Red
    Write-Host "  Dans la plupart des cas : .\scripts\install_bridge.ps1"              -ForegroundColor Gray
    Write-Host "==============================================================" -ForegroundColor White
    Write-Host ""
    exit 1
}
