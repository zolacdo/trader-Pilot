Tu travailles sur un projet EXISTANT nommé TradePilot.

IMPORTANT :

Ne recommence PAS le projet depuis zéro.

Commence par analyser entièrement le dépôt actuel :

* application Flutter ;
* Bridge Python ;
* MT5 ;
* Exness ;
* Telegram ;
* OpenRouter ;
* modèle IA local existant ou à configurer ;
* Risk Manager ;
* base de données ;
* WebSocket ;
* fonctionnalités existantes ;
* tests ;
* documentation.

Préserve tout ce qui fonctionne déjà.

Cette tâche est une MISE À JOUR MAJEURE destinée à transformer TradePilot en système d’intelligence de marché autonome capable de :

1. surveiller les marchés ;
2. analyser plusieurs sources de données ;
3. suivre l’actualité économique, financière et mondiale ;
4. analyser plusieurs timeframes ;
5. rechercher des situations historiques similaires ;
6. analyser les signaux Telegram ;
7. produire ses propres opportunités BUY/SELL ;
8. évaluer chaque opportunité ;
9. décider BUY / SELL / WAIT / IGNORE ;
10. utiliser intelligemment un modèle IA local ET OpenRouter ;
11. soumettre les décisions au Risk Manager ;
12. prendre automatiquement les positions autorisées sur Exness MT5 ;
13. notifier immédiatement l’utilisateur sur son téléphone Android ;
14. conserver un journal extrêmement détaillé expliquant chaque décision.

L’application Flutter reste la SEULE interface utilisateur.

Le Bridge reste un backend SANS interface graphique.

Architecture :

Flutter Android
⇅
API sécurisée / WebSocket / Push
⇅
Bridge Python
│
├── Telegram
├── IA locale
├── OpenRouter
├── AI Router
├── Market Data
├── News
├── Economic Calendar
├── Historical Analysis
├── Market Intelligence
├── Decision Engine
├── Risk Manager
└── MetaTrader 5 Desktop
↓
Exness

# 1. OBJECTIF DE CETTE MISE À JOUR

TradePilot ne doit plus uniquement copier des signaux Telegram.

Telegram devient UNE SOURCE D’INFORMATION parmi plusieurs.

TradePilot doit être capable de générer ses propres opportunités à partir :

* prix en temps réel ;
* données MT5 ;
* données historiques ;
* plusieurs timeframes ;
* structure du marché ;
* volatilité ;
* momentum ;
* tendances ;
* supports/résistances ;
* corrélations ;
* indices ;
* devises ;
* métaux ;
* matières premières ;
* marchés actions lorsque les instruments sont accessibles ;
* actualités économiques ;
* banques centrales ;
* événements macroéconomiques ;
* actualités financières ;
* événements géopolitiques ;
* signaux Telegram ;
* historique des décisions du système ;
* analyse IA locale ;
* analyse OpenRouter.

Le système doit ensuite construire une conviction mesurable.

Exemple :

XAUUSD

Technical       86/100
Market Regime   91/100
Historical      78/100
Macro           72/100
News            65/100
Cross Market    84/100
Telegram        76/100

Global Confidence

81/100

Decision :

BUY

MAIS :

le Risk Manager garde TOUJOURS le droit de veto.

# 2. RÈGLE FONDAMENTALE

Ne jamais programmer le système avec l’idée :

“L’IA doit obligatoirement trouver un trade.”

La bonne décision peut être :

WAIT

ou :

NO TRADE.

Le système doit pouvoir rester plusieurs heures sans ouvrir de position.

La priorité est la qualité des setups, pas la quantité de trades.

# 3. NOUVELLE ARCHITECTURE DU BRIDGE

Ajouter au Bridge des modules propres.

Exemple :

services/
├── market_data/
├── market_scanner/
├── technical_analysis/
├── market_regime/
├── historical_patterns/
├── macro/
├── economic_calendar/
├── news/
├── cross_market/
├── telegram_intelligence/
├── ai/
│   ├── local/
│   ├── openrouter/
│   ├── router/
│   ├── ensemble/
│   └── evaluation/
├── opportunities/
├── decision/
├── confidence/
├── strategies/
├── risk/
├── trading/
├── notifications/
└── learning/

Adapter cette structure à l’architecture existante.

Ne pas créer des fichiers monolithiques énormes.

# 4. ARCHITECTURE IA HYBRIDE

TradePilot dispose de DEUX sources d’intelligence artificielle :

1. un modèle IA LOCAL ;
2. OpenRouter.

Les deux doivent pouvoir fonctionner :

* séparément ;
* en fallback ;
* en cascade ;
* en parallèle lorsque pertinent.

Créer :

AIProvider

avec au minimum :

LocalAIProvider
OpenRouterAIProvider.

Puis créer :

AIRouter.

Le AIRouter décide quel moteur utiliser selon :

* type de tâche ;
* capacités nécessaires ;
* disponibilité ;
* latence ;
* coût ;
* confidentialité ;
* taille du contexte ;
* besoin vision ;
* besoin raisonnement avancé ;
* fiabilité récente du provider.

# 5. RÔLE DU MODÈLE IA LOCAL

Le modèle local doit être utilisé en priorité lorsque ses capacités suffisent.

Utilisations privilégiées :

* classification simple ;
* parsing Telegram ;
* extraction structurée ;
* résumé court ;
* classification de news ;
* détection d’entités ;
* sentiment simple ;
* reformulation ;
* explication locale ;
* préfiltrage des news ;
* scoring préliminaire ;
* détection de doublons sémantiques ;
* génération de résumé du marché ;
* analyse contextuelle légère.

Avantages :

* gratuit ;
* pas de quota externe ;
* confidentialité ;
* faible latence locale ;
* fonctionnement même si OpenRouter tombe.

# 6. CONFIGURATION DU MODÈLE LOCAL

Ne pas supposer une technologie unique.

Créer une architecture compatible avec plusieurs moteurs locaux.

Prévoir des adaptateurs possibles :

Ollama
LM Studio
OpenAI-compatible local server
llama.cpp server
autre endpoint local compatible.

Configuration :

Local AI Enabled
ON/OFF

Provider type

Base URL

Model name

API key facultative si nécessaire

Timeout

Context size

Supports JSON

Supports tools

Supports vision

Test Connection.

Exemple d’endpoint possible :

http://127.0.0.1:11434

Mais ne pas coder cette valeur en dur.

# 7. LOCAL AI DISCOVERY

Lorsque le provider le permet :

récupérer la liste des modèles locaux disponibles.

Afficher dans Flutter :

Modèles locaux détectés.

Exemple :

Model A
Text
Context ...
Status READY

Model B
Vision
Status READY.

Permettre de choisir :

* modèle texte local ;
* modèle vision local ;
* mode automatique.

# 8. OPENROUTER

Conserver l’intégration OpenRouter actuelle.

Ne pas supprimer le système de sélection dynamique des modèles gratuits.

Le système doit :

1. détecter les modèles gratuits disponibles ;
2. choisir le meilleur modèle compatible ;
3. préférer le modèle configuré s’il est encore gratuit et accessible ;
4. sélectionner un fallback gratuit ;
5. ne JAMAIS basculer automatiquement vers un modèle payant.

Si aucun modèle gratuit n’est disponible :

le reste de TradePilot doit continuer.

Les fonctions dépendantes d’OpenRouter passent en :

OPENROUTER_UNAVAILABLE.

# 9. STRATÉGIES DE ROUTAGE IA

Créer plusieurs modes configurables.

LOCAL_ONLY

Utiliser uniquement le modèle local.

OPENROUTER_ONLY

Utiliser uniquement OpenRouter.

LOCAL_FIRST

Local d’abord.
OpenRouter seulement si :

* local échoue ;
* confiance insuffisante ;
* JSON invalide ;
* capacité manquante.

OPENROUTER_FIRST

OpenRouter d’abord puis local en fallback.

AUTO

AIRouter choisit automatiquement.

ENSEMBLE

Les deux modèles analysent indépendamment certains cas critiques.

# 10. MODE AUTO RECOMMANDÉ

Par défaut :

AUTO.

Règles proposées :

Parsing simple Telegram :
LOCAL.

News classification :
LOCAL.

Résumé standard :
LOCAL.

Extraction structurée :
LOCAL si fiable.

Vision :
modèle capable disponible.

Analyse macro complexe :
OpenRouter lorsque nécessaire.

Synthèse de plusieurs centaines d’éléments :
provider ayant la capacité de contexte suffisante.

Analyse incertaine :
LOCAL + OpenRouter.

Décision potentiellement tradable importante :
possibilité d’utiliser ENSEMBLE.

# 11. MODE ENSEMBLE

Créer :

AIEnsembleService.

Il peut demander séparément :

Local Model
et
OpenRouter

de produire une analyse structurée.

Exemple :

Local :

Direction:
BUY

Confidence:
0.78

OpenRouter :

Direction:
BUY

Confidence:
0.82

Résultat :

CONSENSUS BUY.

Autre exemple :

Local :
BUY

OpenRouter :
SELL

Résultat :

AI_DISAGREEMENT.

Pour une décision financière sensible :

AI_DISAGREEMENT doit normalement conduire à :

NEEDS_REVIEW

ou

NO_TRADE

selon la configuration.

Ne jamais faire une moyenne aveugle entre BUY et SELL.

# 12. AI CONSENSUS ENGINE

Créer :

AIConsensusEngine.

Résultats possibles :

CONSENSUS
PARTIAL_CONSENSUS
DISAGREEMENT
INSUFFICIENT_DATA
PROVIDER_UNAVAILABLE.

Conserver :

* réponse locale ;
* réponse OpenRouter ;
* scores ;
* latences ;
* provider ;
* modèle ;
* timestamp.

Ne jamais stocker les chain-of-thought internes.

Stocker uniquement les sorties structurées et explications synthétiques.

# 13. AI CONFIDENCE

Chaque provider peut produire :

providerConfidence.

Mais cette confiance ne doit pas être acceptée telle quelle.

Créer une confidence recalibrée à partir de :

* validation structurée ;
* historique du provider ;
* accord entre providers ;
* données déterministes ;
* cohérence avec le marché.

Exemple :

Local confidence:
90 %

mais contradiction avec données techniques.

Final AI confidence :
55 %.

# 14. ÉVALUATION DES MODÈLES

Créer des métriques pour chaque modèle :

* parsing success rate ;
* valid JSON rate ;
* latency ;
* timeout rate ;
* disagreement rate ;
* Telegram extraction accuracy ;
* News classification accuracy ;
* signal hallucination rate.

Permettre à AIRouter d’utiliser ces métriques.

# 15. INTERDICTION D’HALLUCINATION

Aucun modèle ne peut inventer :

* Entry ;
* SL ;
* TP ;
* symbole ;
* direction ;
* donnée économique ;
* news ;
* prix ;
* date.

Toute valeur utilisée pour trader doit être vérifiée par données déterministes.

# 16. MARKET DATA ENGINE

MetaTrader 5 doit rester la première source pour les données de marché disponibles.

Récupérer :

* BID ;
* ASK ;
* OHLC ;
* spread ;
* volume disponible ;
* tick volume ;
* ticks lorsque pertinent ;
* ATR ;
* historique ;
* état du marché ;
* metadata du symbole.

Supporter au minimum :

M1
M5
M15
M30
H1
H4
D1
W1

Prévoir MN1 lorsque disponible.

Ne pas récupérer inutilement des millions de bougies.

Mettre en cache.

Stocker ce qui est réellement utile aux analyses historiques.

# 17. WATCHLIST

Créer une vraie Watchlist.

L’utilisateur choisit les instruments que TradePilot peut observer.

Exemples :

XAUUSD
EURUSD
GBPUSD
USDJPY
AUDUSD
USDCAD
USDCHF

US30
US100
SPX500

BTCUSD

WTI

selon les symboles réellement disponibles dans son compte Exness MT5.

Ne jamais supposer que tous ces instruments sont disponibles.

Interroger MT5.

# 18. MARKET SCANNER

Créer un MarketScanner.

Il analyse régulièrement tous les instruments autorisés.

Pour chaque instrument produire :

* tendance ;
* volatilité ;
* momentum ;
* structure ;
* support/résistance ;
* changement de régime ;
* anomalie ;
* potentiel setup ;
* priorité d’analyse.

Ne pas appeler une IA pour chaque tick.

Les calculs standards doivent être locaux et déterministes.

# 19. ANALYSE MULTI-TIMEFRAMES

Créer :

MultiTimeframeAnalyzer.

Le système doit comprendre les rôles différents des timeframes.

Exemple :

D1/H4 :
contexte général.

H1/M30 :
structure intermédiaire.

M15/M5 :
setup et trigger.

Ne pas imposer ces timeframes exactement.

Ils doivent être configurables par stratégie.

Produire par exemple :

D1 = BULLISH
H4 = BULLISH
H1 = PULLBACK
M15 = REVERSAL_TRIGGER
M5 = ENTRY_CONFIRMATION.

# 20. TECHNICAL ANALYSIS ENGINE

Créer un moteur déterministe capable d’analyser notamment :

* structure du marché ;
* HH/HL ;
* LH/LL ;
* break of structure ;
* changement de caractère ;
* tendances ;
* ranges ;
* breakout ;
* pullback ;
* support ;
* résistance ;
* ATR ;
* RSI ;
* moyennes mobiles lorsque pertinent ;
* momentum ;
* volatilité ;
* swing highs/lows ;
* distance SL potentielle ;
* ratio Risk/Reward.

Ne pas utiliser 50 indicateurs simplement pour donner une impression d’intelligence.

La logique doit être mesurable et testable.

# 21. MARKET REGIME DETECTOR

Créer :

MarketRegimeDetector.

Classifications possibles :

TRENDING_UP

TRENDING_DOWN

RANGING

HIGH_VOLATILITY

LOW_VOLATILITY

BREAKOUT

NEWS_DRIVEN

UNCERTAIN.

Le moteur de stratégie doit adapter son comportement au régime.

# 22. HISTORICAL PATTERN ENGINE

Je veux que TradePilot puisse rechercher dans le PASSÉ des configurations ressemblant à celle observée aujourd’hui.

Ne demande pas simplement à un LLM :

“Est-ce que tu as déjà vu cette configuration ?”

Construire une véritable analyse statistique.

Créer des features représentant une situation :

* trend D1 ;
* trend H4 ;
* trend H1 ;
* ATR relatif ;
* momentum ;
* distance support ;
* distance résistance ;
* RSI ;
* régime ;
* session ;
* volatilité ;
* structure ;
* spread ;
* contexte cross-market.

Chercher des fenêtres historiques similaires.

Produire :

nombre de configurations comparables ;
résultats positifs ;
résultats négatifs ;
résultats neutres ;
mouvement moyen ;
distribution ;
MAE ;
MFE ;
performance 1h ;
performance 4h ;
performance 24h lorsque pertinent.

Aucune donnée future ne doit être visible lors de la simulation.

# 23. SIMILARITY SCORE

Créer un score de similarité.

Exemple :

Historical Analogues

127 situations trouvées.

Similarity Mean
82 %

Après 4 heures :

Positive
61 %

Negative
29 %

Neutral
10 %

Cela ne doit PAS devenir :

“61 % = BUY automatique.”

C’est uniquement une composante.

# 24. WALK-FORWARD TESTING

Ajouter lorsque possible des tests walk-forward.

Séparer :

training/history

et

validation future.

Éviter le look-ahead bias et le data leakage.

# 25. CROSS-MARKET ENGINE

Créer :

CrossMarketAnalyzer.

Analyser les relations entre instruments accessibles.

Exemples possibles :

Dollar
Gold
indices US
rendements si source fiable disponible
pétrole
devises
Bitcoin.

Ne jamais coder une corrélation éternelle.

Calculer les corrélations récentes et historiques.

# 26. EXPOSITION AGRÉGÉE

Exemple :

BUY EURUSD
BUY GBPUSD
SELL USDCHF

peut produire une forte exposition similaire contre USD.

Le Risk Manager doit comprendre cette exposition.

Créer :

correlated overexposure protection.

# 27. NEWS ENGINE

Créer un NewsEngine.

Objectif :

surveiller en permanence les informations susceptibles d’affecter les instruments observés.

Sources :

privilégier :

* sources officielles ;
* banques centrales ;
* organismes statistiques ;
* institutions publiques ;
* flux RSS publics ;
* sources financières légalement accessibles ;
* providers gratuits configurables.

Ne jamais contourner :

* paywall ;
* CAPTCHA ;
* authentification ;
* protections anti-bot ;
* conditions d’utilisation.

Créer :

NewsProvider.

# 28. ACTUALITÉS MONDIALES

Détecter notamment :

* décisions banques centrales ;
* taux ;
* inflation ;
* chômage ;
* emploi ;
* NFP ;
* CPI ;
* PPI ;
* PIB ;
* FOMC ;
* BCE ;
* BOE ;
* BOJ ;
* annonces économiques ;
* tensions géopolitiques ;
* conflits ;
* sanctions ;
* pétrole ;
* énergie ;
* crise financière ;
* changement réglementaire majeur ;
* déclarations gouvernementales ;
* déclarations de banquiers centraux ;
* informations d’entreprises majeures ;
* événements pouvant provoquer de fortes variations.

# 29. NEWS RELEVANCE ENGINE

Pour chaque actualité produire :

source
title
publishedAt
receivedAt
url
summary
category
countries
entities
affectedAssets
affectedCurrencies
impactLevel
sentiment
confidence
reason.

Impact :

LOW
MEDIUM
HIGH
CRITICAL.

# 30. IA HYBRIDE POUR LES NEWS

Pipeline recommandé :

News brute
↓
préfiltre déterministe
↓
IA locale
↓
si ambigu ou très important :
OpenRouter
↓
si critique :
option ENSEMBLE
↓
NewsRelevanceEngine.

Le modèle local doit traiter la majorité des nouvelles ordinaires.

OpenRouter ne doit pas être appelé inutilement.

# 31. NEWS DEDUPLICATION

La même information peut être reprise par 20 médias.

Créer :

NewsDeduplicator.

Regrouper les nouvelles similaires.

Conserver les sources comme confirmations.

# 32. NEWS VERIFICATION

État :

UNCONFIRMED
PARTIALLY_CONFIRMED
CONFIRMED.

Pour les événements majeurs, rechercher plusieurs confirmations fiables.

# 33. ECONOMIC CALENDAR

Créer :

EconomicCalendarEngine.

Suivre :

date/heure
pays
devise
événement
importance
forecast
previous
actual.

Impact :

LOW
MEDIUM
HIGH.

# 34. NOTIFICATIONS AVANT NEWS

Exemple :

🔔 Événement économique important

USD — CPI

Dans 30 minutes

Impact :
HIGH

Positions potentiellement concernées :
XAUUSD
EURUSD
US100.

Configuration :

60 min
30 min
15 min
5 min.

# 35. NEWS RISK MODE

Le Risk Manager peut bloquer les nouvelles positions autour des HIGH impact.

Configuration :

X minutes avant.

Y minutes après.

# 36. TELEGRAM INTELLIGENCE

Conserver tout le système Telegram existant.

Pipeline :

Telegram Parser
↓
Signal normalization
↓
Technical Analyzer
↓
Market Regime
↓
Historical Pattern
↓
Macro/News
↓
Cross Market
↓
AI Hybrid Analysis
↓
Confidence Engine
↓
Risk Manager.

# 37. PARSING TELEGRAM HYBRIDE

Utiliser :

parser déterministe d’abord.

Si ambigu :

IA locale.

Si le modèle local échoue ou confiance insuffisante :

OpenRouter.

Si signal critique et ambigu :

mode ENSEMBLE possible.

# 38. VÉRIFICATION D’UN SIGNAL TELEGRAM

Exemple :

Telegram :

XAUUSD BUY
Entry 3510
SL 3495
TP 3540.

Le système produit :

Telegram
BUY

Technical
BUY

Historical
BUY

Market regime
TRENDING_UP

Macro
NEUTRAL

News Risk
LOW

Cross Market
BUY

Local AI
BUY

OpenRouter
BUY

AI Consensus
YES

Final Score
84/100

Result :

APPROVED.

# 39. REFUS D’UN SIGNAL TELEGRAM

Telegram :

XAUUSD BUY.

Mais :

Technical
STRONG SELL

Market Regime
DOWNTREND

High impact news
8 minutes

Local AI
SELL

OpenRouter
WAIT

Final Score
31/100.

Résultat :

REJECTED.

# 40. LE SYSTÈME PEUT CRÉER SON PROPRE SIGNAL

Créer :

OpportunityGenerator.

Le système peut produire :

AI_GENERATED_OPPORTUNITY.

Exemple :

XAUUSD

Direction:
BUY

Entry zone:
...

Stop Loss:
...

Targets:
...

Expected RR:
...

Confidence:
82 %

Reasons:

* D1/H4 bullish alignment
* H1 pullback
* M15 bullish BOS
* low news risk
* favorable historical analogues
* cross-market confirmation.

# 41. NE PAS LAISSER L’IA INVENTER LES PRIX

Les niveaux Entry, SL et TP doivent être calculés avec :

* structure ;
* volatilité ;
* support/résistance ;
* ATR ;
* stratégie déterministe.

Les IA servent à interpréter, contextualiser et expliquer.

# 42. DECISION ENGINE

Créer :

DecisionEngine.

Actions :

STRONG_BUY
BUY
WAIT
SELL
STRONG_SELL
NO_TRADE.

Avant exécution :

BUY
SELL
NO_TRADE.

# 43. CONFIDENCE ENGINE

Exemple initial :

Technical
25 %

Historical
15 %

Market Regime
10 %

Macro
15 %

News
10 %

Cross Market
10 %

Telegram
10 %

AI Consensus
5 %.

Poids configurables et testables.

# 44. CONFIANCE ≠ RISQUE

Même si :

Confidence = 99 %

le risque ne dépasse jamais la limite RiskManager.

# 45. STRATEGY ENGINE

Créer :

TradingStrategy.

Premières familles possibles :

Trend Following
Breakout
Pullback
Mean Reversion.

Activer uniquement les stratégies réellement implémentées et testées.

# 46. MARKET INTELLIGENCE REPORT

Pour chaque instrument :

Price

Market Regime

Technical

Historical

Macro

News

Cross Market

Telegram

Local AI

OpenRouter AI

AI Consensus

Overall

Decision

Reason.

# 47. CONTEXT MEMORY

Stocker :

market_snapshots

symbol
timestamp
features
technicalScore
regime
historicalScore
macroScore
newsScore
telegramScore
localAiScore
openRouterScore
aiConsensus
globalScore
decision.

# 48. LEARNING ENGINE

Après chaque trade enregistrer :

contexte
source
scores
décision
stratégie
entry
SL
TP
risque
résultat
MFE
MAE
durée
news
regime
session
modèle local utilisé
modèle OpenRouter utilisé
consensus IA.

Ne jamais permettre au système de réécrire automatiquement ses règles Live sans validation.

# 49. PERFORMANCE PAR IA

Comparer :

Local AI

OpenRouter

AI Ensemble

AI generated

Telegram

Manual.

Afficher :

trades
wins
losses
R
drawdown
profit factor
accuracy parsing
latency.

# 50. MOBILE PUSH NOTIFICATIONS

C’EST UNE EXIGENCE MAJEURE.

Je dois recevoir les informations IMPORTANTES directement sur mon téléphone Android même lorsque l’application n’est pas ouverte.

Mettre en place :

Firebase Cloud Messaging si approprié.

Le Bridge envoie.

Flutter reçoit.

Fallback :

WebSocket
notifications locales
Inbox interne.

# 51. CATÉGORIES DE NOTIFICATIONS

TRADE

SIGNAL

OPPORTUNITY

NEWS

ECONOMIC

RISK

SYSTEM

DAILY_REPORT

AI_SYSTEM.

# 52. NOTIFICATION BUY

🟢 ACHAT OUVERT

XAUUSD

BUY
0.02 lot

Entry
3512.40

SL
3498.00

TP1
3528.00

Risk
0.5 %

Source
TradePilot AI

AI Mode
ENSEMBLE

Confidence
83 %.

# 53. NOTIFICATION SELL

🔴 VENTE OUVERTE

EURUSD

SELL

Lot
...

Entry
...

SL
...

TP
...

Source
...

Confidence
...

# 54. NOTIFICATION OPPORTUNITÉ

🤖 OPPORTUNITÉ DÉTECTÉE

XAUUSD BUY

Confidence
82 %

Technical
86 %

Historical
77 %

News Risk
LOW

AI Consensus
YES

[Voir l’analyse].

# 55. NOTIFICATION TELEGRAM

📡 SIGNAL TELEGRAM

Gold Signals

XAUUSD BUY

TradePilot :
APPROVED

AI Consensus:
YES

Confidence:
81 %.

# 56. NOTIFICATION DÉSACCORD IA

Si une opportunité sensible obtient :

Local = BUY

OpenRouter = SELL

et qu’elle n’est pas autorisée automatiquement :

envoyer éventuellement :

⚠️ ANALYSE INCERTAINE

XAUUSD

IA locale :
BUY

OpenRouter :
SELL

Décision :
NO TRADE

ou

NEEDS REVIEW.

# 57. NOTIFICATION TP

✅ TP1 ATTEINT

XAUUSD BUY

Profit actuel
...

Position restante
...

SL
Break Even.

# 58. NOTIFICATION SL

❌ STOP LOSS

XAUUSD BUY

Result
-0.48 %

Risk planned
0.5 %.

# 59. POSITION FERMÉE

🏁 POSITION FERMÉE

XAUUSD

Result
+1.72 R

Profit
...

Duration
...

Source
TradePilot AI.

# 60. BREAK EVEN

🛡 BREAK EVEN ACTIVÉ

XAUUSD

SL déplacé :
...

# 61. RISK NOTIFICATIONS

⚠️ LIMITE DE PERTE JOURNALIÈRE

Auto Trading suspendu.

# 62. NEWS NOTIFICATIONS

🌍 MARKET NEWS — HIGH IMPACT

FED signals rates may remain higher for longer.

Affected:
USD
XAUUSD
EURUSD
US100

TradePilot interpretation:
...

Source:
...

Publié:
...

# 63. INFORMATION BOURSIÈRE

Créer des notifications importantes concernant :

indices
forex
commodities
métaux
crypto
grandes entreprises lorsque cela affecte les indices suivis.

Exemple :

📈 US MARKET

Major earnings released.

Potential impact:
US100
SPX500

Severity:
HIGH.

# 64. PAS DE SPAM

Créer :

NotificationRelevanceScore.

Par défaut :

Push HIGH et CRITICAL.

MEDIUM dans l’application.

# 65. MARKET MOVEMENT ALERTS

Créer :

Sudden volatility
Spread spike
Gap
Large candle
Breakout
Abnormal move.

Exemple :

⚡ MOUVEMENT ANORMAL

XAUUSD

+1.1 % en 12 min

Volatility
3.2x normal.

# 66. WATCHLIST ALERTS

Réglages par instrument :

News
Opportunities
Volatility
Telegram.

# 67. NOTIFICATION INBOX

Créer page Flutter :

Notifications.

Filtres :

Toutes
Trades
Opportunités
News
Économie
Risques
Système
IA.

# 68. NEWS CENTER

Ajouter :

Actualités.

Sections :

Pour vous
Marchés
Forex
Indices
Métaux
Économie
Monde
Telegram.

# 69. NEWS DETAIL

Afficher :

titre
source
publication
résumé IA
provider IA utilisé
faits principaux
actifs concernés
impact
sentiment
confiance
lien source.

# 70. ECONOMIC CALENDAR UI

Today
Tomorrow
Week.

Filtres :
High
Medium
Low
devise.

# 71. MARKET PULSE

Accueil :

MARKET PULSE

Risk Sentiment
RISK OFF

USD
Strong

Gold
Bullish

US100
Weak

High impact events
3.

# 72. AI OPPORTUNITIES

Accueil :

AI Opportunities.

XAUUSD

BUY

Confidence:
82 %

AI Consensus:
YES

Status:
WAITING ENTRY.

# 73. MARKET SCREEN

Créer :

Marchés.

Pour chaque instrument :

prix
variation
regime
AI direction
confidence
position.

# 74. MARKET DETAIL

Afficher :

chart
timeframe
regime
technical
historical analogues
macro
news
cross market
Telegram
Local AI
OpenRouter
AI Consensus
Open Positions
Recent decisions.

# 75. EXPLICATION DES DÉCISIONS

Afficher des explications synthétiques.

Ne jamais afficher les chain-of-thought internes.

Exemple :

TradePilot selected BUY because:

* D1 bullish trend
* H4 continuation
* H1 pullback
* historical confirmation
* AI consensus
* no major news risk.

Negative factors:

* elevated volatility.

# 76. DECISION JOURNAL

Afficher aussi les trades non pris.

Exemple :

03:14

EURUSD

NO TRADE

Reason:
AI disagreement
high impact news soon.

# 77. NEWS JOURNAL

Conserver :

news_events

id
title
source
url
publishedAt
receivedAt
summary
category
impact
sentiment
affectedAssets
verificationStatus
rawHash
aiProviderUsed
aiModelUsed.

# 78. RELIER NEWS ↔ TRADE

Conserver les informations connues AVANT le trade.

Ne jamais utiliser une news postérieure comme justification rétroactive.

# 79. HORODATAGE

Toutes les données internes UTC.

Flutter convertit en fuseau local.

# 80. LATENCE

Mesurer :

Telegram received → parsed

market signal → decision

decision → order_send

news published → received

Local AI latency

OpenRouter latency.

# 81. RISK MANAGER

Le Risk Manager garde autorité absolue.

Ajouter :

max correlated exposure

news blackout window

market regime restrictions

max AI trades/day

max Telegram trades/day

max trades/symbol/day

max account exposure

max direction exposure.

# 82. AI AUTO TRADING

Réglages séparés :

AI Trading
ON/OFF

Telegram Trading
ON/OFF

Local AI
ON/OFF

OpenRouter
ON/OFF

AI Ensemble
ON/OFF.

# 83. MODES

PAPER

MT5 DEMO

MT5 LIVE.

Toute nouvelle intelligence doit fonctionner d’abord en PAPER.

# 84. SHADOW MODE

Ajouter :

SHADOW MODE.

Le système analyse et décide sans envoyer d’ordre.

Enregistrer :

would_buy
would_sell
would_skip.

# 85. SHADOW COMPARISON

Afficher :

Trades simulés

Win rate

Loss rate

Average R

Max drawdown

Profit Factor

Performance Local AI

Performance OpenRouter

Performance Ensemble.

# 86. CIRCUIT BREAKER

Suspendre auto trading si :

* données incohérentes ;
* MT5 instable ;
* spread anormal ;
* trop d’erreurs ;
* drawdown max ;
* pertes consécutives ;
* Bridge instable ;
* AI consensus obligatoire indisponible.

# 87. SYSTEM NOTIFICATIONS

Bridge Offline

MT5 disconnected

Telegram disconnected

OpenRouter unavailable

Local AI unavailable

Both AI providers unavailable

Market feed stale

News service unavailable

Auto Trading paused.

# 88. DAILY REPORT

📊 TRADEPILOT — JOURNAL DU JOUR

Trades
...

Wins
...

Losses
...

Result
...

AI Local trades
...

OpenRouter assisted
...

Ensemble
...

Telegram
...

News importantes demain
...

# 89. WEEKLY REPORT

Inclure :

trades
win rate
profit factor
average R
drawdown
best instrument
worst instrument
Local AI performance
OpenRouter performance
Ensemble performance
Telegram performance.

# 90. QUIET HOURS

Configurer.

Critical bypass facultatif.

# 91. LANGUE

Français par défaut.

Architecture i18n prévue.

# 92. DESIGN

Conserver design simple.

Couleur principale :

#2563EB.

Vert/rouge seulement pour états fonctionnels.

# 93. BACKGROUND MOBILE

Configurer Flutter Android :

FCM
foreground
background
app fermée
deep links.

# 94. SECURITY DES NOTIFICATIONS

Aucun secret.

Aucune action financière critique directement depuis notification.

# 95. CONFIGURATION IA DANS FLUTTER

Créer une section :

Intelligence Artificielle.

Sous-sections :

AI Mode

AUTO
LOCAL ONLY
OPENROUTER ONLY
LOCAL FIRST
OPENROUTER FIRST
ENSEMBLE.

Puis :

IA locale

Status
Model
Endpoint
Provider
Test Connection
Capabilities
Latency.

OpenRouter

Status
Model
Automatic Free Selection
Test Connection
Latency.

Ensemble

Require consensus before auto trade
ON/OFF

Disagreement behavior :

NO TRADE
MANUAL REVIEW.

# 96. ÉCRAN AI DIAGNOSTIC

Afficher :

Local AI
ONLINE / DEGRADED / OFFLINE

Local model
...

JSON capability
...

Vision
...

Latency
...

OpenRouter
ONLINE / OFFLINE

Model
...

Free
YES

Latency
...

AI Router
AUTO

Last routing decision
...

Consensus Service
ONLINE.

# 97. DATABASE MIGRATIONS

Ajouter notamment :

market_snapshots
market_features
historical_patterns
economic_events
news_events
news_asset_links
market_regimes
ai_opportunities
decision_records
decision_factors
notification_events
notification_preferences
strategy_performance
shadow_trades
cross_market_states
ai_provider_metrics
ai_consensus_records
ai_routing_events.

Préserver données existantes.

# 98. API

Ajouter :

/api/v1/ai/status

/api/v1/ai/providers

/api/v1/ai/local/models

/api/v1/ai/local/test

/api/v1/ai/openrouter/models

/api/v1/ai/openrouter/test

/api/v1/ai/router/settings

/api/v1/ai/metrics

/api/v1/ai/consensus/{decisionId}

et les endpoints market/news existants nécessaires.

# 99. WEBSOCKET

Ajouter événements :

local_ai_status

openrouter_status

ai_routing_event

ai_consensus_event

ai_disagreement

market_update

opportunity_created

decision_created

news_high_impact

trade_executed

trade_closed

risk_breaker.

# 100. FAILOVER IA

Scénarios :

Local down
↓
OpenRouter si autorisé.

OpenRouter down
↓
Local.

Both down
↓
analyses déterministes continuent.

Si une décision exige l’IA :

NEEDS_REVIEW
ou
NO_TRADE.

Jamais :

AI down → trade quand même sans règles.

# 101. TESTS IA

Créer des tests pour :

AIRouter

LocalAIProvider

OpenRouterAIProvider

AIEnsembleService

AIConsensusEngine

AI fallback

AI disagreement

invalid JSON

timeout

provider unavailable

provider recovery.

# 102. TEST LOCAL AI FAILURE

Local AI offline.

Mode LOCAL_FIRST.

OpenRouter online.

Résultat :

fallback OpenRouter.

# 103. TEST OPENROUTER FAILURE

OpenRouter offline.

Local AI online.

Résultat :

local continues.

# 104. TEST BOTH FAILURE

Local + OpenRouter offline.

Technical Engine fonctionne.

Un signal nécessitant IA :

NEEDS_REVIEW.

Aucun trade automatique.

# 105. TEST AI DISAGREEMENT

Local :

BUY.

OpenRouter :

SELL.

Require Consensus = ON.

Résultat :

NO_TRADE.

Journal :

AI_DISAGREEMENT.

# 106. TEST AI CONSENSUS

Local :

BUY.

OpenRouter :

BUY.

Deterministic Technical :

BUY.

Risk :

PASS.

Paper Mode.

Résultat :

Paper BUY.

# 107. TEST DES NOTIFICATIONS

Tester :

BUY
SELL
TP
SL
Break Even
Partial Close
High Impact News
Economic Event
Risk Limit
Bridge Offline
Local AI Offline
OpenRouter Offline
AI Disagreement.

# 108. LOOK-AHEAD BIAS

Créer explicitement des tests garantissant :

pas de bougies futures

pas de news futures.

# 109. DOCUMENTATION

Mettre à jour :

README.md

Créer ou mettre à jour :

docs/AI_HYBRID_ARCHITECTURE.md
docs/LOCAL_AI_SETUP.md
docs/OPENROUTER_SETUP.md
docs/AI_ROUTER.md
docs/AI_ENSEMBLE.md
docs/MARKET_INTELLIGENCE.md
docs/AUTONOMOUS_TRADING.md
docs/MARKET_DATA.md
docs/TECHNICAL_ENGINE.md
docs/HISTORICAL_PATTERN_ENGINE.md
docs/NEWS_ENGINE.md
docs/ECONOMIC_CALENDAR.md
docs/CROSS_MARKET.md
docs/DECISION_ENGINE.md
docs/CONFIDENCE_ENGINE.md
docs/NOTIFICATIONS.md
docs/FCM_SETUP.md
docs/SHADOW_MODE.md
docs/PAPER_TESTING.md
docs/AI_TRADING_SAFETY.md.

# 110. CONFIGURATION

Ajouter :

AI Mode

Local AI Enabled

Local Provider

Local Endpoint

Local Model

OpenRouter Enabled

OpenRouter Auto Free Model

Ensemble Enabled

Require Consensus

AI Trading

Watchlist

Strategies

Timeframes

News

Economic Calendar

Notifications

Shadow Mode

Risk Limits.

# 111. DIAGNOSTIC GLOBAL

Afficher :

Bridge

MT5

Telegram

Local AI

OpenRouter

AI Router

AI Ensemble

Market Data

Market Scanner

News Engine

Economic Calendar

Decision Engine

Notification Service

FCM

WebSocket.

Chaque service :

ONLINE
DEGRADED
OFFLINE.

# 112. OBSERVABILITÉ

Ajouter :

last_market_update

last_news_update

last_calendar_update

last_scan

last_decision

last_notification

local_ai_latency

openrouter_latency

ai_disagreement_rate

ai_fallback_count

mt5_latency.

# 113. FAIL SAFE

En cas de doute :

NO TRADE.

Exemples :

données marché trop vieilles

prix incohérent

IA en désaccord

news critique non analysable

MT5 instable

signal incomplet

risque incalculable

SL invalide

confidence insuffisante.

# 114. OBJECTIF FINAL

Après cette mise à jour, TradePilot doit devenir :

un système de Market Intelligence + Trading Automation + Hybrid AI.

Il doit pouvoir :

observer

analyser

comparer

attendre

détecter

expliquer

notifier

proposer

valider

trader

suivre

apprendre statistiquement

router intelligemment les tâches entre IA locale et OpenRouter.

Flux final :

MARKET DATA
+
HISTORY
+
NEWS
+
MACRO
+
CROSS MARKET
+
TELEGRAM
↓
DETERMINISTIC ENGINES
↓
AI ROUTER
↙ ↘
LOCAL AI   OPENROUTER
↘ ↙
AI CONSENSUS
↓
MARKET INTELLIGENCE
↓
OPPORTUNITY
↓
CONFIDENCE
↓
DECISION
↓
RISK MANAGER
↓
MT5 EXNESS
↓
MOBILE NOTIFICATION
↓
JOURNAL + LEARNING.

# 115. IMPORTANT : NE PAS RÉÉCRIRE LE PROJET

Commence impérativement par :

1. inspecter tout le dépôt ;
2. identifier les fonctionnalités existantes ;
3. identifier comment l’IA locale est actuellement exposée si elle existe déjà ;
4. réutiliser l’intégration locale existante si elle est propre ;
5. identifier les migrations ;
6. préparer une checklist ;
7. modifier progressivement ;
8. compiler régulièrement ;
9. tester régulièrement ;
10. corriger les régressions.

Ne détruis aucune fonctionnalité existante qui fonctionne.

# 116. EXIGENCE DE RÉSULTAT

Ne me donne pas seulement un plan.

MODIFIE RÉELLEMENT LE PROJET.

Crée les fichiers.

Modifie les fichiers existants.

Crée les migrations.

Crée les tests.

Connecte :

Flutter
Bridge
Local AI
OpenRouter
Telegram
MT5
Notifications.

Compile.

# 117. VALIDATION FINALE

Backend :

lancer tous les tests Python.

Flutter :

flutter pub get

flutter analyze

flutter test

flutter build apk.

Corriger ce qui échoue lorsque cela relève du projet.

# 118. RAPPORT FINAL

À la fin donne-moi :

1. architecture finale ;
2. fichiers créés ;
3. fichiers modifiés ;
4. nouvelles fonctionnalités ;
5. fonctionnement IA locale ;
6. provider local utilisé ;
7. modèle local détecté ;
8. fonctionnement OpenRouter ;
9. fonctionnement du AI Router ;
10. fonctionnement Ensemble ;
11. règles de fallback ;
12. fonctionnement des signaux IA ;
13. fonctionnement Telegram ;
14. fonctionnement news ;
15. fonctionnement notifications Android ;
16. configuration FCM ;
17. fonctionnement Paper ;
18. fonctionnement Shadow ;
19. fonctionnement MT5 Demo ;
20. état Live ;
21. tests exécutés ;
22. résultats ;
23. emplacement APK ;
24. commandes Bridge ;
25. étapes de test sur téléphone ;
26. limites connues ;
27. éléments nécessitant configuration externe.

Ne prétends jamais qu’une intégration externe a été testée si elle ne l’a pas réellement été.

Commence maintenant par auditer la version existante de TradePilot et implémente cette mise à jour complète.
