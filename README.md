# TradePilot

Auteur : **zolacdo** — <zolacdojeff@gmail.com>.

TradePilot est une passerelle personnelle entre des canaux Telegram de signaux de
trading et un terminal **MetaTrader 5 Desktop** installé sur un PC Windows.

Le système est composé de deux parties :

- le **Bridge** — un service Python (FastAPI) qui tourne sur le PC, lit les
  messages Telegram, les interprète, applique des règles de risque strictes et
  transmet les ordres au terminal MetaTrader 5 ;
- l'**application Android** (Flutter) — une télécommande qui affiche l'état du
  Bridge et permet de le piloter. Elle ne passe jamais d'ordre elle-même.

Le mode par défaut est **PAPER** : aucun ordre réel n'est envoyé tant que
l'utilisateur ne change pas explicitement de mode.

La connexion du téléphone au PC utilise **ngrok en HTTPS**. Le Bridge écoute
sur `127.0.0.1:8787` et ngrok fournit l'adresse publique à saisir dans
l'application, sur Wi-Fi comme sur réseau mobile.

---

## Ce que TradePilot fait

- Écoute en temps réel les canaux Telegram que vous avez explicitement mis sous
  surveillance, via une session utilisateur MTProto (pas un bot).
- Interprète chaque message avec un **parser déterministe local** (expressions
  régulières, analyse ligne par ligne). Ce parser ne consomme aucun quota et
  n'invente jamais une valeur absente du message.
- Fait appel à un modèle de langage **gratuit** via OpenRouter uniquement
  lorsque le message reste ambigu, et revalide systématiquement sa sortie
  localement.
- Valide la cohérence interne du signal (SL du bon côté, TP ordonnés, type
  d'ordre cohérent, distances plausibles).
- Applique un `RiskManager` complet — interrupteurs, canal, type de compte,
  fraîcheur du signal, fenêtres horaires, spread, limites journalières,
  drawdown, pertes consécutives, exposition, volume, marge — avant tout envoi.
- Calcule le volume à partir des métadonnées réelles du symbole MT5
  (`order_calc_profit`, puis `tick_value` / `tick_size`), jamais à partir d'une
  valeur de pip codée en dur.
- Effectue un `order_check` auprès du broker avant chaque `order_send`.
- Suit les positions ouvertes : take profits multiples, break even, trailing
  stop, réconciliation avec l'historique des deals du terminal.
- Interprète les messages de suivi d'un canal (`TP1 HIT`, `CLOSE 50%`,
  `MOVE SL TO BE`, `CANCEL PENDING`…) et les rattache au signal d'origine.
- Analyse l'historique d'un canal et produit un rapport de mesures factuelles,
  avec une simulation historique prudente et explicitement non concluante en cas
  de doute.
- Conserve un journal fonctionnel et un journal d'audit immuable des actions
  sensibles.
- Fait tourner l'**AI Market Watcher**, un sous-systeme autonome qui surveille
  les marches a partir des bougies MetaTrader reelles, note chaque instrument
  sur 100 critere par critere, et publie ses signaux expliques dans un canal
  Telegram. Il ne passe aucun ordre : il n'importe aucun module d'execution.

## Ce que TradePilot ne fait pas

- Il **ne prédit rien** et ne produit aucune recommandation d'achat ou de vente.
- Il **ne désigne jamais un « meilleur canal »** : le tableau de comparaison
  affiche des mesures observées, l'interprétation appartient à l'utilisateur.
- Il **n'invente jamais** un stop loss, un take profit, une direction ni un
  instrument. Ce qui n'est pas écrit dans le message reste `NULL`.
- Il **n'augmente jamais** le volume après une perte. Aucune martingale n'est
  implémentée, même en option.
- Il **ne rejoint jamais** un canal Telegram automatiquement.
- Il **ne bascule jamais** tout seul de démo vers réel : au démarrage, un mode
  réel non déverrouillé retombe systématiquement en `MT5_DEMO`.
- Il **n'exécute pas** un vieux signal après une reconnexion : la fraîcheur du
  message est vérifiée, et l'idempotence empêche tout doublon.
- Il **ne remplace pas** MetaTrader 5 : le terminal graphique doit être installé,
  ouvert et connecté sur le même PC.
- Il ne fonctionne **pas sans PC allumé**. Le téléphone seul ne trade pas.

---

## Architecture en une image

```
   Canaux Telegram                                   PC Windows (le Bridge)
 ┌────────────────────┐                    ┌──────────────────────────────────────┐
 │  @canal_signaux_1  │   session MTProto  │                                      │
 │  @canal_signaux_2  │ ─────────────────► │  Écoute Telegram (Telethon)          │
 └────────────────────┘                    │            │                         │
                                           │            ▼                         │
                                           │  Normalisation du message            │
                                           │            │                         │
                                           │            ▼                         │
                                           │  Parser déterministe local           │
                                           │            │                         │
                                           │            ▼ (si ambigu seulement)   │
   OpenRouter (modèles gratuits) ◄─────────┤  Repli IA — texte du message uniquement
                                           │            │                         │
                                           │            ▼                         │
                                           │  Validateur strict (local)           │
                                           │            │                         │
                                           │            ▼                         │
                                           │  RiskManager  ──► refus + motif      │
                                           │            │      journalisé         │
                                           │            ▼                         │
                                           │  order_check ──► order_send          │
                                           │            │                         │
                                           │            ▼                         │
                                           │  Processus MT5 isolé et tuable       │
                                           └────────────┼─────────────────────────┘
                                                        │
                                                        ▼
                                           ┌──────────────────────────────────────┐
                                           │  MetaTrader 5 Desktop (terminal64)   │
                                           │  AutoTrading activé                  │
                                           └────────────┼─────────────────────────┘
                                                        │
                                                        ▼
                                              Compte Exness (démo, puis réel)


   Téléphone Android                                   PC Windows
 ┌────────────────────┐                    ┌──────────────────────────────────────┐
 │ Application Flutter│  REST /api/v1      │                                      │
 │                    │ ◄────────────────► │  Bridge FastAPI  (port 8787)         │
 │  jeton de          │  WebSocket /ws     │                                      │
 │  périphérique      │ ◄────────────────► │  Base SQLite + secrets chiffrés      │
 └────────────────────┘                    └──────────────────────────────────────┘
        réseau local en HTTP clair, ou tunnel ngrok HTTPS depuis l'extérieur
```

---

## Prérequis

Le projet se lance en deux parties : le **Bridge sur le PC Windows**, puis
l'**application sur le téléphone Android**. Il n'y a pas de serveur web à ouvrir
sur le téléphone et l'application Android ne remplace pas le Bridge.

| Élément | Utilité / version requise |
|---|---|
| Windows 10 ou 11, 64 bits | PC qui héberge le Bridge et MetaTrader 5 |
| PowerShell | exécuter les scripts fournis |
| Python 3.11 ou plus, **64 bits**, dans le `PATH` | exécuter le Bridge ; cocher « Add python.exe to PATH » à l'installation |
| Connexion Internet | installer les dépendances et accéder aux services externes |
| MetaTrader 5 Desktop et compte broker **démo** | lire les marchés et essayer l'exécution MT5 ; le Bridge peut démarrer sans MT5, mais ses fonctions MT5 seront indisponibles |
| Compte Telegram, `api_id` et `api_hash` | lire les canaux ; obtenir les identifiants sur <https://my.telegram.org> |
| Clé OpenRouter | activer les fonctions IA ; le parser local fonctionne sans clé |
| Téléphone Android | installer l'APK et piloter le Bridge |
| Flutter SDK avec Dart `>=3.5.0 <4.0.0` | construire l'application ; inutile si vous disposez déjà d'un APK compatible |
| Android Studio / Android SDK, JDK 17 ou plus | compiler l'APK ; installer les composants demandés par `flutter doctor` |
| Projet Firebase et `google-services.json` | requis pour compiler la configuration Android actuelle |
| Compte de service Firebase | facultatif, pour recevoir les notifications push même application fermée |
| Compte et binaire ngrok, authtoken et domaine | connecter le téléphone au Bridge via HTTPS |

Le projet déclare Gradle **8.12**, Android Gradle Plugin **8.9.1** et Kotlin
**2.1.0** dans `mobile/android/`. Gradle télécharge sa distribution si elle
n'est pas déjà en cache. Le niveau Android effectif dépend du Flutter installé
(`flutter.minSdkVersion`, `flutter.compileSdkVersion`, `flutter.targetSdkVersion`).

Python : <https://www.python.org/downloads/windows/>.
Flutter : <https://docs.flutter.dev/install>.
Android Studio : <https://developer.android.com/studio>.

Le PC doit rester **allumé, connecté à Internet, avec une session utilisateur
ouverte** et MetaTrader 5 lancé. Le paquet Python `MetaTrader5` dialogue avec le
terminal graphique : sans terminal ouvert, aucun ordre ne peut partir.

---

## Installation et premier démarrage

Téléchargez ou clonez le projet, puis ouvrez PowerShell **à la racine du projet**,
dans le dossier contenant `README.md`, `bridge/`, `mobile/` et `scripts/` :

```powershell
cd "C:\chemin\vers\trader apk"
python --version
python -c "import struct; print(struct.calcsize('P') * 8)"
```

La dernière commande doit afficher `64`. Les étapes ci-dessous indiquent
explicitement quand changer de dossier. Les commandes avec
`-ExecutionPolicy Bypass` s'appliquent uniquement au processus PowerShell lancé.

### 1. Installer les dépendances du Bridge

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_bridge.ps1 -WithNgrok
```

Le script crée `bridge\.venv`, installe les dépendances, génère `bridge\.env` à
partir de `.env.example`, génère une `MASTER_KEY` Fernet si elle est vide et
lance un diagnostic. L'option `-WithNgrok` télécharge le binaire ngrok s'il
est absent. Le script peut être relancé sans écraser
la configuration existante.

**Sauvegardez `bridge\.env` dans un emplacement privé** : la `MASTER_KEY`
chiffre vos secrets stockés. Conservez cette clé avec la sauvegarde de
`bridge/data/` ; sans elle, les secrets chiffrés ne pourront pas être relus.
Ne copiez aucune valeur réelle dans `.env.example`.

### 2. Renseigner la configuration locale

Ouvrez le fichier généré :

```powershell
notepad .\bridge\.env
```

| Paramètre | Que renseigner |
|---|---|
| `BRIDGE_HOST` | conserver `127.0.0.1` : ngrok transmet les requêtes au Bridge local |
| `BRIDGE_PORT` | `8787` par défaut |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` | vos identifiants Telegram et numéro au format international ; vous pouvez aussi les saisir dans l'application |
| `OPENROUTER_API_KEY` | votre clé OpenRouter, ou laissez vide pour la saisir ensuite dans les Paramètres de l'application |
| `OPENROUTER_FREE_ONLY` | conserver `true` pour limiter la sélection automatique aux modèles gratuits |
| `MT5_TERMINAL_PATH` | chemin complet de `terminal64.exe` si l'autodétection ne trouve pas le bon terminal |
| `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` | laisser vides si la connexion est faite directement dans MetaTrader 5 |
| `NGROK_ENABLED` | `true` pour démarrer le tunnel avec le Bridge |
| `NGROK_AUTHTOKEN` | votre authtoken depuis le tableau de bord ngrok ; le conserver uniquement dans `bridge/.env` |
| `NGROK_DOMAIN` | votre domaine réservé ngrok, sans `https://` ni chemin |
| `MASTER_KEY` | conserver la valeur générée, ne pas la remplacer à chaque démarrage |
| `DB_HOST`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD` | laisser vides pour SQLite ; renseigner pour utiliser un serveur PostgreSQL existant |

SQLite est le choix par défaut : la base est créée dans
`bridge/data/tradepilot.sqlite3`, aucune installation de base externe n'est
nécessaire. PostgreSQL est une option ; voir
[le guide du Bridge](docs/BRIDGE_WINDOWS_SETUP.md).

Après toute modification de `.env`, redémarrez le Bridge pour recharger les valeurs.

Pour ngrok, récupérez votre authtoken et réservez le domaine depuis
<https://dashboard.ngrok.com>. Saisissez ces valeurs dans `bridge/.env`.
Ne copiez pas l'authtoken dans le README, une commande committée ou un fichier
d'exemple. Avec `NGROK_ENABLED=true`, le Bridge lance et surveille le tunnel ;
il réutilise un tunnel déjà actif si ngrok est déjà lancé sur le PC.

### 3. Préparer MetaTrader 5

Installez MetaTrader 5, ouvrez votre compte **démo** Exness, connectez-vous dans
le terminal, activez le bouton **Algo Trading / AutoTrading** et cochez
*Outils → Options → Expert Advisors → Autoriser le trading algorithmique*.
Vérifiez que le terminal est connecté au broker et que les instruments souhaités
sont disponibles dans l'Observation du marché. Laissez-le ouvert sur ce PC.

### 4. Lancer le Bridge et vérifier sa réponse

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_bridge.ps1
```

Gardez cette console ouverte. Le Bridge y affiche ses journaux, son adresse et
un **code d'appairage valable 15 minutes et utilisable une seule fois**.
Vérifiez aussi qu'une **adresse publique HTTPS ngrok** est affichée. C'est
cette adresse que le téléphone utilisera ; si elle manque, consultez les
journaux et les paramètres ngrok avant l'appairage.
`Ctrl+C` arrête proprement ce lancement.

Dans une **deuxième console PowerShell** sur le PC, vérifiez l'API :

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/v1/health
```

Une réponse confirme que l'API est accessible. Consultez ensuite les diagnostics
de l'application pour vérifier séparément MT5, Telegram et OpenRouter.

### 5. Préparer Firebase pour Android

Dans <https://console.firebase.google.com>, créez un projet et ajoutez une
application Android dont le nom de paquet est **`com.tradepilot.tradepilot`**.
Téléchargez `google-services.json` et placez-le dans :

```text
mobile/android/app/google-services.json
```

Ce fichier est volontairement exclu de Git. La configuration Gradle actuelle
applique le plugin Google Services : **il faut fournir ce fichier pour compiler
l'APK**, même si vous n'activez pas les push côté Bridge.

Pour recevoir les notifications application fermée, générez aussi une clé de
compte de service dans *Paramètres du projet → Comptes de service* et placez-la
sur le PC dans :

```text
bridge/data/fcm-service-account.json
```

Le Bridge la détecte au démarrage. Cette clé privée reste sur le PC : elle ne
doit être ni versionnée ni intégrée à l'APK. Sans elle, l'inbox et le WebSocket
restent disponibles, mais les push distants ne fonctionneront pas.

### 6. Compiler et installer l'application Android

Si vous avez déjà un APK compatible, installez-le et passez à l'étape 7.
Pour compiler depuis les sources, installez Flutter, Android Studio / SDK et
le JDK, puis, depuis la racine :

```powershell
flutter doctor -v
flutter doctor --android-licenses
cd .\mobile
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter analyze
flutter test
flutter build apk --release
```

Corrigez les composants Android manquants signalés par `flutter doctor`.
`mobile/android/local.properties` doit contenir les chemins de vos SDK ; Flutter
le génère normalement lors de ses commandes. S'il manque, créez-le avec des
chemins adaptés à votre machine, par exemple :

```properties
sdk.dir=C:/Android/Sdk
flutter.sdk=C:/flutter
```

L'APK se trouve dans
**`mobile/build/app/outputs/flutter-apk/app-release.apk`**.
Copiez-le sur le téléphone, ouvrez-le et autorisez l'installation depuis votre
gestionnaire de fichiers. Ou, depuis `mobile/`, avec le débogage USB activé :

```powershell
adb devices
adb install -r .\build\app\outputs\flutter-apk\app-release.apk
```

Sans `mobile/android/key.properties`, la release utilise la clé de débogage et
reste une build de test. Pour conserver une signature personnelle, fournissez
ce fichier et votre keystore selon [le guide Android](docs/ANDROID_SETUP.md).
Ils restent exclus du dépôt. Revenez ensuite à la racine :

```powershell
cd ..
```

Le script `scripts/build_apk.ps1` permet également de construire l'APK avec
les informations de build affichées dans l'application.

### 7. Connecter le téléphone au Bridge

Dans l'application TradePilot, saisissez **l'URL HTTPS publique affichée par
le Bridge**, par exemple `https://votre-domaine.ngrok-free.app`, puis le code
d'appairage affiché dans la console. Remplacez cet exemple par votre vraie URL.
Le PC et le téléphone doivent avoir Internet ; ils peuvent être sur des réseaux
différents. Il n'est pas nécessaire d'ouvrir le port `8787` dans le routeur.

Ne saisissez pas `127.0.0.1` ni `0.0.0.0` dans l'application : ces adresses ne
désignent pas l'URL publique du PC. Si ngrok ne démarre pas, vérifiez le binaire,
l'authtoken, le domaine et les messages d'erreur dans la console du Bridge.

Pour un accès local alternatif sans ngrok, le Bridge peut écouter sur
`0.0.0.0` ; le téléphone utilise alors l'IPv4 du PC et le port `8787` sur le même
réseau privé, avec le pare-feu adapté. La procédure principale de ce projet
reste la connexion HTTPS via ngrok.

Le code a expiré ou a déjà été utilisé ? Depuis une deuxième console à la racine :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pairing_code.ps1
```

Le jeton de périphérique reçu est conservé par l'application et authentifie les
requêtes suivantes. Autorisez les notifications Android si vous souhaitez les recevoir.

### 8. Connecter Telegram et OpenRouter

Dans les écrans de connexion de l'application, ouvrez Telegram, renseignez
`api_id`, `api_hash` et le numéro de téléphone, puis saisissez le code reçu via
Telegram ou SMS. Si votre compte utilise la double authentification, saisissez
ensuite le mot de passe 2FA. Le Bridge conserve la session localement et chiffrée.

Pour OpenRouter, créez votre clé sur <https://openrouter.ai/keys>, puis
enregistrez-la dans *Paramètres → OpenRouter* si elle n'est pas déjà dans `.env`.
Utilisez le test de connexion et sélectionnez un modèle disponible. La disponibilité
et les quotas des modèles gratuits peuvent varier ; gardez
`OPENROUTER_FREE_ONLY=true` si vous voulez limiter la sélection automatique.

### 9. Vérifier le fonctionnement en PAPER

Le mode d'exécution par défaut est `PAPER` et le trading automatique est
désactivé (`auto_trading_enabled = false`). Ajoutez un canal : il démarre
**toujours** en mode `OBSERVE`. Regardez le Bridge interpréter les messages sans
rien envoyer. Vérifiez les signaux, le journal, les diagnostics et les règles de
risque. Passez ensuite à `MANUAL` puis, si souhaité, à `AUTO` en PAPER.
Essayez `MT5_DEMO` seulement après avoir vérifié le compte démo connecté dans MT5.
Le mode réel exige un déverrouillage explicite dans l'application.

Détails : [docs/DEMO_TESTING.md](docs/DEMO_TESTING.md) puis
[docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md).

---

## Utilisation au quotidien

Ouvrez MetaTrader 5 et vérifiez le compte connecté, puis démarrez le Bridge depuis
la racine du projet. Ouvrez ensuite TradePilot sur le téléphone. L'appairage
n'est pas à refaire tant que le jeton de l'appareil reste valide.

| Action | Commande depuis la racine |
|---|---|
| Démarrer avec console | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_bridge.ps1` |
| Démarrer sans tunnel pour cette session | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_bridge.ps1 -NoNgrok` |
| Démarrer en arrière-plan | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_bridge_background.ps1` |
| Arrêter le Bridge en arrière-plan | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_bridge.ps1` |
| Vérifier l'environnement | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_environment.ps1` |
| Obtenir un nouveau code d'appairage | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pairing_code.ps1` |

Pour le lancement avec console, utilisez `Ctrl+C` dans cette console. Les
journaux se trouvent dans `bridge/data/logs/`. Ne démarrez pas simultanément
deux instances sur le même port.

### Démarrage automatique à l'ouverture de session Windows

Dans une console PowerShell **administrateur**, à la racine :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_autostart.ps1
```

Le script installe la tâche `TradePilotBridge`, exécutée en arrière-plan à
l'ouverture de session. MetaTrader 5 doit également être ouvert dans cette
session ; la tâche ne remplace pas son lancement.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_autostart.ps1 -Status
```

Pour supprimer ce démarrage automatique, lancez le même script avec `-Remove`
depuis une console administrateur.

### Connexion HTTPS avec ngrok

Installez ngrok, puis renseignez **uniquement dans `bridge/.env`** :
`NGROK_ENABLED=true`, `NGROK_AUTHTOKEN` et `NGROK_DOMAIN` avec vos propres valeurs.
Le script d'installation accepte `-WithNgrok` pour télécharger le binaire.
`scripts/setup_ngrok.ps1` est également disponible pour la configuration.

Redémarrez le Bridge, puis saisissez dans l'application l'URL **HTTPS réelle**
affichée au démarrage. ngrok peut joindre le Bridge sur `127.0.0.1` ; il n'est
pas nécessaire d'ouvrir le port du routeur. Le PC doit toujours rester allumé.

## Vérifier le projet après une modification

Les tests ne sont pas nécessaires à chaque démarrage. Pour vérifier les sources,
depuis la racine, installez les outils de développement puis lancez les tests du Bridge :

```powershell
.\bridge\.venv\Scripts\python.exe -m pip install -r .\bridge\requirements-dev.txt
cd .\bridge
.\.venv\Scripts\python.exe -m pytest
cd ..
```

Pour Android :

```powershell
cd .\mobile
flutter analyze
flutter test
cd ..
```

## Résoudre les problèmes de démarrage

| Problème | Vérification / solution |
|---|---|
| `python` ou `flutter` introuvable | installer le SDK et corriger le `PATH`, puis rouvrir PowerShell |
| Environnement `bridge/.venv` absent | relancer `scripts/install_bridge.ps1` |
| Port `8787` occupé | vérifier si le Bridge tourne déjà ; arrêter l'instance existante ou modifier `BRIDGE_PORT` et l'adresse dans l'application |
| Le téléphone ne joint pas le PC via ngrok | vérifier que le Bridge et le tunnel tournent, l'URL HTTPS saisie, la connexion Internet, l'authtoken et le domaine ngrok |
| Appairage refusé | demander un nouveau code local, vérifier l'adresse et la validité du code |
| MT5 indisponible | vérifier Python 64 bits, le paquet `MetaTrader5`, le terminal ouvert et `MT5_TERMINAL_PATH` |
| Compilation : `google-services.json` absent | fournir le fichier Firebase correspondant au paquet `com.tradepilot.tradepilot` |
| Compilation : SDK / licences Android | lancer `flutter doctor -v` et `flutter doctor --android-licenses` |
| Notifications absentes application fermée | vérifier le compte de service FCM côté Bridge, le fichier Firebase Android et la permission de notification |
| Erreur OpenRouter / quota | tester la connexion, vérifier la clé et choisir un modèle encore disponible |

Voir également [le dépannage détaillé](docs/TROUBLESHOOTING.md).

## Fichiers locaux et secrets

Ne partagez jamais `bridge/.env`, la `MASTER_KEY`, les sessions Telegram,
les clés API, les mots de passe, les jetons d'appareil ou la clé privée Firebase.
La configuration Android Firebase et les fichiers de signature restent également
locaux. `.gitignore` exclut ces fichiers, les données du Bridge et leurs dossiers
de compilation. Les exemples de configuration doivent contenir uniquement des
valeurs vides ou fictives.

Une exclusion Git ne retire pas un secret déjà commité. Avant tout envoi,
contrôlez aussi les fichiers suivis et l'historique ; ne forcez pas l'ajout d'un
fichier ignoré. Sur une nouvelle machine, recréez la configuration locale et
restaurez les secrets par un moyen privé, séparément du code.

Si Gitleaks est installé, lancez ce contrôle avant un envoi :

```powershell
gitleaks git . --redact --log-opts="--all"
```

La configuration `.gitleaks.toml` conserve les règles standard et autorise
uniquement trois valeurs fictives ou internes vérifiées. Aucun fichier source
n'est exclu du scan. `--redact` masque les valeurs dans les résultats.

---

## Structure du dépôt

```
trader apk/
├── .env.example              modèle de configuration du Bridge
├── cdc.md                    cahier des charges du projet
├── README.md                 ce fichier
│
├── bridge/                   service Python (FastAPI) — terminé
│   ├── app/
│   │   ├── main.py           point d'entrée, cycle de vie des composants
│   │   ├── api/v1/           routes REST et WebSocket
│   │   ├── config/           réglages (.env) et journalisation masquée
│   │   ├── database/         moteur SQLite asynchrone et migrations légères
│   │   ├── models/           23 tables SQLModel et énumérations du domaine
│   │   ├── repositories/     accès aux données
│   │   ├── schemas/          corps de requêtes Pydantic
│   │   └── services/
│   │       ├── channels/     analyse de canal et simulation historique
│   │       ├── mt5/          interface, service réel, simulateur, processus isolé
│   │       ├── openrouter/   client, sélecteur de modèles gratuits, IA
│   │       ├── risk/         RiskManager et calcul du lot
│   │       ├── security/     chiffrement Fernet et appairage
│   │       ├── signals/      normalisation, parsers, validateur, pipeline
│   │       ├── statistics/   agrégats calculés sur les trades fermés
│   │       ├── telegram/     session MTProto, découverte, écoute
│   │       ├── trading/      moteur, exécuteur, gestion des positions, paper
│   │       └── tunnel/       tunnel ngrok
│   ├── tests/                suite pytest
│   ├── requirements.txt
│   └── pyproject.toml
│
├── mobile/                   application Flutter Android
│   ├── lib/
│   │   ├── core/             thème, API, WebSocket, connexion, cache Drift,
│   │   │                     routage, notifications, stockage chiffré
│   │   └── features/         écrans par domaine fonctionnel
│   ├── android/              configuration Gradle, manifeste, politique réseau
│   └── test/
│
├── docs/                     documentation du projet
│   └── openapi.json          contrat d'API complet exporté depuis le Bridge
│
└── scripts/                  scripts PowerShell Windows — terminés
    ├── install_bridge.ps1
    ├── check_environment.ps1
    ├── start_bridge.ps1
    ├── start_bridge_background.ps1
    ├── stop_bridge.ps1
    ├── install_autostart.ps1      démarrage automatique à l'ouverture de session
    ├── pairing_code.ps1           nouveau code pour appairer un téléphone
    ├── build_bridge_exe.ps1       exécutable autonome (PyInstaller)
    └── setup_ngrok.ps1
```

### Appairer un téléphone quand le Bridge tourne déjà

Le code affiché au démarrage ne vaut que 15 minutes et ne sert qu'une fois.
Lorsque le Bridge tourne en permanence, demandez-en un nouveau :

```powershell
.\scripts\pairing_code.ps1
```

La demande n'est acceptée que depuis la machine du Bridge : personne ne peut
réclamer un code à distance.

---

## Documentation

| Document | Contenu |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Couches du Bridge, pipeline d'un message, machine d'état d'un signal, isolation de MetaTrader 5 dans un processus, bus d'événements, schéma de la base, architecture Flutter |
| [docs/BRIDGE_WINDOWS_SETUP.md](docs/BRIDGE_WINDOWS_SETUP.md) | Installation du Bridge sur Windows, `.env`, démarrage automatique, ngrok, journaux |
| [docs/ANDROID_SETUP.md](docs/ANDROID_SETUP.md) | Prérequis Flutter, génération de code, tests, construction et installation de l'APK, signature de release, politique réseau |
| [docs/MT5_EXNESS_SETUP.md](docs/MT5_EXNESS_SETUP.md) | MetaTrader 5, compte démo Exness, AutoTrading, suffixes de symboles, démo contre réel |
| [docs/TELEGRAM_SETUP.md](docs/TELEGRAM_SETUP.md) | `api_id` / `api_hash`, session utilisateur MTProto, connexion en trois étapes, stockage chiffré, FloodWait |
| [docs/OPENROUTER_SETUP.md](docs/OPENROUTER_SETUP.md) | Clé OpenRouter, sélecteur de modèles gratuits, quotas 429, coupe-circuit, données transmises |
| [docs/RISK_MANAGEMENT.md](docs/RISK_MANAGEMENT.md) | Tous les réglages de risque, ordre exact des contrôles, motifs de refus, calcul du lot, TP multiples, break even, trailing |
| [docs/CHANNEL_DISCOVERY.md](docs/CHANNEL_DISCOVERY.md) | Recherche de canaux, ajout à la surveillance, modes OBSERVE / MANUAL / AUTO |
| [docs/CHANNEL_ANALYSIS.md](docs/CHANNEL_ANALYSIS.md) | Mesures du Channel Analyzer, lecture du rapport, simulation historique, règle AMBIGUOUS, comparaison de canaux |
| [docs/SECURITY.md](docs/SECURITY.md) | Appairage, jetons, chiffrement des secrets, `MASTER_KEY`, masquage des journaux, ngrok, checklist avant exposition |
| [docs/DEMO_TESTING.md](docs/DEMO_TESTING.md) | Tests sans risque : PAPER, MT5 DEMO, injection de messages, scénarios à reproduire, suites de tests |
| [docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md) | Checklist avant le mode réel, déverrouillage en deux temps, reverrouillage |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Guide de dépannage : Bridge injoignable, MT5, Telegram, quotas, ngrok, base verrouillée, APK |
| [docs/MARKET_WATCHER.md](docs/MARKET_WATCHER.md) | AI Market Watcher (CDC3) : boucles autonomes, canal Telegram, score sur 100, Risk Manager, cycle de vie des signaux, routes `/api/v1/watcher/*` |
| [docs/openapi.json](docs/openapi.json) | Contrat d'API : 133 chemins, 147 opérations REST, plus le WebSocket `/api/v1/ws` |

---

## État du projet et limites connues

| Composant | État |
|---|---|
| Bridge Python | Fonctionnel. **788 tests `pytest`** passent sur cette machine. |
| Scripts PowerShell | Fonctionnels et documentés. |
| Application Flutter | Fonctionnelle. Socle complet (thème, client HTTP, WebSocket avec reconnexion, cache Drift hors ligne, routage, notifications locales, stockage chiffré) et **tous les écrans implémentés**. `flutter analyze` ne signale aucun problème et les **29 tests `flutter test`** passent. |

> Le dépôt évolue : les chiffres ci-dessus ont été relevés le 11 septembre 2026.
> Relancez `pytest` et `flutter test` pour la valeur du jour.

Ce qui **n'a pas pu être vérifié sur cette machine** :

- l'exécution réelle d'ordres sur MetaTrader 5 (aucun `order_send` réel n'a été
  effectué ; le Bridge expose d'ailleurs un avertissement
  `MT5 REAL NOT TESTED ON THIS MACHINE` dans son diagnostic tant que ce n'est
  pas le cas). Un comportement du terminal **a** en revanche été mesuré sur
  cette machine : un `mt5.initialize` face à un terminal muet a gelé le
  processus pendant 101,9 secondes, ce qui a justifié l'isolation de
  `MetaTrader5` dans un processus enfant tuable ;
- la connexion réelle à un compte Telegram (aucun code de connexion n'a été
  demandé à Telegram) ;
- les appels réels à OpenRouter (aucune clé valide n'a été utilisée) ;
- la construction et l'installation d'un APK sur un téléphone physique.

---

## Avertissement de risque

TradePilot est un outil personnel d'automatisation. Ce n'est ni un produit
commercial, ni un service financier, ni un conseil en investissement.

- **Le trading de produits à effet de levier comporte un risque élevé de perte
  totale du capital engagé.** Les CFD, le forex, les métaux, les indices et les
  crypto-actifs peuvent évoluer très rapidement et à votre défaveur.
- **Copier les signaux d'un tiers ne réduit pas ce risque.** Vous ne connaissez
  ni la méthode, ni les positions réelles, ni les intentions de l'auteur d'un
  canal. Un canal peut cesser de publier, publier des messages contradictoires,
  ou publier des résultats invérifiables.
- **Aucune mesure affichée par cet outil ne prédit un résultat futur.** Les
  rapports d'analyse de canal, les simulations historiques et les statistiques
  décrivent uniquement des données passées et observées.
- **L'automatisation ajoute ses propres risques** : coupure réseau, terminal
  fermé, PC en veille, message mal interprété, écart de prix à l'exécution,
  symbole introuvable chez le broker. Le système refuse d'agir dans le doute,
  mais aucun garde-fou n'élimine le risque.
- Les règles de risque, la checklist avant le mode réel et le mode PAPER
  réduisent la probabilité d'une erreur grossière. **Elles ne rendent pas le
  trading sans risque.**
- N'engagez jamais un capital dont la perte affecterait votre situation.
  Travaillez d'abord en PAPER, puis sur un compte de **démonstration**, aussi
  longtemps que nécessaire.
- Vous restez seul responsable de l'utilisation de cet outil, de sa
  configuration et de ses conséquences financières. Vérifiez également la
  réglementation applicable dans votre pays et les conditions de votre broker.

Ce logiciel est fourni tel quel, sans garantie d'aucune sorte.
