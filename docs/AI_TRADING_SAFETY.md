# Sécurité de l'IA face au trading

**C'est le document le plus important du dossier.** Si vous n'en lisez qu'un,
lisez celui-ci.

TradePilot utilise des modèles de langage. Un modèle de langage produit du
texte plausible. **Plausible n'est pas vrai.** Un modèle peut écrire un prix
qui n'existe pas, un stop loss absent du message d'origine, un symbole que
votre broker ne cote pas, ou un chiffre de chômage qu'il a inventé — et le
faire avec un ton parfaitement assuré.

Toute l'architecture décrite ici part de ce constat. Elle tient en une phrase :

> **Un modèle propose. Des règles déterministes disposent.**

---

## 1. Ce que l'IA ne peut pas faire

Aucun modèle, local ou distant, ne peut inventer une valeur qui servira à
passer un ordre. La liste est explicite dans le cahier des charges et
implémentée dans le code :

| Interdit d'inventer | Où cela vient réellement |
|---|---|
| Un **prix d'entrée** | Du message d'origine, ou d'un calcul déterministe sur les données de marché |
| Un **stop loss** | Idem. Absent du message ⇒ reste `NULL` |
| Un **take profit** | Idem |
| Un **symbole** | De la liste réelle des symboles exposés par MetaTrader 5 |
| Une **direction** | Du parser déterministe, prioritaire sur l'IA |
| Une **donnée économique** | Du calendrier économique collecté, jamais du modèle |
| Une **actualité** | D'une source collectée et horodatée |
| Un **prix de marché** | Du flux MT5 |
| Une **date** | Des horodatages réels du système |

Ce qu'un modèle a le droit de faire, en revanche : **lire, extraire, classer,
résumer, expliquer, contextualiser**. C'est utile, et c'est suffisant.

---

## 2. Les barrières successives

Aucune barrière n'est censée suffire seule. Elles sont empilées, et chacune
peut refuser à elle seule.

```
   Message Telegram, ou analyse d'un instrument
                    │
   ① ─────────────► Le parser déterministe passe TOUJOURS en premier
                    │   pas de quota, pas de réseau, comportement prévisible
                    │
   ② ─────────────► L'IA n'est appelée QUE si le message reste ambigu
                    │
   ③ ─────────────► Sortie structurée exigée : JSON valide, ou échec
                    │
   ④ ─────────────► La lecture locale certaine écrase l'IA
                    │   symbole et direction du parser l'emportent
                    │
   ⑤ ─────────────► Validateur strict : cohérence interne du signal
                    │
   ⑥ ─────────────► Résolution du symbole contre la liste réelle du broker
                    │
   ⑦ ─────────────► Consensus des deux IA, puis recalibrage sur les mesures
                    │
   ⑧ ─────────────► RISKMANAGER — droit de veto absolu, 12 familles de règles
                    │
   ⑨ ─────────────► order_check auprès du broker AVANT order_send
                    │
   ⑩ ─────────────► Mode d'exécution : PAPER par défaut, réel verrouillé
                    ▼
                  Ordre
```

### ① Le déterministe passe toujours en premier

`app/services/signals/pipeline.py` exécute systématiquement le parser
déterministe (expressions régulières, analyse ligne par ligne) avant toute
sollicitation d'un modèle. Ce parser ne consomme aucun quota, ne dépend
d'aucun réseau, et **n'invente jamais une valeur absente du message**.

### ② L'IA n'est appelée que sur un message réellement ambigu

Deux conditions cumulatives :

- le parser local a échoué, ou sa validation n'est pas passée, ou sa confiance
  est inférieure à **0,85** (`AI_FALLBACK_THRESHOLD`) ;
- le message contient au moins un marqueur de trading (`BUY`, `SELL`, `LONG`,
  `SHORT`, `TP`, `SL`, `ENTRY`, `TARGET`, `CLOSE`, `BE`).

Un message de convivialité ne déclenche aucun appel : il ne ressemble à rien de
tradable, donc il ne mérite pas qu'on demande son avis à un modèle.

### ③ Sortie structurée, ou échec

Une réponse de modèle n'est exploitée que si `extract_json` en tire un objet
JSON. Cette fonction essaie le texte brut, puis un bloc de code Markdown, puis
la première accolade équilibrée — et **retourne `None` si rien ne se charge**.
Pas de réparation, pas de repli heuristique, pas de recherche d'un `BUY` dans
du texte libre.

Au niveau du routeur, une réponse non structurée est traitée **exactement comme
une panne** : le moteur est écarté et l'on passe au suivant
([AI_ROUTER.md](AI_ROUTER.md), §4).

Quand plus aucun moteur ne répond, `ai_service.complete_json` renvoie `None`.
L'appelant est donc contraint de traiter l'absence d'IA comme un cas normal.
**Il n'existe aucune valeur par défaut, aucune direction de secours.**

### ④ La lecture locale certaine écrase l'IA

Dans `_run_ai_fallback`, si le parser déterministe avait déjà identifié
l'instrument ou la direction, **la sortie de l'IA est écrasée par la lecture
locale**, et un avertissement est attaché au signal :

- `ia_symbole_ignore_au_profit_du_parser_local`
- `ia_direction_ignoree_au_profit_du_parser_local`

L'IA ne sert alors qu'à compléter les valeurs manquantes. Elle ne peut pas
contredire ce que le code a lu avec certitude.

### ⑤ Le validateur strict

`app/services/signals/validator.py` s'applique **à la sortie de l'IA comme à
celle du parser local**, sans distinction. Il ne consulte ni MT5 ni le risque :
il vérifie la cohérence interne.

| Contrôle | Refus |
|---|---|
| Intention de trade présente | `NO_ACTION` |
| Instrument reconnu | `SYMBOL_MISSING` |
| Direction présente | `DIRECTION_MISSING` |
| Prix et TP strictement positifs | `NEGATIVE_VALUE` |
| Zone d'entrée dans le bon ordre | `ENTRY_RANGE_INVERTED` |
| SL sous l'entrée à l'achat, au-dessus à la vente | `SL_WRONG_SIDE` |
| SL à moins de 25 % de l'entrée | `SL_TOO_FAR` — au-delà, c'est presque sûrement une valeur mal lue |
| SL non confondu avec l'entrée | `SL_TOO_CLOSE` |
| TP du bon côté de l'entrée | `TP_WRONG_SIDE` |
| Ordre en attente accompagné d'un prix | `PENDING_WITHOUT_PRICE` |
| Type d'ordre cohérent avec la direction | `ORDER_TYPE_MISMATCH` |

Deux anomalies mineures sont signalées sans bloquer : TP mal ordonnés
(`TP_ORDER`) et TP en doublon (`TP_DUPLICATE`).

La fonction `sanitize` accompagne le validateur, et son périmètre est
volontairement minuscule : **remettre les bornes d'une zone d'entrée dans
l'ordre et retirer les doublons de TP. Rien d'autre.** Aucune valeur n'est
inventée, aucune valeur n'est « corrigée ». Chaque intervention laisse un
avertissement sur le signal.

### ⑥ Le symbole est résolu contre la liste réelle du broker

Un modèle qui écrit `XAUUSD` n'a rien prouvé : votre compte Exness peut exposer
`XAUUSDm`, `XAUUSDz` ou `XAUUSD.r`. `SymbolResolver` interroge la liste réelle
des symboles MetaTrader 5 et teste les suffixes connus. Un symbole
introuvable chez le broker fait échouer l'exécution — il n'est jamais
« approché ».

### ⑦ Consensus et recalibrage

Quand les deux moteurs sont interrogés, leurs avis sont confrontés. On ne fait
**jamais** la moyenne entre un `BUY` et un `SELL`, et la confiance annoncée est
recalibrée contre les mesures déterministes : une contradiction avec l'analyse
technique plafonne la confiance à **0,55**, et un accord franc ne donne qu'une
prime de 0,05, plafonnée à **0,95**.

Détail complet : [AI_ENSEMBLE.md](AI_ENSEMBLE.md).

### ⑧ Le RiskManager

Voir la section 3 ci-dessous. C'est la barrière décisive.

### ⑨ `order_check` avant `order_send`

Chaque envoi est précédé d'un `order_check` auprès du broker. Un ordre que le
broker refuserait n'est jamais envoyé.

### ⑩ Le mode d'exécution

Le mode par défaut est `PAPER` : aucun ordre réel. Le passage en `MT5_LIVE`
exige un déverrouillage explicite (`live_unlocked`), et au démarrage un mode
réel non déverrouillé **retombe systématiquement en `MT5_DEMO`**.

En mode `MT5_DEMO`, si le compte connecté se révèle être un compte **réel**,
l'exécution est refusée. Si le type de compte est **indéterminable**, elle est
également refusée : dans le doute, on ne passe pas.

---

## 3. Le RiskManager garde un droit de veto absolu

`app/services/risk/manager.py`.

Trois propriétés de conception en font une barrière qu'on ne contourne pas :

1. **Il est totalement indépendant de l'IA.** Il ne connaît ni `ai_service`, ni
   le routeur, ni le consensus, ni le moteur local. Il ne sait même pas qu'une
   IA existe.
2. **Il n'a aucun accès à la base de données.** L'appelant lui assemble un
   `RiskContext` ; le manager applique ses règles sur ce contexte. Il ne peut
   donc pas être influencé par un état persistant modifié ailleurs.
3. **Aucune de ses règles ne peut être désactivée à chaud.**

Il évalue **douze familles de contrôles**, dans un ordre fixe, et **le premier
refus arrête tout** :

| # | Famille | Exemples de refus |
|---|---|---|
| 1 | Interrupteurs généraux | Trading automatique désactivé, automatisation en pause |
| 2 | Canal | Canal désactivé, canal en mode observation |
| 3 | Compte et mode d'exécution | MT5 déconnecté, mode réel non déverrouillé, compte réel alors qu'on demandait démo, type de compte indéterminable, trading non autorisé sur le compte |
| 4 | Contenu du signal | Pas d'intention exploitable, confiance insuffisante, direction non copiée, instrument non autorisé, SL obligatoire absent, TP obligatoire absent |
| 5 | Fraîcheur | Signal trop ancien |
| 6 | Fenêtres horaires | Jour non autorisé, hors plage horaire |
| 7 | Instrument côté broker | Symbole introuvable, spread anormal |
| 8 | Prix de référence | Entrée indéterminable, incohérences de niveaux |
| 9 | Limites journalières et drawdown | Plafond de trades du jour, drawdown maximal, pertes consécutives |
| 10 | Exposition | Positions simultanées, positions par instrument, exposition totale |
| 11 | Volume | Volume invalide, hors bornes du symbole |
| 12 | Marge | Marge insuffisante |

Chaque refus porte un **motif codifié** (`RejectionReason`) et un détail
lisible, et l'ensemble des contrôles franchis est conservé dans la décision :
on sait toujours où et pourquoi cela s'est arrêté.

Détail exhaustif des réglages : [RISK_MANAGEMENT.md](RISK_MANAGEMENT.md).

> **Le RiskManager n'accorde aucune dérogation à l'IA.** Une opportunité
> produite par le système passe exactement les mêmes contrôles qu'un signal
> Telegram. Une confiance de 99 %, un consensus parfait, dix facteurs positifs :
> rien de tout cela ne dispense d'un seul contrôle.

---

## 4. Dans le doute, la réponse est NO_TRADE

C'est une règle de conception, pas un réglage. Elle se vérifie partout.

| Situation | Réponse du système |
|---|---|
| Aucun moteur IA ne répond | `complete_json` renvoie `None`, et une décision exigeant l'IA passe en `NEEDS_REVIEW` |
| Sortie de modèle illisible | Moteur écarté, repli, puis échec explicite |
| Un seul moteur a répondu en ensemble | `INSUFFICIENT_DATA`, confiance plafonnée à 0,60, automatisme bloqué |
| Les deux moteurs se contredisent | `DISAGREEMENT`, **aucune direction retenue**, automatisme bloqué |
| L'IA contredit l'analyse technique | Confiance plafonnée à 0,55, consensus rétrogradé |
| Type de compte MT5 indéterminable | Exécution refusée |
| Symbole introuvable chez le broker | Exécution refusée |
| Prix d'entrée indéterminable | Exécution refusée |
| Spread anormal, marge insuffisante | Exécution refusée |

Le statut global le formule ainsi quand les deux IA sont muettes :

> Aucune intelligence disponible : les analyses déterministes continuent, mais
> toute décision exigeant l'IA passe en revue manuelle.

L'énumération `DecisionAction` prévoit d'ailleurs explicitement deux issues de
prudence à côté des actions de trading : **`NO_TRADE`** et **`NEEDS_REVIEW`**.

---

## 5. La confiance ne module jamais la taille de position

C'est un point sur lequel beaucoup de systèmes automatiques dérapent. Ici,
c'est verrouillé par la signature même de la fonction.

```python
async def calculate_lot(
    service, symbol, direction, entry, stop_loss,
    balance, risk_percent, max_lot=None,
) -> LotCalculation
```

**Il n'y a pas de paramètre de confiance.** Le volume dépend uniquement de :

- le solde du compte ;
- le pourcentage de risque configuré (global, ou surchargé par canal) ;
- la distance réelle entre l'entrée et le stop loss ;
- les métadonnées réelles du symbole MT5 (`order_calc_profit`, puis
  `tick_value` / `tick_size`) — jamais une valeur de pip codée en dur ;
- le volume maximal autorisé.

La confiance intervient à **un seul endroit** : comme **seuil d'admission**.
Si `signal.confidence` est inférieure au minimum configuré, le signal est
refusé (`LOW_CONFIDENCE`). Au-dessus du seuil, une confiance de 0,76 et une
confiance de 0,99 produisent **exactement le même volume**.

> **Confiance ≠ risque.** Même à 99 % de confiance, le risque ne dépasse jamais
> la limite du RiskManager. Et il n'existe aucune martingale, même en option :
> le volume n'augmente jamais après une perte.

---

## 6. Ce qui est mesuré, et ce qui n'est jamais gardé

### Mesuré

La table `ai_provider_metrics` suit, par couple (moteur, tâche) :

- taux de succès et taux de **JSON valides** ;
- latence moyenne, délais dépassés, erreurs ;
- **désaccords** entre les deux moteurs ;
- **`hallucinations_blocked`** — le compteur des valeurs inventées rejetées
  avant d'atteindre le trading, incrémenté par
  `ai_repo.record_blocked_hallucination`.

Un moteur dont le taux de succès tombe sous **50 %** au-delà de 8 appels perd
la priorité auprès du routeur. Automatiquement, sans intervention.

### Jamais gardé

Le raisonnement interne des modèles. Seules les sorties structurées et les
explications synthétiques sont conservées. Les routes de consultation le
rappellent dans leurs réponses.

---

## 7. Les réglages qui bornent l'automatisme

Table `ai_settings`, modifiable par `PUT /api/v1/ai/router/settings`.

| Clé | Défaut | Rôle |
|---|---|---|
| `aiTradingEnabled` | **`false`** | Le trading initié par le système lui-même est désactivé à l'installation |
| `telegramTradingEnabled` | `true` | Copie des signaux Telegram |
| `shadowMode` | **`true`** | Analyser et décider sans envoyer d'ordre — voir [SHADOW_MODE.md](SHADOW_MODE.md) |
| `requireConsensus` | `true` | Exige un consensus franc pour toute exécution automatique |
| `disagreementBehaviour` | `"NO_TRADE"` | Conduite en cas de désaccord |
| `maxAiTradesPerDay` | `3` | Plafond de trades initiés par le système |
| `maxTelegramTradesPerDay` | `10` | Plafond de trades issus de Telegram |
| `maxTradesPerSymbolPerDay` | `2` | Plafond par instrument |
| `minOpportunityConfidence` | `0.75` | Confiance minimale d'une opportunité générée |

Les valeurs par défaut sont volontairement prudentes : **à l'installation, le
système n'initie aucun trade de lui-même et se déclare en mode ombre.**

---

## 8. Ce qui n'est pas encore branché

L'honnêteté fait partie de la sécurité : un garde-fou dont vous croyez à tort
qu'il est actif est pire que pas de garde-fou du tout.

| Élément | État réel au 11 septembre 2026 |
|---|---|
| Contrat `AIProvider`, routeur, consensus, recalibrage | **Écrits et testés** — 21 tests |
| Validateur strict, résolution de symbole, RiskManager, `order_check` | **En production**, utilisés par le pipeline Telegram existant |
| Priorité du parser déterministe sur l'IA | **En production** |
| Routage du parsing Telegram par `ai_service` | **Non branché.** Le pipeline appelle encore `openrouter_service.parse_signal` directement |
| Appel au consensus avant une décision | **Aucun appelant en production.** Le moteur de décision est en cours d'écriture |
| `shadowMode` et `aiTradingEnabled` | **Stockés et exposés, lus par personne.** Aucun code d'exécution ne les consulte encore |
| `disagreementBehaviour` | **Stocké, non lu.** Un désaccord bloque de toute façon l'automatisme |
| Compteur `hallucinations_blocked` | La fonction d'incrément existe ; **aucun appelant en production** |
| Génération d'opportunités par le système | **Table seule.** Le générateur n'est pas écrit — voir [AUTONOMOUS_TRADING.md](AUTONOMOUS_TRADING.md) |

**Ce que cela veut dire concrètement :** le système ne peut pas aujourd'hui
initier un trade de lui-même, puisque le code qui le ferait n'existe pas
encore. Le chemin réellement actif reste celui du cahier des charges initial :
message Telegram → parser déterministe → repli OpenRouter si ambigu →
validateur → RiskManager → `order_check` → `order_send`.

Un écart de conception mérite aussi d'être signalé : la route
`PUT /api/v1/ai/router/settings` **accepte n'importe quelle chaîne** pour `mode`
et pour `disagreementBehaviour`, sans les valider contre les énumérations. Un
mode inexistant serait écrit tel quel en base et provoquerait une erreur à la
relecture. Ne saisissez que les valeurs documentées.

---

## 9. Ce que tout cela ne garantit pas

Ces barrières réduisent la probabilité d'une erreur grossière. **Elles ne
rendent pas le trading sans risque.**

- **Le trading de produits à effet de levier comporte un risque élevé de perte
  totale du capital engagé.**
- Une donnée parfaitement lue, parfaitement validée et parfaitement exécutée
  peut produire une perte. Un signal correct peut être un mauvais signal.
- L'automatisation ajoute ses propres risques : coupure réseau, terminal fermé,
  PC en veille, écart de prix à l'exécution, symbole introuvable.
- Aucune mesure affichée par cet outil ne prédit un résultat futur.
- Vous restez seul responsable de l'utilisation de cet outil, de sa
  configuration et de ses conséquences financières.

Travaillez en `PAPER`, puis sur un compte de **démonstration**, aussi longtemps
que nécessaire. Relisez [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) avant
toute bascule en réel.
