# Gestion du risque

Ce document décrit le `RiskManager` de TradePilot : chaque réglage, son rôle,
sa valeur par défaut réelle, et l'ordre exact dans lequel les contrôles sont
appliqués.

Sources : `bridge/app/models/core.py` (classe `RiskSettings`),
`bridge/app/services/risk/manager.py`, `bridge/app/services/risk/calculator.py`,
`bridge/app/services/trading/position_manager.py`,
`bridge/app/schemas/requests.py`.

C'est la partie la plus importante du système. Le `RiskManager` est la
**dernière barrière** avant tout envoi d'ordre. Il n'a aucun accès à la base de
données : l'appelant lui remet un `RiskContext` complet et il applique les
règles. Aucune règle ne peut être désactivée à chaud, et l'IA ne peut pas
l'atteindre.

---

## 1. Les réglages

Tous les réglages vivent dans une **ligne unique** de la table `risk_settings`
(`id = 1`). Ils se lisent avec `GET /api/v1/risk/settings` et se modifient avec
`PATCH /api/v1/risk/settings`.

Les noms cités ci-dessous sont les noms de colonnes du modèle ; l'API les expose
en `camelCase` (par exemple `risk_percent` → `riskPercent`).

### 1.1 Interrupteurs principaux

| Réglage | Défaut | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|
| `auto_trading_enabled` | `false` | Interrupteur général. Tant qu'il est faux, aucun signal n'est exécuté automatiquement, quel que soit le mode ou le canal. | Trading auto désactivé : un signal parfaitement valide est refusé avec `AUTO_TRADING_OFF` et enregistré pour consultation. |
| `execution_mode` | `PAPER` | Destination des ordres : `PAPER`, `MT5_DEMO` ou `MT5_LIVE`. **Non modifiable par `PATCH /api/v1/risk/settings`** : il faut passer par `POST /api/v1/trading/execution-mode`. | En `PAPER`, un ordre de 0,05 lot est enregistré dans le carnet simulé ; aucun ordre ne part vers le broker. |
| `live_unlocked` | `false` | Verrou du mode réel. **Non modifiable par `PATCH /api/v1/risk/settings`** : le champ est protégé côté dépôt. Seule la route `POST /api/v1/trading/live-unlock` peut le passer à vrai. | Au démarrage, si `execution_mode = MT5_LIVE` et `live_unlocked = false`, le Bridge repasse en `MT5_DEMO` et journalise « Mode réel non déverrouillé : retour au mode demo ». |

### 1.2 Risque

| Réglage | Défaut | Bornes API | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|---|
| `risk_percent` | `0.5` | `0.01` à `10` | Part du **solde** risquée par trade. C'est l'entrée principale du calcul du lot. | Solde 10 000 USD, `risk_percent = 0.5` → capital risqué 50 USD par trade. |
| `max_daily_risk_percent` | `3.0` | `0.1` à `50` | Somme des risques engagés dans la journée UTC. Empêche d'enchaîner vingt trades le même jour. | À 0,5 % par trade, le sixième trade de la journée est refusé (`DAILY_RISK_LIMIT`) une fois 3 % cumulés. |
| `max_daily_loss_percent` | `3.0` | `0.1` à `50` | Perte réalisée maximale sur la journée, rapportée au solde d'ouverture de journée. | Solde d'ouverture 10 000 USD, pertes réalisées −300 USD → 3 % atteints, tout nouveau trade est refusé (`DAILY_LOSS_LIMIT`). |
| `max_drawdown_percent` | `10.0` | `1` à `90` | Écart maximal entre le pic d'equity observé et l'equity courante. | Pic 11 000 USD, equity 9 900 USD → drawdown 10 %, refus `MAX_DRAWDOWN`. |
| `daily_profit_target_percent` | `null` (désactivé) | `0.1` à `100` | Arrête la journée après un gain donné, pour ne pas « rendre » les gains. | Réglé à 2 % : sur un solde d'ouverture de 10 000 USD, dès +200 USD réalisés, refus `DAILY_PROFIT_TARGET`. |

Le pic d'equity (`trading_state.peak_equity`) est mis à jour à chaque cycle de
suivi. Les compteurs journaliers (`day_realized_pnl`, `day_risked_percent`,
`day_start_balance`) sont remis à zéro au changement de **jour UTC** par
`settings_repo.ensure_day_rollover`.

### 1.3 Volumes et exposition

| Réglage | Défaut | Bornes API | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|---|
| `max_lot` | `0.10` | `> 0` à `100` | Plafond absolu du volume d'une position, quel que soit le calcul de risque. | Le calcul demande 0,37 lot ; le volume est ramené à 0,10 lot et `cappedByLimit` passe à vrai dans la trace. |
| `max_positions` | `3` | `1` à `50` | Nombre de positions ouvertes simultanément, tous instruments confondus. | 3 positions ouvertes → le quatrième signal est refusé (`MAX_POSITIONS`). |
| `max_positions_per_symbol` | `1` | `1` à `20` | Empêche d'empiler plusieurs positions sur le même instrument. | Une position sur `XAUUSDm` est déjà ouverte : un second signal or est refusé (`MAX_POSITIONS_SYMBOL`). |
| `max_total_exposure_lots` | `1.0` | `> 0` à `500` | Somme des volumes ouverts. Complète `max_positions` pour les gros lots. | 0,60 + 0,40 lot ouverts = 1,00 lot : le signal suivant est refusé (`MAX_EXPOSURE`). |

`max_positions_per_symbol` et `max_total_exposure_lots` sont **globaux
uniquement** : ils ne peuvent pas être surchargés par canal.

### 1.4 Conditions de marché

| Réglage | Défaut | Bornes API | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|---|
| `max_spread_points` | `40` | `0` à `2000` | Refuse d'entrer quand l'écart achat/vente est anormal (ouverture, news, faible liquidité). | `XAUUSDm`, `point = 0.01`, bid 2400.00 / ask 2400.55 → 55 points > 40 → refus `SPREAD_TOO_HIGH`. |
| `max_slippage_points` | `20` | `0` à `500` | Écart de prix toléré à l'exécution ; transmis au broker comme `deviation`. | Le prix bouge de 15 points entre la décision et l'exécution : l'ordre passe. Au-delà de 20 points, le broker le rejette. |
| `max_signal_age_seconds` | `300` | `10` à `86400` | Empêche d'exécuter un vieux signal, notamment après une reconnexion réseau. | Message publié il y a 7 minutes → 420 s > 300 s → refus `SIGNAL_EXPIRED`. |

### 1.5 Exigences sur le signal

| Réglage | Défaut | Bornes API | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|---|
| `require_stop_loss` | `true` | — | Interdit d'ouvrir une position sans stop loss. Le stop loss est de toute façon indispensable au calcul du volume. | « BUY GOLD 2400, TP 2420 » sans SL → refus `MISSING_STOP_LOSS`. |
| `require_take_profit` | `false` | — | Exige au moins un objectif. Désactivé par défaut : beaucoup de canaux gèrent la sortie par messages de suivi. | Activé, « SELL EURUSD 1.0850 SL 1.0880 » sans TP → refus `MISSING_TAKE_PROFIT`. |
| `min_risk_reward` | `null` (désactivé) | `0` à `100` | Ratio minimal entre le gain visé au **premier** TP et le risque. Ignoré si le signal n'a aucun TP. | Réglé à `1.5` : entrée 2400, SL 2390 (risque 10), TP1 2412 (gain 12) → RR = 1,2 → refus `RR_TOO_LOW`. |
| `min_confidence` | `0.85` | `0` à `1` | Seuil du score du parser en dessous duquel l'exécution automatique est refusée. | Confiance 0,80 < 0,85 → refus `LOW_CONFIDENCE`. |

> **Point important à connaître.** Le parser déterministe peut atteindre `1.00` ;
> le parser IA est **plafonné à `0.80`** (`services/openrouter/signal_ai.py`).
> Avec la valeur par défaut `min_confidence = 0.85`, un signal lu par l'IA est
> donc systématiquement refusé en mode automatique avec `LOW_CONFIDENCE`. Ce
> comportement est cohérent avec le principe « l'IA n'a jamais le dernier mot »,
> mais il faut le savoir : pour laisser passer des signaux lus par l'IA, il faut
> soit abaisser `min_confidence` explicitement, soit passer le canal en mode
> `MANUAL` et valider à la main (la validation manuelle contourne ce seul
> contrôle de confiance, pas les autres).

### 1.6 Protections comportementales

| Réglage | Défaut | Bornes API | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|---|
| `max_consecutive_losses` | `3` | `0` à `50` | Interrompt une série perdante. `0` désactive le contrôle. | Après 3 trades perdants d'affilée, tout nouveau signal est refusé (`CONSECUTIVE_LOSSES`). Le compteur repart à zéro dès un trade gagnant. |
| `pause_after_max_losses` | `true` | — | Met en plus l'automatisation en pause, pas seulement le signal courant. | À la 3ᵉ perte, `trading_state.paused` passe à vrai avec le motif « 3 pertes consecutives ». |
| `pause_duration_minutes` | `240` | `1` à `10080` | Durée de cette pause automatique. | 240 minutes = 4 heures. Passé ce délai, la pause expire d'elle-même. |

### 1.7 Fenêtres autorisées

| Réglage | Défaut | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|
| `trading_hours_start` | `"00:00"` | Début de la plage horaire autorisée, **en UTC**. Format `HH:MM` validé par l'API. | `"07:00"` → aucun ordre avant 07:00 UTC. |
| `trading_hours_end` | `"23:59"` | Fin de la plage. Une plage inversée (`22:00` → `04:00`) est acceptée et interprétée comme chevauchant minuit. | Réglé `22:00`–`04:00`, un signal à 02:30 UTC passe ; un signal à 12:00 UTC est refusé (`OUTSIDE_TRADING_HOURS`). |
| `trading_days` | `[0, 1, 2, 3, 4]` | Jours autorisés, `0` = lundi … `6` = dimanche. Par défaut, du lundi au vendredi. | Un signal reçu le samedi est refusé (`OUTSIDE_TRADING_DAYS`). |
| `allowed_symbols` | `[]` (aucune restriction) | Liste blanche d'instruments **canoniques**. Vide = tous les instruments reconnus sont autorisés. | `["XAUUSD", "EURUSD"]` → un signal `US30` est refusé (`SYMBOL_NOT_ALLOWED`). |

### 1.8 Take profits multiples

| Réglage | Défaut | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|
| `multi_tp_strategy` | `PARTIAL_CLOSE` | Détermine comment un signal à plusieurs objectifs est traduit en positions. | Voir la section 5. |
| `split_ratios` | `[40.0, 30.0, 30.0]` | Répartition en pourcentage utilisée par `SPLIT_POSITIONS`, et pourcentages de fermeture partielle par TP en `PARTIAL_CLOSE`. | 0,10 lot réparti en 0,04 / 0,03 / 0,03 lot. |

### 1.9 Break even

| Réglage | Défaut | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|
| `break_even_enabled` | `true` | Autorise le déplacement du stop loss au prix d'entrée. | Désactivé, aucun break even automatique n'est appliqué, même si le canal l'annonce. |
| `break_even_trigger` | `TP1_HIT` | Déclencheur : `TP1_HIT`, `R_MULTIPLE`, `POINTS`, `SIGNAL_ONLY`. | `TP1_HIT` : le break even n'est appliqué que lorsque le canal annonce que TP1 est atteint. |
| `break_even_r_multiple` | `1.0` | Multiple de R exigé pour le déclencheur `R_MULTIPLE`. Également utilisé par le trailing `R_BASED`. | Risque 10 USD par unité de prix ; à +1 R de progression, le stop est remonté. |
| `break_even_points` | `100` | Progression en points exigée pour le déclencheur `POINTS`. | `XAUUSDm`, `point = 0.01` : 100 points = 1,00 USD de progression. |
| `break_even_offset_points` | `5` | Petit tampon au-delà de l'entrée, pour couvrir spread et commission. | Entrée à 2400.00, achat, `point = 0.01` → stop placé à 2400.05. |

`SIGNAL_ONLY` et `TP1_HIT` ne déclenchent **jamais** de break even automatique
depuis la boucle de suivi : ils attendent un message du canal. Seuls `POINTS` et
`R_MULTIPLE` sont évalués à chaque cycle.

### 1.10 Trailing stop

| Réglage | Défaut | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|
| `trailing_mode` | `DISABLED` | `DISABLED`, `FIXED_DISTANCE`, `AFTER_TP1`, `R_BASED`. | `DISABLED` : le stop ne bouge que sur break even ou message du canal. |
| `trailing_distance_points` | `200` | Distance conservée entre le cours et le stop suiveur. | `XAUUSDm`, `point = 0.01` : 200 points = 2,00 USD sous le cours pour un achat. |
| `trailing_step_points` | `50` | Pas minimal de déplacement : évite d'envoyer une modification à chaque tick. | Le stop ne bouge que si le nouveau candidat s'écarte d'au moins 50 points de l'actuel. |

### 1.11 Paper trading

| Réglage | Défaut | Ce qu'il protège | Exemple chiffré |
|---|---|---|---|
| `paper_balance` | `10000.0` | Solde de départ du carnet simulé. Appliqué au moteur PAPER au démarrage du Bridge. | 10 000 USD, `risk_percent = 0.5` → 50 USD risqués par trade simulé. |
| `paper_currency` | `"USD"` | Devise affichée pour le compte papier. Exposée en lecture par l'API, **non modifiable** par `PATCH /api/v1/risk/settings`. | — |
| `paper_leverage` | `500` | Levier du carnet simulé. Présent en base, **ni exposé ni modifiable** par l'API actuelle. | — |

---

## 2. Surcharges par canal

La table `channel_settings` permet de surcharger certains réglages pour un canal
précis. **Un champ `NULL` signifie : utiliser le réglage global.** La fusion est
faite par `resolve_settings` dans `manager.py`.

| Réglage global | Surchargeable par canal ? | Champ correspondant |
|---|---|---|
| `risk_percent` | oui | `channel_settings.risk_percent` |
| `max_lot` | oui | `channel_settings.max_lot` |
| `max_positions` | oui | `channel_settings.max_positions` |
| `max_spread_points` | oui | `channel_settings.max_spread_points` |
| `max_signal_age_seconds` | oui | `channel_settings.max_signal_age_seconds` |
| `require_stop_loss` | oui | `channel_settings.require_stop_loss` |
| `require_take_profit` | oui | `channel_settings.require_take_profit` |
| `min_confidence` | oui | `channel_settings.min_confidence` |
| `multi_tp_strategy` | oui | `channel_settings.multi_tp_strategy` |
| `allowed_symbols` | oui, si la liste du canal est non vide | `channel_settings.allowed_symbols` |
| `max_positions_per_symbol` | non | — |
| `max_total_exposure_lots` | non | — |
| `min_risk_reward` | non | — |
| `split_ratios` | non | — |
| `max_slippage_points` | non | — |

Deux réglages n'existent qu'au niveau du canal : `copy_buy` et `copy_sell`
(défaut `true` tous les deux), qui permettent de ne copier que les achats ou que
les ventes d'un canal donné, et `enabled` / `mode`.

Route de modification : `PATCH /api/v1/channels/{channel_id}/settings`.

---

## 3. L'ordre exact des contrôles

`RiskManager.evaluate` applique les blocs suivants, dans cet ordre précis. **Le
premier échec arrête l'évaluation** et renvoie une `RiskDecision` refusée. Chaque
contrôle franchi ou échoué est ajouté à la liste `checks`, persistée dans la
table `risk_events` et visible via `GET /api/v1/risk/events`.

### Bloc 1 — Interrupteurs généraux

| Ordre | Contrôle | Nom du contrôle | Motif de refus |
|---|---|---|---|
| 1.1 | `auto_trading_enabled` est vrai, ou validation manuelle | `auto_trading` | `AUTO_TRADING_OFF` |
| 1.2 | l'automatisation n'est pas en pause (`paused`, `paused_until`) | `pause` | `TRADING_PAUSED` |

### Bloc 2 — Canal

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 2.1 | `channel_settings.enabled` est vrai | `channel_enabled` | `CHANNEL_DISABLED` |
| 2.2 | le canal n'est pas en mode `OBSERVE` (sauf validation manuelle) | `channel_mode` | `CHANNEL_OBSERVE_MODE` |

### Bloc 3 — Compte et mode d'exécution

Ce bloc ne s'applique **qu'en `MT5_DEMO` et `MT5_LIVE`**. Le mode `PAPER` le
traverse sans contrôle.

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 3.1 | MetaTrader 5 est connecté | `mt5` | `MT5_DISCONNECTED` |
| 3.2 | les informations de compte sont disponibles | `account` | `MT5_DISCONNECTED` |
| 3.3 | en `MT5_LIVE` : `live_unlocked` est vrai | `live_unlock` | `LIVE_NOT_UNLOCKED` |
| 3.4 | en `MT5_DEMO` : le compte n'est pas un compte **réel** | `account_kind` | `ACCOUNT_MISMATCH` |
| 3.5 | en `MT5_DEMO` : le type de compte n'est pas `UNKNOWN` | `account_kind` | `ACCOUNT_MISMATCH` |
| 3.6 | le trading est autorisé sur ce compte et dans le terminal | `trade_allowed` | `MT5_DISCONNECTED` |

Le type de compte est déduit de `account_info().trade_mode` : `0` et `1` (démo,
concours) donnent `DEMO`, `2` donne `REAL`, toute autre valeur ou l'absence
d'information donne `UNKNOWN`. **Un compte indéterminable n'est jamais présenté
comme une démo** : l'exécution est refusée.

### Bloc 4 — Contenu du signal

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 4.1 | le message contient une intention de trade (instrument + direction) | `signal` | `NO_ACTION` |
| 4.2 | `confidence >= min_confidence` (sauf validation manuelle) | `confidence` | `LOW_CONFIDENCE` |
| 4.3 | la direction est copiée pour ce canal (`copy_buy` / `copy_sell`) | `direction` | `DIRECTION_NOT_ALLOWED` |
| 4.4 | l'instrument figure dans `allowed_symbols` si la liste est non vide | `symbol_allowed` | `SYMBOL_NOT_ALLOWED` |
| 4.5 | stop loss présent si `require_stop_loss` | `stop_loss` | `MISSING_STOP_LOSS` |
| 4.6 | take profit présent si `require_take_profit` | `take_profit` | `MISSING_TAKE_PROFIT` |

### Bloc 5 — Fraîcheur du signal

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 5.1 | âge du message ≤ `max_signal_age_seconds` | `signal_age` | `SIGNAL_EXPIRED` |

L'âge est calculé à partir de `message_date`, la date du message Telegram, pas de
sa date de réception. Si `message_date` est inconnue, le contrôle est marqué
`inconnu` et n'échoue pas.

### Bloc 6 — Fenêtres horaires

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 6.1 | le jour de la semaine figure dans `trading_days` | `trading_days` | `OUTSIDE_TRADING_DAYS` |
| 6.2 | l'heure courante est dans `trading_hours_start` – `trading_hours_end` | `trading_hours` | `OUTSIDE_TRADING_HOURS` |

Tout est évalué en **UTC**.

### Bloc 7 — Instrument chez le broker

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 7.1 | le symbole existe chez le broker | `symbol_available` | `SYMBOL_NOT_FOUND` |
| 7.2 | le symbole est ouvert au trading (`trade_mode == 4`) | `symbol_tradable` | `MARKET_CLOSED` |
| 7.3 | une cotation est disponible (`bid > 0` et `ask > 0`) | `quote` | `MARKET_CLOSED` |
| 7.4 | spread ≤ `max_spread_points` | `spread` | `SPREAD_TOO_HIGH` |

### Bloc 8 — Prix et cohérence

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 8.1 | un prix d'entrée de référence est déterminable | `entry_price` | `INVALID_ENTRY` |
| 8.2 | le stop loss est du bon côté par rapport à ce prix | `stop_side` | `INVALID_STOP_LOSS` |
| 8.3 | le stop loss respecte `trade_stops_level` imposé par le broker | `stop_distance` | `INVALID_STOP_LOSS` |
| 8.4 | ratio rendement/risque ≥ `min_risk_reward`, si configuré et calculable | `risk_reward` | `RR_TOO_LOW` |

Le prix de référence est choisi ainsi (`_resolve_entry_price`) :

1. si le message donne un prix précis, c'est ce prix ;
2. si le message donne une **zone** `[min, max]` : le cours courant s'il est dans
   la zone, sinon la borne la plus favorable (`entry_min` pour un achat,
   `entry_max` pour une vente) ;
3. sinon le cours courant (`ask` pour un achat, `bid` pour une vente).

Le ratio rendement/risque est calculé sur le **premier** take profit.

### Bloc 9 — Limites journalières, drawdown et pertes consécutives

Ce bloc est volontairement évalué **avant** les limites d'exposition : quand une
limite de perte est atteinte, c'est ce motif que l'utilisateur doit voir, même
si une position est déjà ouverte sur le même instrument.

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 9.1 | perte réalisée du jour < `max_daily_loss_percent` | `daily_limits` | `DAILY_LOSS_LIMIT` |
| 9.2 | risque cumulé du jour < `max_daily_risk_percent` | `daily_limits` | `DAILY_RISK_LIMIT` |
| 9.3 | objectif de gain journalier non atteint, si configuré | `daily_limits` | `DAILY_PROFIT_TARGET` |
| 9.4 | drawdown depuis le pic d'equity < `max_drawdown_percent` | `daily_limits` | `MAX_DRAWDOWN` |
| 9.5 | pertes consécutives < `max_consecutive_losses` | `consecutive_losses` | `CONSECUTIVE_LOSSES` |

### Bloc 10 — Exposition

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 10.1 | positions ouvertes < `max_positions` | `max_positions` | `MAX_POSITIONS` |
| 10.2 | positions sur cet instrument < `max_positions_per_symbol` | `max_positions_symbol` | `MAX_POSITIONS_SYMBOL` |
| 10.3 | somme des volumes ouverts < `max_total_exposure_lots` | `exposure` | `MAX_EXPOSURE` |

### Bloc 11 — Volume

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 11.1 | un stop loss est disponible pour dimensionner la position | `lot` | `MISSING_STOP_LOSS` |
| 11.2 | un service de marché est disponible | `lot` | `MT5_DISCONNECTED` |
| 11.3 | le calcul du volume aboutit à un volume valide | `lot` | `INVALID_VOLUME` |
| 11.4 | le risque effectif ne dépasse pas `risk_percent × 1.5` | `effective_risk` | `RISK_TOO_HIGH` |

Le contrôle 11.4 est un garde-fou contre un arrondi défavorable ou une donnée de
symbole incohérente : si la perte au stop du volume finalement retenu s'éloigne
trop de la cible, le signal est refusé plutôt qu'exécuté.

### Bloc 12 — Marge

| Ordre | Contrôle | Nom | Motif |
|---|---|---|---|
| 12.1 | marge requise ≤ marge libre du compte | `margin` | `INSUFFICIENT_MARGIN` |

Si le terminal ne sait pas calculer la marge pour ce symbole, le contrôle est
marqué `non evaluee` et n'échoue pas.

### Après le RiskManager

Le `RiskManager` approuvé, `OrderExecutor` fait encore deux contrôles auprès du
broker, dont l'échec produit un statut `FAILED` :

| Étape | Motif en cas d'échec |
|---|---|
| `order_check` avant chaque envoi | `ORDER_CHECK_FAILED` |
| `order_send` | `ORDER_SEND_FAILED` |

Enfin, `TradingEngine.handle_message` refuse en amont tout message déjà traité,
avec le motif `DUPLICATE_SIGNAL`.

---

## 4. Liste complète des motifs de refus

Valeurs de `RejectionReason` (`bridge/app/models/enums.py`), avec l'endroit du
code qui les émet.

| Motif | Émis par | Signification |
|---|---|---|
| `AUTO_TRADING_OFF` | RiskManager 1.1 | Le trading automatique est désactivé |
| `TRADING_PAUSED` | RiskManager 1.2 | L'automatisation est en pause |
| `CHANNEL_DISABLED` | RiskManager 2.1 | Le canal est désactivé |
| `CHANNEL_OBSERVE_MODE` | RiskManager 2.2 | Le canal est en mode observation |
| `MT5_DISCONNECTED` | RiskManager 3.1, 3.2, 3.6, 11.2 | Terminal, compte ou service de marché indisponible |
| `LIVE_NOT_UNLOCKED` | RiskManager 3.3 | Le mode réel n'a pas été déverrouillé |
| `ACCOUNT_MISMATCH` | RiskManager 3.4, 3.5 | Compte réel en mode démo, ou type de compte indéterminable |
| `NO_ACTION` | RiskManager 4.1 | Message sans intention de trade exploitable |
| `LOW_CONFIDENCE` | RiskManager 4.2 | Score du parser sous `min_confidence` |
| `DIRECTION_NOT_ALLOWED` | RiskManager 4.3 | Achats ou ventes non copiés pour ce canal |
| `SYMBOL_NOT_ALLOWED` | RiskManager 4.4 | Instrument hors de la liste blanche |
| `MISSING_STOP_LOSS` | RiskManager 4.5, 11.1 | Stop loss requis et absent |
| `MISSING_TAKE_PROFIT` | RiskManager 4.6 | Take profit requis et absent |
| `SIGNAL_EXPIRED` | RiskManager 5.1, validation manuelle tardive | Signal trop ancien |
| `OUTSIDE_TRADING_DAYS` | RiskManager 6.1 | Jour non autorisé |
| `OUTSIDE_TRADING_HOURS` | RiskManager 6.2 | Hors plage horaire |
| `SYMBOL_NOT_FOUND` | RiskManager 7.1, moteur | Instrument introuvable chez le broker |
| `MARKET_CLOSED` | RiskManager 7.2, 7.3 | Instrument fermé ou sans cotation |
| `SPREAD_TOO_HIGH` | RiskManager 7.4 | Spread au-delà du maximum |
| `INVALID_ENTRY` | RiskManager 8.1 | Prix d'entrée indéterminable |
| `INVALID_STOP_LOSS` | RiskManager 8.2, 8.3 | Stop du mauvais côté ou trop proche |
| `RR_TOO_LOW` | RiskManager 8.4 | Ratio rendement/risque insuffisant |
| `DAILY_LOSS_LIMIT` | RiskManager 9.1 | Perte journalière atteinte |
| `DAILY_RISK_LIMIT` | RiskManager 9.2 | Risque journalier cumulé atteint |
| `DAILY_PROFIT_TARGET` | RiskManager 9.3 | Objectif de gain journalier atteint |
| `MAX_DRAWDOWN` | RiskManager 9.4 | Drawdown maximal atteint |
| `CONSECUTIVE_LOSSES` | RiskManager 9.5 | Seuil de pertes consécutives atteint |
| `MAX_POSITIONS` | RiskManager 10.1 | Trop de positions ouvertes |
| `MAX_POSITIONS_SYMBOL` | RiskManager 10.2 | Trop de positions sur cet instrument |
| `MAX_EXPOSURE` | RiskManager 10.3 | Exposition totale au plafond |
| `INVALID_VOLUME` | RiskManager 11.3, exécuteur | Volume incalculable, trop faible ou invalide |
| `RISK_TOO_HIGH` | RiskManager 11.4 | Risque effectif trop éloigné de la cible |
| `INSUFFICIENT_MARGIN` | RiskManager 12.1 | Marge libre insuffisante |
| `ORDER_CHECK_FAILED` | `OrderExecutor` | Le broker a refusé le contrôle préalable |
| `ORDER_SEND_FAILED` | `OrderExecutor` | Le broker a refusé l'envoi |
| `DUPLICATE_SIGNAL` | `TradingEngine` | Message déjà traité |
| `MANUAL_REJECTION` | `TradingEngine.reject_manually` | Refusé explicitement par l'utilisateur |
| `BRIDGE_OFFLINE` | — | Déclaré dans l'énumération, **jamais émis** par le code actuel |
| `CHANNEL_NOT_ALLOWED` | — | Déclaré, **jamais émis** |
| `INVALID_TAKE_PROFIT` | — | Déclaré, **jamais émis** (l'incohérence de TP est traitée par le validateur, avant le RiskManager) |
| `LOT_LIMIT` | — | Déclaré, **jamais émis** (le plafond de lot est appliqué en écrêtant le volume, pas en refusant) |

---

## 5. Le calcul du lot

Fichier : `bridge/app/services/risk/calculator.py`.

**Aucune valeur de pip n'est codée en dur.** Tout provient des métadonnées
renvoyées par MetaTrader 5 pour le symbole concerné.

### 5.1 Perte pour un lot

`loss_for_one_lot` essaie trois méthodes, dans cet ordre, et la méthode retenue
est tracée dans le champ `method` :

| Ordre | Méthode | Détail |
|---|---|---|
| 1 | `order_calc_profit` | Fonction native du terminal. C'est la plus fiable : elle gère les conversions de devises et les particularités du symbole. Retenue si elle renvoie une valeur négative. |
| 2 | `tick_value` | `perte = |entrée − stop| / trade_tick_size × trade_tick_value`. Utilisée si le terminal refuse `order_calc_profit`, ou en mode PAPER hors connexion. |
| 3 | `contract_size` | Dernier recours : `|entrée − stop| × trade_contract_size`. Valable pour les instruments cotés dans la devise du compte. |
| — | `unavailable` | Aucune méthode disponible : le signal est refusé (`INVALID_VOLUME`). |

### 5.2 Enchaînement complet

```
risk_amount   = solde × risk_percent / 100
loss_per_lot  = loss_for_one_lot(...)
raw_volume    = risk_amount / loss_per_lot
volume        = round_to_step(raw_volume, symbol.volume_step)     arrondi vers le BAS
plafond       = min(symbol.volume_max, max_lot)
si volume > plafond  →  volume = round_to_step(plafond, volume_step), cappedByLimit = true
si volume < symbol.volume_min  →  refus INVALID_VOLUME
loss_at_stop  = volume × loss_per_lot
```

L'arrondi est toujours **vers le bas** : le volume réellement envoyé ne dépasse
jamais le risque cible.

### 5.3 Exemple chiffré complet

Contexte : compte 10 000 USD, `risk_percent = 0.5`, `max_lot = 0.10`,
signal `BUY XAUUSD entrée 2400.00 SL 2390.00 TP 2420.00`, symbole broker
`XAUUSDm` avec `volume_min = 0.01`, `volume_step = 0.01`, `volume_max = 200`,
`trade_contract_size = 100`, `digits = 2`, `point = 0.01`.

| Étape | Calcul | Résultat |
|---|---|---|
| Capital risqué | `10 000 × 0,5 / 100` | `50,00 USD` |
| Distance au stop | `2400,00 − 2390,00` | `10,00 USD` soit `1000` points |
| Perte pour 1 lot | `order_calc_profit(BUY, 1.0, 2400, 2390)` → `−1000,00` | `1000,00 USD` |
| Volume brut | `50 / 1000` | `0,05 lot` |
| Arrondi au pas | `round_to_step(0,05 ; 0,01)` | `0,05 lot` |
| Plafond | `min(200 ; 0,10)` | `0,10 lot` — non atteint |
| Minimum broker | `0,05 ≥ 0,01` | accepté |
| Perte au stop | `0,05 × 1000` | `50,00 USD` = `0,50 %` du solde |
| Ratio rendement/risque | `(2420 − 2400) / (2400 − 2390)` | `2,00` |

Deuxième cas, stop très serré : mêmes réglages mais `SL 2399.00`, soit une
distance de `1,00 USD` et une perte de `100 USD` par lot.
`raw_volume = 50 / 100 = 0,50 lot`, écrêté à `0,10 lot` par `max_lot`, avec
`cappedByLimit = true`. La perte réelle au stop devient `0,10 × 100 = 10 USD`,
soit `0,10 %` — **moins** que la cible, ce qui est sans danger.

Troisième cas, stop très large : `SL 2100.00`, distance `300 USD`, perte
`30 000 USD` par lot. `raw_volume = 50 / 30 000 = 0,00167 lot`, en dessous du
`volume_min` de `0,01`. Le signal est **refusé** avec `INVALID_VOLUME` et le
détail « Volume requis 0.0017 inférieur au minimum broker 0.01 : risque trop
faible pour ce stop ». Le système ne prend jamais 0,01 lot « pour faire quand
même » : cela représenterait 300 USD de risque, soit 3 % au lieu de 0,5 %.

Le résultat complet du calcul est conservé dans `risk_events.computed_lot`,
`risk_events.risk_amount` et dans le champ `checks`, avec `requestedVolume`,
`cappedByLimit`, `volumeStep`, `effectiveRiskPercent`, `lossPerLot`,
`stopDistancePoints` et `method`.

---

## 6. Stratégies de take profits multiples

Un canal publie souvent plusieurs objectifs. `plan_take_profits`
(`services/trading/executor.py`) traduit cela en positions concrètes selon
`multi_tp_strategy`.

Exemple commun : volume calculé `0,10 lot`, objectifs `TP1 = 2410`,
`TP2 = 2420`, `TP3 = 2430`, `split_ratios = [40, 30, 30]`.

| Stratégie | Positions ouvertes | Comportement ensuite |
|---|---|---|
| `FIRST_TP_ONLY` | une position `0,10 lot`, TP à `2410` | Sortie complète au premier objectif. Le plus simple et le plus prudent. |
| `LAST_TP_ONLY` | une position `0,10 lot`, TP à `2430` | Aucune prise partielle : tout ou rien sur le dernier objectif. |
| `PARTIAL_CLOSE` **(défaut)** | une position `0,10 lot`, TP à `2430` | Les objectifs intermédiaires déclenchent des **fermetures partielles** quand le canal annonce `TP1 HIT` / `TP2 HIT` : 40 % à TP1, 30 % à TP2, le reste court jusqu'à TP3. |
| `SPLIT_POSITIONS` | trois positions : `0,04` @ `2410`, `0,03` @ `2420`, `0,03` @ `2430` | Chaque position est gérée indépendamment par le broker. Trois ordres, donc trois `order_check` et trois `order_send`. |

Sécurité de `SPLIT_POSITIONS` : `split_volume` refuse de fractionner si l'une des
parts tombe sous `volume_min`. Dans ce cas, une **position unique** est ouverte
sur le premier objectif, et l'événement est journalisé
(« Fractionnement impossible (volume trop faible) : position unique conservée »).

En `PARTIAL_CLOSE`, si le volume partiel calculé tombe sous `volume_min`, la
position est **entièrement** fermée plutôt que de laisser un reliquat inexécutable.

---

## 7. Break even

Deux chemins mènent au break even.

### 7.1 Sur message du canal

Le `follow_up_parser` reconnaît `BREAK EVEN`, `BREAKEVEN`, `MOVE SL TO BE`,
`SL TO BE`, `SL BE`, `BE NOW`, `SECURE ENTRY`, `RISK FREE` et produit un
`FollowUp` avec l'action `MOVE_SL_BE`. Un message `TP1 HIT` qui contient aussi
l'une de ces formules porte `also_break_even = true` et déclenche les deux
actions.

### 7.2 Automatiquement

À chaque cycle de suivi, `apply_automatic_rules` évalue le break even si
`break_even_enabled` est vrai et si le trade n'y est pas déjà passé :

| `break_even_trigger` | Évaluation automatique | Condition |
|---|---|---|
| `TP1_HIT` | non | attend le message du canal, ou `tp_index ≥ 1` traité par `_handle_tp_hit` |
| `SIGNAL_ONLY` | non | attend exclusivement le message du canal |
| `POINTS` | oui | progression ≥ `break_even_points × symbol.point` |
| `R_MULTIPLE` | oui | progression ≥ `break_even_r_multiple × |entrée − stop initial|` |

### 7.3 Garde-fous

Le prix cible est calculé par `break_even_price` : entrée décalée de
`break_even_offset_points × symbol.point` dans le sens du trade.

Trois refus possibles, tous journalisés :

1. **Le stop ne recule jamais.** `_stop_is_better` refuse tout nouveau stop moins
   protecteur que l'actuel.
2. **Distance broker.** Si le cours est trop proche du prix cible au regard de
   `trade_stops_level`, la modification est refusée localement plutôt que rejetée
   par le broker.
3. **Symbole introuvable** : l'action échoue proprement et l'échec est visible
   dans la timeline du signal.

Exemple : achat `XAUUSDm` ouvert à `2400,00`, `point = 0.01`,
`break_even_offset_points = 5`. Le break even place le stop à `2400,05`. Si le
broker exige `trade_stops_level = 30` points et que le cours n'est qu'à
`2400,20`, la distance est de 15 points : le break even est refusé et réessayé au
cycle suivant.

---

## 8. Trailing stop

Évalué à chaque cycle de suivi lorsque `trailing_mode` n'est pas `DISABLED`.

| Mode | Condition d'activation |
|---|---|
| `FIXED_DISTANCE` | actif dès l'ouverture |
| `AFTER_TP1` | actif seulement si `trade.tp_index ≥ 1` |
| `R_BASED` | actif seulement si la progression atteint `break_even_r_multiple` R |
| `DISABLED` | jamais |

Calcul du candidat, pour un achat :
`candidat = cours_bid − trailing_distance_points × symbol.point`
(pour une vente : `cours_ask + distance`), arrondi à `symbol.digits`.

Le déplacement n'est envoyé que si les quatre conditions sont réunies :

1. le candidat est **plus protecteur** que le stop actuel ;
2. il s'écarte du stop actuel d'au moins `trailing_step_points × point` ;
3. il respecte `trade_stops_level` ;
4. le symbole et le tick sont disponibles.

Exemple : achat `XAUUSDm` ouvert à `2400,00`, `trailing_distance_points = 200`,
`trailing_step_points = 50`, `point = 0.01`. Le cours monte à `2405,00` : le
candidat est `2403,00`, plus protecteur, le stop est déplacé. Le cours monte à
`2405,30` : le candidat serait `2403,30`, soit 30 points au-dessus du stop
actuel — moins que le pas de 50 points, aucune modification n'est envoyée.

---

## 9. Ce que le système ne fera jamais

Ces garanties sont des propriétés du code, pas des intentions.

- **Il n'inventera jamais un stop loss ni un take profit.** `ParsedSignal`
  laisse à `None` toute valeur absente du message. Sans stop loss, le volume ne
  peut pas être calculé : le signal est refusé (`MISSING_STOP_LOSS`), il n'est
  pas complété par une valeur arbitraire.
- **Il n'inventera jamais une direction ni un instrument.** Sans `BUY`/`SELL`
  explicite et sans instrument reconnu, `is_signal` reste faux et le statut est
  `NO_ACTION`. « Gold looking good today » ne produira jamais un `BUY XAUUSD`.
- **Il n'augmentera jamais le lot après une perte.** Le volume ne dépend que de
  trois choses : le solde courant, `risk_percent` et la distance au stop. Aucun
  chemin de code ne consulte le résultat du trade précédent pour dimensionner le
  suivant. Une perte **réduit** mécaniquement le volume suivant, puisque le solde
  a baissé.
- **Il n'implémente aucune martingale**, ni par défaut ni en option. Aucun
  réglage, aucune colonne, aucune fonction ne permet de multiplier le risque
  après une perte. À l'inverse, `max_consecutive_losses` et
  `pause_after_max_losses` **arrêtent** l'automatisation après une série
  perdante.
- **Il ne laissera jamais l'IA contourner le risque.** L'IA sert uniquement à
  lire un texte ambigu. Sa sortie est retypée champ par champ
  (`payload_to_signal`), toute valeur douteuse devient `None`, elle est
  revalidée par le validateur local, elle ne peut pas contredire une lecture
  locale certaine, sa confiance est plafonnée à `0.80`, et elle passe ensuite par
  exactement les mêmes contrôles de risque que n'importe quel autre signal. Le
  `RiskManager` n'a aucune dépendance vers le module OpenRouter.
- **Il n'exécutera jamais un vieux signal après une reconnexion.** Trois
  mécanismes s'additionnent : la contrainte d'unicité
  `(channel_id, message_id)` sur la table `messages`, la clé d'idempotence sur la
  table `signals` (`tg:<canal>:<message>`, ou une empreinte du contenu), et le
  contrôle de fraîcheur `max_signal_age_seconds` calculé sur la date du message
  Telegram.
- **Il ne basculera jamais tout seul en réel.** Le passage en `MT5_LIVE` exige un
  déverrouillage explicite avec la phrase exacte `JE COMPRENDS LES RISQUES`, puis
  un changement de mode séparé exigeant à nouveau cette phrase, un terminal
  connecté et un type de compte déterminable. Au démarrage, un mode réel non
  déverrouillé retombe en `MT5_DEMO`.
- **Il ne présentera jamais un compte indéterminable comme une démo.**
  `AccountKind.UNKNOWN` bloque l'exécution au lieu de supposer.
- **Il n'enverra jamais un ordre en aveugle.** Chaque `order_send` est précédé
  d'un `order_check` auprès du broker, et les deux sont tracés dans
  `signal_events`.

Aucune de ces garanties ne rend le trading sans risque. Elles réduisent
seulement la probabilité d'une erreur du système lui-même.
