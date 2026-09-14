# Tester sans risque

Ce document décrit comment exercer TradePilot de bout en bout sans engager
d'argent : le mode PAPER, puis un compte MetaTrader 5 de démonstration, les
scénarios à reproduire, la lecture de la piste d'audit d'un signal, et les suites
de tests automatisés.

---

## 1. Les deux étages de test

| | `PAPER` | `MT5_DEMO` |
|---|---|---|
| Ordre envoyé au broker | **non** | oui, sur un compte de démonstration |
| Prix utilisés | **réels**, lus dans le terminal MT5 s'il est connecté ; simulés sinon | réels |
| Métadonnées de symbole | réelles si MT5 est connecté | réelles |
| Solde | `paper_balance` (10 000 par défaut) | solde du compte démo |
| Contraintes du broker | celles du symbole réel si MT5 est connecté ; sinon celles du catalogue interne | réelles, y compris le refus d'un ordre |
| Ce que cela valide | tout le pipeline jusqu'au volume calculé | en plus : `order_check`, `order_send`, exécution, suivi réel |
| Ce que cela ne valide pas | l'acceptation de l'ordre par le broker | rien de plus, à part la fiscalité et l'émotion |

Commencez par `PAPER`, restez-y jusqu'à ce que le comportement soit prévisible,
puis passez à `MT5_DEMO`.

### 1.1 Le mode PAPER

`PaperTradingService` hérite du simulateur `FakeMetaTraderService` mais interroge
le terminal réel dès qu'il est connecté :

- les **cotations** viennent du terminal (`symbol_tick`) et sont réinjectées dans
  le carnet simulé, ce qui permet aux stop loss et take profits simulés de se
  déclencher sur de vrais mouvements de prix ;
- les **métadonnées** du symbole (pas de volume, minimum, `trade_stops_level`,
  `tick_value`) sont celles du broker, ce qui rend le volume calculé réaliste ;
- la **liste des symboles** est celle du terminal.

Sans terminal disponible, la simulation retombe sur son catalogue interne. Ce
n'est jamais présenté comme du réel : le diagnostic affiche alors

```
Le paper trading utilise des prix simules : MetaTrader 5 n'est pas connecte.
```

et `GET /api/v1/mt5/account` renvoie `paperUsesLivePrices: false`.

Le compte papier est toujours identifié comme tel : `name = "Paper Trading"`,
`company = "TradePilot"`, `server = "TradePilot-Paper"`, `login = 99000001`,
`kind = DEMO`.

### 1.2 Activer le mode PAPER

C'est déjà le mode par défaut. Pour le vérifier et le remettre :

```
GET  /api/v1/trading/state
POST /api/v1/trading/execution-mode      { "mode": "PAPER" }
```

Ajuster le solde de départ :

```
PATCH /api/v1/risk/settings              { "paperBalance": 10000 }
```

Le solde est appliqué au moteur papier **au démarrage du Bridge** : redémarrez-le
après l'avoir changé.

### 1.3 Passer en MT5 DEMO

Prérequis : MetaTrader 5 ouvert, connecté à un compte **démo**, AutoTrading
activé (voir [MT5_EXNESS_SETUP.md](MT5_EXNESS_SETUP.md)).

```
POST /api/v1/trading/execution-mode      { "mode": "MT5_DEMO" }
```

Si le compte connecté est un compte réel, ou si son type est indéterminable, le
`RiskManager` refusera chaque signal avec `ACCOUNT_MISMATCH`. C'est voulu.

---

## 2. Appeler l'API depuis PowerShell

L'application couvre la plupart de ces opérations, mais appeler l'API
directement reste le moyen le plus rapide de préparer un scénario et d'en lire
le résultat brut. Toutes les routes ci-dessous exigent le jeton de périphérique.

```powershell
# À faire une fois par session PowerShell
$Bridge  = "http://127.0.0.1:8787"
$Token   = "<le jeton obtenu a l'appairage>"
$Headers = @{ Authorization = "Bearer $Token" }
```

Vérifier que le Bridge répond, sans jeton :

```powershell
Invoke-RestMethod "$Bridge/api/v1/health"
```

Une lecture authentifiée :

```powershell
Invoke-RestMethod "$Bridge/api/v1/trading/state" -Headers $Headers | Format-List
```

Un envoi de données :

```powershell
$body = @{ text = "GOLD BUY NOW`nSL 3310`nTP 3330" } | ConvertTo-Json
Invoke-RestMethod "$Bridge/api/v1/signals/parse-test" -Method Post -Headers $Headers -ContentType "application/json" -Body $body
```

> Si vous n'avez pas encore de jeton, démarrez le Bridge, relevez le code
> d'appairage affiché dans la console, puis appelez `POST /api/v1/pairing` avec
> ce code et un `deviceId` de votre choix (au moins 4 caractères). La réponse
> contient le jeton, affiché une seule fois.

---

## 3. Injecter un message de test

### 3.1 `POST /api/v1/signals/parse-test`

C'est la route de test du parser.

```
POST /api/v1/signals/parse-test
{ "text": "XAUUSD BUY 3320-3315\nSL 3300\nTP1 3330\nTP2 3345\nTP3 3360",
  "channelId": null,
  "useAi": true }
```

| Champ | Défaut | Rôle |
|---|---|---|
| `text` | — | le message à interpréter, 1 à 4 000 caractères |
| `channelId` | `null` | applique les alias de symboles appris pour ce canal |
| `useAi` | `true` | autorise le repli IA ; mettez `false` pour tester le parser local seul |

La réponse contient :

| Champ | Contenu |
|---|---|
| `parsed` | l'interprétation complète : `isSignal`, `symbol`, `symbolRaw`, `direction`, `orderType`, `entryPrice`, `entryMin`, `entryMax`, `stopLoss`, `takeProfits`, `confidence`, `source` (`deterministic` / `ai`), `formatSignature`, `aiModel`, `warnings` |
| `validation` | `ok` et la liste des anomalies, avec leur code et leur caractère bloquant |
| `followUp` | l'action de suivi détectée si le texte n'est pas un signal |
| `note` | « Test d'interprétation uniquement : aucun ordre n'est envoyé. » |

**Ce que cette route ne fait pas**, et c'est important : elle **n'écrit rien en
base**, ne crée aucun signal, n'appelle pas le `RiskManager`, ne calcule aucun
volume et n'envoie aucun ordre. Elle sert exclusivement à vérifier la lecture
d'un texte.

### 3.2 Exercer le pipeline complet

Il n'existe **aucune route** permettant d'injecter un message dans le moteur
complet. Le seul point d'entrée du pipeline est le message Telegram reçu par
`ChannelListener`.

Pour exercer réellement le pipeline de bout en bout :

1. créez **votre propre canal Telegram privé** depuis votre application
   Telegram ;
2. ajoutez-le à la surveillance :
   ```powershell
   $body = @{ username = "<le pseudonyme de votre canal>" } | ConvertTo-Json
   Invoke-RestMethod "$Bridge/api/v1/channels" -Method Post -Headers $Headers -ContentType "application/json" -Body $body
   ```
   ou, pour un canal privé sans pseudonyme, avec son `telegramId` ;
3. laissez-le en mode `OBSERVE` pour commencer ;
4. publiez vos messages de test dans ce canal, depuis votre téléphone.

C'est la seule façon de valider la chaîne complète : réception, déduplication,
interprétation, risque, exécution, suivi, messages de suivi. C'est aussi le seul
moyen de tester le rattachement d'un `TP1 HIT` à son signal d'origine.

---

## 4. Messages de test à utiliser

Ces textes sont ceux du jeu de tests du projet
(`bridge/tests/fixtures/messages.py`), avec le résultat attendu vérifié à la
main.

### 4.1 Signaux propres

| Message | Interprétation attendue |
|---|---|
| `GOLD BUY NOW` / `SL 3310` / `TP 3330` | `XAUUSD`, `BUY`, `MARKET`, SL `3310`, TP `[3330]`, confiance `0.85` |
| `XAUUSD BUY 3320-3315` / `SL 3300` / `TP1 3330` / `TP2 3345` / `TP3 3360` | `XAUUSD`, `BUY`, zone `3315`–`3320`, SL `3300`, TP `[3330, 3345, 3360]`, confiance `0.95` |
| `Sell gold now @ 3341` / `stop 3350` / `targets 3330, 3320, 3300` | `XAUUSD`, `SELL`, `MARKET`, entrée `3341`, SL `3350`, TP `[3330, 3320, 3300]`, confiance `1.00` |
| `XAU/USD LONG` / `Entry 3325` / `SL 3310` / `TP1 3340` / `TP2 3355` | `XAUUSD`, `BUY`, entrée `3325`, SL `3310`, TP `[3340, 3355]`, confiance `0.95` |
| `SELL GOLD 3350` / `SL 3362` / `TP 3330` | `XAUUSD`, `SELL`, entrée `3350`, SL `3362`, TP `[3330]`, confiance `0.95` |

Notez que le type d'ordre reste `null` quand le message donne un prix sans dire
`LIMIT` ni `STOP` : c'est `resolve_order_type` qui tranchera, en comparant le
prix demandé au cours réel au moment de l'exécution.

### 4.2 Messages de suivi

| Message | Action attendue |
|---|---|
| `TP1 HIT` | `TP_HIT`, index `1` |
| `TP2 HIT` | `TP_HIT`, index `2` |
| `TARGET 2 REACHED` | `TP_HIT`, index `2` |
| `TP1 HIT MOVE SL BE` | `TP_HIT`, index `1`, `alsoBreakEven = true` |
| `SL HIT` | `SL_HIT` |
| `CLOSE GOLD` | `CLOSE_ALL`, symbole `XAUUSD` |
| `Close all positions now` | `CLOSE_ALL` |
| `CLOSE 50%` | `CLOSE_PARTIAL`, 50 % |
| `CLOSE HALF` | `CLOSE_PARTIAL`, 50 % |
| `Book 30% profit` | `CLOSE_PARTIAL`, 30 % |
| `MOVE SL TO BE`, `SL BE`, `BREAK EVEN`, `risk free now` | `MOVE_SL_BE` |
| `MOVE SL 3350` | `MOVE_SL`, prix `3350` |
| `MOVE TP1 TO 3360` | `MOVE_TP`, index `1`, prix `3360` |
| `CANCEL GOLD`, `DELETE PENDING`, `Cancel the pending order on gold` | `CANCEL_PENDING` |
| `RUNNING +50 PIPS`, `HOLD` | `INFO`, aucune action |

### 4.3 Messages qui ne doivent jamais devenir un trade

Tous ces messages doivent donner `isSignal = false` :

| Message |
|---|
| `GOOD MORNING FAMILY 🔥` |
| `Gold is looking very bullish today` |
| `Results of the week: +450 pips` |
| `Join our VIP channel now for premium signals` |
| `Congratulations everyone on todays profits` |
| `we are watching gold closely` |
| `Market is very volatile today, stay safe` |
| `Please read the pinned message before trading` |
| `Well done team, great session` |
| `Our analysis of the dollar index shows strength` |
| `Have a nice weekend everyone` |
| `The account grew from 1000 to 2500 this month` |
| `🔥🔥🔥` |

C'est le test le plus important de tous : un message d'ambiance **ne doit jamais**
produire un ordre. Si l'un de ces textes produit un `BUY` ou un `SELL`, ne passez
sous aucun prétexte en mode réel.

Notez le cas `Our analysis of the dollar index shows strength` : il contient un
instrument implicite et une opinion haussière, mais aucune instruction d'ouverture
de position. C'est exactement le cas que la protection contre les hallucinations
doit couvrir.

### 4.4 Messages ambigus ou incohérents

| Message | Résultat attendu |
|---|---|
| `BUY NOW` / `SL 3310` / `TP 3330` | `isSignal = false`, code `NO_ACTION` : aucun instrument |
| `GOLD 3320 3310 3330` | `isSignal = false`, code `NO_ACTION` : aucune direction |
| `XAUUSD BUY 3320` / `SL 3340` / `TP 3350` | signal reconnu, validation bloquée, code `SL_WRONG_SIDE` |
| `XAUUSD SELL 3320` / `SL 3300` / `TP 3350` | validation bloquée, codes `SL_WRONG_SIDE` et `TP_WRONG_SIDE` |
| `EURUSD BUY 1.0820` / `SL 0.5000` / `TP 1.0870` | validation bloquée, code `SL_TOO_FAR` : plus de 25 % d'écart, valeur probablement mal lue |
| `BUY EURUSD @ 1,0820` / `SL 1,0790` / `TP 1,0870` | validation bloquée, code `SL_TOO_CLOSE` : virgule à quatre décimales mal interprétée |
| `XAUUSD BUY LIMIT` / `SL 3300` / `TP 3350` | validation bloquée, code `PENDING_WITHOUT_PRICE` |
| `XAUUSD BUY` / `ENTRY 3320` / `SL 3310` / `TP 3300` | validation bloquée, code `TP_WRONG_SIDE` |

---

## 5. Scénarios à reproduire

Parcourez-les dans l'ordre. Chacun vérifie un comportement précis.

### Scénario 1 — signal complet

**But :** valider la chaîne nominale.

1. Mode `PAPER`, `auto_trading_enabled = true`, canal en `AUTO`.
2. Publiez `XAUUSD BUY 3320-3315 / SL 3300 / TP1 3330 / TP2 3345 / TP3 3360`
   dans votre canal de test.
3. Vérifiez `GET /api/v1/signals?limit=5`.

**Attendu :** un signal en statut `OPEN` ou `SENT`, avec `computedLot`,
`riskAmount` et `riskReward` renseignés, et une position visible dans
`GET /api/v1/positions`.

**À contrôler :** le volume est-il cohérent avec `risk_percent` et le solde ?
Reprenez le calcul à la main avec la section 5 de
[RISK_MANAGEMENT.md](RISK_MANAGEMENT.md).

### Scénario 2 — TP1 HIT et break even

**But :** valider le rattachement d'un message de suivi et le break even.

1. Après le scénario 1, publiez `TP1 HIT MOVE SL BE` dans le même canal —
   idéalement **en réponse** au message d'origine, ce qui garantit le
   rattachement.
2. Regardez `GET /api/v1/signals/{id}` du signal d'origine, section `followUps`.

**Attendu :** un second signal avec `followUpAction = TP_HIT`, une fermeture
partielle de 40 % (valeur par défaut de `split_ratios` en stratégie
`PARTIAL_CLOSE`), et un stop loss déplacé au prix d'entrée décalé de
`break_even_offset_points`.

**À contrôler :** `breakEvenApplied` est-il passé à `true` sur le trade ? Le
`stopLoss` est-il bien à l'entrée décalée, et pas ailleurs ?

Si le rattachement échoue, le journal contient `follow_up_orphan` : « Message de
suivi (TP_HIT) sans signal correspondant ». Vérifiez que le signal d'origine est
toujours dans un statut actif et date de moins de 48 heures.

### Scénario 3 — message de convivialité

**But :** vérifier qu'aucun ordre n'est produit.

1. Publiez `GOOD MORNING FAMILY 🔥`, puis
   `Our analysis of the dollar index shows strength`.

**Attendu :** aucun signal exécutable. Le message est soit ignoré, soit
enregistré avec le statut `NO_ACTION`. Aucune position n'apparaît.

### Scénario 4 — doublon

**But :** vérifier l'idempotence.

1. Publiez un signal complet.
2. Publiez **exactement le même texte** juste après.

**Attendu :** une seule position. Le second message est arrêté à l'entrée avec
`DUPLICATE_SIGNAL` — « Message déjà traité : aucun ordre supplémentaire ».

Variante plus proche du réel : modifiez le message d'origine dans Telegram plutôt
que d'en republier un. La contrainte d'unicité `(channel_id, message_id)`
s'applique aussi.

### Scénario 5 — limite de perte journalière

**But :** vérifier que la limite bloque réellement.

1. Abaissez temporairement la limite :
   ```powershell
   $body = @{ maxDailyLossPercent = 0.5 } | ConvertTo-Json
   Invoke-RestMethod "$Bridge/api/v1/risk/settings" -Method Patch -Headers $Headers -ContentType "application/json" -Body $body
   ```
2. Laissez un ou deux trades papier se clôturer en perte, ou fermez-les
   manuellement à perte.
3. Publiez un nouveau signal.

**Attendu :** refus avec `DAILY_LOSS_LIMIT` et un détail chiffré du type
« Perte du jour 0.62% : limite 0.50% ».

**À contrôler :** `GET /api/v1/risk/events?limit=5` montre la décision complète,
avec la liste des contrôles franchis avant le refus.

Testez de la même façon `max_consecutive_losses` : avec la valeur par défaut de
`3` et `pause_after_max_losses = true`, la troisième perte consécutive met
l'automatisation en pause pour 240 minutes. `GET /api/v1/trading/state` doit
alors montrer `paused = true` avec le motif « 3 pertes consecutives ».

### Scénario 6 — Bridge coupé

**But :** vérifier que rien ne part au rattrapage, et que l'application le dit.

1. Arrêtez le Bridge :
   ```powershell
   .\scripts\stop_bridge.ps1
   ```
2. Publiez deux ou trois signaux dans votre canal de test.
3. Attendez **plus de 5 minutes** (`max_signal_age_seconds` vaut 300 secondes).
4. Redémarrez le Bridge.

**Attendu :** aucun ordre n'est envoyé pour les messages publiés pendant la
coupure. Selon le comportement de Telegram à la reconnexion, soit les messages ne
sont pas rejoués du tout, soit ils le sont et sont alors refusés avec
`SIGNAL_EXPIRED`.

**Côté application :** pendant la coupure, le bandeau `BRIDGE HORS LIGNE` doit
s'afficher, et les écrans doivent montrer les dernières données connues
**marquées comme telles** (`stale = true`), jamais présentées comme fraîches.

Variante utile : coupez MetaTrader 5 sans couper le Bridge, en mode `MT5_DEMO`.
Les signaux doivent être refusés avec `MT5_DISCONNECTED`, pas silencieusement
ignorés.

### Scénario 7 — arrêt d'urgence

**But :** savoir l'utiliser avant d'en avoir besoin.

```powershell
Invoke-RestMethod "$Bridge/api/v1/emergency/info" -Headers $Headers

$body = @{ confirmation = "FERMER TOUTES LES POSITIONS"; suspendAutomation = $true } | ConvertTo-Json
Invoke-RestMethod "$Bridge/api/v1/emergency/close-all" -Method Post -Headers $Headers -ContentType "application/json" -Body $body
```

**Attendu :** toutes les positions du mode courant sont fermées, l'automatisation
est mise en pause si `suspendAutomation` vaut `true`, et le journal contient une
entrée `emergency_close_all` de niveau `CRITICAL`.

La phrase de confirmation doit être saisie **exactement** —
`FERMER TOUTES LES POSITIONS`. Toute autre valeur donne un `400`. La comparaison
ignore la casse et les espaces multiples, rien de plus.

Ce test coche également l'élément « Arrêt d'urgence testé » de la checklist de
mise en production.

---

## 6. Lire la timeline d'audit d'un signal

```
GET /api/v1/signals/{signal_id}
```

C'est la vue la plus utile pour comprendre ce qui s'est passé. Elle rassemble :

| Bloc | Contenu |
|---|---|
| champs du signal | texte brut, interprétation, statut, motif de refus, mode d'exécution, volume calculé, montant risqué, ratio rendement/risque |
| `channel` | canal d'origine |
| `timeline` | **une ligne par étape**, avec `stage`, `status`, `success`, `message` et le bloc `data` complet |
| `trades` | positions ouvertes par ce signal, avec `rMultiple`, `breakEvenApplied`, `tpIndex`, `closeReason` |
| `pendingOrders` | ordres en attente |
| `followUps` | messages de suivi rattachés à ce signal |
| `audit` | entrées du journal d'audit liées à ce signal |

### 6.1 Les étapes de la timeline

| `stage` | Ce qu'il contient |
|---|---|
| `parser` | l'interprétation complète et le résultat de la validation |
| `risk` | la décision du `RiskManager` : liste de tous les contrôles avec leur détail, le calcul du volume, le prix d'entrée retenu, le ratio rendement/risque |
| `order_check` | la requête envoyée au broker et sa réponse |
| `order_send` | idem pour l'envoi réel |
| `execution` | le résultat consolidé, avec les tickets |
| `follow_up` | les actions déclenchées par un message de suivi |
| `manual` | validation ou refus manuel |
| `lifecycle` | expiration, clôture de toutes les positions |

### 6.2 Lire un refus

Pour un signal refusé, la ligne `risk` contient la liste `checks` : chaque
contrôle franchi apparaît avec `passed = true` et son détail, et le dernier
apparaît avec `passed = false` et le motif exact. On voit donc **jusqu'où** le
signal est allé, pas seulement qu'il a été refusé.

Exemple de lecture :

```
auto_trading    passed=true
pause           passed=true
channel         passed=true
execution_mode  passed=true   PAPER
signal          passed=true
confidence      passed=true   0.95
direction       passed=true   BUY
symbol_allowed  passed=true   XAUUSD
stop_take       passed=true
signal_age      passed=true   12s
trading_window  passed=true
symbol_available passed=true  XAUUSDm
spread          passed=false  Spread 55 points superieur au maximum 40
```

Les mêmes décisions sont aussi listées, indépendamment du signal, par
`GET /api/v1/risk/events`.

### 6.3 Le journal fonctionnel

```
GET /api/v1/journal?limit=100
GET /api/v1/journal?category=risk
GET /api/v1/journal?signalId=42
GET /api/v1/journal/audit
```

Catégories utilisées : `system`, `signal`, `risk`, `trading`, `channel`,
`telegram`, `ai`, `security`, `emergency`, `mt5`.

---

## 7. Lancer les suites de tests

### 7.1 Tests Python

```powershell
cd "C:\Users\<votre-nom>\Desktop\trader apk\bridge"
.\.venv\Scripts\python.exe -m pytest
```

Résultat observé sur cette machine le 11 septembre 2026 : **788 tests réussis**
en environ 33 secondes. Le dépôt évolue : relancez la commande pour la valeur du
jour.

Les tests utilisent une base **en mémoire** (`testing = true`) et le simulateur
`FakeMetaTraderService` : ils ne touchent ni à votre base, ni à MetaTrader 5, ni
à Telegram, ni à OpenRouter.

Variantes utiles :

```powershell
# Un seul fichier
.\.venv\Scripts\python.exe -m pytest tests\test_risk_manager.py

# Un seul test, sortie détaillée
.\.venv\Scripts\python.exe -m pytest tests\test_risk_manager.py -k daily_loss -vv

# Avec la couverture
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
```

Contenu de la suite :

| Fichier | Ce qu'il couvre |
|---|---|
| `test_normalizer.py` | nettoyage du texte, emojis, séparateurs, nombres |
| `test_symbols.py` | alias vers symbole canonique, paires de devises, suffixes broker |
| `test_deterministic_parser.py` | lecture des signaux, formats variés, faux positifs |
| `test_follow_up_parser.py` | messages de suivi |
| `test_validator.py` | cohérence interne d'un signal |
| `test_pipeline.py` | orchestration, idempotence, repli IA |
| `test_risk_calculator.py` | calcul du volume, arrondis, fractionnement |
| `test_risk_manager.py` | **tous** les contrôles de risque, un par un |
| `test_fake_mt5.py` | conformité du simulateur au contrat `MetaTraderService` |
| `test_engine_scenarios.py` | scénarios de bout en bout |
| `test_channels_analyzer.py` | mesures d'analyse et simulation historique |
| `test_openrouter.py` | client, coupe-circuit, sélecteur, retypage de la sortie IA |
| `test_statistics.py` | agrégats et comparaison de canaux |
| `test_api.py` | routes HTTP et authentification |

Qualité du code :

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
```

### 7.2 Tests Flutter

```powershell
cd "C:\Users\<votre-nom>\Desktop\trader apk\mobile"
flutter analyze
flutter test
```

Résultat observé sur cette machine : `No issues found!` pour l'analyse, et
**29 tests réussis** répartis sur quatre fichiers : `widget_test.dart`,
`signals_channels_test.dart`, `signals_channels_layout_test.dart` et
`trades_risk_settings_test.dart`.

La suite couvre le thème et les couleurs, le bandeau hors ligne, le blocage de la
confirmation par phrase exacte, les écrans Signaux et Canaux, leur mise en page,
l'écran Trades, le formulaire de risque, la section trading en mode réel
déverrouillé, le cas « aucun modèle gratuit » et le réessai après une erreur
d'historique.

---

## 8. Grille de sortie du mode test

Avant d'envisager la suite, vous devriez pouvoir répondre oui à tout :

- [ ] Un signal complet produit une position, avec un volume que je sais
      recalculer à la main.
- [ ] Un message de convivialité ne produit jamais rien.
- [ ] Un doublon ne produit jamais deux positions.
- [ ] Un `TP1 HIT` est bien rattaché à son signal d'origine.
- [ ] Le break even se déclenche et place le stop au bon endroit.
- [ ] Une limite de risque, quand je l'abaisse, bloque réellement, avec un motif
      compréhensible.
- [ ] Après une coupure du Bridge, aucun ordre de rattrapage n'est envoyé.
- [ ] Je sais lire la timeline d'un signal refusé et comprendre pourquoi.
- [ ] Je sais déclencher l'arrêt d'urgence sans hésiter.
- [ ] Les suites `pytest` et `flutter test` passent intégralement.

Ensuite seulement : [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md).

---

## 9. Ce qui n'a pas pu être vérifié sur cette machine

- Les scénarios 1 à 7 **n'ont pas été exécutés** : ils exigent une session
  Telegram réelle et un terminal MetaTrader 5 connecté, dont aucun n'était
  disponible ici.
- Aucun ordre, même de démonstration, n'a été envoyé à un broker.
- Seules les suites de tests automatisées ont été réellement exécutées :
  788 tests `pytest` réussis, 29 tests `flutter test` réussis, `flutter analyze`
  sans avertissement.
- L'absence de route permettant d'injecter un message directement dans le moteur
  complet est une limite connue : le contournement décrit en section 3.2 — un
  canal Telegram privé qui vous appartient — est la seule voie disponible
  aujourd'hui.
