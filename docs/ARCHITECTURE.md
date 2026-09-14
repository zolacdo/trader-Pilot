# Architecture technique de TradePilot

Ce document décrit l'architecture réelle du code, telle qu'elle existe dans
`bridge/app/` et `mobile/lib/`. Il ne décrit pas une architecture souhaitée.

---

## 1. Vue d'ensemble

TradePilot est un monorepo composé de deux exécutables indépendants :

| Composant | Technologie | Rôle |
|---|---|---|
| `bridge/` | Python 3.11+, FastAPI, SQLModel, SQLite, Telethon | Toute la logique métier. Seul composant qui parle à MetaTrader 5, à Telegram et à OpenRouter. |
| `mobile/` | Flutter (Dart `>=3.5.0 <4.0.0`), Riverpod, go_router, Drift | Interface de consultation et de pilotage. Ne contient aucune règle de trading. |

L'application mobile ne détient **aucun secret métier** : ni clé OpenRouter, ni
session Telegram, ni identifiants MetaTrader. Elle ne conserve localement que
l'adresse du Bridge et son jeton de périphérique, dans le stockage chiffré du
téléphone (`flutter_secure_storage`, `EncryptedSharedPreferences` sur Android).

---

## 2. Les couches du Bridge

```
bridge/app/
├── main.py            cycle de vie (lifespan), middlewares, gestionnaires d'erreurs
├── api/v1/            couche HTTP : validation d'entrée, sérialisation JSON
├── schemas/           corps de requêtes Pydantic (validation stricte)
├── services/          logique métier — le cœur du système
├── repositories/      accès aux données, une fonction par intention
├── models/            tables SQLModel + énumérations du domaine
├── database/          moteur asynchrone, sessions, migrations légères
└── config/            réglages issus du .env, journalisation masquée
```

### 2.1 `api/v1` — la couche HTTP

Un routeur par domaine, agrégés dans `app/api/v1/router.py` sous le préfixe
`/api/v1` :

| Module | Préfixe | Contenu |
|---|---|---|
| `system.py` | — | `/health`, appairage, périphériques, `/status`, `/dashboard`, `/diagnostics`, `/go-live-checklist` |
| `telegram.py` | `/telegram` | connexion du compte, découverte de canaux |
| `channels.py` | `/channels` | canaux surveillés, réglages, analyse, comparaison |
| `signals.py` | `/signals` | liste, détail, validation manuelle, test du parser |
| `trading.py` | — | MT5, positions, ordres, mode d'exécution, urgence |
| `settings.py` | — | risque, OpenRouter, analyse IA, symboles, export/import |
| `stats.py` | — | statistiques, journal, audit, onboarding |
| `websocket.py` | — | `/ws`, flux temps réel |

Toutes les routes sauf `GET /api/v1/health`, `GET /api/v1/pairing/status` et
`POST /api/v1/pairing` dépendent de `require_device`, qui exige un jeton de
périphérique valide (`Authorization: Bearer …` ou en-tête `X-Device-Token`).

`main.py` installe deux gestionnaires d'exceptions qui renvoient un message
lisible en français plutôt qu'une trace technique, et un middleware
`SecurityHeadersMiddleware` qui ajoute `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` et
`Cache-Control: no-store`.

### 2.2 `services/` — la logique métier

| Paquet | Responsabilité |
|---|---|
| `signals/` | `normalizer` (nettoyage du texte), `symbols` (alias → symbole canonique), `deterministic_parser`, `follow_up_parser`, `validator`, `pipeline` (orchestration), `models` (structures `ParsedSignal`, `FollowUp`, `ValidationResult`) |
| `risk/` | `manager` (le `RiskManager`), `calculator` (volume, arrondis, distances broker, découpage) |
| `trading/` | `engine` (orchestrateur unique), `executor` (construction et envoi des ordres), `position_manager` (TP multiples, break even, trailing, réconciliation), `paper` (moteur PAPER), `symbol_resolver` (symbole canonique → symbole broker) |
| `mt5/` | `interface` (contrat abstrait + dataclasses), `real_service` (terminal Windows), `fake_service` + `_fake_engine` (simulateur en mémoire), `process_worker` + `_child_process` (isolation de `MetaTrader5` dans un processus enfant), `worker` (thread générique, plus utilisé par MT5), `_mapping` (traduction vers le dialecte MT5) |
| `telegram/` | `client` (session MTProto), `discovery` (recherche, résolution, historique), `listener` (écoute temps réel) |
| `openrouter/` | `client` (HTTP + coupe-circuit), `model_selector` (`FreeModelSelector`), `signal_ai`, `chart_ai`, `service` (façade) |
| `channels/` | `analyzer` (mesures d'un canal), `backtester` (simulation historique) |
| `statistics/` | agrégats calculés uniquement sur les trades fermés |
| `security/` | `crypto` (Fernet, jetons), `auth` (appairage, dépendance FastAPI) |
| `tunnel/` | `ngrok_service` |
| — | `events.py` (bus d'événements), `journal.py` (journal + audit), `runtime.py` (état du processus), `telegram_runtime.py` (branchement écoute → moteur) |

Le `RiskManager` est volontairement **sans accès à la base de données** :
l'appelant assemble un `RiskContext` (réglages, état, canal, compte, symbole,
tick, positions ouvertes) et le manager applique les règles. C'est ce qui le
rend testable exhaustivement et impossible à contourner.

### 2.3 `repositories/`

Cinq modules de fonctions asynchrones prenant une `AsyncSession` en premier
argument : `channel_repo`, `journal_repo`, `settings_repo`, `signal_repo`,
`trade_repo`. Aucun ORM lazy-loading n'est utilisé ; chaque fonction exprime une
intention (`open_trades`, `find_parent_signal`, `ensure_day_rollover`…).

### 2.4 `models/` et `database/`

Les tables sont déclarées en SQLModel dans `models/core.py`,
`models/telegram.py` et `models/trading.py`. Le moteur est
`sqlite+aiosqlite`, avec `PRAGMA journal_mode=WAL` et
`PRAGMA foreign_keys=ON`.

`database/migrations.py` applique une stratégie volontairement simple, adaptée
aux limites de SQLite :

1. `SQLModel.metadata.create_all` crée les tables absentes ;
2. `_sync_missing_columns` ajoute les colonnes présentes dans les modèles mais
   absentes en base (`ALTER TABLE … ADD COLUMN`) ;
3. des migrations numérotées gèrent les cas particuliers.

`SCHEMA_VERSION` vaut actuellement `1`. Les anciennes données ne sont jamais
supprimées.

---

## 3. Le pipeline d'un message

Le chemin complet, de la réception à la position ouverte, est le suivant.

```
 message Telegram
        │
        ▼
 ChannelListener._handle          filtrage du canal, texte non vide
        │
        ▼
 ChannelListener._persist         table "messages", unicité (channel_id, message_id)
        │                          → un doublon s'arrête ici
        ▼
 telegram_runtime._on_message
        │
        ▼
 TradingEngine.handle_message
        │
        ▼
 pipeline.process_message
        │
        ├─ 1. clé d'idempotence  ─────────► action "duplicate"
        │
        ├─ 2. analyse : pipeline.analyze_text
        │        │
        │        ├─ normalize_upper       emojis, espaces, virgules décimales,
        │        │                        séparateurs "SL: 3300" → "SL 3300"
        │        ├─ deterministic_parser.parse
        │        ├─ validator.sanitize + validator.validate
        │        └─ repli IA si (pas un signal) OU (validation KO)
        │           OU (confiance < 0.85)  →  openrouter_service.parse_signal
        │              puis revalidation locale de la sortie du modèle
        │
        ├─ 3. si non-signal : follow_up_parser.parse_follow_up
        │        │            + signal_repo.find_parent_signal
        │        └─────────► action "follow_up"
        │
        ├─ 4. si rien d'exploitable ──────► action "no_action" / "ignored"
        │
        └─ 5. signal structuré ──────────► action "new_signal"
                 │
                 ▼
        TradingEngine.process_signal
                 │
                 ├─ canal OBSERVE  ─────►  statut OBSERVED, aucun ordre
                 ├─ canal MANUAL   ─────►  statut NEEDS_REVIEW + expires_at
                 │
                 ├─ SymbolResolver.resolve   XAUUSD → XAUUSDm
                 ├─ service.symbol_tick / account_info / positions
                 ├─ settings_repo.ensure_day_rollover
                 │
                 ▼
        RiskManager.evaluate            12 blocs de contrôles (voir RISK_MANAGEMENT.md)
                 │
                 ├─ refus ──► RiskEvent + SignalEvent + journal + statut REJECTED
                 │
                 ▼ approbation
        signal.computed_lot / risk_amount / risk_reward, statut APPROVED
                 │
                 ▼
        OrderExecutor.execute
                 ├─ resolve_order_type       MARKET / LIMIT / STOP selon le cours réel
                 ├─ plan_take_profits        selon multi_tp_strategy
                 ├─ service.order_check      ── échec ► statut FAILED
                 ├─ service.order_send       ── échec ► statut FAILED
                 └─ persistance TradeRecord ou PendingOrderRecord
                 │
                 ▼
        statut SENT (ordre en attente) ou OPEN (position ouverte)
                 │
                 ▼
        boucle de suivi TradingEngine._monitor_loop (toutes les MT5_POLL_INTERVAL secondes)
                 ├─ PositionManager.sync_with_broker
                 ├─ PositionManager.apply_automatic_rules   break even, trailing
                 └─ expiration des signaux NEEDS_REVIEW périmés
```

### 3.1 Priorité au parser local

`AI_FALLBACK_THRESHOLD` vaut `0.85` dans `services/signals/pipeline.py`. L'IA
n'est sollicitée que si le parser local échoue, produit un signal invalide ou
reste sous ce seuil — et jamais sur un message qui ne contient aucun des
marqueurs `BUY`, `SELL`, `LONG`, `SHORT`, `TP`, `SL`, `ENTRY`, `TARGET`,
`CLOSE`, `BE`.

Lorsque le parser local a déjà identifié un instrument et une direction avec
certitude, l'IA ne peut pas les contredire : `_run_ai_fallback` réécrit la sortie
du modèle avec les valeurs locales et ajoute les avertissements
`ia_symbole_ignore_au_profit_du_parser_local` /
`ia_direction_ignoree_au_profit_du_parser_local`.

### 3.2 Score de confiance

| Origine | Calcul |
|---|---|
| Parser déterministe | `0.50` (instrument + direction) `+ 0.15` (entrée) `+ 0.20` (stop loss) `+ 0.15` (au moins un TP) `− 0.05` par avertissement, borné à `[0, 1]` |
| Parser IA | `0.60` de base `+ 0.05` (entrée) `+ 0.10` (stop loss) `+ 0.05` (TP), **plafonné à `0.80`** |

Conséquence directe, à connaître : avec la valeur par défaut
`min_confidence = 0.85`, un signal lu par l'IA **ne peut jamais** passer le
contrôle de confiance en mode automatique. Il est refusé avec le motif
`LOW_CONFIDENCE`, sauf validation manuelle (`manual_override`) ou abaissement
explicite du seuil.

---

## 4. Machine d'état d'un signal

Les valeurs réelles de `SignalStatus` (`bridge/app/models/enums.py`) :

| Statut | Signification | Attribué par |
|---|---|---|
| `RECEIVED` | Valeur par défaut à la création de la ligne | `Signal.status` |
| `PARSED` | Message interprété et cohérent | `pipeline.process_message` |
| `NEEDS_REVIEW` | Validation manuelle requise, ou signal incohérent | `pipeline`, `TradingEngine.process_signal` (mode MANUAL) |
| `VALIDATED` | Déclaré dans l'énumération | — jamais attribué dans le code actuel |
| `REJECTED` | Refusé par le `RiskManager` ou par l'utilisateur | `TradingEngine._reject` |
| `APPROVED` | Contrôles de risque passés, avant envoi | `TradingEngine.process_signal` |
| `ORDER_CHECKED` | Déclaré dans l'énumération, utilisé comme filtre | — jamais attribué |
| `SENT` | Ordre(s) en attente placé(s) | `TradingEngine.process_signal` |
| `OPEN` | Position ouverte | `TradingEngine.process_signal` |
| `PARTIALLY_CLOSED` | Déclaré, utilisé comme filtre | — jamais attribué (l'état partiel vit sur `TradeRecord.state`) |
| `MODIFIED` | Déclaré, utilisé comme filtre | — jamais attribué |
| `CLOSED` | Toutes les positions du signal sont fermées ; également attribué au message de suivi traité | `PositionManager._finalize` |
| `FAILED` | `order_check` ou `order_send` refusé, ou suivi en échec | `OrderExecutor._fail`, `PositionManager._finalize` |
| `EXPIRED` | Délai de validation manuelle dépassé | `TradingEngine._expire_stale_signals`, `approve_manually` |
| `NO_ACTION` | Message sans intention de trade explicite | `pipeline.process_message` |
| `OBSERVED` | Canal en mode observation : enregistré sans exécution | `TradingEngine.process_signal` |
| `CANCELLED` | Déclaré dans l'énumération | — jamais attribué |

`TERMINAL_SIGNAL_STATUSES` regroupe `REJECTED`, `CLOSED`, `FAILED`, `EXPIRED`,
`NO_ACTION`, `CANCELLED`.

Chaque transition écrit une ligne dans `signal_events` (colonnes `stage`,
`status`, `success`, `message`, `data`). Les valeurs de `stage` réellement
utilisées sont : `parser`, `risk`, `order_check`, `order_send`, `execution`,
`follow_up`, `manual`, `lifecycle`. C'est cette table qui alimente la timeline
de `GET /api/v1/signals/{signal_id}`.

---

## 5. Le worker MT5 : un processus isolé, pas un thread

### 5.1 Pourquoi un processus

Le paquet Python `MetaTrader5` n'est pas seulement non thread-safe : c'est une
**extension C qui conserve le GIL pendant toute son attente IPC** avec le
terminal.

La mesure faite sur cette machine, citée dans le code, est sans appel :
`mt5.initialize(path=…, timeout=5000)` a bloqué **101,9 secondes** face à un
terminal muet — le paramètre `timeout` étant ignoré par l'extension — et le
thread principal n'a exécuté **aucune instruction** pendant ce temps (0 battement
observé sur environ 509 attendus).

Conséquence directe : un worker *thread* ne protège de rien. Un terminal qui ne
répond pas gelait tout le Bridge, API, WebSocket et écoute Telegram compris.

### 5.2 L'architecture retenue

`MetaTrader5` n'est importé et appelé que dans un **processus enfant** créé en
mode `spawn` :

```
 Processus Bridge                              Processus enfant "mt5-process"
┌────────────────────────────────┐            ┌──────────────────────────────┐
│ RealMetaTraderService          │            │ _child_process.child_main    │
│        │                       │  Queue     │        │                     │
│        ▼                       │ ─────────► │        ▼                     │
│ Mt5ProcessWorker.call(...)     │  requêtes  │  import MetaTrader5          │
│        │                       │            │  appel réel au terminal      │
│        │ asyncio.to_thread     │  Queue     │        │                     │
│        ▼ (jamais la boucle)    │ ◄───────── │        ▼ to_plain(...)       │
│ _wait_response(...)            │  réponses  │  dict / listes picklables    │
└────────────────────────────────┘            └──────────────────────────────┘
```

Fichiers : `process_worker.py` (côté parent), `_child_process.py` (côté enfant).

### 5.3 Le protocole

Tout doit être picklable et indépendant de l'extension C.

| Sens | Forme |
|---|---|
| requête | `{"id": int, "command": str, "args": list, "kwargs": dict}` |
| réponse | `{"id": int, "ok": bool, "result": Any, "error": str \| None, "code": int \| None}` |

Les *namedtuples* MetaTrader5 sont convertis en `dict` via `._asdict()` et les
tableaux numpy en listes de `dict` (`to_plain`) **avant** de traverser la
frontière de processus.

### 5.4 Garanties

| Mécanisme | Effet |
|---|---|
| Attente hors boucle asyncio | `_wait_response` tourne dans un `asyncio.to_thread` ; la boucle du Bridge n'est jamais bloquée |
| `DEFAULT_CALL_TIMEOUT = 30.0` s | délai d'un appel courant : compte, cotation, ordre |
| `CONNECT_TIMEOUT = 15.0` s | délai volontairement court de la séquence de connexion |
| Dépassement du délai | l'enfant est **tué** (`recycle`), une `MetaTraderError` explicite est levée, un enfant neuf est créé au prochain appel |
| Enfant mort | détecté à chaque cycle de `_POLL = 0.25` s, message distinct de celui du timeout |
| Sérialisation | un `asyncio.Lock` garantit un seul appel en vol à la fois |
| `set_on_restart(...)` | callback appelé après un recyclage forcé : la session MT5 est perdue, le service le sait |
| `generation` | numéro de session, incrémenté à chaque démarrage d'un enfant |
| `_neutral_main()` | neutralise `__main__` pendant le `spawn`, sinon l'enfant réimporterait tout le démarrage du Bridge, voire la suite de tests |
| Codes d'erreur propres | `ERROR_NO_RESPONSE = -20001`, `ERROR_NO_PROCESS = -20002`, `ERROR_PACKAGE = -20003`, hors de la plage des codes MT5 |
| `stats()` | `alive`, `pid`, `generation`, `restarts`, `completed`, `failed` |

Les arguments d'un appel ne sont **jamais journalisés** : la séquence de login
passe par la file de commandes, et le mot de passe n'apparaît ni dans le parent
ni dans l'enfant.

### 5.5 Le worker thread générique

`bridge/app/services/mt5/worker.py` définit encore `Mt5Worker`, un worker
mono-thread générique. **Il ne pilote plus MetaTrader 5** : son en-tête porte
l'avertissement correspondant. Il est conservé comme utilitaire pour
d'éventuelles bibliothèques bloquantes qui, elles, relâchent le GIL.

### 5.6 Les deux implémentations du contrat

`RealMetaTraderService` fait passer *tous* ses appels par `Mt5ProcessWorker`, y
compris `initialize` / `login`. Le mode recommandé reste la session déjà ouverte
manuellement dans MT5 Desktop : aucun identifiant n'est alors stocké.

`FakeMetaTraderService` implémente le même contrat `MetaTraderService` en
mémoire, sans dépendance à `MetaTrader5`, ce qui permet à toute la suite de tests
et au mode PAPER de fonctionner sur n'importe quelle plateforme.
`PaperTradingService` hérite du simulateur mais interroge le terminal réel pour
les cotations et les métadonnées lorsque celui-ci est connecté.

---

## 6. Bus d'événements et WebSocket

### 6.1 `services/events.py`

`EventBus` distribue un objet `Event` — `{type, ts, data}` — à un ensemble
d'abonnés. Chaque abonné possède **sa propre file bornée** à
`QUEUE_MAX_SIZE = 500`. Si la file d'un client est pleine, l'événement le plus
ancien est abandonné : un client lent ne bloque jamais le moteur de trading.

`publish()` est non bloquant et conserve le dernier événement de chaque type.
`snapshot()` renvoie les derniers états connus pour `mt5.status`,
`telegram.status`, `openrouter.status`, `trading.state`, `account.updated` et
`tunnel.status` ; ils sont envoyés immédiatement à un client qui se connecte.

Types d'événements réellement publiés :

| Type | Émis par |
|---|---|
| `hello` | connexion WebSocket |
| `ping` | maintien de la ligne, toutes les 25 s |
| `signal.new`, `signal.updated`, `signal.rejected`, `signal.needs_review` | pipeline, moteur |
| `position.opened`, `position.updated`, `position.closed` | exécuteur, gestionnaire de positions |
| `order.placed`, `order.cancelled` | exécuteur, gestionnaire de positions |
| `account.updated`, `pnl.updated` | boucle de suivi |
| `mt5.status`, `telegram.status`, `openrouter.status`, `tunnel.status` | services correspondants |
| `trading.state` | pause, reprise, démarrage |
| `channel.updated`, `channel.analysis` | analyse de canal |
| `journal` | chaque entrée de journal diffusée |
| `error`, `notification` | échecs d'ordre, arrêt d'urgence, tests de diagnostic |

### 6.2 `/api/v1/ws`

Le client s'authentifie avec son jeton, soit en paramètre de requête
(`?token=…`), soit dans le premier message JSON (`{"token": "…"}`) — cette
seconde forme évite que le jeton finisse dans les journaux d'accès. Un jeton
absent ou invalide ferme la connexion avec le code `4401`.

Ensuite : `hello`, puis l'instantané des états, puis le flux au fil de l'eau.
Deux tâches tournent en parallèle — `_pump` (envoi, avec `ping` toutes les
`PING_INTERVAL_SECONDS = 25.0` secondes) et `_drain` (réception, répond à un
`{"type": "ping"}` applicatif).

Le WebSocket n'apparaît pas dans `docs/openapi.json` : OpenAPI ne décrit que les
opérations HTTP.

---

## 7. Schéma de la base

Une base SQLite unique, `bridge/data/tradepilot.sqlite3` par défaut (le chemin
dérive de `DATA_DIR`). **23 tables.**

### 7.1 Tables transverses — `models/core.py`

| Table | Modèle | Contenu |
|---|---|---|
| `settings` | `AppSetting` | clé/valeur générique, valeurs JSON, préférences non sensibles |
| `secrets` | `Secret` | secrets chiffrés Fernet + indice partiel (`hint`) |
| `devices` | `Device` | téléphones appairés : `device_id`, `token_hash` (SHA-256), `revoked`, `push_token` |
| `risk_settings` | `RiskSettings` | ligne unique `id=1` — tous les réglages du `RiskManager` |
| `trading_state` | `TradingState` | ligne unique `id=1` — pause, pertes consécutives, compteurs du jour, `peak_equity`, `live_unlocked_at`, `onboarding_completed` |
| `journal_entries` | `JournalEntry` | journal fonctionnel affiché dans l'application |
| `audit_logs` | `AuditLog` | trace immuable des actions sensibles |

### 7.2 Tables Telegram — `models/telegram.py`

| Table | Modèle | Contenu |
|---|---|---|
| `telegram_account` | `TelegramAccount` | ligne unique `id=1` : `api_id`, téléphone, identité publique, `authorized`. Ni `api_hash` ni session ici. |
| `channels` | `Channel` | canaux connus : `telegram_id` unique, `joined`, `monitored`, compteurs |
| `channel_settings` | `ChannelSettings` | surcharges par canal ; `NULL` = utiliser le réglage global |
| `channel_analysis` | `ChannelAnalysis` | rapports d'analyse, avec le bloc `backtest` en JSON |
| `channel_parser_profiles` | `ChannelParserProfile` | gabarits appris : `symbol_aliases`, `known_formats` (20 derniers), compteurs local/IA, `confidence` |
| `messages` | `TelegramMessage` | messages bruts ; contrainte d'unicité `uq_message_channel` sur `(channel_id, message_id)` |

### 7.3 Tables de trading — `models/trading.py`

| Table | Modèle | Contenu |
|---|---|---|
| `signals` | `Signal` | signal interprété ; `idempotency_key` unique ; toute information absente reste `NULL` |
| `signal_events` | `SignalEvent` | une ligne par étape du pipeline — c'est la piste d'audit d'un signal |
| `trades` | `TradeRecord` | positions ouvertes puis fermées, PAPER comme MT5 |
| `orders` | `PendingOrderRecord` | ordres en attente (limit / stop) |
| `risk_events` | `RiskEvent` | chaque décision du `RiskManager`, acceptée ou refusée, avec le détail des contrôles |
| `daily_statistics` | `DailyStatistic` | agrégat journalier, global ou par canal |
| `symbol_mappings` | `SymbolMapping` | alias → symbole canonique → symbole broker |
| `backtest_results` | `BacktestResult` | un signal historique rejoué, avec son issue |
| `ai_requests` | `AiRequest` | trace des appels OpenRouter : but, modèle, latence, taille — aucun contenu de message |
| `ai_model_state` | `AiModelState` | ligne unique `id=1` : mode auto, modèles retenus, liste des modèles gratuits |

Relations déclarées par clé étrangère : `signals.channel_id → channels.id`,
`signal_events.signal_id → signals.id`, `trades.signal_id → signals.id`,
`orders.signal_id → signals.id`, `channel_settings.channel_id → channels.id`,
`channel_analysis.channel_id → channels.id`,
`channel_parser_profiles.channel_id → channels.id`,
`messages.channel_id → channels.id`,
`backtest_results.analysis_id → channel_analysis.id`.

---

## 8. Architecture de l'application Flutter

### 8.1 Organisation

```
mobile/lib/
├── main.dart               restauration de la configuration avant tout affichage
├── app/app_shell.dart      coque : navigation basse 5 onglets + bandeau hors ligne
├── core/
│   ├── api/                api_client (Dio), endpoints, ws_client, api_exception
│   ├── connection/         connection_controller : appairage, bascule d'adresse
│   ├── database/           local_database (Drift) : cache hors ligne
│   ├── notifications/      notification_service : notifications locales
│   ├── providers/          bridge_data : lecture d'une route + cache
│   ├── routing/            app_router (go_router), classe Routes
│   ├── security/           secure_store : adresse + jeton, chiffrés
│   ├── theme/              app_colors, app_theme (clair et sombre)
│   ├── utils/              formatters
│   └── widgets/            composants partagés (OfflineBanner, StatusChip…)
└── features/               un dossier par domaine : ai, bridge, channels, dashboard,
                            diagnostics, journal, more, onboarding, orders,
                            positions, risk, settings, signals, statistics
```

### 8.2 Gestion d'état — Riverpod

- `ProviderScope` enveloppe l'application entière (`main.dart`).
- `apiClientProvider`, `wsClientProvider`, `localDatabaseProvider`,
  `connectionProvider` (un `StateNotifier`) constituent le socle.
- Les écrans consomment des `FutureProvider` définis dans
  `core/providers/bridge_data.dart` (`dashboardProvider`, `statusProvider`,
  `riskSettingsProvider`, `tradingStateProvider`…) et dans les dossiers
  `features/*/providers/`.
- `liveRefreshProvider`, observé par `AppShell`, maintient l'abonnement WebSocket
  actif tant que la coque est montée et invalide les providers concernés à la
  réception d'un événement.

### 8.3 Navigation — go_router

Un `ShellRoute` porte les cinq onglets (`/`, `/signals`, `/channels`, `/trades`,
`/more`). Les écrans de détail et les écrans modaux
(`/pairing`, `/onboarding`, `/emergency`, `/channels/discover`,
`/channels/compare`, `/more/*`) sont rattachés au navigateur racine.

La redirection globale est simple et stricte : **tant que
`connection.paired` est faux, toute la navigation est renvoyée vers
`/pairing`.** Aucune donnée de trading n'est accessible sans liaison
authentifiée.

### 8.4 Cache hors ligne — Drift

`LocalDatabase` définit trois tables SQLite locales :

| Table | Contenu |
|---|---|
| `CacheEntries` | instantané JSON d'un écran, par clé, avec sa date |
| `CachedSignals` | derniers signaux reçus, consultables sans réseau |
| `CachedTrades` | historique récent des trades |

Elle ne contient **que des données d'affichage** : aucun secret, aucun jeton.

`fetchWithCache` lit la route, écrit l'instantané puis le renvoie. En cas
d'échec réseau, elle renvoie l'instantané précédent avec `stale = true` et sa
date. L'interface affiche alors explicitement le bandeau `BRIDGE HORS LIGNE`
plutôt que de laisser croire que le Bridge a répondu.

### 8.5 Client HTTP et WebSocket

`ApiClient` (Dio) normalise l'adresse saisie par l'utilisateur : une adresse IP
ou `localhost` est préfixée `http://`, un nom de domaine `https://`. Timeouts :
8 s à la connexion, 30 s en lecture et en écriture. Deux `ValueNotifier`
exposent `reachable` et `unauthorized` ; un 401 fait repasser l'application par
l'appairage.

`WsClient` reconnecte automatiquement avec un délai croissant
(`1, 2, 5, 10, 20, 30, 60` secondes), expose un `Stream<BridgeEvent>` et un
filtre `on({...})` par type d'événement.

### 8.6 État d'implémentation

**Tous les écrans sont implémentés.** Aucun écran provisoire ne subsiste dans
`mobile/lib/features/` : Accueil, Appairage, Onboarding, Signaux et détail d'un
signal, Canaux, détail d'un canal, Découvrir, Comparaison, Trades, Statistiques,
Journal, Risque, Réglages, Correspondance des symboles, Diagnostic, Go Live,
Analyse IA, Connexions, Plus et Arrêt d'urgence.

`flutter analyze` ne signale aucun problème et la suite `flutter test` compte
**29 tests** répartis sur 4 fichiers (`widget_test.dart`,
`signals_channels_test.dart`, `signals_channels_layout_test.dart`,
`trades_risk_settings_test.dart`), tous réussis.

---

## 9. Résilience et démarrage tolérant

`main.py` applique un principe explicite : **le Bridge doit démarrer même si
MetaTrader 5, Telegram ou OpenRouter sont absents ou mal configurés.** Chaque
composant indisponible est signalé dans le diagnostic plutôt que de bloquer le
service.

| Situation | Comportement |
|---|---|
| Paquet `MetaTrader5` absent | `mt5_state = NOT_CONFIGURED`, le mode PAPER reste utilisable avec des prix simulés |
| Terminal détecté mais non connecté | `mt5_state = DISCONNECTED` avec un message d'action explicite |
| Terminal muet, qui ne répond plus | le processus enfant MT5 est tué au bout du délai imparti, une erreur explicite est levée et un processus neuf est créé au prochain appel. L'API, le WebSocket et l'écoute Telegram continuent de fonctionner. |
| Aucune session Telegram | démarrage normal, message d'information, écoute non démarrée |
| Clé OpenRouter absente | le parser déterministe fonctionne seul |
| `execution_mode = MT5_LIVE` mais `live_unlocked = false` | retour forcé à `MT5_DEMO` avec un avertissement |
| Connexion Telegram perdue | watchdog interne, reconnexion 5 s / 10 s / 20 s / 60 s, abandon après 12 tentatives |
| Boucle de suivi en erreur | compteur d'échecs consécutifs, ralentissement progressif au-delà de 5 |
| OpenRouter en échec répété | coupe-circuit ouvert après 4 échecs, réarmé au bout de 300 s |
