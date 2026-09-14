Tu es l’architecte logiciel principal et l’agent de développement responsable de construire entièrement ce projet.

Je veux que tu réalises le projet COMPLET, fonctionnel et exploitable de A à Z.

Ne crée pas seulement une maquette.
Ne crée pas seulement une “V1”.
Ne me donne pas seulement du pseudo-code.
Ne t’arrête pas après avoir créé l’architecture.
Ne laisse pas de boutons non fonctionnels.
Ne laisse pas de TODO importants.
Ne crée pas de fausses données qui donnent l’impression que le trading réel fonctionne.
Ne me demande pas de confirmer chaque étape.

Analyse le dépôt existant s’il existe, puis implémente directement ce qui est nécessaire.

Si le projet est vide, crée tout proprement.

À chaque étape :

* préserve ce qui fonctionne déjà ;
* écris du code propre et maintenable ;
* exécute les tests ;
* exécute les analyseurs/lint ;
* corrige les erreurs rencontrées ;
* documente les éléments nécessitant une configuration externe ;
* continue jusqu’à obtenir le maximum de fonctionnalités réellement opérationnelles.

# 1. OBJECTIF DU PROJET

Créer une application personnelle de gestion et de copie de signaux de trading.

Nom provisoire :

TradePilot

L’utilisateur possède :

* un téléphone Android ;
* un compte Exness ;
* un compte MetaTrader 5 ;
* un compte Telegram ;
* un compte OpenRouter.

L’application principale doit être une application Flutter Android installable sous forme d’APK.

L’utilisateur doit pouvoir depuis son téléphone :

* rechercher des canaux Telegram publics de signaux ;
* ajouter ses propres canaux Telegram ;
* analyser la qualité des canaux ;
* surveiller plusieurs canaux ;
* recevoir les nouveaux signaux ;
* interpréter automatiquement les signaux ;
* afficher le signal compris par le système ;
* appliquer ses propres règles de risque ;
* accepter ou refuser automatiquement un signal ;
* envoyer les ordres vers son compte Exness MT5 ;
* suivre les positions ;
* modifier SL/TP ;
* gérer TP1, TP2, TP3, etc. ;
* gérer le Break Even ;
* gérer les fermetures partielles ;
* gérer les messages de fermeture ;
* gérer les pending orders ;
* consulter l’historique ;
* suivre les performances ;
* mettre en pause l’automatisation ;
* arrêter immédiatement les nouvelles opérations ;
* fermer toutes les positions avec une action d’urgence explicite ;
* utiliser une IA OpenRouter pour comprendre les messages difficiles ;
* analyser une capture d’écran de graphique avec un modèle vision gratuit lorsque disponible.

L’application est destinée à UN SEUL UTILISATEUR pour son usage personnel.

Ne construis donc pas :

* SaaS multi-utilisateur ;
* abonnement ;
* paiement ;
* facturation ;
* marketplace ;
* gestion d’équipes.

# 2. CONTRAINTE IMPORTANTE : MT5 ANDROID

Ne tente PAS de contrôler directement l’application MetaTrader 5 Android.

MT5 Android ne doit être utilisé que comme application complémentaire permettant à l’utilisateur de consulter son compte et éventuellement intervenir manuellement.

Le trading automatisé doit passer par une passerelle MT5 fonctionnant avec MetaTrader 5 Desktop.

Architecture principale :

Telegram
↓
Moteur de réception/analyse
↓
Moteur de validation
↓
Risk Manager
↓
Bridge MT5
↓
MetaTrader 5 Desktop
↓
Compte Exness MT5

Et :

Application Flutter Android
⇅
API sécurisée + WebSocket
⇅
Bridge

L’utilisateur contrôle l’ensemble depuis son téléphone.

# 3. ARCHITECTURE DU MONOREPO

Créer quelque chose de propre comme :

/
├── mobile/
│   └── application Flutter
│
├── bridge/
│   └── backend Python
│
├── docs/
│
├── scripts/
│
├── README.md
├── .gitignore
└── .env.example

Le nom peut être adapté si le dépôt existant possède déjà une structure cohérente.

# 4. APPLICATION MOBILE

Technologie obligatoire :

Flutter / Dart.

Architecture recommandée :

* Clean Architecture raisonnable ;
* architecture feature-first ;
* Riverpod ;
* go_router ;
* Dio ;
* Drift/SQLite ;
* flutter_secure_storage ;
* websocket_channel ;
* modèles immuables et sérialisation JSON propre.

Ne surcharge pas inutilement le projet de dépendances.

Structure approximative :

lib/
├── app/
├── core/
│   ├── api/
│   ├── database/
│   ├── security/
│   ├── routing/
│   ├── theme/
│   ├── widgets/
│   └── utils/
│
└── features/
├── onboarding/
├── dashboard/
├── bridge/
├── telegram/
├── channels/
├── signals/
├── positions/
├── orders/
├── risk/
├── statistics/
├── ai/
├── journal/
└── settings/

# 5. DESIGN DE L’APPLICATION

Je veux une interface TRÈS SIMPLE, moderne et professionnelle.

Pas de design multicolore.

Couleur principale unique :

#2563EB

Utiliser principalement :

* blanc ;
* gris très clair ;
* gris foncé/noir pour le texte ;
* #2563EB comme seule vraie couleur d’accent.

Vert et rouge sont autorisés UNIQUEMENT lorsqu’ils ont une signification fonctionnelle :

* profit ;
* perte ;
* BUY ;
* SELL ;
* succès ;
* erreur critique.

Pas de :

* dégradés ;
* néons ;
* arrière-plans extravagants ;
* animations inutiles ;
* dizaines de couleurs ;
* glassmorphism excessif.

Utiliser Material 3.

Style :

* sobre ;
* espace généreux ;
* cards simples ;
* bordures discrètes ;
* coins légèrement arrondis ;
* excellente lisibilité ;
* responsive ;
* adapté à un téléphone Android.

Créer aussi une icône simple pour TradePilot utilisant la couleur principale.

# 6. NAVIGATION

Bottom navigation principale :

Accueil
Signaux
Canaux
Trades
Plus

Dans Plus :

* Statistiques
* Analyse IA
* Journal
* Gestion du risque
* Connexions
* Paramètres

# 7. ONBOARDING

Au premier lancement afficher un onboarding complet.

Étapes :

1. Présentation rapide.
2. Configuration du Bridge.
3. Vérification de MetaTrader.
4. Connexion Telegram.
5. Configuration OpenRouter.
6. Configuration du risque.
7. Choix obligatoire du MODE DEMO.
8. Test général des connexions.

Afficher un écran final avec :

Telegram : connecté/non connecté
OpenRouter : connecté/non connecté
Bridge : connecté/non connecté
MT5 : connecté/non connecté
Compte : DEMO/REAL
Auto trading : actif/inactif

# 8. BRIDGE PYTHON

Créer dans /bridge un backend Python propre.

Utiliser :

* Python moderne ;
* FastAPI ;
* Pydantic ;
* SQLAlchemy ou SQLModel ;
* SQLite ;
* httpx ;
* WebSocket ;
* MetaTrader5 ;
* Telethon ;
* asyncio lorsque pertinent ;
* pytest.

Organisation approximative :

bridge/
├── app/
│   ├── main.py
│   ├── api/
│   ├── config/
│   ├── database/
│   ├── models/
│   ├── repositories/
│   ├── schemas/
│   └── services/
│       ├── mt5/
│       ├── telegram/
│       ├── signals/
│       ├── risk/
│       ├── trading/
│       ├── channels/
│       ├── openrouter/
│       ├── statistics/
│       └── security/
├── tests/
├── requirements.txt ou pyproject.toml
└── .env.example

# 9. CONNEXION À METATRADER 5

Utiliser le package Python officiel MetaTrader5.

Le Bridge doit détecter le terminal MetaTrader 5 installé.

L’utilisateur doit normalement se connecter manuellement à son compte Exness dans MT5 Desktop.

Éviter de stocker inutilement son mot de passe Exness dans l’application Flutter.

Le Bridge doit récupérer :

* login ;
* serveur ;
* balance ;
* equity ;
* margin ;
* free margin ;
* currency ;
* leverage ;
* type de compte si disponible ;
* positions ;
* pending orders ;
* historique ;
* symboles ;
* informations de symboles ;
* prix BID/ASK ;
* spread.

Créer un service dédié :

MetaTraderService

Il doit gérer proprement :

* initialize ;
* reconnect ;
* shutdown ;
* account_info ;
* terminal_info ;
* symbol_info ;
* symbol_info_tick ;
* positions_get ;
* orders_get ;
* history ;
* order_check ;
* order_send ;
* order modification ;
* position closing.

Toutes les commandes MT5 doivent passer par UNE file de travail/worker sérialisée afin d’éviter des accès concurrents dangereux au terminal.

# 10. MODE DEMO OBLIGATOIRE

Le système doit être sécurisé par défaut.

Au premier lancement :

AUTO TRADING = OFF.

Et :

LIVE TRADING = OFF.

Le système doit détecter si le compte MT5 connecté est un compte DEMO ou REAL lorsque possible.

Le trading automatique réel ne doit jamais être activé accidentellement.

Pour passer en réel, prévoir plusieurs protections :

* réglage local explicite ;
* confirmation dans Flutter ;
* écran expliquant les risques ;
* saisie d’une phrase de confirmation ;
* aucun passage automatique DEMO → REAL.

Ne jamais simuler que le compte est Demo s’il est impossible de le déterminer.

# 11. TELEGRAM

L’utilisateur n’a actuellement AUCUN canal de signaux.

L’application doit donc intégrer une vraie gestion Telegram.

Utiliser une SESSION UTILISATEUR Telegram via Telethon et MTProto, et non seulement un Bot Telegram.

Créer un onboarding Telegram :

* API ID ;
* API Hash ;
* numéro de téléphone ;
* code OTP Telegram ;
* gestion du mot de passe 2FA Telegram si activé.

Stocker la session de manière sécurisée sur le Bridge.

Ne jamais loguer :

* API Hash ;
* OTP ;
* session Telegram ;
* mot de passe 2FA.

# 12. RECHERCHE DE CANAUX TELEGRAM

Créer une vraie fonctionnalité :

“Découvrir des canaux”.

L’utilisateur doit pouvoir rechercher par exemple :

gold signals
XAUUSD
forex signals
forex trading
gold trading
scalping gold
EURUSD signals
GBPUSD signals
NASDAQ signals

Utiliser les capacités de recherche Telegram accessibles à une session utilisateur autorisée.

Afficher pour chaque résultat disponible :

* nom ;
* username ;
* photo si accessible ;
* description ;
* nombre de membres si disponible ;
* public/privé ;
* déjà rejoint ou non ;
* activité récente ;
* nombre approximatif de messages analysables.

Ne jamais rejoindre automatiquement un canal sans action explicite de l’utilisateur.

Ajouter :

[Voir]
[Analyser]
[Ajouter à ma surveillance]

# 13. ANALYSE DES CANAUX

Créer un véritable “Channel Analyzer”.

Lorsqu’un utilisateur sélectionne un canal, récupérer un nombre configurable de messages historiques accessibles, par exemple les 100, 250, 500 derniers messages.

Chercher :

* combien ressemblent à des signaux ;
* quels instruments sont utilisés ;
* BUY/SELL ;
* présence d’Entry ;
* présence de SL ;
* présence de TP ;
* nombre de TP ;
* fréquence des signaux ;
* clarté des messages ;
* pourcentage de messages parseables ;
* messages de modification ;
* messages de fermeture ;
* signaux dupliqués.

Créer une note technique du canal.

Ne PAS écrire :

“ce canal va te faire gagner de l’argent”.

Afficher plutôt des mesures factuelles.

Exemple :

Qualité de structure : 92 %
Signaux avec SL : 95 %
Signaux avec TP : 98 %
Signaux correctement interprétables : 89 %
Fréquence : 4.2 signaux/jour

# 14. ANALYSE HISTORIQUE DES SIGNAUX

Lorsque les données MT5 permettent de récupérer les cours historiques :

faire une simulation historique prudente des signaux passés du canal.

Pour chaque signal ayant :

* date ;
* instrument ;
* direction ;
* entry ;
* SL ;
* TP ;

essayer de comparer avec les cours historiques disponibles dans MT5.

Produire :

* nombre de signaux testables ;
* gagnants ;
* perdants ;
* non déterminables ;
* R moyen ;
* gains/pertes théoriques ;
* drawdown théorique ;
* TP1 touchés ;
* SL touchés.

IMPORTANT :

Ne jamais inventer un résultat.

Si, dans une même bougie historique, SL et TP peuvent avoir été atteints et qu’on ne possède pas assez de données pour savoir lequel est arrivé en premier :

marquer :

AMBIGUOUS

et ne pas compter ce trade comme gagné.

Afficher clairement :

“Simulation historique indicative — elle ne garantit aucune performance future.”

# 15. GESTION DES CANAUX SUIVIS

Page :

Mes canaux

Pour chaque canal :

* ON/OFF ;
* mode manuel ;
* mode automatique ;
* instruments autorisés ;
* risque spécifique ;
* nombre maximum de positions ;
* copier BUY ;
* copier SELL ;
* SL obligatoire ;
* TP obligatoire ;
* durée maximale d’un signal ;
* lots maximums ;
* spread maximum ;
* score minimum de confiance du parser.

Permettre des réglages globaux et des overrides par canal.

# 16. PARSER DE SIGNAUX

C’est un composant critique.

Créer un pipeline hybride :

MESSAGE TELEGRAM
↓
NORMALISATION
↓
PARSER DÉTERMINISTE
↓
si ambigu
↓
OPENROUTER
↓
VALIDATEUR STRICT
↓
SIGNAL STRUCTURÉ

Le parser déterministe doit être utilisé en priorité afin :

* d’être rapide ;
* d’être prédictible ;
* de réduire les appels OpenRouter ;
* de réduire la dépendance à l’IA.

Reconnaître des formats différents.

Exemples :

BUY XAUUSD

GOLD BUY NOW

XAU/USD LONG

SELL GOLD 3350

BUY GOLD 3350-3345

XAUUSD BUY LIMIT 3340

XAUUSD SELL STOP 3320

SL 3300

STOP LOSS 3300

TP 3360

TP1 3360
TP2 3370
TP3 3385

TARGET 1
TARGET 2

etc.

Créer des alias :

GOLD → XAUUSD
XAU/USD → XAUUSD
XAU USD → XAUUSD

Mais conserver une table de mapping configurable, car Exness peut utiliser un nom de symbole spécifique.

# 17. FORMAT INTERNE D’UN SIGNAL

Créer un modèle similaire à :

TradingSignal

id
channelId
telegramMessageId
replyToMessageId
receivedAt
messageDate
rawText

symbol
normalizedSymbol
direction
orderType

entryMin
entryMax
entryPrice

stopLoss

takeProfits[]

confidence

parserSource
deterministic
ai
manual

status

rejectionReason

originalSignalId

Ne jamais remplacer une donnée inconnue par une valeur inventée.

Utiliser NULL.

# 18. SIGNAUX DE SUIVI

Le système doit comprendre les messages liés à un signal existant.

Exemples :

TP1 HIT
TP2 HIT

CLOSE GOLD

CLOSE XAUUSD

CLOSE NOW

CLOSE 50%

CLOSE HALF

MOVE SL TO BE

SL BE

BREAK EVEN

MOVE SL 3350

CANCEL GOLD

DELETE PENDING

RUNNING +50 PIPS

HOLD

Le moteur doit essayer de rattacher le message au bon signal grâce à :

1. reply_to Telegram ;
2. channel ;
3. symbole ;
4. message original ;
5. positions ouvertes ;
6. proximité temporelle.

Ne jamais modifier plusieurs positions ambiguës sans règle explicite.

# 19. OPENROUTER

Utiliser OpenRouter.

Créer :

OpenRouterService.

L’utilisateur saisit sa clé OpenRouter dans les réglages.

La clé ne doit jamais être :

* écrite dans Git ;
* envoyée dans les logs ;
* affichée intégralement ;
* stockée en clair.

Stockage sécurisé côté Bridge.

Modèle texte préféré actuellement :

nvidia/nemotron-3-ultra-550b-a55b:free

Mais NE PAS dépendre définitivement de ce modèle.

Les modèles gratuits OpenRouter changent.

Créer donc :

FreeModelSelector

Au démarrage ou à la demande :

* récupérer la liste actuelle des modèles ;
* identifier les modèles réellement gratuits ;
* tester les capacités nécessaires ;
* conserver le modèle préféré s’il fonctionne ;
* sélectionner automatiquement un fallback gratuit lorsqu’il n’est plus disponible.

Ajouter dans Paramètres IA :

Mode automatique : ON/OFF

Modèle texte :
Automatique / modèle choisi

Modèle vision :
Automatique / modèle choisi

Afficher :

* modèle actif ;
* gratuit/payant ;
* état ;
* dernier test ;
* latence approximative.

NE JAMAIS sélectionner automatiquement un modèle payant.

Si aucun modèle gratuit n’est disponible :

ne lancer aucun appel payant.

Afficher :

“Aucun modèle gratuit disponible actuellement.”

# 20. ÉCONOMISER LES REQUÊTES OPENROUTER

Ne pas envoyer chaque signal à l’IA.

Pipeline :

Regex/parser local
→ validation locale
→ seulement si ambigu : OpenRouter.

Mettre en cache les formats déjà compris par canal.

Créer des templates par fournisseur.

Exemple :

si le même canal utilise toujours :

GOLD BUY
ENTRY
SL
TP1
TP2

le parser local doit apprendre/utiliser ce template sans appeler OpenRouter.

# 21. UTILISATION DE L’IA POUR LES SIGNAUX

L’IA sert à COMPRENDRE LE TEXTE.

Elle ne doit PAS décider si un trade sera rentable.

Elle doit extraire des informations.

Prompt système interne strict :

“Extract only information explicitly present or strongly unambiguous in the message. Never invent prices, stop losses, targets, symbols or directions. Unknown values must be null.”

Faire produire un objet strict.

Lorsque le modèle prend en charge tool calling, préférer un outil interne :

parse_trading_signal

avec schéma typé.

Valider ensuite toutes les données localement.

Une sortie IA invalide ne doit jamais atteindre MT5.

# 22. ANALYSE IA DE GRAPHIQUES

Créer une page :

Analyse IA

L’utilisateur peut :

* importer une capture d’écran ;
* prendre une image ;
* choisir éventuellement l’instrument ;
* ajouter une question.

Utiliser seulement un modèle OpenRouter GRATUIT supportant réellement les images.

Si le modèle texte préféré ne supporte pas les images, sélectionner un autre modèle vision gratuit.

L’analyse peut présenter :

* tendance observée ;
* supports visibles ;
* résistances visibles ;
* structure ;
* scénarios possibles ;
* invalidation.

Cette analyse est informative.

Elle ne doit JAMAIS déclencher automatiquement un trade.

Aucun bouton :

“Trade automatiquement l’analyse IA”.

# 23. MOTEUR DE RISQUE

Créer un RiskManager complètement indépendant de l’IA.

Il constitue la dernière barrière avant toute opération.

Paramètres globaux :

* auto trading ON/OFF ;
* mode DEMO/REAL ;
* risque maximum par trade en % ;
* risque maximum journalier ;
* perte maximale journalière ;
* drawdown maximum ;
* profit journalier facultatif pour arrêter ;
* lot maximum ;
* positions simultanées maximum ;
* positions par instrument maximum ;
* exposition maximum ;
* spread maximum ;
* slippage/deviation maximum ;
* signal maximum age ;
* SL obligatoire ;
* TP obligatoire ;
* ratio RR minimum facultatif ;
* nombre maximum de pertes consécutives ;
* pause automatique après N pertes ;
* heures autorisées ;
* jours autorisés ;
* instruments autorisés ;
* canaux autorisés.

Le RiskManager ne doit jamais être contourné.

# 24. CALCUL DU LOT

NE PAS utiliser des calculs de pips codés en dur pour tous les instruments.

Utiliser les informations réelles retournées par MT5 :

* point ;
* digits ;
* trade_tick_size ;
* trade_tick_value ;
* volume_min ;
* volume_max ;
* volume_step ;
* contract_size lorsque pertinent.

Utiliser également les fonctions MT5 de calcul de profit/marge lorsque cela améliore la précision.

Exemple conceptuel :

capital risqué =
balance × riskPercent

Puis calculer le volume permettant que la perte au SL ne dépasse pas ce capital.

Arrondir selon volume_step.

Limiter selon :

* volume_min ;
* volume_max ;
* lotMaximum utilisateur.

Si le volume valide est impossible :

REFUSER LE TRADE.

# 25. VALIDATION D’UN SIGNAL

Avant order_send vérifier au minimum :

* Bridge connecté ;
* MT5 connecté ;
* compte correct ;
* auto trading actif ;
* compte autorisé ;
* canal autorisé ;
* symbole disponible ;
* symbole autorisé ;
* BUY/SELL autorisé ;
* signal non dupliqué ;
* signal non périmé ;
* Entry cohérente ;
* SL cohérent ;
* TP cohérent ;
* spread acceptable ;
* marché accessible ;
* volume valide ;
* marge suffisante ;
* risque acceptable ;
* limites journalières respectées ;
* drawdown respecté ;
* pertes consécutives respectées ;
* order_check MT5 réussi.

Sinon :

NE PAS envoyer l’ordre.

Journaliser clairement le motif.

# 26. GESTION DES DOUBLONS

C’est obligatoire.

Créer un identifiant/idempotency key basé sur :

channelId
telegramMessageId
signal
symbol
action

Un message Telegram ne doit jamais produire accidentellement deux ordres.

Les reconnexions réseau ne doivent pas dupliquer les trades.

# 27. EXÉCUTION MT5

Supporter :

BUY market
SELL market

BUY LIMIT
SELL LIMIT

BUY STOP
SELL STOP

Puis si utile selon MT5 :

BUY STOP LIMIT
SELL STOP LIMIT

Supporter :

* SL ;
* TP ;
* modification ;
* annulation pending ;
* fermeture totale ;
* fermeture partielle ;
* Break Even ;
* déplacement du SL.

Les caractéristiques du symbole et les contraintes broker doivent être vérifiées avant chaque envoi.

# 28. PLUSIEURS TAKE PROFITS

Un signal peut contenir :

TP1
TP2
TP3
TP4
...

Prévoir plusieurs stratégies configurables :

A. TP1 uniquement comme TP final.

B. Plusieurs positions séparées :
exemple :
30 % TP1
30 % TP2
40 % TP3

C. Une seule position + fermetures partielles.

Ne pas imposer une seule stratégie.

L’utilisateur choisit la stratégie globale ou par canal.

# 29. BREAK EVEN

Paramètres :

Break Even automatique :
ON/OFF

Déclencheur :

* TP1 atteint ;
* X R atteint ;
* X points atteint.

Offset facultatif :
entrée + petit buffer.

Toujours respecter :

* stop level broker ;
* freeze level ;
* précision du symbole.

# 30. TRAILING STOP

Prévoir un trailing stop optionnel.

Modes :

* distance fixe ;
* après TP1 ;
* basé sur R ;
* étapes configurables.

Ne pas utiliser l’IA pour le trailing stop.

# 31. PAGE ACCUEIL

Afficher :

Balance
Equity
Profit aujourd’hui
Perte aujourd’hui
Drawdown
Marge libre

Statut :

Bridge
Telegram
MT5
OpenRouter
Auto trading

Afficher ensuite :

Positions ouvertes
Derniers signaux
Derniers événements

Boutons :

PAUSE AUTO TRADING

et séparément :

URGENCE

Ne pas confondre les deux.

# 32. PAUSE ET ARRÊT D’URGENCE

PAUSE AUTO TRADING :

* arrête seulement les nouveaux trades automatiques ;
* ne ferme PAS automatiquement les positions existantes.

URGENCE :

ouvrir un écran distinct.

Actions :

* Annuler tous les pending ;
* Fermer toutes les positions ;
* Tout fermer + suspendre l’automatisation.

Pour “Fermer toutes les positions” :

demander une confirmation forte.

Éviter tout clic accidentel.

# 33. PAGE SIGNAUX

Filtres :

* tous ;
* aujourd’hui ;
* canal ;
* instrument ;
* BUY ;
* SELL ;
* accepté ;
* rejeté ;
* exécuté ;
* erreur ;
* manuel ;
* automatique.

Card signal :

Canal
heure
symbole
direction
entry
SL
TP
confiance
statut
motif si rejeté

Permettre d’ouvrir le détail.

# 34. DÉTAIL DU SIGNAL

Afficher :

message Telegram original

↓ puis

interprétation

↓ puis

validation

↓ puis

calcul du risque

↓ puis

ordre MT5

↓ puis

résultat

Afficher une timeline :

Message reçu
Parser
Validation
Risk Check
Order Check
Order Send
Position ouverte
TP/SL/modifications
Fermeture

# 35. PAGE TRADES

Onglets :

Ouverts
Pending
Fermés

Position :

instrument
BUY/SELL
lot
entry
prix actuel
SL
TP
profit
heure
canal source

Actions manuelles :

Fermer
Fermer partiellement
Modifier SL
Modifier TP
BE

Toujours afficher une confirmation pour les actions sensibles.

# 36. STATISTIQUES

Créer de vraies statistiques.

Globales et par canal :

* P&L ;
* nombre de trades ;
* win rate ;
* loss rate ;
* break even ;
* profit factor ;
* average win ;
* average loss ;
* R moyen ;
* meilleur trade ;
* pire trade ;
* maximum drawdown ;
* pertes consécutives ;
* gains consécutifs ;
* résultats par instrument ;
* résultats par jour ;
* résultats par heure ;
* résultats par canal.

Ajouter des graphiques simples.

Ne pas transformer l’application en sapin de Noël.

# 37. JOURNAL

Tout événement important doit être enregistré.

Exemples :

Telegram connected
Telegram disconnected
Signal received
Signal parsed
AI fallback used
Signal rejected
Risk limit exceeded
Order check failed
Order sent
Position opened
SL modified
TP reached
Partial close
Position closed
MT5 disconnected
Bridge disconnected

Les secrets ne doivent JAMAIS apparaître dans les logs.

# 38. API BRIDGE

Créer une API versionnée.

Exemple :

/api/v1/health
/api/v1/pairing
/api/v1/dashboard

/api/v1/telegram/status
/api/v1/telegram/login/start
/api/v1/telegram/login/code
/api/v1/telegram/login/2fa

/api/v1/channels/search
/api/v1/channels
/api/v1/channels/{id}
/api/v1/channels/{id}/analyze

/api/v1/signals
/api/v1/signals/{id}

/api/v1/mt5/status
/api/v1/mt5/account
/api/v1/mt5/symbols

/api/v1/positions
/api/v1/orders
/api/v1/history

/api/v1/risk/settings

/api/v1/openrouter/status
/api/v1/openrouter/models
/api/v1/openrouter/test

/api/v1/trading/pause
/api/v1/trading/resume

/api/v1/emergency/cancel-pending
/api/v1/emergency/close-all

Adapter les routes si une organisation meilleure est pertinente.

# 39. WEBSOCKET

Flutter doit recevoir en temps réel :

* nouveau signal ;
* signal modifié ;
* position ouverte ;
* position modifiée ;
* position fermée ;
* P&L ;
* balance/equity ;
* état MT5 ;
* état Telegram ;
* état OpenRouter ;
* erreur importante.

Créer reconnexion automatique avec backoff.

# 40. MODE OFFLINE DU MOBILE

Flutter doit conserver localement :

* paramètres non sensibles ;
* dernières statistiques ;
* derniers signaux ;
* historique récent ;
* informations du dernier état.

Lorsque le Bridge est hors ligne :

afficher clairement :

BRIDGE HORS LIGNE.

Ne jamais prétendre qu’un ordre a été envoyé.

IMPORTANT :

Ne PAS mettre en file d’attente un trade automatique pour l’envoyer plusieurs minutes plus tard lorsque le Bridge revient.

Un signal de marché périmé doit être rejeté.

# 41. SÉCURITÉ BRIDGE ↔ MOBILE

Créer un système de pairing.

Lors de la première connexion :

Bridge génère un code ou QR pairing.

Flutter saisit/scanne ce code.

Après pairing :

générer un secret sécurisé.

Utiliser authentification sur toutes les routes sensibles.

Prévoir rotation/révocation du device token.

Ne jamais exposer une API de trading sans authentification.

Par défaut :

le Bridge écoute uniquement de manière sécurisée sur le réseau local.

Documenter clairement ce qui est nécessaire pour une utilisation distante.

# 42. SECRETS

Protéger :

* OpenRouter API key ;
* Telegram API Hash ;
* Telegram session ;
* secrets de pairing.

Utiliser :

* variables d’environnement ;
* stockage chiffré adapté ;
* secure storage Flutter.

Aucun secret dans Git.

Créer :

.env.example

avec uniquement des valeurs fictives.

# 43. BASE DE DONNÉES

Créer les migrations.

Tables/domaines au minimum :

settings
devices
telegram_account
channels
channel_settings
channel_analysis
messages
signals
signal_events
positions
orders
trades
risk_events
daily_statistics
ai_requests
audit_logs

Ne pas stocker inutilement des informations personnelles.

# 44. RÉSILIENCE

Gérer proprement :

* perte Internet ;
* redémarrage du Bridge ;
* redémarrage MT5 ;
* Telegram déconnecté ;
* OpenRouter indisponible ;
* modèle gratuit indisponible ;
* rate limit OpenRouter ;
* message Telegram supprimé ;
* signal dupliqué ;
* symbole inexistant ;
* marché fermé ;
* requote ;
* invalid stops ;
* volume incorrect ;
* marge insuffisante.

Le système doit échouer en mode SAFE.

En cas de doute :

ne pas trader.

# 45. NOTIFICATIONS ANDROID

Ajouter les notifications locales/push via le Bridge si possible.

Notifications importantes :

Signal reçu
Signal rejeté
Trade ouvert
TP atteint
SL atteint
Trade fermé
Limite de perte atteinte
Auto trading suspendu
Bridge hors ligne
MT5 hors ligne

Donner des réglages pour les activer/désactiver.

# 46. PARAMÈTRES

Sections :

Compte
Bridge
Telegram
MetaTrader
OpenRouter
Trading
Risk Management
Notifications
Apparence
Données
Logs
À propos

OpenRouter :

clé
modèle automatique
modèle sélectionné
test connexion
modèle actif

Telegram :

compte
état
reconnecter
déconnecter

MT5 :

état
login masqué
serveur
balance
mode demo/real

# 47. TESTS

Créer des tests sérieux.

Flutter :

* tests unitaires ;
* repositories ;
* parser ;
* risk calculations ;
* widgets critiques.

Python :

* pytest ;
* parser ;
* normalisation ;
* risk manager ;
* channel analyzer ;
* duplication ;
* signal matching ;
* order builder ;
* API ;
* OpenRouter mocks ;
* Telegram mocks ;
* MT5 mocks.

Créer un :

FakeMetaTraderService

pour tester sans argent réel.

# 48. DATASETS DE TEST

Créer beaucoup d’exemples de messages Telegram.

Exemples normaux, ambigus et mauvais.

Tester par exemple :

“GOLD BUY NOW
SL 3310
TP 3330”

“XAUUSD BUY 3320-3315
SL 3300
TP1 3330
TP2 3345
TP3 3360”

“Sell gold now @ 3341
stop 3350
targets 3330, 3320, 3300”

“TP1 HIT MOVE SL BE”

“CLOSE HALF”

“CLOSE GOLD NOW”

“GOOD MORNING FAMILY 🔥”

Le dernier ne doit évidemment PAS devenir un trade.

Créer au moins plusieurs dizaines de fixtures réalistes.

# 49. PROTECTION CONTRE LES HALLUCINATIONS

L’IA n’a jamais le dernier mot.

Exemple :

Message :

“Gold looking good today.”

L’IA ne doit pas pouvoir produire :

BUY XAUUSD.

Le système doit répondre :

NO_ACTION.

Exiger une intention de trade suffisamment explicite.

# 50. SCORE DE CONFIANCE

Créer un score du parser.

Exemple :

1.00 = structure parfaitement reconnue localement.

0.80 = IA utilisée mais toutes les données sont cohérentes.

0.40 = informations ambiguës.

Paramètre :

Minimum confidence for automatic execution.

Par défaut élevé.

En dessous :

NEEDS_REVIEW.

# 51. VALIDATION MANUELLE

Même si l’automatisation existe, permettre un mode :

Validation manuelle.

Signal détecté :

XAUUSD BUY

Entry
SL
TP
Lot calculé
Risque

Boutons :

REFUSER
EXÉCUTER

Après expiration du délai :

signal invalide.

# 52. MODE AUTOMATIQUE

En mode automatique :

Signal
→ Parser
→ Validation
→ RiskManager
→ order_check
→ order_send.

Même en AUTO :

aucun contournement des protections.

# 53. APPRENTISSAGE DES FORMATS DE CANAUX

Ne pas faire de machine learning opaque.

Créer plutôt des profils/templates.

Exemple :

ChannelParserProfile

channelId
symbolAliases
knownFormats
confidence
lastSuccessfulFormat

Le moteur apprend qu’un canal utilise une structure particulière et privilégie ce template.

# 54. MAPPING DES SYMBOLES EXNESS

Créer une page :

Symbol Mapping.

Exemple :

Telegram :
GOLD

Canonical :
XAUUSD

MT5 :
symbole réellement trouvé automatiquement.

Ne jamais supposer aveuglément que le broker utilise exactement le même nom.

Proposer automatiquement les correspondances à partir des symboles disponibles dans MT5.

# 55. DONNÉES DE MARCHÉ

Le Bridge MT5 est la source prioritaire pour :

* BID ;
* ASK ;
* spread ;
* symbol metadata ;
* historique nécessaire aux simulations.

Ne pas ajouter une API de données de marché payante inutilement.

# 56. AUCUNE API PAYANTE OBLIGATOIRE

L’application doit être exploitable sans abonnement logiciel supplémentaire.

OpenRouter :
utiliser uniquement les modèles gratuits sélectionnés.

Telegram :
API officielle/MTProto.

Trading :
MT5 + compte Exness.

Ne pas intégrer un service payant comme dépendance obligatoire.

# 57. DOCUMENTATION À PRODUIRE

Créer :

README.md

docs/ARCHITECTURE.md
docs/ANDROID_SETUP.md
docs/BRIDGE_WINDOWS_SETUP.md
docs/MT5_EXNESS_SETUP.md
docs/TELEGRAM_SETUP.md
docs/OPENROUTER_SETUP.md
docs/RISK_MANAGEMENT.md
docs/CHANNEL_DISCOVERY.md
docs/CHANNEL_ANALYSIS.md
docs/SECURITY.md
docs/DEMO_TESTING.md
docs/GO_LIVE_CHECKLIST.md
docs/TROUBLESHOOTING.md

# 58. INSTALLATION WINDOWS

Créer des scripts PowerShell :

scripts/install_bridge.ps1
scripts/start_bridge.ps1
scripts/check_environment.ps1

Ils doivent :

* vérifier Python ;
* créer le venv ;
* installer les dépendances ;
* vérifier MT5 ;
* créer le fichier de configuration si nécessaire ;
* lancer le Bridge.

Prévoir également un packaging PyInstaller si raisonnable afin de produire un exécutable facile à lancer.

Ne pas prétendre embarquer MetaTrader lui-même.

# 59. BUILD ANDROID

Configurer complètement Flutter Android.

Vérifier :

flutter pub get
flutter analyze
flutter test
flutter build apk

Corriger les erreurs.

À la fin, l’APK doit pouvoir être généré.

# 60. ÉCRAN DIAGNOSTIC

Créer une page très importante :

Diagnostic système.

Afficher :

Flutter
✅

Bridge
✅/❌

Telegram
✅/❌

OpenRouter
✅/❌

MetaTrader 5
✅/❌

Compte
DEMO/REAL

Market connection
✅/❌

WebSocket
✅/❌

Dernier signal
...

Dernier trade
...

Ajouter :

Tester Telegram
Tester OpenRouter
Tester MT5
Tester WebSocket
Tester notification

Ne PAS mettre un bouton qui envoie un trade réel pour tester.

Pour tester l’exécution :

utiliser uniquement le simulateur ou un compte Demo explicitement détecté.

# 61. OBSERVABILITÉ

Logs structurés.

Niveaux :
DEBUG
INFO
WARNING
ERROR
CRITICAL

Créer rotation des fichiers de logs.

Créer un export de diagnostic depuis Flutter.

Masquer les secrets dans tout export.

# 62. UX ERREURS

Pas d’erreur technique incompréhensible comme :

SocketException 10061.

Afficher :

“Impossible de joindre le Bridge.”

Et dans détails :

message technique.

Même principe pour MT5, Telegram et OpenRouter.

# 63. PERFORMANCE

Ne pas interroger MT5 toutes les 50 ms.

Définir des intervalles raisonnables.

Utiliser WebSocket pour pousser les changements vers Flutter.

Éviter les rebuilds Flutter inutiles.

Paginer :

* logs ;
* signaux ;
* historique ;
* messages.

# 64. ÉVÉNEMENTS DE TRADING

Créer une vraie machine d’état.

Exemple :

RECEIVED
PARSED
NEEDS_REVIEW
VALIDATED
REJECTED
APPROVED
ORDER_CHECKED
SENT
OPEN
PARTIALLY_CLOSED
MODIFIED
CLOSED
FAILED

Conserver les transitions.

# 65. AUDIT

Pour chaque trade, je veux pouvoir savoir exactement :

* quel canal ;
* quel message ;
* quelle heure ;
* quelle interprétation ;
* parser local ou IA ;
* quel modèle IA ;
* score de confiance ;
* quels contrôles de risque ;
* lot calculé ;
* prix demandé ;
* prix exécuté ;
* résultat MT5 ;
* raison de fermeture.

# 66. NE JAMAIS FAIRE CECI

Ne jamais :

* inventer un SL ;
* inventer un TP ;
* inventer une direction ;
* augmenter le lot pour “récupérer une perte” ;
* activer une martingale par défaut ;
* multiplier automatiquement le risque après une perte ;
* laisser l’IA contourner le RiskManager ;
* envoyer un trade réel lors d’un test ;
* exposer une API sans authentification ;
* enregistrer les secrets dans Git ;
* exécuter un vieux signal après reconnexion réseau.

# 67. MARTINGALE

Ne pas implémenter de martingale automatique par défaut.

Si une option avancée est prévue un jour :

elle doit être explicitement désactivée et séparée.

Pour le projet actuel :

pas de martingale.

# 68. CRITÈRES AVANT LE LIVE

Créer une checklist.

Le mode réel doit rester désactivé jusqu’à ce que l’utilisateur ait au minimum vérifié :

* MT5 Demo connecté ;
* Telegram connecté ;
* plusieurs signaux reçus ;
* parser vérifié ;
* aucune duplication ;
* SL/TP corrects ;
* lot calculé correctement ;
* fermeture correcte ;
* Break Even correct ;
* limites de risque testées ;
* reconnexion testée ;
* arrêt automatique testé ;
* emergency stop testé.

Ne jamais affirmer que cela rend le trading sans risque.

# 69. RECHERCHE DES CANAUX : EXPÉRIENCE UTILISATEUR

Puisque je n’ai aucun canal aujourd’hui, cette fonction doit être réellement agréable.

Écran :

Découvrir

Barre de recherche.

Suggestions :

Gold / XAUUSD
Forex
Scalping
EURUSD
GBPUSD
Indices

Résultats.

Après sélection :

Voir activité

Analyser 100 messages
Analyser 250 messages
Analyser 500 messages

Puis rapport.

Bouton :

Ajouter à ma surveillance

Ensuite :

Mode observation uniquement

Je veux que le canal commence d’abord en mode OBSERVATION.

L’utilisateur pourra ensuite choisir :

MANUEL
AUTO

# 70. MODE OBSERVATION

Créer trois modes par canal :

OBSERVE
MANUAL
AUTO

OBSERVE :

* reçoit ;
* parse ;
* simule ;
* ne trade jamais.

MANUAL :

* reçoit ;
* parse ;
* propose ;
* utilisateur confirme.

AUTO :

* reçoit ;
* parse ;
* valide ;
* exécute si toutes les protections réussissent.

Un nouveau canal doit être en :

OBSERVE

par défaut.

# 71. PAPER TRADING

Créer un véritable mode Paper Trading interne.

Il permet de :

* recevoir les signaux ;
* simuler leur exécution ;
* suivre les résultats ;
* tester un canal sans compte réel.

Modes généraux :

PAPER
MT5 DEMO
MT5 LIVE

Par défaut :

PAPER.

Puis :

MT5 DEMO.

MT5 LIVE uniquement plus tard et explicitement.

# 72. TABLEAU DE COMPARAISON DES CANAUX

Permettre de comparer plusieurs canaux selon des données observées :

* signaux détectés ;
* parse rate ;
* SL rate ;
* TP rate ;
* fréquence ;
* trades simulables ;
* résultats paper ;
* drawdown paper ;
* R moyen ;
* historique disponible.

L’application ne doit pas désigner arbitrairement un “meilleur trader”.

Présenter les données.

# 73. OPENROUTER ET RATE LIMIT

Les modèles gratuits peuvent avoir des quotas ou des indisponibilités.

Gérer :

* 429 ;
* timeout ;
* 5xx ;
* modèle indisponible ;
* contexte trop long.

Retry seulement lorsque cela est raisonnable.

Ne jamais répéter 20 appels inutilement.

Créer circuit breaker.

Si l’IA tombe :

le parser déterministe continue.

Si le message nécessite absolument l’IA :

NEEDS_REVIEW.

Jamais :

IA indisponible → envoyer quand même le trade.

# 74. CONFIDENTIALITÉ

N’envoyer à OpenRouter que le texte strictement nécessaire.

Ne pas envoyer :

* identifiants MT5 ;
* mot de passe ;
* login Exness ;
* clé Telegram ;
* session ;
* balance ;
* informations non nécessaires.

# 75. SAUVEGARDE

Créer export/import local des paramètres non secrets et statistiques.

Pour les secrets :
ne jamais les mettre dans un export non chiffré.

Prévoir sauvegarde chiffrée si tu implémentes cette fonction.

# 76. VERSIONING

Prévoir migrations de base de données.

Prévoir version de l’API.

Ne pas casser les anciennes données à chaque mise à jour.

# 77. QUALITÉ DE CODE

Pas de fichiers énormes de 3 000 lignes.

Séparer :

* UI ;
* domain ;
* data ;
* services ;
* repositories.

Commentaires seulement lorsqu’ils apportent réellement quelque chose.

Noms clairs.

Gestion d’erreurs propre.

# 78. CE QUE JE VEUX À LA FIN

Je veux un dépôt réellement exploitable contenant :

1. application Flutter complète ;
2. Bridge Python fonctionnel ;
3. intégration MT5 ;
4. intégration Telegram ;
5. recherche de canaux ;
6. monitoring des canaux ;
7. parser local ;
8. parser IA OpenRouter ;
9. gestion dynamique des modèles gratuits ;
10. Paper Trading ;
11. MT5 Demo ;
12. possibilité de Live explicitement protégée ;
13. Risk Manager ;
14. exécution des trades ;
15. SL/TP ;
16. TP multiples ;
17. Break Even ;
18. fermeture partielle ;
19. pending orders ;
20. suivi des positions ;
21. statistiques ;
22. analyse des canaux ;
23. comparaison des canaux ;
24. analyse IA de captures de graphiques ;
25. WebSocket ;
26. notifications ;
27. logs ;
28. diagnostic ;
29. tests ;
30. documentation ;
31. scripts d’installation ;
32. build APK.

# 79. ORDRE DE TRAVAIL

Tu peux organiser l’implémentation intelligemment, mais ne me rends pas uniquement un plan.

Commence par inspecter l’environnement et le dépôt.

Ensuite crée une checklist technique interne et implémente réellement les composants.

Après chaque gros bloc :

* compile ;
* teste ;
* corrige.

Ne me demande pas :

“Voulez-vous que je continue ?”

Continue.

# 80. SI UNE INFORMATION EXTERNE EST INCERTAINE

Si une API, un package Flutter, Telethon, MetaTrader5 ou OpenRouter a changé :

consulte sa documentation actuelle avant de coder.

Ne programme pas à partir d’une API obsolète.

# 81. SI MT5 N’EST PAS DISPONIBLE SUR LA MACHINE DE DÉVELOPPEMENT

Ne bloque pas tout le projet.

Implémente :

MetaTraderService interface

avec :

RealMetaTraderService
FakeMetaTraderService

Le Fake permet les tests.

Mais le Real doit être entièrement codé.

Indique clairement dans les diagnostics :

MT5 REAL NOT TESTED ON THIS MACHINE

si tu n’as pas réellement pu le lancer.

Ne prétends jamais qu’une intégration a été testée si elle ne l’a pas été.

# 82. PREMIER OBJECTIF END-TO-END

Avant de considérer le projet comme correctement intégré, ce scénario doit fonctionner :

Telegram reçoit :

XAUUSD BUY
ENTRY 3320
SL 3310
TP1 3330
TP2 3340

Le système :

1. reçoit le message ;
2. le stocke ;
3. le parse ;
4. normalise XAUUSD ;
5. identifie BUY ;
6. identifie Entry ;
7. identifie SL ;
8. identifie TP1/TP2 ;
9. calcule le score de confiance ;
10. passe le RiskManager ;
11. calcule le lot ;
12. vérifie le signal ;
13. exécute en Paper ou MT5 Demo ;
14. affiche le résultat dans Flutter ;
15. reçoit les changements via WebSocket ;
16. écrit l’audit complet.

Puis si Telegram publie :

TP1 HIT
MOVE SL TO BE

le système doit :

1. rattacher le message à la position ;
2. enregistrer TP1 ;
3. appliquer la stratégie de prise partielle configurée ;
4. déplacer le SL au Break Even si la configuration l’autorise ;
5. mettre à jour Flutter en temps réel.

# 83. SECOND SCÉNARIO CRITIQUE

Telegram publie :

“Gold is looking very bullish today 🔥”

Résultat :

NO_ACTION.

Aucun trade.

# 84. TROISIÈME SCÉNARIO CRITIQUE

Telegram publie un vrai signal.

Mais :

* perte journalière maximale atteinte.

Résultat :

REJECTED
DAILY_LOSS_LIMIT

Aucun trade.

# 85. QUATRIÈME SCÉNARIO CRITIQUE

Le même message Telegram est reçu deux fois à cause d’une reconnexion.

Résultat :

un seul trade.

# 86. CINQUIÈME SCÉNARIO CRITIQUE

OpenRouter tombe en panne.

Signal parfaitement structuré :

le parser local peut continuer.

Signal ambigu :

NEEDS_REVIEW.

Aucun trade ambigu.

# 87. SIXIÈME SCÉNARIO CRITIQUE

Bridge coupé au moment du signal.

Le téléphone affiche :

Bridge hors ligne.

Lorsque le Bridge revient 10 minutes plus tard :

NE PAS envoyer automatiquement le vieux signal.

# 88. FINALISATION

Lorsque l’implémentation est terminée :

exécute tous les tests disponibles.

Flutter :
flutter analyze
flutter test
flutter build apk

Backend :
tests Python
lint/type checks configurés

Corrige les problèmes.

Puis donne-moi un rapport FINAL contenant :

* ce qui a été créé ;
* structure du projet ;
* fonctionnalités opérationnelles ;
* tests réussis ;
* APK générée et son emplacement si disponible ;
* comment lancer le Bridge ;
* comment connecter MT5 Exness ;
* comment connecter Telegram ;
* comment créer/configurer OpenRouter ;
* comment rechercher les premiers canaux ;
* comment démarrer en PAPER ;
* comment passer en MT5 DEMO ;
* quelles parties n’ont pas pu être testées réellement ;
* erreurs ou limites restantes.

Ne remplace jamais une fonctionnalité réelle par une simple interface factice sans me le dire.

Construis maintenant le projet complet.


utilise le gradwle deja telecharge en cache


url :  https://votre-domaine.ngrok-free.app 