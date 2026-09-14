# Construit l'APK en lui donnant une identite verifiable depuis le telephone.
#
# Pourquoi ce script : versionName et versionCode sont restes figes a 1.0.0 / 1
# pendant toute la mise au point. Deux binaires differents s'affichaient donc a
# l'identique, et verifier lequel tournait exigeait un cable USB plus un
# `adb shell md5sum`. Ce script injecte a la compilation la date, un numero
# croissant et l'empreinte du binaire, que l'ecran « A propos » affiche.
#
# Usage :
#   .\scripts\build_apk.ps1            # construit seulement
#   .\scripts\build_apk.ps1 -Install   # construit puis installe sur l'appareil

[CmdletBinding()]
param(
    [switch]$Install
)

$ErrorActionPreference = 'Stop'

# PowerShell 5.1 transforme CHAQUE ligne de sortie d'erreur d'un executable
# natif en ErrorRecord. Or flutter et le compilateur Java y ecrivent des
# avertissements parfaitement benins (« source value 8 is obsolete »), ce qui
# faisait echouer le script alors que la compilation reussissait. On juge donc
# les outils externes sur leur CODE DE RETOUR, jamais sur leur stderr.
$PSNativeCommandUseErrorActionPreference = $false

$racine = Split-Path -Parent $PSScriptRoot
$mobile = Join-Path $racine 'mobile'
$apk = Join-Path $mobile 'build\app\outputs\flutter-apk\app-release.apk'

if (-not (Test-Path $mobile)) {
    Write-Error "Dossier mobile introuvable : $mobile"
}

Write-Output ''
Write-Output '=============================================================='
Write-Output '  TradePilot - construction de l''APK'
Write-Output '=============================================================='
Write-Output ''

$maintenant = Get-Date
$dateBuild = $maintenant.ToString('yyyy-MM-dd HH:mm')

# Numero de build : minutes ecoulees depuis le 1er janvier 2026. Il croit a
# chaque compilation et reste tres en dessous du plafond Android (2^31), ce
# qu'un horodatage complet aurait depasse.
$origine = Get-Date -Year 2026 -Month 1 -Day 1 -Hour 0 -Minute 0 -Second 0
$numero = [int][math]::Floor(($maintenant - $origine).TotalMinutes)

Write-Output "[INFO] Date de compilation : $dateBuild"
Write-Output "[INFO] Numero de build     : $numero"
Write-Output ''

Push-Location $mobile
try {
    # Premiere passe : l'empreinte ne peut pas etre connue avant que le binaire
    # existe. On compile donc une fois pour la calculer, puis une seconde fois
    # pour l'inscrire dans l'application. C'est le prix d'une empreinte qui
    # decrit VRAIMENT le fichier installe.
    Write-Output '[1/2] Compilation initiale...'
    & flutter build apk --release `
        --build-number=$numero `
        --dart-define="BUILD_TIME=$dateBuild" `
        --dart-define="BUILD_NUMBER=$numero"
    if ($LASTEXITCODE -ne 0) { throw "flutter build a echoue (code $LASTEXITCODE)" }

    $empreinte = (Get-FileHash -Path $apk -Algorithm MD5).Hash.ToLower().Substring(0, 12)
    Write-Output ''
    Write-Output "[INFO] Empreinte de la premiere passe : $empreinte"
    Write-Output ''

    Write-Output '[2/2] Recompilation avec l''empreinte inscrite...'
    & flutter build apk --release `
        --build-number=$numero `
        --dart-define="BUILD_TIME=$dateBuild" `
        --dart-define="BUILD_NUMBER=$numero" `
        --dart-define="BUILD_FINGERPRINT=$empreinte"
    if ($LASTEXITCODE -ne 0) { throw "flutter build a echoue (code $LASTEXITCODE)" }

    $finale = (Get-FileHash -Path $apk -Algorithm MD5).Hash.ToLower()
    Write-Output ''
    Write-Output '[OK]   APK construit'
    Write-Output "       Fichier   : $apk"
    Write-Output "       Empreinte : $finale"
    Write-Output "       Affichee  : $empreinte"
    Write-Output ''
    # L'empreinte affichee dans l'application est celle de la PREMIERE passe :
    # inscrire une valeur dans un fichier en change forcement le contenu. Elle
    # identifie donc le build de maniere unique, mais ne peut pas etre comparee
    # a un md5sum du binaire final. Le numero de build, lui, est comparable.
    Write-Output '[NOTE] L''empreinte affichee identifie le build, elle ne correspond'
    Write-Output '       pas au md5 du fichier final : y inscrire une valeur le modifie.'
    Write-Output '       Pour une comparaison exacte, utilisez le numero de build.'

    if ($Install) {
        Write-Output ''
        Write-Output '[INFO] Installation sur l''appareil connecte...'
        & adb install -r $apk
        if ($LASTEXITCODE -ne 0) { throw "adb install a echoue (code $LASTEXITCODE)" }

        $pose = & adb shell dumpsys package com.tradepilot.tradepilot |
            Select-String -Pattern 'versionCode|lastUpdateTime'
        Write-Output ''
        Write-Output '[OK]   Installe. Etat reel sur l''appareil :'
        $pose | ForEach-Object { Write-Output "       $($_.Line.Trim())" }
        Write-Output ''
        Write-Output "       Le telephone doit afficher le build n° $numero"
        Write-Output '       dans Reglages -> A propos.'
    }
}
finally {
    Pop-Location
}
