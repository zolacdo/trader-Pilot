# Checklist avant le mode réel

Ce document décrit la vérification préalable au passage en `MT5_LIVE`, la
procédure de déverrouillage en deux temps, et la façon de revenir en arrière.

Avant de le lire, vous devriez avoir parcouru
[DEMO_TESTING.md](DEMO_TESTING.md) et coché sa grille de sortie.

---

## 1. La checklist automatique

```
GET /api/v1/go-live-checklist
```

Le Bridge évalue **9 critères** et renvoie, pour chacun, un `done` calculé à
partir de vos données réelles — pas une case à cocher manuelle.

| # | `key` | Libellé | Condition évaluée |
|---|---|---|---|
| 1 | `mt5_demo_connected` | MT5 connecté sur un compte demo | l'état MT5 est `CONNECTED` **et** le type de compte est `DEMO` |
| 2 | `telegram_connected` | Telegram connecté | le compte Telegram est `authorized` |
| 3 | `signals_received` | Au moins 20 signaux reçus et analysés | au moins 20 signaux enregistrés sur les **30 derniers jours** |
| 4 | `signals_executed` | Au moins 10 signaux exécutés en paper ou demo | au moins 10 signaux dans les statuts `OPEN`, `CLOSED` ou `SENT` |
| 5 | `no_duplicates` | Aucun doublon détecté | **toujours vrai** ; détail : « Clé d'idempotence active sur chaque message » |
| 6 | `trades_closed` | Des trades ont été fermés correctement | au moins 5 trades fermés en `MT5_DEMO` ou `PAPER` sur les 30 derniers jours |
| 7 | `break_even_tested` | Break even déclenché au moins une fois | au moins un trade fermé avec `break_even_applied = true` |
| 8 | `risk_configured` | Limites de risque configurées | `risk_percent > 0` **et** `max_daily_loss_percent > 0` |
| 9 | `emergency_tested` | Arrêt d'urgence testé | au moins une entrée de journal de catégorie `emergency` |

La réponse contient aussi :

| Champ | Contenu |
|---|---|
| `completed` | nombre de critères satisfaits |
| `total` | `9` |
| `ready` | vrai seulement si `completed == total` |
| `disclaimer` | « Cette liste aide à vérifier la configuration. Elle ne rend en aucun cas le trading sans risque. » |

Plusieurs critères renvoient un `detail` chiffré, par exemple
« 34 signaux sur 30 jours », « 12 executions », « 7 trades fermes »,
« 0.5% par trade, 3.0% par jour ».

### 1.1 Ce que la checklist ne vérifie pas

Il faut le savoir pour ne pas lui accorder plus de crédit qu'elle n'en mérite.

- Le critère 5 (`no_duplicates`) est **toujours satisfait**. Il documente
  l'existence du mécanisme d'idempotence ; il ne mesure pas l'absence effective
  de doublons dans votre historique. Vérifiez-le vous-même avec le scénario 4 de
  [DEMO_TESTING.md](DEMO_TESTING.md).
- Le critère 4 (`signals_executed`) compte les signaux dans les statuts
  `OPEN`, `CLOSED` et `SENT` parmi les 200 plus récents, **sans filtre de date** :
  contrairement au libellé, la fenêtre de 30 jours ne lui est pas appliquée.
- `ready = true` signifie « les 9 conditions techniques sont réunies ». Cela ne
  dit **rien** de la qualité de vos canaux, de la pertinence de vos réglages ni
  de votre capacité à supporter une perte.
- Aucun critère ne mesure une performance. Rien dans le système ne vous dira
  jamais que vous êtes « prêt » au sens financier du terme.

> L'écran **Go Live** de l'application (route `/more/go-live`) affiche cette même
> checklist. La route peut aussi être appelée directement.

---

## 2. Vérifications manuelles complémentaires

À faire en plus de la checklist automatique, dans cet ordre.

### Configuration

- [ ] `GET /api/v1/risk/settings` : je comprends **chacune** des valeurs
      affichées et je les ai choisies délibérément, en particulier
      `risk_percent`, `max_lot`, `max_positions`, `max_daily_loss_percent`,
      `max_drawdown_percent` et `max_consecutive_losses`.
- [ ] Le montant réellement risqué par trade, en devise, m'est acceptable
      — pas seulement le pourcentage. Recalculez-le : `solde × risk_percent / 100`.
- [ ] `max_signal_age_seconds` correspond à ma tolérance réelle après une
      coupure.
- [ ] `trading_hours_start`, `trading_hours_end` et `trading_days` sont réglés,
      **en UTC**, et je sais quel décalage cela représente chez moi.
- [ ] `allowed_symbols` restreint aux instruments que je veux réellement traiter,
      ou je l'ai laissé vide en connaissance de cause.

### Canaux

- [ ] Chaque canal en mode `AUTO` a été observé pendant une durée significative
      en `OBSERVE` puis en `PAPER`.
- [ ] J'ai lu le rapport d'analyse de chacun de ces canaux
      ([CHANNEL_ANALYSIS.md](CHANNEL_ANALYSIS.md)) et je connais leur
      `parseableRate` et leur `withStopLossRate`.
- [ ] Aucun canal que je ne reconnais pas n'est en `AUTO`
      (`GET /api/v1/channels?monitoredOnly=true`).
- [ ] Le nombre de signaux par jour de mes canaux est compatible avec
      `max_positions` et `max_daily_risk_percent`.

### Symboles

- [ ] `GET /api/v1/symbols/mappings` : chaque correspondance pointe sur le
      symbole broker que j'attends réellement, en particulier celles marquées
      `autoDetected = true`.
- [ ] J'ai vérifié dans MetaTrader 5 (`Ctrl + U`) que ces symboles existent bien
      sur mon compte.

### Exécution

- [ ] J'ai vu au moins un ordre partir réellement en `MT5_DEMO`, être accepté par
      le broker, et se fermer correctement.
- [ ] J'ai vu un break even se déclencher sur un trade réel de démonstration.
- [ ] J'ai vu au moins un refus du `RiskManager` et j'ai su lire pourquoi dans la
      timeline du signal.
- [ ] J'ai déclenché l'arrêt d'urgence au moins une fois et je sais où le
      retrouver rapidement.

### Poste et sécurité

- [ ] Le PC reste allumé, connecté, avec une session ouverte et MetaTrader 5
      lancé ; la veille est désactivée.
- [ ] Le démarrage automatique du Bridge est en place et a été testé après un
      redémarrage complet.
- [ ] La `MASTER_KEY` et `bridge\.env` sont sauvegardés hors du PC.
- [ ] `GET /api/v1/devices` ne montre aucun appareil inconnu ni oublié.
- [ ] La checklist de [SECURITY.md](SECURITY.md), section 9, est parcourue si le
      Bridge est exposé via ngrok.

### Vous

- [ ] Le capital du compte réel est une somme dont la perte **totale**
      n'affecterait pas ma situation.
- [ ] Je sais qu'une série perdante est un événement normal, pas un
      dysfonctionnement.
- [ ] Je sais comment tout arrêter en moins d'une minute, depuis mon téléphone.
- [ ] Je commence avec un `risk_percent` plus faible qu'en démonstration, pas
      plus élevé.

---

## 3. La procédure de déverrouillage en deux temps

Le passage en réel est délibérément découpé en **deux actions distinctes**. Il
n'existe aucun raccourci, aucune bascule automatique, aucun réglage unique qui
ferait les deux à la fois.

### Étape 1 — déverrouiller

```
POST /api/v1/trading/live-unlock
{ "confirmation": "JE COMPRENDS LES RISQUES", "acknowledgedRisks": true }
```

Depuis PowerShell :

```powershell
$body = @{ confirmation = "JE COMPRENDS LES RISQUES"; acknowledgedRisks = $true } | ConvertTo-Json
Invoke-RestMethod "$Bridge/api/v1/trading/live-unlock" -Method Post -Headers $Headers -ContentType "application/json" -Body $body
```

Conditions, toutes obligatoires :

| Condition | Sinon |
|---|---|
| `acknowledgedRisks` vaut `true` | `400` — « Les risques doivent être explicitement acceptés » |
| `confirmation` vaut exactement `JE COMPRENDS LES RISQUES` | `400` — « Saisissez exactement la phrase : JE COMPRENDS LES RISQUES » |

La phrase est comparée après passage en majuscules et réduction des espaces
multiples : `je comprends les risques` fonctionne, `Je comprend les risques`
non. Elle ne comporte **aucun accent**.

Ce que fait cette route :

- `risk_settings.live_unlocked` passe à `true` ;
- `trading_state.live_unlocked_at` est horodaté ;
- une entrée de journal de niveau **`CRITICAL`** est écrite, catégorie
  `security` : « Mode reel deverrouille par l'utilisateur » ;
- une entrée d'audit `live_unlocked` est écrite, acteur `user`.

Ce que cette route **ne fait pas** — et la réponse le dit explicitement :

> Le mode réel est déverrouillé mais pas actif. Changez le mode d'exécution pour
> l'activer.

À ce stade, **aucun ordre réel ne peut encore partir.** Le mode d'exécution est
toujours `PAPER` ou `MT5_DEMO`.

### Étape 2 — activer le mode réel

```
POST /api/v1/trading/execution-mode
{ "mode": "MT5_LIVE", "confirmation": "JE COMPRENDS LES RISQUES" }
```

Quatre conditions sont vérifiées, dans cet ordre :

| # | Condition | Sinon |
|---|---|---|
| 1 | `live_unlocked` est `true` | `403` — « Le mode réel doit d'abord être déverrouillé depuis l'écran dédié » |
| 2 | `confirmation` vaut exactement `JE COMPRENDS LES RISQUES` | `400` |
| 3 | MetaTrader 5 est connecté et le compte est lisible | `409` — « MetaTrader 5 doit être connecté avant de passer en réel » |
| 4 | le type de compte n'est pas `UNKNOWN` | `409` — « Impossible de déterminer le type du compte MT5 : passage en réel refusé » |

La phrase de confirmation est donc exigée **deux fois**, à deux moments
différents.

Notez le point 4 : le Bridge refuse de passer en réel s'il ne sait pas dire si le
compte est une démo ou un compte réel. Il n'accepte pas de « faire confiance ».

Le changement est journalisé en `WARNING` et écrit dans le journal d'audit
(`execution_mode_changed`).

### Étape 3 — les interrupteurs restants

Même en `MT5_LIVE`, rien ne part tant que :

- `auto_trading_enabled` n'est pas `true`
  (`POST /api/v1/trading/auto?enabled=true`) ;
- l'automatisation n'est pas en pause (`GET /api/v1/trading/state`) ;
- au moins un canal n'est pas en mode `AUTO` ou `MANUAL`.

Il faut donc **quatre décisions séparées** pour qu'un ordre réel puisse partir :
déverrouiller, changer de mode, activer le trading automatique, et passer un
canal hors du mode observation.

### 3.1 Le garde-fou du démarrage

À chaque démarrage du Bridge, `main.py` vérifie l'état enregistré. Si
`execution_mode` vaut `MT5_LIVE` alors que `live_unlocked` est `false`, le mode
retombe **automatiquement** en `MT5_DEMO`, avec ce message :

```
Mode reel non deverrouille : retour au mode demo
```

Un état incohérent en base ne peut donc pas produire d'ordres réels.

### 3.2 Ce que le RiskManager continue de vérifier en réel

Passer en `MT5_LIVE` ne relâche aucun contrôle. Le bloc 3 du `RiskManager`
vérifie toujours :

- que MetaTrader 5 est connecté ;
- que les informations de compte sont disponibles ;
- que `live_unlocked` est vrai — sinon `LIVE_NOT_UNLOCKED` ;
- que le trading est autorisé sur le compte et dans le terminal.

Et les blocs 4 à 12 s'appliquent exactement comme en démonstration. Le détail
complet est dans [RISK_MANAGEMENT.md](RISK_MANAGEMENT.md).

---

## 4. Reverrouiller

```
POST /api/v1/trading/live-lock
```

Aucune confirmation n'est demandée : revenir en arrière doit être plus facile que
d'avancer.

Effet immédiat :

- `live_unlocked` repasse à `false` ;
- si le mode d'exécution était `MT5_LIVE`, il repasse à **`MT5_DEMO`** ;
- une entrée de journal de niveau `WARNING` est écrite, catégorie `security` :
  « Mode reel reverrouille ».

Les **positions déjà ouvertes ne sont pas fermées.** Le reverrouillage empêche
l'ouverture de nouvelles positions ; il ne liquide rien.

### 4.1 Les trois freins, du plus doux au plus radical

| Action | Effet | Positions ouvertes |
|---|---|---|
| `POST /api/v1/trading/pause` | suspend les nouveaux trades automatiques | conservées |
| `POST /api/v1/trading/auto?enabled=false` | coupe le trading automatique | conservées |
| `POST /api/v1/trading/live-lock` | reverrouille le réel et repasse en `MT5_DEMO` | conservées |
| `POST /api/v1/emergency/cancel-pending` | annule tous les ordres en attente | positions conservées |
| `POST /api/v1/emergency/close-all` | **ferme tout**, réalise immédiatement pertes et gains | fermées |

L'arrêt d'urgence exige la phrase exacte `FERMER TOUTES LES POSITIONS` et met
l'automatisation en pause par défaut (`suspendAutomation` vaut `true`). Il est
journalisé en `CRITICAL` et écrit dans le journal d'audit.

Sachez lequel utiliser **avant** d'en avoir besoin. La route
`GET /api/v1/emergency/info` rappelle la phrase exacte et l'avertissement.

---

## 5. Après le passage en réel

Les premiers jours :

- [ ] Vérifiez chaque exécution dans la timeline du signal : le volume, le prix
      obtenu, le stop loss réellement placé.
- [ ] Comparez le prix d'exécution au prix attendu : l'écart révèle le slippage
      réel de votre broker sur vos instruments.
- [ ] Surveillez `GET /api/v1/trading/state` : `consecutiveLosses`,
      `dayRealizedPnl`, `dayRiskedPercent`, `paused`.
- [ ] Relisez `GET /api/v1/journal/audit` : aucune action que vous n'avez pas
      faite ne doit y figurer.
- [ ] Gardez un canal ou deux en `PAPER` en parallèle, pour comparer.

Reprenez le mode démonstration sans hésiter si quelque chose vous surprend. Le
reverrouillage est immédiat et sans conséquence sur vos positions.

---

## 6. Avertissement final

Cette checklist vérifie une **configuration**, pas une stratégie et pas un
résultat.

- Aucun des 9 critères, aucune des vérifications manuelles, aucun des garde-fous
  du `RiskManager` ne rend le trading sans risque. Ils réduisent seulement la
  probabilité d'une erreur du système lui-même.
- **Le trading de produits à effet de levier comporte un risque élevé de perte
  totale du capital engagé.** Copier les signaux d'un tiers n'atténue pas ce
  risque : vous ne connaissez ni sa méthode, ni ses positions réelles, ni ses
  intentions.
- Des résultats favorables en paper trading ou en démonstration **ne prédisent
  rien**. Les conditions d'exécution diffèrent : spread réel, slippage, latence,
  requotes, marché rapide, rejets du broker.
- Un canal peut changer de comportement du jour au lendemain, cesser de publier,
  publier des messages contradictoires, ou publier des résultats invérifiables.
  Rien dans TradePilot ne peut le prévoir.
- L'automatisation ajoute ses propres modes de défaillance : coupure réseau,
  terminal fermé, PC en veille, message mal interprété, symbole mal résolu. Le
  système refuse d'agir dans le doute, mais l'inaction a aussi un coût.
- Vous restez seul responsable de l'utilisation de cet outil, de sa
  configuration et de ses conséquences financières. Vérifiez la réglementation
  applicable dans votre pays et les conditions de votre broker.

**Ne mettez en jeu que ce que vous pouvez perdre entièrement.**

---

## 7. Ce qui n'a pas pu être vérifié sur cette machine

- La checklist n'a **jamais été exécutée avec de vraies données** : elle exige un
  historique de signaux, de trades fermés et un compte MT5 connecté.
- Aucun passage en `MT5_LIVE` n'a été effectué, ni même en `MT5_DEMO`.
- Les procédures de déverrouillage, d'activation et de reverrouillage décrites
  ici proviennent du code des routes correspondantes
  (`bridge/app/api/v1/trading.py`) et de la suite de tests locale, pas d'une
  exécution réelle contre un broker.
