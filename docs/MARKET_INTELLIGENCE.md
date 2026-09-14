# Intelligence de marché

L'intelligence de marché est la couche qui doit répondre, pour un instrument
donné, à la question : *que se passe-t-il, et pourquoi le système en tire-t-il
cette conclusion ?*

> **À lire en premier.** Au 11 septembre 2026, cette couche existe
> **au niveau des données** : les tables, les énumérations et les scores sont
> définis et créés en base. **Les moteurs qui les remplissent sont en cours
> d'écriture par d'autres équipes.** Ce document décrit donc la structure
> réellement présente dans le code, et signale explicitement ce qui n'est pas
> encore branché. La documentation détaillée de chaque moteur
> (`MARKET_DATA.md`, `TECHNICAL_ENGINE.md`, `HISTORICAL_PATTERN_ENGINE.md`,
> `NEWS_ENGINE.md`, `ECONOMIC_CALENDAR.md`, `CROSS_MARKET.md`,
> `DECISION_ENGINE.md`, `CONFIDENCE_ENGINE.md`) sera écrite au fur et à mesure
> que ces moteurs seront livrés.

---

## 1. Le principe : un rapport par instrument

L'objectif est un rapport unique, lisible, qui rassemble pour chaque instrument
surveillé :

| Rubrique | Source prévue |
|---|---|
| Prix | Flux MetaTrader 5 |
| Régime de marché | Détection déterministe sur ATR et structure |
| Technique | Moteur d'analyse technique |
| Historique | Recherche de situations comparables |
| Macro | Analyse macroéconomique |
| Actualités | Moteur de news |
| Inter-marchés | Corrélations entre instruments |
| Telegram | Signaux reçus sur cet instrument |
| IA locale | Avis du moteur local |
| IA OpenRouter | Avis du moteur distant |
| Consensus IA | Confrontation des deux |
| Score global | Agrégation pondérée |
| Décision | `STRONG_BUY` … `NO_TRADE` |
| Motif | Explication lisible |

Ce que cette liste dit en creux, et qui compte : **l'avis des IA est une
rubrique parmi douze**, pas la conclusion. Le cahier des charges lui attribue
d'ailleurs le plus petit poids de la pondération proposée — 5 % contre 25 % pour
l'analyse technique.

---

## 2. La structure des données, telle qu'elle existe

### 2.1 `watchlist` — ce que le système a le droit de regarder

Un instrument n'est observé que s'il figure dans cette table. Rien n'y entre
tout seul.

| Champ | Rôle |
|---|---|
| `canonical` | Nom canonique, unique (`XAUUSD`) |
| `broker_symbol` | Nom réel chez le broker (`XAUUSDm`) — **jamais supposé**, résolu depuis la liste MT5 |
| `available` | Confirmé présent chez le broker |
| `enabled`, `scan_priority` | Activation et priorité de scrutation (1 à 10) |
| `allow_ai_trading` | **`false` par défaut** — autorisation par instrument |
| `allow_telegram_trading` | `true` par défaut |
| `notify_news`, `notify_opportunities`, `notify_volatility` | Préférences d'alerte |
| `last_scanned_at` | Dernière analyse |

Le découplage `allow_ai_trading` / `allow_telegram_trading` permet, par exemple,
de laisser le système copier les signaux Telegram sur un instrument tout en lui
interdisant d'en initier un de lui-même.

### 2.2 `market_snapshots` — la mémoire de contexte

Une photographie chiffrée d'un instrument à un instant donné. C'est la table
centrale : c'est sur ces enregistrements que la recherche de situations
comparables travaillera.

| Groupe | Champs |
|---|---|
| Identité | `symbol`, `captured_at` |
| Prix | `bid`, `ask`, `spread_points` |
| Contexte | `regime`, `trend_d1`, `trend_h4`, `trend_h1` |
| Caractéristiques | `features` — dictionnaire normalisé, comparable d'un instrument à l'autre |
| Scores partiels | `technical_score`, `historical_score`, `macro_score`, `news_score`, `cross_market_score`, `telegram_score`, `local_ai_score`, `openrouter_score` |
| Conclusion | `ai_consensus`, `global_score`, `decision` |

Le fait que chaque score soit stocké **séparément** est ce qui rend une décision
explicable après coup : on peut dire quelle rubrique a fait pencher la balance.

### 2.3 Les régimes et les tendances

`MarketRegime` — huit valeurs :

`TRENDING_UP`, `TRENDING_DOWN`, `RANGING`, `HIGH_VOLATILITY`,
`LOW_VOLATILITY`, `BREAKOUT`, `NEWS_DRIVEN`, `UNCERTAIN`.

La valeur par défaut est **`UNCERTAIN`**, et c'est délibéré : tant qu'un moteur
n'a pas établi le régime, le système ne prétend pas le connaître.

`TrendState` — `BULLISH`, `BEARISH`, `NEUTRAL`.

`Timeframe` — `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D1`, `W1`, `MN1`.

La table `market_regimes` conserve l'historique des changements de régime, avec
l'ATR et son ratio.

### 2.4 `historical_patterns` — les analogues historiques

| Champ | Contenu |
|---|---|
| `reference_features` | La situation cherchée |
| `matches`, `similarity_mean` | Nombre de correspondances et similarité moyenne |
| `positive`, `negative`, `neutral` | Répartition des issues |
| `average_move`, `average_mae`, `average_mfe` | Mouvement moyen, excursion adverse et favorable |
| `horizon_hours` | Horizon d'observation, 4 heures par défaut |
| `distribution` | Distribution complète |
| `disclaimer` | **Inscrit en dur dans le modèle** |

Le champ `disclaimer` porte cette valeur par défaut :

> Statistiques historiques indicatives : elles ne prédisent aucune performance
> future.

Ce n'est pas un ornement : c'est la règle. Une analogie historique décrit ce qui
s'est produit, jamais ce qui va se produire.

### 2.5 `cross_market_states` — les corrélations

Corrélations récentes d'un instrument de référence vers les autres, sur une
fenêtre de 30 jours par défaut. Sert à éviter d'empiler trois positions qui
sont en réalité le même pari.

### 2.6 Actualités et calendrier

`news_events` conserve, pour chaque actualité : source, titre, résumé, dates de
publication et de réception, catégorie, pays, entités, actifs et devises
concernés, impact, sentiment, confiance, motif, statut de vérification,
déduplication — **et le moteur IA qui a servi à la qualifier**
(`ai_provider_used`, `ai_model_used`).

Cette dernière colonne est importante : elle permet de mesurer après coup
quelle intelligence classe correctement les actualités.

| Énumération | Valeurs |
|---|---|
| `NewsImpact` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `NewsSentiment` | `BULLISH`, `BEARISH`, `NEUTRAL`, `MIXED` |
| `VerificationStatus` | `UNCONFIRMED`, `PARTIALLY_CONFIRMED`, `CONFIRMED` |

Le statut par défaut est **`UNCONFIRMED`** : une actualité collectée n'est pas
une actualité vérifiée.

`news_asset_links` relie explicitement une actualité à un instrument avec une
pertinence chiffrée. `economic_events` porte le calendrier économique :
échéance, devise, impact, prévision, valeur précédente, valeur réelle, et les
préavis déjà notifiés.

### 2.7 Décisions et traçabilité

`decision_records` conserve **toutes** les décisions, y compris les trades
**non pris**. C'est ce qui rend le système auditable.

| Champ | Contenu |
|---|---|
| `source` | `TELEGRAM`, `AI_GENERATED` ou `MANUAL` |
| `action` | `STRONG_BUY`, `BUY`, `WAIT`, `SELL`, `STRONG_SELL`, `NO_TRADE`, `NEEDS_REVIEW` |
| `global_score`, `confidence`, `regime` | Contexte chiffré |
| `reason`, `positive_factors`, `negative_factors` | Explication, dans les deux sens |
| `signal_id`, `opportunity_id`, `snapshot_id`, `trade_id` | Rattachements |
| `executed`, `shadow` | Ce qui a été fait, ou pas |

La présence de `negative_factors` à côté de `positive_factors` n'est pas
cosmétique : une décision qui n'énumère que ses arguments favorables n'est pas
une analyse, c'est un argumentaire.

`decision_factors` décompose chaque décision en composantes chiffrées : nom,
score, poids, contribution, détail. On sait d'où vient chaque point.

`strategy_performance` agrège les résultats par jour, par stratégie et par
origine — ce qui permettra de comparer honnêtement ce qui vient de Telegram et
ce qui vient du système lui-même.

---

## 3. Les actions de décision

`DecisionAction` compte sept valeurs, dont **deux issues de prudence** :

| Action | Sens |
|---|---|
| `STRONG_BUY`, `BUY` | Achat |
| `WAIT` | Attendre, sans écarter l'instrument |
| `SELL`, `STRONG_SELL` | Vente |
| `NO_TRADE` | Ne pas trader ce cas |
| `NEEDS_REVIEW` | Revue manuelle nécessaire |

`NEEDS_REVIEW` est l'issue prévue quand une décision exigeait l'IA et qu'aucune
intelligence n'était disponible, ou quand le consensus n'était pas franc.

---

## 4. Ce qui existe, ce qui n'existe pas

### Existe aujourd'hui

- les **19 tables** de `app/models/intelligence.py`, créées automatiquement au
  démarrage, avec ajout à chaud des colonnes d'une nouvelle version ;
- toutes les énumérations décrites ci-dessus ;
- la couche d'intelligence artificielle complète : contrat, moteur local,
  OpenRouter, routeur, consensus, métriques, dix routes REST
  ([AI_HYBRID_ARCHITECTURE.md](AI_HYBRID_ARCHITECTURE.md)) ;
- les briques déterministes déjà en production depuis le cahier des charges
  initial : parser Telegram, validateur, résolution de symbole, `RiskManager`,
  gestion des positions, statistiques sur trades fermés.

### N'existe pas encore

Les paquets de services suivants sont des **emplacements vides**
(`__init__.py` sans contenu) :

| Paquet | Moteur attendu |
|---|---|
| `app/services/market_data` | Collecte des cotations et des bougies |
| `app/services/market_regime` | Détection de régime |
| `app/services/market_scanner` | Scrutation de la liste d'instruments |
| `app/services/technical_analysis` | Analyse technique multi-horizons |
| `app/services/historical_patterns` | Recherche de situations comparables |
| `app/services/cross_market` | Corrélations |
| `app/services/news` | Collecte, qualification, déduplication |
| `app/services/economic_calendar` | Calendrier économique |
| `app/services/decision` | Moteur de décision |
| `app/services/confidence` | Pondération et confiance globale |
| `app/services/opportunities` | Génération d'opportunités |
| `app/services/strategies` | Familles de stratégies |
| `app/services/learning` | Apprentissage après trade |
| `app/services/notifications` | Notifications enrichies |

Les modules de routes `market`, `patterns`, `news`, `decisions` et
`notifications` sont déclarés et enregistrés auprès de FastAPI, mais
**n'exposent aucun chemin**. Les appeler ne renvoie rien : il n'y a rien à
appeler.

La pondération proposée par le cahier des charges — technique 25 %, historique
15 %, régime 10 %, macro 15 %, news 10 %, inter-marchés 10 %, Telegram 10 %,
consensus IA 5 % — **n'est pas implémentée**. Elle est citée ici comme intention,
pas comme comportement.

---

## 5. Ce qui ne changera pas quand ces moteurs arriveront

Trois règles sont déjà inscrites dans les structures, et elles tiendront quel
que soit le moteur qui les remplira :

1. **Les niveaux de prix viennent de calculs déterministes**, jamais d'un
   modèle : structure, volatilité, supports et résistances, ATR. L'IA
   interprète et explique ; elle ne chiffre pas.
2. **Chaque décision est décomposable** en facteurs chiffrés, et les décisions
   non exécutées sont conservées au même titre que les autres.
3. **Le `RiskManager` reste la dernière barrière**, indépendante de tout ce qui
   précède. Voir [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md).

---

Le trading comporte un risque de perte. Un rapport d'intelligence de marché
décrit des mesures observées sur des données passées. Il ne prédit rien, et
aucune de ses rubriques n'est une recommandation.
