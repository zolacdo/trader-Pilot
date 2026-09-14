# Analyse d'un canal

Le **Channel Analyzer** rejoue l'historique d'un canal Telegram à travers le
parser local et produit un rapport de **mesures factuelles**. Il ne note pas le
canal, ne le recommande pas et ne prédit rien.

Sources : `bridge/app/services/channels/analyzer.py`,
`bridge/app/services/channels/backtester.py`,
`bridge/app/services/statistics/service.py`,
`bridge/app/models/telegram.py` (classe `ChannelAnalysis`).

---

## 1. Lancer une analyse

```
POST /api/v1/channels/{channel_id}/analyze
{ "messages": 250, "backtest": false }
```

| Paramètre | Défaut | Bornes | Rôle |
|---|---|---|---|
| `messages` | `250` | `50` à `1000` | nombre de messages d'historique à récupérer |
| `backtest` | `false` | — | ajoute la simulation historique sur les cours MT5 |

Le canal doit déjà exister dans la table `channels` : ajoutez-le d'abord avec
`POST /api/v1/channels` (voir [CHANNEL_DISCOVERY.md](CHANNEL_DISCOVERY.md)).
L'ajout ne rejoint pas le canal et l'analyse non plus.

Réponses d'erreur possibles :

| Code | Cause |
|---|---|
| `404` | canal inconnu du Bridge |
| `502` | historique indisponible côté Telegram (dont un `FloodWait`) |
| `422` | aucun message texte accessible dans ce canal |

Consultation ultérieure :

```
GET /api/v1/channels/{channel_id}/analyses     # toutes les analyses du canal
GET /api/v1/channels/{channel_id}              # champ latestAnalysis
```

### 1.1 Aucun appel à l'IA pendant une analyse

L'analyse rejoue chaque message avec `allow_ai = False`. Analyser plusieurs
centaines de messages avec un modèle gratuit épuiserait la totalité du quota
disponible pour un simple rapport de mesures.

La contrepartie est assumée et importante à comprendre : **les taux mesurés
reflètent ce que le parser local sait lire, seul.** C'est une mesure plus honnête
de la structure réelle du canal qu'un taux gonflé par une interprétation
assistée.

---

## 2. Ce que mesure le rapport

Table `channel_analysis`. Voici la totalité des champs produits, dans l'ordre du
modèle.

### 2.1 Volumes

| Champ (API) | Colonne | Signification |
|---|---|---|
| `messagesScanned` | `messages_scanned` | Nombre de messages parcourus, y compris ceux sans rapport avec le trading. |
| `signalLikeMessages` | `signal_like_messages` | Messages portant une **intention de trade**. Un message est compté ici s'il est reconnu comme signal par le parser, **ou** s'il contient `BUY`, `SELL`, `LONG` ou `SHORT` sans être exploitable. C'est le dénominateur des taux de structure. |
| `parsedMessages` | `parsed_messages` | Messages reconnus comme signal **et** ayant passé la validation locale sans problème bloquant. C'est le nombre de signaux réellement exploitables. |
| `followUpMessages` | `follow_up_messages` | Messages de suivi rattachables à un signal : `TP1 HIT`, `CLOSE`, `MOVE SL`, `CANCEL`… |
| `closeMessages` | `close_messages` | Sous-ensemble des suivis : fermetures totales ou partielles. |
| `modifyMessages` | `modify_messages` | Sous-ensemble des suivis : déplacement de SL, break even, déplacement de TP, annulation d'ordre en attente. |
| `duplicateSignals` | `duplicate_signals` | Signaux republiés à l'identique — même instrument, même direction, même prix d'entrée arrondi — dans une fenêtre de **30 minutes**. |

### 2.2 Taux et moyennes

| Champ (API) | Calcul exact | Ce qu'il dit |
|---|---|---|
| `structureQuality` | signaux structurés ÷ `signalLikeMessages`, en % | Part des messages à intention de trade que le parser reconnaît comme un signal. Un canal qui écrit en phrases libres fait chuter cette valeur. |
| `parseableRate` | `parsedMessages` ÷ `signalLikeMessages`, en % | Part des messages à intention de trade réellement **exploitables** : reconnus **et** cohérents. C'est la mesure la plus utile du rapport. |
| `withStopLossRate` | signaux avec SL ÷ signaux structurés, en % | Discipline du canal sur le stop loss. Avec `require_stop_loss = true` (le défaut), un canal à faible taux produira beaucoup de refus `MISSING_STOP_LOSS`. |
| `withTakeProfitRate` | signaux avec au moins un TP ÷ signaux structurés, en % | Un canal à faible taux gère probablement ses sorties par messages de suivi. |
| `averageTakeProfits` | total des TP ÷ signaux structurés | Nombre moyen d'objectifs par signal. Utile pour choisir `multi_tp_strategy` : une moyenne proche de 3 justifie `PARTIAL_CLOSE` ou `SPLIT_POSITIONS`, une moyenne de 1 rend `FIRST_TP_ONLY` équivalent. |
| `signalsPerDay` | `parsedMessages` ÷ étendue réelle des dates, en jours (minimum 1) | Fréquence observée. À croiser avec `max_positions` et `max_daily_risk_percent`. |

Les taux sont arrondis à une décimale. Un dénominateur nul donne `0.0` — le
rapport ne divise jamais par zéro.

### 2.3 Période et répartitions

| Champ | Contenu |
|---|---|
| `firstMessageAt`, `lastMessageAt` | bornes réelles de la période analysée, en UTC |
| `symbols` | dictionnaire `{symbole canonique: nombre}` — par exemple `{"XAUUSD": 148, "EURUSD": 12}` |
| `directions` | dictionnaire `{"BUY": n, "SELL": m}` |
| `backtest` | bloc de simulation historique, ou `null` — voir la section 4 |
| `notes` | résumé textuel en français, strictement descriptif |
| `disclaimer` | « Mesures factuelles observées sur les messages analysés. Elles ne prédisent aucune performance future. » |

---

## 3. Comment lire le rapport

### 3.1 Commencez par la période

`firstMessageAt` et `lastMessageAt` déterminent la valeur de tout le reste. 250
messages étalés sur 3 jours et 250 messages étalés sur 8 mois ne se lisent pas de
la même façon. `signalsPerDay` est calculé sur cette étendue réelle, pas sur une
hypothèse.

### 3.2 `parseableRate` avant tout

C'est la mesure qui conditionne l'usage du canal avec TradePilot. Elle répond à
une seule question : **quelle proportion des messages de ce canal le système
peut-il réellement exploiter, tout seul ?**

| Valeur observée | Lecture |
|---|---|
| élevée | canal très structuré, le parser local suffit, peu d'appels IA, peu de refus |
| moyenne | une partie des messages partira en repli IA — et sera refusée en automatique à cause du plafond de confiance de `0.80` face à `min_confidence = 0.85` (voir [OPENROUTER_SETUP.md](OPENROUTER_SETUP.md), section 9) |
| faible | canal peu automatisable en l'état ; le mode `MANUAL` est plus adapté que le mode `AUTO` |

Aucun seuil n'est imposé par l'outil. Il n'y a pas de « bonne » valeur affichée
quelque part : c'est votre lecture.

### 3.3 Croisez avec vos réglages

| Mesure | Réglage concerné | Question à se poser |
|---|---|---|
| `withStopLossRate` | `require_stop_loss` | Combien de signaux seront refusés faute de SL ? |
| `withTakeProfitRate` | `require_take_profit` | Faut-il activer cette exigence sur ce canal ? |
| `averageTakeProfits` | `multi_tp_strategy`, `split_ratios` | Le fractionnement a-t-il un sens ici ? |
| `signalsPerDay` | `max_positions`, `max_daily_risk_percent` | Le canal produira-t-il plus de signaux que mes limites n'en acceptent ? |
| `duplicateSignals` | idempotence | Le canal republie-t-il beaucoup ? |
| `followUpMessages` vs `parsedMessages` | gestion des positions | Le canal gère-t-il ses sorties par messages, ou par TP fixes ? |
| `symbols` | `allowed_symbols` | Le canal traite-t-il des instruments que je ne veux pas ? |

Exemple de lecture : un canal à `signalsPerDay = 12`, avec `max_positions = 3` et
`max_positions_per_symbol = 1`, sur un canal qui ne traite que `XAUUSD` : la
grande majorité des signaux sera refusée avec `MAX_POSITIONS_SYMBOL`. Ce n'est
pas un défaut du système, c'est une incompatibilité entre le rythme du canal et
vos limites — et il vaut mieux la découvrir dans un rapport que sur un compte.

### 3.4 Les doublons

Le compteur `duplicateSignals` applique exactement la même règle que le pipeline
temps réel : même symbole canonique, même direction, même prix d'entrée arrondi à
5 décimales, à moins de **30 minutes** d'écart.

En temps réel, un doublon est de toute façon bloqué en amont par la clé
d'idempotence. Le compteur sert à qualifier le canal : un canal qui republie
massivement produit beaucoup de bruit dans le journal.

### 3.5 Le champ `notes`

Un résumé textuel généré automatiquement, en français neutre. Il reprend les
mêmes chiffres, sous forme de phrases, et se termine toujours par :

> Mesures relevées sur l'historique disponible, sans projection de performance.

Il ne contient aucune appréciation, aucune recommandation, aucun superlatif.

---

## 4. La simulation historique

Activée avec `"backtest": true`. Elle exige un service de marché disponible
(`trading_engine.market`) pour récupérer les cours historiques.

### 4.1 Quels signaux sont testables

Un signal historique n'est rejoué que s'il est **complet** : date, instrument,
direction, prix d'entrée, stop loss et au moins un take profit. Une zone d'entrée
est ramenée à son milieu. Un signal dont le risque calculé est nul ou négatif est
écarté.

Seul le **premier** take profit est simulé. Les prises partielles et les messages
de suivi ne sont pas rejoués : la simulation ne prétend pas reproduire la gestion
réelle d'une position.

### 4.2 Comment se déroule le rejeu

| Paramètre | Valeur |
|---|---|
| Unité de temps | bougies **M15** |
| Fenêtre maximale | **7 jours** après la date du signal |
| Entrée au marché | prise à l'ouverture de la première bougie |
| Entrée sur ordre en attente | prise quand une bougie englobe le prix demandé |

Le symbole canonique est traduit en symbole broker si un résolveur est fourni ;
sinon il est utilisé tel quel.

### 4.3 Les cinq issues possibles

Énumération `BacktestOutcome` :

| Issue | Quand | Compte dans les moyennes ? |
|---|---|---|
| `WIN` | le take profit est atteignable dans une bougie où le stop ne l'est pas | oui |
| `LOSS` | le stop loss est atteignable dans une bougie où le TP ne l'est pas | oui |
| `AMBIGUOUS` | **les deux** sont atteignables dans la même bougie M15 | oui, **compté au pire** : `−1 R` |
| `UNDETERMINED` | prix d'entrée jamais atteint, instrument introuvable chez le broker, ou aucune bougie historique disponible | non |
| `OPEN` | toujours ouvert au bout de 7 jours | non |

Chaque signal testé produit une ligne dans la table `backtest_results`, avec son
issue, son R multiple et un détail lisible.

### 4.4 La règle AMBIGUOUS — le point le plus important

Une bougie OHLC ne donne que quatre valeurs : ouverture, plus haut, plus bas,
clôture. Elle ne dit **rien** de l'ordre dans lequel ces prix ont été atteints à
l'intérieur de la bougie.

Prenons un achat, entrée 2400, stop loss 2390, take profit 2420. Une bougie M15
affiche `low = 2388` et `high = 2425`. Le prix a donc touché le stop **et** la
cible pendant ces 15 minutes. Mais dans quel ordre ?

- s'il est descendu à 2388 d'abord, la position était fermée en perte avant
  d'atteindre 2425 : c'est une **perte** ;
- s'il est monté à 2425 d'abord, c'est un **gain**.

**Avec des données OHLC, il est strictement impossible de le savoir.** Deviner
reviendrait à fabriquer un résultat.

TradePilot fait donc trois choses, et les assume :

1. l'issue est marquée `AMBIGUOUS`, avec le détail « SL et TP atteignables dans
   la meme bougie M15 : ordre reel inconnu » ;
2. le trade n'est **jamais** compté comme gagnant ;
3. l'hypothèse prudente `AMBIGUOUS_R = −1.0` lui est appliquée : il pèse comme
   une perte pleine dans le R total, le R moyen et le drawdown théorique.

Ce choix rend la simulation **pessimiste par construction**. C'est délibéré.
L'alternative — supposer le meilleur cas, ou même supposer 50/50 — produirait des
chiffres flatteurs et faux.

Le nombre de cas `AMBIGUOUS` est lui-même une information : un canal dont les
signaux ont des stops et des cibles très serrés en produira beaucoup, ce qui
signale que ses signaux sont difficiles à évaluer honnêtement sur des données
M15 — et probablement sensibles au spread et au slippage en conditions réelles.

Pourquoi M15 et pas M1 ? Une bougie plus fine réduirait le nombre de cas ambigus,
mais dépasserait ce que le terminal renvoie confortablement sur plusieurs mois
d'historique. Le compromis est explicite dans le code.

### 4.5 Le bloc `backtest`

| Champ | Contenu |
|---|---|
| `testable` | nombre de signaux complets rejoués |
| `wins` | issues `WIN` |
| `losses` | issues `LOSS` |
| `ambiguous` | issues `AMBIGUOUS` |
| `undetermined` | issues `UNDETERMINED` |
| `open` | issues `OPEN` |
| `averageR` | R moyen sur les issues tranchées (`WIN`, `LOSS`, `AMBIGUOUS`), ou `null` si aucune |
| `totalR` | somme des R sur ces mêmes issues |
| `theoreticalDrawdownR` | plus forte baisse de la courbe cumulée de R, en valeur positive |
| `tp1Hits` | identique à `wins` |
| `slHits` | identique à `losses` |
| `disclaimer` | « Simulation historique indicative - elle ne garantit aucune performance future. » |

### 4.6 Ce que la simulation ne modélise pas

Cette liste est aussi importante que les chiffres eux-mêmes :

- le **spread** et la commission ;
- le **slippage** à l'exécution ;
- les **swaps** de nuit ;
- la **latence** entre la publication du message et l'exécution réelle ;
- les **prises partielles** et les messages de suivi du canal ;
- le **break even** et le trailing stop ;
- les **limites de risque** : un signal refusé en conditions réelles par
  `MAX_POSITIONS`, `DAILY_LOSS_LIMIT` ou `SPREAD_TOO_HIGH` est quand même rejoué
  ici ;
- le **dimensionnement** : tout est exprimé en R, pas en devise.

Un résultat de simulation n'est donc pas une performance. C'est une mesure de la
cohérence interne des signaux d'un canal, sur des données passées, avec des
hypothèses volontairement défavorables.

---

## 5. Le tableau de comparaison des canaux

```
GET /api/v1/channels/compare/table
```

Une ligne par canal connu. Colonnes réellement produites par
`statistics.compare_channels` :

| Colonne | Source |
|---|---|
| `channelId`, `title`, `username`, `monitored` | table `channels` |
| `signalsDetected` | `parsed_messages` de la dernière analyse, sinon le compteur `signals_count` du canal |
| `messagesScanned` | dernière analyse |
| `parseRate` | `parseable_rate` de la dernière analyse |
| `slRate` | `with_stop_loss_rate` |
| `tpRate` | `with_take_profit_rate` |
| `signalsPerDay` | dernière analyse |
| `analysedAt` | date de la dernière analyse |
| `historyAvailable` | vrai si cette analyse contient un bloc `backtest` |
| `backtest` | le bloc complet, ou `null` |
| `paperTrades` | nombre de trades PAPER **fermés** attribués à ce canal |
| `paperPnl` | résultat net cumulé en paper trading |
| `paperWinRate` | taux de réussite paper, ou `null` sans aucun trade |
| `paperDrawdown` | plus forte baisse de la courbe d'equity paper, ou `null` |
| `averageR` | R moyen des trades paper dont le R multiple est renseigné, ou `null` |

Les mesures `paper*` proviennent des trades **réellement exécutés** en mode
`PAPER`, pas de la simulation historique. Les deux blocs ne se confondent pas :
`backtest` regarde le passé du canal, `paper*` regarde ce que TradePilot a
effectivement fait avec ce canal chez vous.

### 5.1 Aucun classement, aucun meilleur canal

Le tableau est renvoyé avec ce texte :

> Données observées uniquement. L'application ne désigne pas de meilleur canal :
> les résultats passés ne prédisent pas les résultats futurs.

C'est une propriété du code, pas une formule de politesse :

- les lignes ne sont **pas triées par performance** — elles sortent dans l'ordre
  de `list_channels` ;
- aucun score composite, aucune note, aucune étoile, aucun rang n'est calculé ;
- aucune colonne n'est mise en avant par rapport à une autre ;
- aucun champ « recommandé », « meilleur », « à éviter » n'existe dans la
  réponse.

### 5.2 `null` plutôt que zéro

Lorsqu'une mesure n'a pas de sens — aucun trade fermé, aucune perte pour calculer
un profit factor, aucun R renseigné — la valeur retournée est **`null`**, pas
`0`. Un zéro laisserait croire à un résultat mesuré ; `null` dit clairement qu'il
n'y a rien à mesurer.

La même règle s'applique aux statistiques globales
(`GET /api/v1/statistics`) : `winRate`, `profitFactor`, `averageWin`,
`averageLoss`, `averageR`, `maxDrawdown` et `expectancy` valent `null` quand
l'échantillon ne permet pas de les calculer.

### 5.3 Comparer honnêtement

Deux canaux ne sont comparables que si :

- ils ont été analysés sur un **volume de messages** comparable ;
- leurs analyses couvrent des **périodes** comparables ;
- ils traitent des **instruments** comparables ;
- ils ont tourné en paper trading pendant une durée comparable, avec les mêmes
  réglages de risque.

Comparer 500 messages sur 6 mois avec 100 messages sur 4 jours ne veut rien dire,
même si le tableau affiche les deux lignes côte à côte.

---

## 6. Ce qui n'a pas pu être vérifié sur cette machine

- **Aucune analyse de canal réelle n'a été effectuée** : aucun historique
  Telegram n'a été récupéré.
- **Aucune simulation historique n'a été exécutée sur de vraies bougies MT5** :
  la récupération des cours passe par un terminal MetaTrader 5 connecté, ce qui
  n'a pas été le cas ici. La logique de rejeu, y compris la règle `AMBIGUOUS`,
  est couverte par la suite de tests locale contre le simulateur.
- Les écrans **Détail d'un canal** et **Comparaison des canaux** sont
  implémentés, mais n'ont jamais été affichés avec un rapport d'analyse réel.
  Les routes décrites ici peuvent aussi être appelées directement.
