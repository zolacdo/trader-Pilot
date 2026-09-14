# TradePilot

Auteur : **zolacdo** — <zolacdojeff@gmail.com>.

Pour publier le projet sur GitHub, voir [le guide GitHub](docs/GITHUB_SETUP.md).

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

| Élément | Version / détail | Où l'obtenir |
|---|---|---|
| Windows | 10 ou 11, 64 bits | — |
| Python | 3.11 minimum, 64 bits | <https://www.python.org/downloads/windows/> |
| MetaTrader 5 Desktop | build de votre broker (Exness) | site du broker |
| Compte Exness **démo** | gratuit | <https://www.exness.com> |
| Identifiants Telegram | `api_id` + `api_hash` | <https://my.telegram.org> |
| Clé OpenRouter | clé gratuite | <https://openrouter.ai/keys> |
| Flutter SDK | 3.x (Dart `>=3.5.0 <4.0.0`) | uniquement pour construire l'APK |
| Android SDK | API 23 minimum, compilation via Gradle 8.12 | uniquement pour construire l'APK |
| Compte ngrok | offre gratuite | facultatif, pour l'accès hors du réseau local |

Le PC doit rester **allumé, connecté à Internet, avec une session utilisateur
ouverte** et MetaTrader 5 lancé. Le paquet Python `MetaTrader5` dialogue avec le
terminal graphique : sans terminal ouvert, aucun ordre ne peut partir.

---

## Démarrage rapide en 6 étapes

Toutes les commandes se lancent depuis la racine du dépôt, dans PowerShell :

```powershell
cd "C:\Users\<votre-nom>\Desktop\trader apk"
```

### 1. Installer le Bridge

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_bridge.ps1
```

Le script crée `bridge\.venv`, installe les dépendances, génère `bridge\.env` à
partir de `.env.example`, génère une `MASTER_KEY` Fernet si elle est vide et
lance un diagnostic. Il est idempotent.

**Sauvegardez immédiatement `bridge\.env`** : la `MASTER_KEY` chiffre tous vos
secrets stockés. La perdre oblige à tout reconfigurer.

Détails complets : [docs/BRIDGE_WINDOWS_SETUP.md](docs/BRIDGE_WINDOWS_SETUP.md).

### 2. Connecter MetaTrader 5

Installez MetaTrader 5, ouvrez votre compte **démo** Exness, connectez-vous dans
le terminal, activez le bouton **AutoTrading** de la barre d'outils et cochez
*Outils → Options → Expert Advisors → Autoriser le trading algorithmique*.

Puis démarrez le Bridge et vérifiez qu'il détecte le terminal :

```powershell
.\scripts\start_bridge.ps1
```

Détails : [docs/MT5_EXNESS_SETUP.md](docs/MT5_EXNESS_SETUP.md).

### 3. Connecter Telegram

Récupérez `api_id` et `api_hash` sur <https://my.telegram.org> et renseignez
`TELEGRAM_API_ID`, `TELEGRAM_API_HASH` et `TELEGRAM_PHONE` dans `bridge\.env`.
La connexion elle-même se fait en trois appels : envoi du code, saisie du code,
puis mot de passe 2FA si votre compte en a un.

Détails : [docs/TELEGRAM_SETUP.md](docs/TELEGRAM_SETUP.md).

### 4. Configurer OpenRouter

Créez une clé sur <https://openrouter.ai/keys> et renseignez
`OPENROUTER_API_KEY` dans `bridge\.env`, ou enregistrez-la ensuite via
`PUT /api/v1/openrouter/key` (elle est alors chiffrée en base). Laissez
`OPENROUTER_FREE_ONLY=true` : aucun modèle payant ne sera jamais sélectionné
automatiquement.

Détails : [docs/OPENROUTER_SETUP.md](docs/OPENROUTER_SETUP.md).

### 5. Appairer le téléphone

Au démarrage, le Bridge affiche une bannière dans la console :

```
==================================================================
  TradePilot Bridge 1.0.0 (API v1)
==================================================================
  Adresse locale   : http://127.0.0.1:8787
  Adresse publique : aucune (tunnel desactive)
  Code d'appairage : XXXX-XXXX   (valable 15 minutes)
```

Dans l'application, saisissez l'adresse du Bridge (par exemple
`192.168.1.20:8787` sur le réseau local, ou l'URL HTTPS ngrok à distance) puis
le code. Le Bridge renvoie un **jeton de périphérique** qui authentifie ensuite
toutes les routes sensibles.

Détails : [docs/SECURITY.md](docs/SECURITY.md) et
[docs/ANDROID_SETUP.md](docs/ANDROID_SETUP.md).

### 6. Démarrer en PAPER

Le mode d'exécution par défaut est `PAPER` et le trading automatique est
désactivé (`auto_trading_enabled = false`). Ajoutez un canal : il démarre
**toujours** en mode `OBSERVE`. Regardez le Bridge interpréter les messages sans
rien envoyer, puis passez progressivement à `MANUAL`, puis à `AUTO`, et
seulement ensuite au mode `MT5_DEMO`.

Détails : [docs/DEMO_TESTING.md](docs/DEMO_TESTING.md) puis
[docs/GO_LIVE_CHECKLIST.md](docs/GO_LIVE_CHECKLIST.md).

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
