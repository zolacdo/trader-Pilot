# MetaTrader 5 et compte Exness

Ce document décrit la mise en place du terminal MetaTrader 5 sur lequel repose
tout le côté exécution de TradePilot.

Point de départ à garder en tête : **le Bridge ne parle pas au serveur du
broker.** Il pilote le terminal **MetaTrader 5 Desktop** installé sur le même PC,
via le paquet Python `MetaTrader5`. Sans terminal ouvert et connecté, aucun
ordre ne peut partir, aucun prix ne peut être lu.

---

## 1. Installer MetaTrader 5

1. Téléchargez MetaTrader 5 **depuis le site de votre broker** (Exness), pas
   depuis un site tiers. La build fournie par le broker contient déjà les
   serveurs de celui-ci.
2. Installez-le avec les options par défaut. L'emplacement typique est
   `C:\Program Files\MetaTrader 5 EXNESS\`.
3. Lancez le terminal une première fois pour qu'il se configure.

Le Bridge cherche `terminal64.exe` automatiquement dans ces emplacements
(`bridge/app/services/mt5/real_service.py`, fonction `detect_terminals`) :

```
C:\Program Files\MetaTrader 5*\terminal64.exe
C:\Program Files\*MetaTrader*\terminal64.exe
C:\Program Files (x86)\*MetaTrader*\terminal64.exe
%APPDATA%\MetaQuotes\Terminal\*\terminal64.exe
%APPDATA%\MetaQuotes\Terminal\*\*\terminal64.exe
```

Si votre installation est ailleurs, renseignez le chemin complet dans
`bridge\.env` :

```
MT5_TERMINAL_PATH=D:\Trading\MetaTrader 5 EXNESS\terminal64.exe
```

Le paquet Python doit également être présent dans l'environnement virtuel du
Bridge. Il est installé par `scripts\install_bridge.ps1` et n'existe **que sous
Windows** :

```powershell
.\bridge\.venv\Scripts\python.exe -c "import MetaTrader5; print(MetaTrader5.__version__)"
```

Si ce paquet est absent, le Bridge démarre quand même : il signale MetaTrader 5
comme `NOT_CONFIGURED` dans son diagnostic et seul le mode `PAPER` avec prix
simulés reste utilisable.

---

## 2. Ouvrir un compte démo Exness

Travaillez **d'abord et longtemps** sur un compte de démonstration. C'est la
règle par défaut du projet, et le mode `MT5_LIVE` est verrouillé tant que vous ne
le déverrouillez pas explicitement.

1. Créez un compte sur <https://www.exness.com> et validez votre adresse
   électronique.
2. Dans l'espace personnel, ouvrez un **compte de démonstration** (Demo). Exness
   propose plusieurs types : *Standard*, *Standard Cent*, *Pro*, *Raw Spread*,
   *Zero*. Le type retenu détermine les suffixes de symboles que vous verrez
   (voir la section 5). Un compte *Standard* en démo est un bon point de départ.
3. Notez le **numéro de compte**, le **mot de passe** et surtout le **nom exact
   du serveur** (par exemple `Exness-MT5Trial8`). Le nom du serveur est
   indispensable pour se connecter.

---

## 3. Se connecter dans MT5 Desktop

Dans le terminal : *Fichier → Se connecter à un compte de trading*.

1. Saisissez le numéro de compte et le mot de passe.
2. Choisissez le serveur exactement tel que fourni par Exness.
3. Cochez **Conserver le mot de passe**. C'est nécessaire pour que le terminal se
   reconnecte tout seul après un redémarrage du PC, sans intervention.

Vérification : en bas à droite du terminal, l'indicateur doit afficher un débit
de données actif (par exemple `2/1 kb`) et non « Pas de connexion ».

### 3.1 Faut-il renseigner les identifiants dans `bridge\.env` ?

**Non, et c'est le mode recommandé.** Laissez `MT5_LOGIN`, `MT5_PASSWORD` et
`MT5_SERVER` vides. Le Bridge se contente alors d'un `mt5.initialize()` et
réutilise la session déjà ouverte dans le terminal. Aucun identifiant n'est
stocké nulle part.

Si les trois variables sont renseignées, le Bridge effectue en plus un
`mt5.login(...)` explicite. Les journaux ne montrent alors que les trois derniers
chiffres du numéro de compte et jamais le mot de passe, mais vous avez inscrit un
mot de passe de trading en clair dans un fichier : ne le faites que si vous en
avez réellement besoin.

---

## 4. Activer l'AutoTrading

C'est l'étape la plus souvent oubliée. Deux réglages distincts, tous les deux
obligatoires.

### 4.1 Le bouton AutoTrading

Dans la barre d'outils du terminal, le bouton **AutoTrading** (ou *Trading
algorithmique*). Il doit être **vert**. S'il est rouge, cliquez dessus.

Raccourci clavier : `Ctrl + E`.

### 4.2 L'option globale

*Outils → Options → Expert Advisors* : cochez **Autoriser le trading
algorithmique**.

Sans ces deux réglages, tout `order_send` est refusé par le terminal avec le code
`10027` — « Trading automatique désactivé dans le terminal ». Le Bridge traduit
ce code et le fait remonter tel quel dans le journal et dans la timeline du
signal.

### 4.3 Le compte doit aussi autoriser le trading

Certains comptes (investisseur en lecture seule, compte archivé, restriction
appliquée par le broker) n'autorisent pas le trading. Le Bridge lit
`account_info().trade_allowed` et refuse d'exécuter avec le motif
`MT5_DISCONNECTED` et le détail « Le trading n'est pas autorisé sur ce compte ou
dans le terminal ». Le code de retour côté broker serait `10017`.

### 4.4 Démarrage automatique du terminal

Le Bridge a besoin que MT5 soit lancé **avant** lui. Pour que le terminal démarre
avec Windows :

1. `Windows + R`, tapez `shell:startup`, validez ;
2. déposez-y un raccourci vers
   `C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe`.

La tâche planifiée du Bridge (`scripts\install_autostart.ps1`) attend 60 secondes
après l'ouverture de session, ce qui laisse au terminal le temps de se connecter.
Le détail est documenté dans [BRIDGE_WINDOWS_SETUP.md](BRIDGE_WINDOWS_SETUP.md).

---

## 5. Vérifier que le Bridge détecte le terminal

### 5.1 Au démarrage du Bridge

La console affiche l'une de ces trois situations :

| Message | Signification |
|---|---|
| `MetaTrader 5 connecte : serveur Exness-MT5Trial8, compte DEMO, 10000.0 USD` | tout va bien |
| `Terminal MetaTrader 5 detecte mais non connecte. Ouvrez MT5 Desktop et connectez-vous a votre compte Exness.` | le terminal existe mais n'a pas de session ouverte |
| `MetaTrader 5 indisponible : Le paquet MetaTrader5 n'est pas installe sur cette machine.` | le paquet Python manque |

### 5.2 Par le diagnostic PowerShell

```powershell
cd "C:\Users\<votre-nom>\Desktop\trader apk"
.\scripts\check_environment.ps1
```

Le rapport contient une section MetaTrader 5 indiquant le nombre d'installations
trouvées, leur chemin et si le processus `terminal64` tourne.

### 5.3 Par l'API

Toutes ces routes exigent le jeton de périphérique obtenu à l'appairage.

| Route | Ce qu'elle renvoie |
|---|---|
| `GET /api/v1/mt5/status` | état de connexion, chemin du terminal, dernière erreur, compte, informations du terminal, `realTestedOnThisMachine` |
| `GET /api/v1/mt5/account` | compte réellement utilisé par le mode d'exécution actif, avec `kind` (`DEMO`, `REAL`, `UNKNOWN`) |
| `POST /api/v1/mt5/reconnect` | force une reconnexion (coupure puis relance, avec attente croissante) |
| `GET /api/v1/mt5/symbols?search=XAU` | liste filtrée des symboles réellement disponibles |
| `GET /api/v1/mt5/symbols/{symbol}` | métadonnées complètes d'un symbole plus le tick courant et le spread en points |
| `POST /api/v1/diagnostics/test/mt5` | test de connexion, sans envoyer le moindre ordre |
| `GET /api/v1/diagnostics` | vue d'ensemble, avec les avertissements |

Une fois la connexion établie, le Bridge rafraîchit compte et positions toutes
les `MT5_POLL_INTERVAL` secondes (`2.0` par défaut).

### 5.4 L'avertissement « MT5 REAL NOT TESTED ON THIS MACHINE »

Tant qu'aucune connexion réelle au terminal n'a réussi depuis ce poste, le
diagnostic affiche :

```
MT5 REAL NOT TESTED ON THIS MACHINE : l'integration MetaTrader n'a pas encore ete
validee par une connexion reelle depuis ce poste.
```

Cet avertissement n'apparaît que si le mode d'exécution n'est pas `PAPER`. Il est
volontairement explicite : il ne faut pas supposer que l'intégration fonctionne
avant de l'avoir constatée.

---

## 6. Les suffixes de symboles Exness

C'est la source d'erreur la plus fréquente lorsqu'on copie des signaux.

Un canal Telegram écrit `GOLD`, `XAUUSD`, `XAU/USD` ou `OR`. Votre broker, lui,
n'expose presque jamais ce nom tel quel : selon le type de compte, l'or peut
s'appeler `XAUUSD`, `XAUUSDm`, `XAUUSD.r`, `XAUUSDc`, `XAUUSDz`… Le suffixe
identifie le type de compte (micro, cent, raw spread, zero…).

TradePilot résout cela en **deux étapes distinctes**.

### 6.1 Étape 1 — alias vers symbole canonique

`bridge/app/services/signals/symbols.py` traduit ce qu'écrit le canal en un
symbole canonique, sans jamais interroger le broker.

| Ce que le canal écrit | Symbole canonique |
|---|---|
| `GOLD`, `XAU`, `OR`, `GOLDUSD`, `XAU/USD` | `XAUUSD` |
| `SILVER`, `XAG` | `XAGUSD` |
| `DOW`, `DJI`, `DJIA`, `WALLSTREET`, `US30` | `US30` |
| `NASDAQ`, `NAS`, `USTEC`, `NDX`, `US100` | `NAS100` |
| `SP500`, `SPX`, `US500` | `SPX500` |
| `DAX`, `DAX40`, `DE40`, `GER30` | `GER40` |
| `FTSE`, `FTSE100` | `UK100` |
| `NIKKEI` | `JP225` |
| `CAC40` | `FRA40` |
| `OIL`, `WTI`, `CRUDE`, `USOIL` | `XTIUSD` |
| `BRENT`, `UKOIL` | `XBRUSD` |
| `NATGAS`, `GAS` | `XNGUSD` |
| `BTC`, `BITCOIN`, `BTCUSDT` | `BTCUSD` |
| `EU`, `FIBER` | `EURUSD` |
| `GU`, `CABLE` | `GBPUSD` |
| `UJ` | `USDJPY` |
| `GJ` | `GBPJPY` |

Toute paire de devises correctement formée est également reconnue
(`EURUSD`, `AUDNZD`, `EUR/USD`, `EUR USD`…). Un suffixe broker écrit par le canal
est également toléré : `XAUUSDM` est ramené à `XAUUSD`.

Chaque canal apprend en plus **ses propres alias** : lorsque le parser voit
`GOLD` produire `XAUUSD` sur ce canal, la correspondance est mémorisée dans
`channel_parser_profiles.symbol_aliases`.

### 6.2 Étape 2 — symbole canonique vers symbole broker

`bridge/app/services/trading/symbol_resolver.py` interroge la **liste réelle des
symboles MT5**. Il ne suppose jamais que le broker utilise le nom canonique.

Ordre de résolution :

1. **cache mémoire** de la session courante ;
2. **correspondance enregistrée** dans la table `symbol_mappings`, si elle
   correspond à un symbole encore valide chez le broker ;
3. **essais directs** : le nom canonique, puis le nom suivi de chacun de ces
   suffixes, dans cet ordre —
   `""`, `m`, `c`, `z`, `e`, `.r`, `.a`, `micro`, `_i`, `.p`, `pro`, `ecn`,
   `#`, `+` ;
4. **recherche dans la liste complète** des symboles du terminal : correspondance
   exacte du jeton nettoyé, puis symboles commençant par ce jeton (le nom le plus
   court d'abord, donc `XAUUSD` avant `XAUUSD.raw`), puis symboles dont le
   suffixe broker retiré donne le jeton cherché.

Une correspondance trouvée automatiquement est enregistrée dans
`symbol_mappings` avec `auto_detected = true`, et le symbole est rendu visible
dans le *Market Watch* du terminal si nécessaire (`ensure_symbol`).

Si rien n'est trouvé, le signal est refusé avec le motif `SYMBOL_NOT_FOUND` et le
détail « XAUUSD introuvable chez le broker ». Aucun ordre n'est envoyé « au cas
où » sur un nom approchant.

### 6.3 L'écran de correspondance des symboles

L'écran **Correspondance des symboles** de l'application (route `/more/symbols`)
s'appuie sur ces routes :

| Route | Rôle |
|---|---|
| `GET /api/v1/symbols/mappings` | liste des correspondances connues, avec `autoDetected` et `enabled` |
| `PUT /api/v1/symbols/mappings` | crée ou corrige une correspondance : `alias`, `canonical`, `brokerSymbol`. Une correspondance saisie ici est marquée `autoDetected = false` et le cache du résolveur est invalidé. |
| `DELETE /api/v1/symbols/mappings/{mapping_id}` | supprime une correspondance |
| `GET /api/v1/symbols/suggestions/{canonical}` | propose jusqu'à 8 symboles broker plausibles pour un symbole canonique |

Cas d'usage typique : le résolveur a retenu `XAUUSDm` alors que votre compte
utilise `XAUUSD.r`. Vous consultez les suggestions pour `XAUUSD`, vous choisissez
le bon nom et vous enregistrez la correspondance. Le prochain signal or partira
sur `XAUUSD.r`.

Ces routes s'utilisent aussi directement, par exemple avec `Invoke-RestMethod`
depuis PowerShell (voir [DEMO_TESTING.md](DEMO_TESTING.md) pour la forme des
appels authentifiés).

### 6.4 Vérifier manuellement les symboles disponibles

Depuis le terminal : *Affichage → Symboles* (`Ctrl + U`) montre l'arborescence
complète des instruments de votre compte, avec leurs noms exacts.

---

## 7. Compte démo et compte réel

### 7.1 Comment le Bridge fait la différence

Il lit `account_info().trade_mode`, une valeur fournie par MetaTrader 5 :

| `trade_mode` | `AccountKind` |
|---|---|
| `0` (démonstration) | `DEMO` |
| `1` (concours) | `DEMO` |
| `2` (réel) | `REAL` |
| autre valeur, ou information absente | `UNKNOWN` |

### 7.2 Pourquoi le Bridge refuse d'exécuter sur `UNKNOWN`

Parce qu'un compte indéterminable pourrait être un compte réel.

Supposer « c'est sûrement une démo » reviendrait à envoyer de vrais ordres avec
de l'argent réel sur la base d'une supposition. Le code choisit l'inverse :
`AccountKind.UNKNOWN` **bloque** l'exécution, en `MT5_DEMO` comme en `MT5_LIVE`.

Concrètement :

| Situation | Comportement |
|---|---|
| mode `MT5_DEMO`, compte `DEMO` | exécution autorisée |
| mode `MT5_DEMO`, compte `REAL` | refus `ACCOUNT_MISMATCH` — « Le compte MT5 connecté est un compte RÉEL alors que le mode demandé est DEMO » |
| mode `MT5_DEMO`, compte `UNKNOWN` | refus `ACCOUNT_MISMATCH` — « Impossible de déterminer si le compte est demo ou réel : exécution refusée » |
| mode `MT5_LIVE`, `live_unlocked = false` | refus `LIVE_NOT_UNLOCKED` |
| passage en `MT5_LIVE` demandé, compte `UNKNOWN` | la route `POST /api/v1/trading/execution-mode` répond `409` et refuse le changement de mode |
| n'importe quel mode MT5, compte non joignable | refus `MT5_DISCONNECTED` |
| mode `PAPER` | aucun de ces contrôles ne s'applique : rien ne part vers le broker |

Le diagnostic affiche également un avertissement dédié lorsque le type de compte
est `UNKNOWN` et que le mode d'exécution n'est pas `PAPER`.

### 7.3 Que faire si le type reste `UNKNOWN`

1. Vérifiez que le terminal est bien connecté (l'indicateur en bas à droite).
2. Relancez `POST /api/v1/mt5/reconnect` ou redémarrez le Bridge.
3. Vérifiez que vous n'êtes pas connecté en **compte investisseur** (mot de passe
   investisseur), qui limite les informations retournées.
4. Consultez `GET /api/v1/mt5/status` : le champ `account.tradeAllowed` et le
   bloc `terminal` donnent des indices supplémentaires.

Tant que le doute persiste, restez en `PAPER`. Le paper trading utilise les prix
réels du terminal dès que celui-ci est connecté, ce qui reste un test utile.

---

## 8. Codes de retour MT5 les plus fréquents

Le Bridge traduit les codes du terminal (`bridge/app/services/mt5/interface.py`)
et les affiche tels quels dans le journal et dans la timeline du signal.

| Code | Message affiché | Cause typique |
|---|---|---|
| `10004` | Requote : le prix a changé avant l'exécution | marché rapide |
| `10006` | Requête refusée par le broker | restriction côté compte |
| `10008` | Ordre placé | succès, ordre en attente |
| `10009` | Requête exécutée | succès, position ouverte |
| `10010` | Requête exécutée partiellement | volume partiellement rempli |
| `10013` | Requête invalide | paramètre incohérent |
| `10014` | Volume invalide | pas de volume non respecté, hors bornes |
| `10015` | Prix invalide | prix hors marché pour un ordre en attente |
| `10016` | Stops invalides (SL/TP trop proches ou du mauvais côté) | `trade_stops_level` non respecté |
| `10017` | Trading désactivé sur le compte | compte en lecture seule |
| `10018` | Marché fermé | week-end, instrument hors horaires |
| `10019` | Fonds insuffisants | marge libre trop faible |
| `10021` | Aucune cotation pour traiter la requête | symbole non coté à cet instant |
| `10026` | Trading automatique désactivé par le serveur | restriction du broker |
| `10027` | **Trading automatique désactivé dans le terminal** | bouton AutoTrading rouge — voir section 4 |
| `10030` | Mode de remplissage non supporté | le Bridge choisit FOK, IOC ou RETURN selon le symbole |
| `10031` | Pas de connexion au serveur de trading | terminal déconnecté |
| `10034` | Volume total maximal atteint | limite du compte |

Les problèmes plus larges (terminal non détecté, base verrouillée, session
perdue) sont traités dans [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## 9. Ce qui n'a pas pu être vérifié sur cette machine

- **Aucun ordre réel n'a été envoyé** à MetaTrader 5, ni en démo ni en réel.
  L'ensemble de la couche `order_check` / `order_send` a été validé contre le
  simulateur `FakeMetaTraderService`, qui implémente le même contrat, mais pas
  contre un terminal Exness réel.
- La détection automatique du terminal, la lecture du compte, la résolution des
  suffixes de symboles Exness et la valeur réelle de `trade_mode` n'ont pas été
  observées sur une installation MetaTrader 5 connectée.
- Les codes de retour listés à la section 8 proviennent de la table de traduction
  du code, pas d'échanges réellement constatés avec un broker.
