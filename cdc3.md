# PROJET : AI MARKET WATCHER + TELEGRAM SIGNAL ENGINE

Tu es un architecte logiciel senior, développeur Python expert en trading algorithmique, MetaTrader 5, analyse quantitative, IA, NLP, sentiment analysis, analyse fondamentale, Telegram Bot API et systèmes temps réel.

Ta mission est de CONCEVOIR ET DÉVELOPPER COMPLÈTEMENT un système de surveillance des marchés financiers capable de :

- surveiller plusieurs marchés 24h/24 ;
- récupérer les données directement depuis MetaTrader 5 ;
- analyser plusieurs timeframes ;
- analyser la structure du marché ;
- effectuer de l'analyse technique ;
- effectuer de l'analyse comportementale du prix ;
- analyser les actualités ;
- effectuer de l'analyse fondamentale ;
- effectuer de l'analyse sémantique ;
- analyser le sentiment des marchés ;
- analyser éventuellement des signaux provenant de Telegram ;
- utiliser une IA locale ET OpenRouter ;
- combiner toutes ces informations ;
- produire une décision structurée ;
- générer BUY / SELL / NO TRADE ;
- générer automatiquement Entry, SL, TP1, TP2, TP3 ;
- calculer le Risk/Reward ;
- attribuer un score de confiance ;
- envoyer les signaux dans un canal Telegram ;
- envoyer des alertes concernant les événements importants ;
- sauvegarder tous les signaux ;
- vérifier automatiquement leurs résultats ;
- produire des statistiques ;
- apprendre progressivement quelles configurations fonctionnent le mieux.

IMPORTANT :

Le système doit d'abord fonctionner en mode ANALYSE / SIGNAL uniquement.

AUCUNE position réelle ne doit être ouverte automatiquement dans la première version.

Préparer néanmoins l'architecture afin qu'un module d'exécution automatique MT5 puisse être ajouté plus tard.

Le système ne doit JAMAIS être obligé de produire un BUY ou SELL.

Il doit pouvoir décider :

NO TRADE
WAIT
WATCH
BUY
SELL

La qualité du signal est plus importante que la quantité des signaux.

==================================================
1. OBJECTIF GLOBAL
==================================================

Créer une plateforme appelée provisoirement :

AI Market Watcher

Le système doit fonctionner comme un analyste financier automatisé surveillant continuellement les marchés.

Exemples de marchés :

BTCUSD
XAUUSD
EURUSD
GBPUSD
USDJPY
ETHUSD
US30
NAS100
SP500

La liste doit être configurable.

Le système doit pouvoir analyser simultanément :

M1
M5
M15
M30
H1
H4
D1

La fréquence d'analyse doit être configurable.

Exemple :

M1 : toutes les 30 secondes ou 1 minute
M5 : à chaque nouvelle bougie
M15 : à chaque nouvelle bougie
H1 : à chaque nouvelle bougie

Ne pas recalculer inutilement toutes les analyses.

==================================================
2. ENVIRONNEMENT TECHNIQUE
==================================================

Backend principal :

Python 3.12+

Utiliser une architecture propre et modulaire.

Framework API :

FastAPI

Interface éventuelle :

React
Vite
TypeScript

Base de données première version :

SQLite

Préparer une abstraction permettant de passer ultérieurement à PostgreSQL.

Connexion trading :

MetaTrader 5 Python API

IA :

1. modèle IA local ;
2. OpenRouter.

Le moteur doit pouvoir utiliser les deux.

Le fournisseur local doit être compatible autant que possible avec une API de type OpenAI.

Support souhaité :

Ollama
LM Studio
LocalAI
serveur OpenAI-compatible personnalisé

Telegram :

Telegram Bot API.

Configuration :

.env
config.yaml

Logs :

logging structuré.

Tests :

pytest.

==================================================
3. CONTRAINTE IMPORTANTE : WINDOWS + MT5
==================================================

MetaTrader 5 tourne sur la machine Windows.

Le backend doit pouvoir communiquer avec le terminal MT5 local installé.

Créer un module robuste permettant :

- connexion MT5 ;
- reconnexion automatique ;
- vérification de connexion ;
- détection terminal fermé ;
- récupération du compte ;
- récupération des symboles ;
- récupération des ticks ;
- récupération OHLC ;
- récupération spread ;
- récupération volume ;
- récupération positions ouvertes ;
- récupération ordres ;
- historique.

Aucun mot de passe MT5 ne doit être écrit directement dans le code source.

==================================================
4. ARCHITECTURE ATTENDUE
==================================================

Créer approximativement cette architecture :

market-watcher/
│
├── backend/
│   │
│   ├── app/
│   │   ├── main.py
│   │   │
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── logging.py
│   │   │   ├── security.py
│   │   │   └── constants.py
│   │   │
│   │   ├── mt5/
│   │   │   ├── connector.py
│   │   │   ├── market_data.py
│   │   │   ├── symbols.py
│   │   │   └── account.py
│   │   │
│   │   ├── analysis/
│   │   │   ├── technical.py
│   │   │   ├── indicators.py
│   │   │   ├── structure.py
│   │   │   ├── price_action.py
│   │   │   ├── volatility.py
│   │   │   ├── volume.py
│   │   │   ├── liquidity.py
│   │   │   ├── support_resistance.py
│   │   │   ├── multi_timeframe.py
│   │   │   └── patterns.py
│   │   │
│   │   ├── intelligence/
│   │   │   ├── local_ai.py
│   │   │   ├── openrouter.py
│   │   │   ├── ai_router.py
│   │   │   ├── prompts.py
│   │   │   └── consensus.py
│   │   │
│   │   ├── news/
│   │   │   ├── collector.py
│   │   │   ├── rss.py
│   │   │   ├── economic_calendar.py
│   │   │   ├── classifier.py
│   │   │   └── impact.py
│   │   │
│   │   ├── sentiment/
│   │   │   ├── analyzer.py
│   │   │   ├── semantic.py
│   │   │   ├── market_sentiment.py
│   │   │   └── telegram_sentiment.py
│   │   │
│   │   ├── telegram/
│   │   │   ├── bot.py
│   │   │   ├── publisher.py
│   │   │   ├── formatter.py
│   │   │   ├── commands.py
│   │   │   └── reader.py
│   │   │
│   │   ├── signals/
│   │   │   ├── engine.py
│   │   │   ├── scoring.py
│   │   │   ├── confirmation.py
│   │   │   ├── levels.py
│   │   │   ├── filters.py
│   │   │   └── lifecycle.py
│   │   │
│   │   ├── risk/
│   │   │   ├── manager.py
│   │   │   ├── position_sizing.py
│   │   │   ├── risk_reward.py
│   │   │   └── protections.py
│   │   │
│   │   ├── backtesting/
│   │   │   ├── engine.py
│   │   │   ├── metrics.py
│   │   │   └── simulator.py
│   │   │
│   │   ├── learning/
│   │   │   ├── signal_tracker.py
│   │   │   ├── performance.py
│   │   │   ├── strategy_stats.py
│   │   │   └── optimizer.py
│   │   │
│   │   ├── scheduler/
│   │   │   ├── scheduler.py
│   │   │   └── jobs.py
│   │   │
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   └── api/
│   │
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
│
│
├── config/
│   ├── config.yaml
│   ├── symbols.yaml
│   └── scoring.yaml
│
├── data/
├── logs/
├── scripts/
├── README.md
└── .gitignore

Cette structure peut être améliorée si nécessaire.

==================================================
5. MARKET DATA ENGINE
==================================================

Créer un moteur qui récupère pour chaque symbole :

bid
ask
spread
tick
OHLC
volume
tick volume
heure serveur
heure locale
état du marché

Récupérer suffisamment de bougies historiques pour analyser correctement chaque timeframe.

Exemple :

1000 à 5000 bougies selon les besoins.

Stocker localement les données utiles afin d'éviter de demander inutilement les mêmes informations à MT5.

==================================================
6. ANALYSE MULTI-TIMEFRAME
==================================================

Le système ne doit JAMAIS analyser M1 isolément.

Pour chaque instrument, analyser plusieurs horizons.

Exemple BTCUSD :

M1
M5
M15
M30
H1
H4
D1

Déterminer pour chaque timeframe :

STRONG BULLISH
BULLISH
NEUTRAL
BEARISH
STRONG BEARISH

Exemple :

M1  : BULLISH
M5  : BULLISH
M15 : BULLISH
H1  : NEUTRAL
H4  : BEARISH
D1  : BEARISH

Créer ensuite un consensus multi-timeframe.

==================================================
7. ANALYSE DE STRUCTURE DU MARCHÉ
==================================================

Identifier automatiquement :

Higher High
Higher Low
Lower High
Lower Low

Détecter :

Break Of Structure
BOS

Change Of Character
CHoCH

Market Structure Shift

trend continuation

trend reversal

range

consolidation

breakout

false breakout

retest

sweep

liquidity grab

compression

expansion

impulse

correction

accumulation

distribution lorsque raisonnablement détectable.

Ne jamais considérer un pattern comme une certitude.

Retourner également un score de confiance.

==================================================
8. SUPPORTS ET RÉSISTANCES
==================================================

Détecter automatiquement :

supports
résistances
zones importantes
swing highs
swing lows
previous high
previous low
day high
day low
week high
week low

Détecter les niveaux testés plusieurs fois.

Utiliser des ZONES plutôt que toujours des prix parfaitement exacts.

==================================================
9. PRICE ACTION
==================================================

Analyser :

taille bougies
corps bougie
mèches
rejets
engulfing
pin bar
inside bar
outside bar
doji
marubozu
momentum candles
breakout candles
indecision
compression

Comparer la bougie actuelle aux bougies précédentes.

Détecter notamment :

forte pression acheteuse
forte pression vendeuse
essoufflement
absorption potentielle
rejet
accélération
ralentissement

==================================================
10. INDICATEURS
==================================================

Implémenter notamment :

EMA
SMA
RSI
MACD
ATR
ADX
Bollinger Bands
Stochastic
VWAP lorsque les données permettent une utilisation correcte

Les indicateurs ne doivent JAMAIS décider seuls d'un trade.

Ils doivent seulement constituer une partie du score global.

==================================================
11. VOLATILITÉ
==================================================

Analyser la volatilité actuelle.

Comparer l'ATR actuel avec son historique.

Classifier :

LOW
NORMAL
HIGH
EXTREME

Détecter les explosions soudaines de volatilité.

Si volatilité EXTREME :

réduire la confiance ;
augmenter les protections ;
ou interdire temporairement un nouveau signal.

==================================================
12. VOLUME
==================================================

Analyser le volume disponible dans MT5.

Si volume réel non disponible, clairement distinguer :

REAL VOLUME
TICK VOLUME

Ne jamais prétendre avoir du volume réel lorsqu'il ne s'agit que de tick volume.

Détecter :

volume croissant
volume décroissant
breakout avec volume
breakout sans volume
divergence prix / volume potentielle

==================================================
13. LIQUIDITÉ
==================================================

Identifier des zones potentielles de liquidité :

equal highs
equal lows
recent highs
recent lows
swing points

Détecter :

liquidity sweep
stop hunt potentiel
breakout puis réintégration

Ne pas utiliser ces notions comme vérité certaine.

==================================================
14. ANALYSE FONDAMENTALE
==================================================

Créer un module séparé.

Pour Forex :

taux directeurs
inflation
emploi
PIB
Fed
BCE
BoE
BoJ
banques centrales
NFP
CPI
PPI
FOMC

Pour crypto :

régulation
ETF
adoption
exchange incidents
hack
stablecoins
institutionnels
activité majeure des marchés

Pour indices :

banques centrales
inflation
résultats entreprises majeures
géopolitique
taux obligataires
dollar
pétrole

Le système doit déterminer :

impact potentiel
direction potentielle
durée potentielle

Exemple :

USD impact : BULLISH
BTC impact : BEARISH
Importance : HIGH

==================================================
15. CALENDRIER ÉCONOMIQUE
==================================================

Le système doit connaître les événements à venir.

Créer une structure :

event
country
currency
datetime
importance
forecast
previous
actual

Importance :

LOW
MEDIUM
HIGH
CRITICAL

Créer un filtre.

Par défaut :

AUCUN nouveau trade quelques minutes avant une annonce HIGH/CRITICAL.

Exemple configurable :

15 minutes avant
15 minutes après.

Pour FOMC/NFP/CPI :

configurable à 30 minutes ou davantage.

==================================================
16. ACTUALITÉS
==================================================

Créer un collecteur utilisant prioritairement des sources gratuites et légales :

RSS
flux publics
sources ouvertes

Éviter les dépendances obligatoires envers des API payantes.

Le système doit :

collecter ;
supprimer les doublons ;
normaliser ;
classifier ;
résumer ;
déterminer les actifs concernés ;
estimer l'importance.

Stocker :

titre
source
date
résumé
actifs concernés
sentiment
importance

==================================================
17. ANALYSE SÉMANTIQUE
==================================================

Utiliser NLP + IA pour comprendre les nouvelles.

Exemple :

"Fed unexpectedly raises rates"

Le système doit comprendre que cela peut :

renforcer USD ;
faire monter les rendements ;
mettre sous pression certains actifs risk-on ;
augmenter la volatilité.

Ne jamais réduire l'analyse au simple comptage de mots positifs/négatifs.

==================================================
18. SENTIMENT ANALYSIS
==================================================

Créer un score :

-100 = extrêmement baissier
0 = neutre
+100 = extrêmement haussier

Calculer éventuellement :

news sentiment
social sentiment si disponible
Telegram sentiment
market sentiment

Retourner :

direction
score
confiance
sources principales

==================================================
19. TELEGRAM : LECTURE DE SIGNAUX EXTERNES
==================================================

Prévoir un module OPTIONNEL permettant d'analyser des messages Telegram accessibles légalement au compte/bot configuré.

Exemple :

BUY BTCUSD
Entry 77200
SL 76900
TP 78000

Le système doit extraire :

symbole
direction
entry
stop loss
take profits
source
date

IMPORTANT :

Un signal Telegram externe ne doit JAMAIS être copié automatiquement.

Il doit être analysé.

Comparer le signal avec :

structure marché
tendance
news
sentiment
volatilité
risk/reward

Décision :

ACCEPT
REJECT
WAIT
PARTIAL CONFIRMATION

==================================================
20. IA HYBRIDE : LOCAL + OPENROUTER
==================================================

J'ai :

- un modèle IA local ;
- OpenRouter.

Le système doit pouvoir utiliser les deux ensemble.

Créer :

AIProvider
LocalAIProvider
OpenRouterProvider
AIRouter

La logique doit être configurable.

Exemple :

Analyse technique fréquente :
LOCAL AI

Analyse complexe d'une actualité :
OpenRouter

Deuxième opinion :
OpenRouter

Fallback si OpenRouter indisponible :
Local AI

Fallback si modèle local indisponible :
OpenRouter si autorisé.

Créer un mode :

LOCAL_ONLY
OPENROUTER_ONLY
HYBRID
AUTO

==================================================
21. CONSENSUS IA
==================================================

Lorsque nécessaire :

analyse déterministe
+
IA locale
+
OpenRouter

doivent produire plusieurs avis.

Exemple :

Technical Engine : BUY
Local AI : BUY
OpenRouter : WAIT

Consensus :

BUY MODERATE CONFIDENCE

L'IA ne doit pas pouvoir remplacer les règles critiques du Risk Manager.

==================================================
22. IMPORTANT : NE PAS LAISSER LE LLM INVENTER LES PRIX
==================================================

Les niveaux Entry, SL et TP doivent être calculés principalement avec les données de marché.

L'IA peut commenter ou évaluer les niveaux.

Elle ne doit pas inventer un prix absent des données.

Tous les niveaux doivent être validés contre :

prix actuel
spread
ATR
structure
support/résistance
distance minimum broker
risk/reward

==================================================
23. SIGNAL ENGINE
==================================================

Créer un moteur final qui transforme toutes les analyses en décision.

Décisions possibles :

STRONG BUY
BUY
WATCH BUY
WAIT
NO TRADE
WATCH SELL
SELL
STRONG SELL

==================================================
24. SYSTÈME DE SCORE
==================================================

Créer un score global sur 100.

Exemple :

Market structure        /20
Multi timeframe         /15
Momentum                /10
Support/Resistance      /10
Volume                  /5
Volatility              /5
Technical indicators    /10
Sentiment               /10
Fundamental             /10
Risk/Reward             /5

TOTAL                    /100

Les pondérations doivent être configurables.

Exemple :

0-49 :
NO TRADE

50-59 :
WATCH

60-69 :
WEAK SIGNAL

70-79 :
VALID SIGNAL

80-89 :
STRONG SIGNAL

90-100 :
EXCEPTIONAL SETUP

Ne jamais garantir le succès.

==================================================
25. CONFIRMATIONS
==================================================

Un signal BUY doit par exemple pouvoir nécessiter :

structure bullish
+
timeframes compatibles
+
Entry logique
+
SL valide
+
Risk/Reward suffisant
+
absence d'annonce dangereuse
+
spread acceptable
+
volatilité acceptable

Un seul indicateur ne doit pas suffire.

==================================================
26. CALCUL DE ENTRY
==================================================

Prévoir plusieurs types d'entrée :

MARKET
LIMIT
STOP
BREAKOUT
RETEST

Exemple :

breakout détecté à 77340

Le système peut choisir :

BUY STOP 77345

ou attendre un retest.

Retourner :

entry_type
entry_price
reason

==================================================
27. STOP LOSS
==================================================

Le SL doit être calculé selon :

structure
swing high/low
ATR
volatilité
support/resistance
spread

Éviter les SL arbitraires.

Le système doit expliquer :

SL sous dernier swing low
SL au-dessus résistance
SL = X ATR

==================================================
28. TAKE PROFITS
==================================================

Créer :

TP1
TP2
TP3

Utiliser :

support/résistance
liquidity levels
ATR
Risk/Reward

Exemple :

TP1 = 1R
TP2 = 2R
TP3 = 3R

Mais privilégier les véritables zones techniques lorsqu'elles existent.

==================================================
29. RISK / REWARD
==================================================

Calculer automatiquement :

Risk
Reward TP1
Reward TP2
Reward TP3

et :

RR1
RR2
RR3

Exemple :

RR1 1:1
RR2 1:2
RR3 1:3

Le minimum acceptable doit être configurable.

Exemple :

minimum RR = 1.5

==================================================
30. RISK MANAGER
==================================================

C'est le module le plus important.

Il peut REFUSER un signal même si l'IA veut trader.

Vérifier :

spread
volatilité
news imminente
RR
confiance
corrélation
duplicate signal
signal trop récent
marché fermé
données insuffisantes
connexion instable

Retourner :

APPROVED
REJECTED
WAIT

avec raison.

==================================================
31. ANTI-SPAM / ANTI-DUPLICATE
==================================================

Ne pas envoyer :

BUY BTCUSD

toutes les minutes.

Détecter que le signal précédent est toujours actif.

Créer un cycle :

CREATED
CONFIRMED
ACTIVE
TP1_HIT
TP2_HIT
TP3_HIT
SL_HIT
INVALIDATED
EXPIRED
CANCELLED

==================================================
32. SIGNAL LIFECYCLE
==================================================

Après publication d'un signal :

continuer à le suivre.

Exemple :

09:00
BUY BTCUSD

09:25
TP1 HIT ✅

10:10
TP2 HIT ✅

11:03
TP3 HIT ✅

ou :

09:30
Signal invalidated ❌

ou :

SL HIT ❌

Envoyer éventuellement les mises à jour sur Telegram.

==================================================
33. FORMAT TELEGRAM PRINCIPAL
==================================================

Créer un format propre :

🚨 BTCUSD SIGNAL

BUY BTCUSD

Entry: 77 345
SL: 77 260

TP1: 77 430
TP2: 77 515
TP3: 77 600

Confidence: 78/100

Timeframes:
M1  🟢
M5  🟢
M15 🟢
H1  🟡
H4  🟡

Risk/Reward:
TP1 1:1
TP2 1:2
TP3 1:3

Technical:
• bullish structure
• resistance broken
• momentum increasing
• retest confirmed

Sentiment:
🟢 Bullish

Fundamental:
🟡 Neutral

Risk:
🟡 Moderate

Invalidation:
Price closes below 77 260

Generated:
2026-XX-XX XX:XX

Le format exact doit être configurable.

==================================================
34. FORMAT SIMPLE DEMANDÉ
==================================================

Créer également un mode minimal :

BUY BTCUSD
Entry 77205
SL 76819
TP1 77591
TP2 77977
TP3 78363

Permettre :

telegram_format = simple

ou

telegram_format = detailed

==================================================
35. WATCH ALERT
==================================================

Lorsque le signal n'est pas confirmé :

👀 BTCUSD WATCH

Current:
77320

Important resistance:
77340

BUY confirmation:
> 77345

SELL confirmation:
< 77260

Decision:
WAIT

Confidence:
62%

==================================================
36. NEWS ALERT
==================================================

Envoyer également :

⚠️ MARKET ALERT

Asset:
BTCUSD / USD

Event:
US CPI

Importance:
CRITICAL

Time:
14:30

Expected volatility:
HIGH

Decision:
New trades temporarily disabled.

==================================================
37. BREAKING NEWS
==================================================

Lorsque le système détecte une actualité très importante :

🚨 BREAKING MARKET NEWS

Headline:
...

Affected:
USD
BTCUSD
XAUUSD
NAS100

Estimated impact:
HIGH

Sentiment:
Risk-off

Le système doit éviter les alertes inutiles.

==================================================
38. BASE DE DONNÉES
==================================================

Créer les tables nécessaires.

Notamment :

symbols
market_data
analyses
signals
signal_targets
signal_events
news
sentiment
economic_events
ai_requests
ai_responses
telegram_messages
strategies
performance_stats
settings

==================================================
39. SIGNAL HISTORY
==================================================

Pour chaque signal conserver :

ID
symbol
direction
timestamp
entry
SL
TP1
TP2
TP3
score
technical_score
sentiment_score
fundamental_score
risk_score
RR
reason
market context
AI analysis
result

==================================================
40. PERFORMANCE TRACKING
==================================================

Calculer :

win rate
loss rate
breakeven
average RR
profit factor simulé
max losing streak
max winning streak
performance par symbole
performance par timeframe
performance par heure
performance par jour
performance par type de setup

==================================================
41. APPRENTISSAGE PAR L'HISTORIQUE
==================================================

Le système doit pouvoir découvrir :

Breakout + volume + H1 bullish
= 72% réussite historique

RSI oversold seul
= 43%

EMA crossover + H1 confirmation
= 63%

Ne PAS modifier automatiquement les stratégies en production sans validation.

Créer des recommandations :

"augmenter poids de X"
"réduire poids de Y"

mais conserver validation humaine.

==================================================
42. BACKTESTING
==================================================

Créer un moteur de backtest.

Permettre :

symbol
date_from
date_to
timeframe
strategy
initial_balance

Calculer :

trades
wins
losses
win rate
profit factor
drawdown
expectancy
average RR

IMPORTANT :

éviter le look-ahead bias.

Le backtesting ne doit jamais utiliser des données futures pour créer un signal passé.

==================================================
43. PAPER TRADING
==================================================

Ajouter un mode :

paper_trading = true

Simuler les ordres sans toucher au compte réel.

Enregistrer :

entry
SL
TP
result

C'est ce mode qui doit être utilisé pour la validation initiale.

==================================================
44. FUTUR MODULE AUTO-TRADING
==================================================

Préparer mais NE PAS ACTIVER PAR DÉFAUT :

execution/
    executor.py
    mt5_orders.py

Prévoir :

ENABLE_LIVE_TRADING=false

Même si quelqu'un modifie le code, ajouter plusieurs protections avant activation.

Par exemple :

ENABLE_LIVE_TRADING=true
ACKNOWLEDGE_LIVE_RISK=true
ACCOUNT_ALLOWLIST=...

Ne pas ouvrir de position réelle durant le développement initial.

==================================================
45. DASHBOARD WEB
==================================================

Créer une interface React moderne.

Pages :

Dashboard
Markets
Signals
Active Signals
News
Economic Calendar
Performance
Backtests
Telegram
AI
Settings
Logs

Dashboard :

MT5 connected
Local AI connected
OpenRouter connected
Telegram connected

Symbols monitored

active signals
today signals
win rate
market risk

==================================================
46. PAGE MARKETS
==================================================

Afficher :

symbol
price
spread
trend
score
M1
M5
M15
H1
H4
sentiment
risk
last update

Possibilité d'ouvrir une fiche complète.

==================================================
47. FICHE MARCHÉ
==================================================

Afficher :

prix
bougies
timeframes
supports
resistances
structure
indicators
sentiment
news
economic events
current analysis
possible scenarios

Exemple :

Bullish scenario
Bearish scenario
No-trade zone

==================================================
48. PAGE SIGNALS
==================================================

Afficher :

symbol
BUY/SELL
entry
SL
TP
confidence
status
created at
result

Filtres :

symbol
direction
date
status
score

==================================================
49. PAGE PERFORMANCE
==================================================

Afficher :

global win rate
par marché
par timeframe
par setup
par heure
par jour

Graphiques propres.

==================================================
50. PAGE IA
==================================================

Afficher :

Local AI:
status
model
endpoint

OpenRouter:
status
model

Mode :

LOCAL_ONLY
OPENROUTER_ONLY
HYBRID
AUTO

Afficher statistiques :

requests
errors
latency

Ne jamais afficher la clé API complète.

==================================================
51. PARAMÈTRES
==================================================

Permettre de configurer :

symbols
timeframes
Telegram
OpenRouter
Local AI
scores
RR
news filters
economic calendar filters
analysis frequency
signal thresholds

==================================================
52. FICHIER ENV
==================================================

Créer :

.env.example

Exemple :

MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=

OPENROUTER_API_KEY=
OPENROUTER_MODEL=

LOCAL_AI_BASE_URL=
LOCAL_AI_MODEL=

DATABASE_URL=sqlite:///...

ENABLE_LIVE_TRADING=false

Ne jamais versionner .env.

==================================================
53. CONFIGURATION YAML
==================================================

Exemple :

symbols:
  - BTCUSD
  - XAUUSD
  - EURUSD

timeframes:
  - M1
  - M5
  - M15
  - H1
  - H4

signals:
  minimum_score: 70
  minimum_rr: 1.5

risk:
  block_high_impact_news: true
  before_news_minutes: 15
  after_news_minutes: 15

telegram:
  send_watch_alerts: true
  send_news_alerts: true
  send_signal_updates: true

==================================================
54. SCHEDULER
==================================================

Créer un ordonnanceur robuste.

Jobs :

market update
M1 analysis
M5 analysis
M15 analysis
H1 analysis
news update
economic calendar update
signal tracker
performance calculation

Chaque tâche doit être indépendante.

Une erreur d'un job ne doit pas arrêter tout le système.

==================================================
55. GESTION DES ERREURS
==================================================

Prévoir :

MT5 disconnected
internet lost
OpenRouter unavailable
local AI unavailable
Telegram unavailable
database locked
invalid market data
rate limit
timeout

Le système doit continuer à fonctionner autant que possible.

==================================================
56. RECONNEXION AUTOMATIQUE
==================================================

Implémenter exponential backoff.

Exemple :

1 sec
2 sec
5 sec
10 sec
30 sec
60 sec

Puis continuer périodiquement.

==================================================
57. LOGGING
==================================================

Créer plusieurs niveaux :

DEBUG
INFO
WARNING
ERROR
CRITICAL

Logs :

logs/app.log
logs/mt5.log
logs/signals.log
logs/ai.log
logs/telegram.log

Rotation automatique.

==================================================
58. SÉCURITÉ
==================================================

Ne jamais logger :

mot de passe
Telegram token
OpenRouter key

Masquer les secrets.

Ajouter .gitignore approprié.

==================================================
59. API FASTAPI
==================================================

Créer notamment :

GET /health

GET /markets

GET /markets/{symbol}

GET /signals

GET /signals/active

GET /signals/{id}

GET /news

GET /economic-calendar

GET /performance

POST /analysis/{symbol}

POST /backtest

GET /settings

PUT /settings

Créer documentation Swagger automatiquement.

==================================================
60. HEALTH CHECK
==================================================

GET /health

doit retourner :

{
  "backend": "ok",
  "database": "ok",
  "mt5": "connected",
  "telegram": "connected",
  "local_ai": "connected",
  "openrouter": "connected"
}

==================================================
61. TESTS
==================================================

Créer des tests unitaires.

Tester notamment :

calcul RSI
ATR
market structure
support/resistance
score
Risk/Reward
SL/TP
signal formatting
duplicate filtering

Mock MT5 et Telegram.

Les tests ne doivent pas envoyer de vrais messages pendant les tests.

==================================================
62. MODE DRY RUN
==================================================

Créer :

DRY_RUN=true

Ce mode :

analyse tout ;
génère des signaux ;
les sauvegarde ;

mais ne publie pas forcément Telegram selon config.

==================================================
63. MODE DEMO
==================================================

Créer :

TRADING_MODE=DEMO

Le projet doit être testé initialement uniquement avec un compte MT5 DEMO.

==================================================
64. RÈGLE CRITIQUE POUR L'IA
==================================================

Les LLM ne sont PAS la source de vérité.

Les données de prix sont la source de vérité.

Le pipeline doit être :

REAL MARKET DATA
→ deterministic analysis
→ statistical analysis
→ context/news
→ AI interpretation
→ Risk Manager
→ signal decision

et NON :

"Demander à ChatGPT s'il faut acheter."

==================================================
65. AUCUNE HALLUCINATION
==================================================

Si une donnée manque :

retourner UNKNOWN.

Exemple :

ETF flows unavailable

=> ne pas inventer ETF flows.

News unavailable

=> Fundamental confidence réduite.

==================================================
66. QUALITÉ DES DONNÉES
==================================================

Chaque analyse doit connaître :

data freshness
number candles
missing candles
timestamp

Refuser ou dégrader un signal lorsque les données sont anciennes.

==================================================
67. HORODATAGE
==================================================

Stocker les dates en UTC dans la base.

Convertir seulement pour affichage.

Afficher heure locale configurable.

==================================================
68. SCÉNARIOS FUTURS
==================================================

Pour chaque marché, générer éventuellement :

Bullish scenario
Bearish scenario
Neutral scenario

Exemple :

Bullish:
break above 77340
targets 77420 / 77500

Bearish:
break below 77260
targets 77200 / 77150

Neutral:
77260-77340 range

Ces scénarios doivent provenir des niveaux calculés.

==================================================
69. SURVEILLANCE CONTINUE
==================================================

Si le système détecte une situation presque valide :

mettre le marché en WATCH.

Exemple :

BTCUSD WATCH
Score 66

Attente :
Break 77340

Quand le prix atteint la confirmation :

recalculer toute l'analyse.

Ne pas transformer automatiquement WATCH → BUY sans nouvelle validation.

==================================================
70. NOTIFICATIONS MOBILES
==================================================

Telegram servira de système de notification mobile.

Envoyer :

nouveau signal
TP atteint
SL atteint
signal invalidé
breaking news
annonce économique
MT5 déconnecté si panne longue
MT5 reconnecté
erreur critique

Éviter le spam.

==================================================
71. COMMANDES TELEGRAM
==================================================

Créer éventuellement :

/status
/markets
/btcusd
/xauusd
/signals
/active
/performance
/news
/risk

Exemple :

/btcusd

retourne analyse actuelle BTCUSD.

==================================================
72. SOURCES EXTERNES
==================================================

Priorité aux solutions gratuites.

Le projet ne doit pas nécessiter une API payante pour fonctionner dans sa version de base.

OpenRouter reste configurable.

Pour les actualités et calendriers :

prévoir des interfaces abstraites afin de pouvoir changer de fournisseur.

==================================================
73. OPTIMISATION DES COÛTS IA
==================================================

Ne pas envoyer chaque tick à l'IA.

Faire :

calculs techniques localement ;
filtrage local ;
IA uniquement lorsque utile.

Exemple :

Score déterministe < 50
=> pas d'appel LLM.

Score > 60
=> demander analyse IA.

Cela évite les appels inutiles.

==================================================
74. CACHE IA
==================================================

Pour les news identiques :

éviter de demander plusieurs fois à l'IA.

Hasher les articles.

Sauvegarder analyse.

==================================================
75. PROMPT IA STRUCTURÉ
==================================================

Exiger des réponses JSON.

Exemple :

{
  "bias": "BULLISH",
  "confidence": 72,
  "fundamental_impact": "NEUTRAL",
  "sentiment": 16,
  "risks": [],
  "reasoning_summary": "...",
  "recommendation": "WAIT"
}

Valider le JSON avec Pydantic.

Si réponse invalide :

retry limité.

==================================================
76. PAS DE CHAÎNE DE PENSÉE
==================================================

Ne pas demander au modèle d'enregistrer une chaîne de pensée privée.

Demander seulement :

résumé des facteurs
arguments principaux
risques
résultat structuré

==================================================
77. PERFORMANCE
==================================================

Le système doit pouvoir surveiller plusieurs marchés sans bloquer.

Utiliser async lorsque pertinent.

Mais MT5 pouvant avoir des contraintes synchrones, isoler correctement ses appels.

Éviter les race conditions.

==================================================
78. LOCK PAR SYMBOLE
==================================================

Empêcher deux analyses complètes simultanées du même symbole.

Créer un lock.

==================================================
79. VERSIONING DES STRATÉGIES
==================================================

Chaque signal doit garder :

strategy_version

Exemple :

market_engine_v1.0

Pour comparer les performances après modification.

==================================================
80. EXPLICATION DES DÉCISIONS
==================================================

Chaque signal doit être explicable.

Exemple :

BUY approved because:

+ M5 bullish
+ M15 bullish
+ resistance breakout
+ volume confirmation
+ RR 2.4
+ no critical news

Risks:

- H4 neutral
- volatility above average

==================================================
81. SCORE DE CONFIANCE
==================================================

Le score de confiance n'est PAS une probabilité de gagner.

Ne jamais afficher :

"78% de chance de gagner"

si aucune calibration statistique réelle ne le prouve.

Afficher :

Confidence Score: 78/100

==================================================
82. CALIBRATION FUTURE
==================================================

Après suffisamment de données historiques, permettre de comparer :

score 70-75
résultat réel

score 75-80
résultat réel

etc.

Cela permettra éventuellement de calibrer de vraies probabilités.

==================================================
83. DOCUMENTATION
==================================================

Créer README complet :

installation Python
création environnement
installation dépendances
installation MT5
configuration compte DEMO
création bot Telegram
création canal Telegram
configuration bot admin
configuration OpenRouter
configuration IA locale
lancement backend
lancement frontend
tests
troubleshooting

==================================================
84. INSTALLATION SIMPLE WINDOWS
==================================================

Créer :

scripts/setup_windows.ps1

si possible.

Puis :

scripts/start_backend.ps1
scripts/start_frontend.ps1

et éventuellement :

start_all.ps1

==================================================
85. DÉVELOPPEMENT PAR PHASE
==================================================

Ne tente pas de tout coder dans un énorme fichier.

PHASE 1

Architecture
Configuration
DB
MT5 connector

PHASE 2

Market Data
Indicators
Technical Analysis

PHASE 3

Market Structure
Price Action
Multi-Timeframe

PHASE 4

Signal Engine
Risk Manager
Entry/SL/TP

PHASE 5

Telegram publishing

PHASE 6

News
Fundamental
Semantic
Sentiment

PHASE 7

Local AI
OpenRouter
Hybrid Consensus

PHASE 8

Signal tracking
Statistics
Backtesting

PHASE 9

React Dashboard

PHASE 10

Optimisation
Tests
Documentation

==================================================
86. À CHAQUE PHASE
==================================================

Avant de coder :

1. analyser ce qui existe ;
2. expliquer brièvement ce qui va être fait ;
3. identifier les fichiers concernés ;
4. coder ;
5. tester ;
6. corriger les erreurs ;
7. ne pas casser les modules existants.

==================================================
87. INTERDICTION DE FAUSSE IMPLÉMENTATION
==================================================

Je ne veux pas :

TODO partout
fake data
boutons non fonctionnels
fonctions vides
retours statiques prétendant fonctionner.

Si une fonction n'est pas encore implémentée :

le dire explicitement.

==================================================
88. RÉSULTAT ATTENDU
==================================================

À la fin, je dois pouvoir faire :

1.

Lancer MT5.

2.

Lancer :

start_all.ps1

3.

Le backend se connecte à MT5.

4.

Il surveille BTCUSD et autres actifs.

5.

Il analyse les timeframes.

6.

Il récupère actualités et événements disponibles.

7.

Il calcule un score.

8.

Il décide :

BUY
SELL
WAIT
NO TRADE

9.

Si signal validé :

Telegram reçoit :

BUY BTCUSD
Entry XXXXX
SL XXXXX
TP1 XXXXX
TP2 XXXXX
TP3 XXXXX

10.

Le programme continue ensuite à surveiller le signal.

11.

Il enregistre si :

TP1 atteint
TP2 atteint
TP3 atteint
SL atteint
signal invalidé.

12.

Les statistiques deviennent visibles dans le dashboard.

==================================================
89. EXEMPLE FINAL
==================================================

Données :

BTCUSD
Price 77320

Structure :
Bullish

M1:
Bullish

M5:
Bullish

M15:
Bullish

H1:
Neutral

Resistance:
77340

Support:
77260

News:
No critical immediate event

Score:
73

Décision actuelle :

WATCH

Puis :

BTCUSD casse 77345.

Le système recalcule.

Score:
81

Décision :

BUY

Résultat :

BUY BTCUSD
Entry 77345
SL 77260
TP1 77430
TP2 77515
TP3 77600

Puis publier Telegram.

==================================================
90. PRIORITÉS ABSOLUES
==================================================

Dans cet ordre :

1. sécurité ;
2. qualité des données ;
3. Risk Manager ;
4. robustesse ;
5. fiabilité des signaux ;
6. explicabilité ;
7. performance ;
8. interface graphique.

Une belle interface avec une mauvaise logique de trading est inutile.

==================================================
91. COMMENCE MAINTENANT
==================================================

Commence par :

- inspecter le projet existant s'il existe ;
- ne supprimer aucun fichier utile ;
- créer l'architecture ;
- créer requirements ;
- créer config ;
- créer .env.example ;
- créer la base SQLite ;
- implémenter le connecteur MetaTrader 5 ;
- créer un endpoint /health ;
- tester réellement la connexion ;
- puis continuer progressivement.

Si quelque chose nécessite une clé, un token, un login ou une décision de ma part :

prépare tout le code possible avant de me demander cette information.

Ne bloque pas tout le développement pour une seule configuration manquante.

Ne me demande pas de confirmer chaque fichier.

Travaille comme un véritable ingénieur responsable du projet.

Continue jusqu'à obtenir une version réellement exécutable.


==================================================
FIN DU PROMPT
==================================================