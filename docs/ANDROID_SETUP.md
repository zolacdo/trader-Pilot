# Construction de l'application Android

Ce guide décrit comment construire l'APK TradePilot depuis le dossier `mobile/`
et l'installer sur un téléphone.

Le Bridge, lui, s'installe séparément sur le PC Windows :
voir [BRIDGE_WINDOWS_SETUP.md](BRIDGE_WINDOWS_SETUP.md).

---

## 1. Prérequis

| Élément | Version attendue | Vérification |
|---|---|---|
| Flutter SDK | canal stable, Dart `>=3.5.0 <4.0.0` | `flutter --version` |
| Android SDK | plateforme et *build-tools* installées | `flutter doctor` |
| JDK | 17 ou plus (fourni avec Android Studio) | `java -version` |
| Gradle | **8.12**, téléchargé automatiquement par le wrapper | `mobile/android/gradle/wrapper/gradle-wrapper.properties` |
| Android Gradle Plugin | **8.9.1** | `mobile/android/settings.gradle.kts` |
| Kotlin | **2.1.0** | `mobile/android/settings.gradle.kts` |
| Android minimum | **API 23** (Android 6.0) | `mobile/android/app/build.gradle.kts` |

Le minimum d'API 23 est imposé par `flutter_secure_storage`, qui s'appuie sur
`EncryptedSharedPreferences`. C'est là que sont stockés l'adresse du Bridge et le
jeton de périphérique.

Vérifiez l'installation complète :

```powershell
flutter doctor -v
```

### 1.1 `android/local.properties`

Ce fichier n'est pas versionné (voir `.gitignore`). Il indique à Gradle où
trouver les deux SDK. Créez-le s'il est absent, dans
`mobile\android\local.properties` :

```properties
sdk.dir=C:\\Android
flutter.sdk=C:\\flutter
```

Adaptez les deux chemins à votre installation. Les antislashs doivent être
doublés : c'est un fichier de propriétés Java.

---

## 2. Installer les dépendances

Toutes les commandes de ce document se lancent depuis `mobile/` :

```powershell
cd "C:\Users\<votre-nom>\Desktop\trader apk\mobile"
```

```powershell
flutter pub get
```

---

## 3. Générer le code

La base locale hors ligne utilise **Drift**, qui repose sur de la génération de
code. Le fichier `lib/core/database/local_database.g.dart` doit être régénéré
après toute modification de `lib/core/database/local_database.dart` :

```powershell
dart run build_runner build --delete-conflicting-outputs
```

L'option `--delete-conflicting-outputs` évite l'échec « conflicting outputs »
lorsqu'un fichier généré existe déjà.

Pendant le développement, la variante qui régénère à la volée :

```powershell
dart run build_runner watch --delete-conflicting-outputs
```

L'icône de l'application est générée depuis `assets/icon/tradepilot_icon.png` et
`assets/icon/tradepilot_icon_foreground.png` par `flutter_launcher_icons`. Elle
n'a besoin d'être régénérée que si vous changez ces images :

```powershell
dart run flutter_launcher_icons
```

---

## 4. Vérifier le code

```powershell
flutter analyze
```

Résultat attendu : `No issues found!`. Le projet inclut
`package:flutter_lints/flutter.yaml` via `analysis_options.yaml`.

```powershell
flutter test
```

Résultat attendu : `All tests passed!`. La suite compte **29 tests** répartis sur
quatre fichiers :

| Fichier | Ce qu'il couvre |
|---|---|
| `test/widget_test.dart` | thème et couleurs, couleur d'un montant selon son signe, bandeau hors ligne, pastille de direction BUY/SELL, blocage de la confirmation par phrase exacte |
| `test/signals_channels_test.dart` | écrans Signaux et Canaux |
| `test/signals_channels_layout_test.dart` | mise en page de ces mêmes écrans |
| `test/trades_risk_settings_test.dart` | Trades, réglages de risque, section trading en mode réel déverrouillé, absence de modèle gratuit, erreur d'historique, apparence et notifications |

---

## 5. Construire l'APK

### 5.1 Construction de release

```powershell
flutter build apk --release
```

L'APK produit se trouve dans :

```
mobile\build\app\outputs\flutter-apk\app-release.apk
```

> Le dossier de sortie de Gradle est redirigé vers `mobile\build\` par
> `android/build.gradle.kts`. C'est bien ce chemin qu'il faut regarder.

### 5.2 Variantes utiles

| Commande | Résultat |
|---|---|
| `flutter build apk --release` | un APK universel, le plus simple à transférer |
| `flutter build apk --release --split-per-abi` | trois APK plus légers : `app-armeabi-v7a-release.apk`, `app-arm64-v8a-release.apk`, `app-x86_64-release.apk`. Sur un téléphone récent, prenez `arm64-v8a`. |
| `flutter build apk --debug` | build de développement, plus lourde et plus lente |
| `flutter build appbundle --release` | `.aab` pour le Play Store — inutile pour un usage personnel |

En cas de build capricieuse :

```powershell
flutter clean
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter build apk --release
```

---

## 6. Installer sur le téléphone

### 6.1 Avec `adb` (câble USB)

Sur le téléphone : *Paramètres → À propos du téléphone*, tapez sept fois sur
« Numéro de build » pour activer les options de développement, puis activez
**Débogage USB**.

```powershell
adb devices
adb install -r "C:\Users\<votre-nom>\Desktop\trader apk\mobile\build\app\outputs\flutter-apk\app-release.apk"
```

`-r` réinstalle par-dessus une version existante en conservant les données.

Si l'installation échoue avec `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, c'est que
l'APK installé est signé avec une autre clé (par exemple une build de debug
remplacée par une build signée). Désinstallez d'abord :

```powershell
adb uninstall com.tradepilot.tradepilot
adb install "C:\Users\<votre-nom>\Desktop\trader apk\mobile\build\app\outputs\flutter-apk\app-release.apk"
```

Autre voie, avec un téléphone branché et détecté par Flutter :

```powershell
flutter install --release
```

### 6.2 Par transfert de fichier

Copiez `app-release.apk` sur le téléphone (câble USB, carte SD, service de
fichiers, partage local). Ouvrez-le avec le gestionnaire de fichiers du
téléphone et autorisez l'installation depuis cette source lorsque Android le
demande.

Le nom du paquet est `com.tradepilot.tradepilot` ; l'application apparaît sous le
libellé **TradePilot**.

### 6.3 Permissions demandées

Déclarées dans `mobile/android/app/src/main/AndroidManifest.xml` :

| Permission | Pourquoi |
|---|---|
| `INTERNET` | joindre le Bridge en HTTP et en WebSocket |
| `ACCESS_NETWORK_STATE` | savoir si le téléphone a un réseau |
| `POST_NOTIFICATIONS` | notifications locales (signal reçu, TP atteint, limite de perte…) |
| `VIBRATE` | vibration des notifications |
| `CAMERA` | photographier un graphique pour l'analyse IA ; déclarée `required="false"`, l'application fonctionne sans appareil photo |

Aucune permission de localisation, de contacts, de SMS ni de stockage étendu
n'est demandée.

---

## 7. Signature de release

Sans configuration particulière, `flutter build apk --release` **retombe sur la
clé de débogage** : l'APK s'installe et fonctionne, mais reste une build de test.
Pour signer avec votre propre clé, il faut deux choses : un magasin de clés et le
fichier `key.properties`.

### 7.1 Créer un magasin de clés

```powershell
keytool -genkey -v -keystore "C:\Users\<votre-nom>\tradepilot.jks" -keyalg RSA -keysize 2048 -validity 10000 -alias tradepilot
```

`keytool` est fourni avec le JDK. Conservez ce fichier **et** ses mots de passe :
sans eux, vous ne pourrez plus jamais publier de mise à jour installable
par-dessus l'application existante.

### 7.2 Écrire `android/key.properties`

Créez le fichier **`mobile\android\key.properties`** — c'est bien le dossier
`android`, pas `android/app`, car `build.gradle.kts` le lit avec
`rootProject.file("key.properties")`.

Format exact attendu, quatre clés obligatoires :

```properties
storeFile=C:/Users/<votre-nom>/tradepilot.jks
storePassword=<mot de passe du magasin>
keyAlias=tradepilot
keyPassword=<mot de passe de la clé>
```

Points de vigilance :

- utilisez des **barres obliques** `/` dans `storeFile`, ou doublez les
  antislashs (`C:\\Users\\...`) ; un antislash simple est un caractère
  d'échappement dans un fichier de propriétés ;
- pas de guillemets autour des valeurs ;
- pas d'espace avant ou après le signe `=` ;
- `keyAlias` doit correspondre exactement à l'alias passé à `keytool` ;
- ce fichier est **ignoré par Git** (`mobile/android/key.properties` figure dans
  le `.gitignore` racine, ainsi que `*.jks` et `*.keystore`). Ne le versionnez
  jamais.

### 7.3 Ce que fait Gradle

`mobile/android/app/build.gradle.kts` :

1. cherche `key.properties` à la racine du projet Android ;
2. s'il existe, charge les quatre propriétés et crée une `signingConfig`
   nommée `release` ;
3. le `buildType` `release` utilise cette configuration si elle existe, sinon la
   configuration `debug` ;
4. `isMinifyEnabled` et `isShrinkResources` sont à `false` : aucune obfuscation,
   ce qui simplifie le diagnostic d'une build.

Vérifier après coup qu'un APK est bien signé avec votre clé :

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\build-tools\<version>\apksigner.bat" verify --print-certs "C:\Users\<votre-nom>\Desktop\trader apk\mobile\build\app\outputs\flutter-apk\app-release.apk"
```

Adaptez le chemin de `apksigner` à votre installation du SDK Android
(`C:\Android\build-tools\<version>\apksigner.bat` si votre `sdk.dir` est
`C:\Android`).

---

## 8. Politique réseau : pourquoi du HTTP en clair

Depuis Android 9, le trafic HTTP non chiffré est bloqué par défaut. TradePilot
l'autorise explicitement dans
`mobile/android/app/src/main/res/xml/network_security_config.xml`, référencé par
l'attribut `android:networkSecurityConfig` du manifeste :

```xml
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
        </trust-anchors>
    </base-config>
</network-security-config>
```

### 8.1 La raison

Le Bridge tourne sur le PC personnel de l'utilisateur, **sans certificat TLS**.
En réseau local, le téléphone le joint sur une adresse privée du type
`192.168.x.x`, `10.x.x.x` ou `172.16-31.x.x`, qui n'est pas connue à l'avance et
change d'un domicile à l'autre. Android ne sait pas exprimer une **plage**
d'adresses dans ce fichier : on ne peut y déclarer que des noms de domaine
précis. Pour rendre le mode « réseau local » possible, le trafic en clair doit
donc être autorisé globalement.

### 8.2 Ce que cela n'affaiblit pas

- L'accès à distance passe par un **tunnel HTTPS** (ngrok ou votre propre
  domaine). Le client HTTP de l'application préfixe automatiquement `https://`
  toute adresse qui n'est pas une IP ou `localhost`.
- Toutes les routes sensibles du Bridge exigent le **jeton de périphérique** :
  le trafic en clair n'ouvre aucun accès anonyme.
- Aucun secret ne circule vers le téléphone : la clé OpenRouter, la session
  Telegram et les éventuels identifiants MetaTrader restent sur le Bridge et n'y
  sont lisibles que sous forme d'indice partiel (`sk-o...9f2a`).
- Le seul élément sensible transmis est le jeton de périphérique lui-même, dans
  l'en-tête `Authorization`.

### 8.3 Recommandation

Sur un réseau Wi-Fi que vous ne maîtrisez pas (lieu public, réseau partagé),
**utilisez l'adresse HTTPS du tunnel**, pas l'adresse IP locale. Le jeton
transiterait autrement en clair sur ce réseau. Voir [SECURITY.md](SECURITY.md).

---

## 9. Première utilisation

1. Démarrez le Bridge sur le PC ; notez le **code d'appairage** affiché dans la
   console (valable 15 minutes) et l'adresse.
2. Ouvrez TradePilot sur le téléphone. Tant qu'aucun appairage n'existe, toute
   la navigation est redirigée vers l'écran d'appairage.
3. Saisissez l'adresse du Bridge. Les trois formes suivantes sont acceptées et
   normalisées automatiquement : `192.168.1.20:8787`,
   `http://192.168.1.20:8787/`, `https://tradepilot-xyz.ngrok-free.app`.
4. Appuyez sur **Tester** : l'application interroge `GET /api/v1/health`, qui ne
   demande aucun jeton.
5. Saisissez le code au format `XXXX-XXXX` puis validez. Le Bridge renvoie un
   jeton de périphérique, stocké chiffré sur le téléphone.

En cas d'échec, consultez la section « L'APK ne se connecte pas au Bridge » de
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## 10. Les écrans de l'application

Tous les écrans sont implémentés. La navigation basse comporte cinq onglets ; les
autres écrans sont accessibles depuis l'onglet **Plus** ou par navigation
contextuelle.

| Onglet ou écran | Route | Contenu |
|---|---|---|
| Appairage | `/pairing` | premier écran tant que le téléphone n'est pas relié à un Bridge |
| Onboarding | `/onboarding` | parcours de première configuration |
| Accueil | `/` | mode d'exécution, chiffres du compte, état des liaisons, listes récentes, commandes de pilotage |
| Signaux | `/signals` | liste filtrable, bandeau de validation en attente |
| Détail d'un signal | `/signals/:id` | message brut, interprétation, timeline, trades, audit |
| Canaux | `/channels` | canaux surveillés, sélecteur de mode |
| Détail d'un canal | `/channels/:id` | réglages, profil de parser, analyses |
| Découvrir | `/channels/discover` | recherche de canaux publics |
| Comparaison | `/channels/compare` | tableau de comparaison |
| Trades | `/trades` | positions ouvertes, ordres en attente, historique fermé |
| Arrêt d'urgence | `/emergency` | annulation des ordres, fermeture de toutes les positions |
| Statistiques | `/more/statistics` | agrégats et graphiques |
| Analyse IA | `/more/ai` | analyse d'une capture de graphique |
| Journal | `/more/journal` | journal fonctionnel |
| Risque | `/more/risk` | tous les réglages du `RiskManager` |
| Connexions | `/more/connections` | état de Bridge, MT5, Telegram, OpenRouter |
| Réglages | `/more/settings` | appareils, OpenRouter, données, apparence, notifications |
| Diagnostic | `/more/diagnostics` | contrôles et tests unitaires de connexion |
| Correspondance des symboles | `/more/symbols` | alias, symbole canonique, symbole broker |
| Go Live | `/more/go-live` | checklist avant le mode réel |
| Plus | `/more` | accès aux écrans secondaires |

---

## 11. Ce qui n'a pas été vérifié sur cette machine

- Aucun APK n'a été construit ni installé sur un téléphone physique : la
  procédure ci-dessus décrit la configuration réelle du projet, pas un résultat
  observé.
- La signature de release n'a pas été exercée : aucun `key.properties` ni
  magasin de clés n'existe dans le dépôt, conformément au `.gitignore`.
- `flutter analyze` (aucun problème) et `flutter test` (**29 tests réussis**) ont
  bien été exécutés.
