# AI Market Watcher (CDC3)

Sous-système autonome du Bridge TradePilot. Il surveille les marchés en
continu, produit des signaux expliqués et les publie dans un canal Telegram.

**Il ne passe aucun ordre.** Ce n'est pas une option désactivée : le paquet
`app/watcher/` n'importe aucun module d'exécution, et un test le vérifie à
chaque exécution de la suite (`test_le_watcher_n_importe_aucun_moteur_d_execution`).

---

## Démarrage

Aucune action n'est requise. Le watcher démarre avec le Bridge :

```powershell
.\scripts\start_bridge.ps1
```

Ses quatre boucles se lancent décalées pour laisser MetaTrader, Telegram et le
moteur d'actualités se mettre en place :

| Boucle        | Démarre après | Période | Rôle |
|---------------|---------------|---------|------|
| `analysis`    | 75 s          | 90 s    | analyse chaque instrument, décide, publie |
| `lifecycle`   | 45 s          | 30 s    | suit les signaux publiés (TP, SL, invalidation) |
| `news`        | 150 s         | 300 s   | relaie les actualités majeures dans le canal |
| `maintenance` | 300 s         | 1 h     | purge les traces d'analyse de plus de 30 jours |

Chaque boucle survit à ses propres pannes : une erreur d'actualités ne suspend
pas le suivi des signaux, et un instrument en panne n'arrête pas les autres.

---

## Canal Telegram

Le watcher publie via la **session utilisateur Telegram déjà connectée au
Bridge** — pas via un bot. Aucun jeton supplémentaire n'est nécessaire.

Le canal est désigné par son titre dans `config/watcher.yaml` :

```yaml
telegram_channel: "tradepilot test"
```

Au premier envoi, le watcher cherche ce titre parmi les conversations du
compte, vérifie qu'il a le droit d'y publier, puis mémorise l'identifiant
numérique pour les fois suivantes. Vous pouvez aussi donner directement un
`@pseudo` ou un identifiant numérique.

**Aucun canal n'est rejoint automatiquement.** Si le canal n'existe pas dans le
compte, le watcher le dit et n'envoie rien.

Pour vérifier la résolution à tout moment :

```
POST /api/v1/watcher/telegram/resolve
```

---

## Ce qui est publié

| Message | Quand |
|---------|-------|
| Signal (détaillé ou simple) | décision BUY / SELL / STRONG_* validée par le Risk Manager |
| Alerte de surveillance | score entre `watch_score` et `minimum_score`, au plus une par instrument toutes les 2 h |
| Mise à jour de signal | TP1/2/3 atteint, SL touché, signal invalidé ou expiré |
| Actualité majeure | dépêche HIGH ou CRITICAL, jamais deux fois |
| Message de démarrage | une fois par lancement du Bridge |

Chacun se coupe indépendamment : `send_watch_alerts`, `send_signal_updates`,
`send_news_alerts`, `send_startup_message`.

Pour tout analyser sans rien publier, passez `dry_run: true`.

---

## Chaîne de décision

```
bougies MT5 réelles
  → analyse déterministe (structure, multi-TF, price action, volatilité, volume, liquidité)
  → niveaux calculés (Entry / SL / TP1-3 / RR)
  → score sur 100
  → Risk Manager  ← droit de veto
  → lecture IA (commentaire seulement, si le score le justifie)
  → décision
  → publication
  → suivi du cycle de vie
```

Trois garanties structurelles, pas déclaratives :

**L'IA n'invente aucun prix.** `levels.py` calcule Entry, SL et TP avant tout
appel IA. Le schéma de réponse de l'IA (`AIOpinion`) ne contient aucun champ de
prix — un test le vérifie. L'IA commente, elle ne décide pas.

**Donnée absente ≠ donnée neutre.** Un critère sans données est retiré du
calcul et la couverture baisse. Sans actualités, un setup techniquement parfait
plafonne à 80/100 au lieu de prétendre 100. Le Risk Manager refuse en dessous
de 45 % de couverture.

**Le Risk Manager peut tout refuser.** Marché fermé, données périmées, spread
excessif, volatilité extrême, annonce imminente, doublon, plafond quotidien,
délai entre signaux — chacun peut annuler un signal que tout le reste approuve.

---

## Score sur 100

| Critère | Poids | Mesure |
|---------|-------|--------|
| Structure | 20 | HH/HL, LH/LL, BOS, CHoCH, balayage de liquidité |
| Multi-timeframe | 15 | cohésion entre unités de temps du profil |
| Momentum | 10 | pente normalisée, pression de la dernière bougie |
| Supports / résistances | 10 | place devant le prix, appui derrière |
| Volume | 5 | activité vs habitude, cassure accompagnée ou non |
| Volatilité | 5 | ATR vs son propre historique |
| Indicateurs | 10 | RSI, moyennes mobiles |
| Sentiment | 10 | actualités rattachées à l'instrument |
| Fondamental | 10 | actualités HIGH/CRITICAL |
| Risk/Reward | 5 | ratio réellement calculé |

Les poids sont modifiables dans `config/watcher.yaml`. Une pondération
partielle complète les valeurs d'origine plutôt que de les effacer.

Le score publié vaut `score_des_critères_disponibles × couverture`. Il **n'est
pas une probabilité de gain** : il n'est affiché que comme `Confiance : 78/100`.

Paliers : `< 50` NO TRADE · `50-59` WATCH · `60-69` WEAK · `70-79` VALID ·
`80-89` STRONG · `90+` EXCEPTIONAL.

---

## Instruments

Utilisez les **noms canoniques que le Bridge sait traduire**. Il résout
`NAS100` vers `USTECm` et `US500` vers `US500m` chez Exness.

`SPX500` ne fonctionne pas : ce n'est pas un nom canonique connu du résolveur,
il faut demander `US500`.

Les instruments absents du compte sont écartés au démarrage et listés dans
`/api/v1/watcher/health` sous `unavailableSymbols`. Ils ne sont jamais analysés
sur des données supposées.

**Premier passage lent.** La première fois qu'un instrument est analysé,
MetaTrader doit télécharger son historique D1 depuis le serveur du courtier,
ce qui peut dépasser le délai de garde et faire redémarrer le processus MT5.
C'est un comportement connu du terminal, pas une panne : le Bridge se
reconnecte seul, et l'ordre de balayage tourne à chaque cycle pour qu'aucun
instrument ne soit systématiquement pénalisé. Après quelques cycles, tous les
instruments sont en cache et les analyses redeviennent rapides.

---

## Fraîcheur des données

La tolérance sur l'âge de la dernière bougie **suit l'unité de temps analysée** :
deux bougies, avec `max_data_age_seconds` comme plancher.

Sur M15, la tolérance est donc de 30 minutes. Un plafond fixe plus court
déclarerait les données périmées en permanence — une bougie M15 qui vient de
s'ouvrir a légitimement quinze minutes — et aucun signal ne sortirait jamais.

---

## Suivi du cycle de vie

Deux choix assumés, tous deux pessimistes :

- quand une même bougie M1 contient le stop **et** un objectif, c'est le stop
  qui est retenu. On ne sait pas lequel a été touché en premier, et supposer le
  contraire gonflerait artificiellement les statistiques ;
- le résultat est mesuré sur position entière. Un signal qui touche TP1 puis
  revient au stop compte −1 R. L'excursion maximale atteinte est conservée à
  part (`maxFavorableR`).

Un signal invalidé avant son déclenchement n'a **pas** de résultat : il rend
`null`, pas zéro. Le compter comme une opération à zéro fausserait le taux de
réussite.

---

## API

Toutes les routes exigent un appareil appairé.

| Route | Rôle |
|-------|------|
| `GET /api/v1/watcher/health` | état des boucles, du canal, de la configuration |
| `GET /api/v1/watcher/markets` | dernière analyse de chaque instrument |
| `GET /api/v1/watcher/markets/{symbol}` | fiche complète d'un instrument |
| `GET /api/v1/watcher/signals` | historique filtrable |
| `GET /api/v1/watcher/signals/active` | signaux encore suivis |
| `GET /api/v1/watcher/signals/{id}` | détail et chronologie d'un signal |
| `GET /api/v1/watcher/performance` | statistiques (win rate, RR, par symbole / heure / score) |
| `POST /api/v1/watcher/analysis/{symbol}` | analyser un instrument maintenant |
| `POST /api/v1/watcher/run/{target}` | déclencher une boucle (`analysis`, `lifecycle`, `news`, `maintenance`) |
| `GET` / `PUT /api/v1/watcher/settings` | lire et modifier la configuration à chaud |
| `POST /api/v1/watcher/telegram/resolve` | vérifier le canal cible |

Documentées dans Swagger : `http://127.0.0.1:8787/docs`.

---

## Configuration

Trois sources, par priorité croissante :

1. les valeurs par défaut du code — le watcher tourne sans aucune configuration ;
2. `config/watcher.yaml` — pour changer les seuils sans passer par l'API ;
3. les réglages `watcher.*` en base — modifiables à chaud via `PUT /settings`,
   pris en compte en moins de 30 secondes, sans redémarrage.

Aucun secret n'y figure : jetons et identifiants restent dans `bridge/.env`.

Pour couper le watcher sans arrêter le Bridge : `enabled: false`.

---

## Étanchéité

- Toutes ses tables sont préfixées `watcher_` : `watcher_signals`,
  `watcher_signal_events`, `watcher_analyses`. Aucune collision possible avec
  les tables existantes.
- Il lit les services du Bridge (MetaTrader, analyse technique, actualités,
  calendrier, IA, session Telegram) sans jamais les modifier.
- Il ne collecte pas d'actualités lui-même : le moteur du Bridge remplit déjà
  ces tables. Dupliquer la collecte doublerait les requêtes réseau pour un
  résultat identique.
- Trois lignes seulement ont été ajoutées à l'existant : enregistrement des
  tables (`database/session.py`), démarrage et arrêt (`main.py`), montage des
  routes (`api/v1/router.py`).

---

## Tests

```powershell
cd bridge
.\.venv\Scripts\python.exe -m pytest tests/test_watcher_analyses.py tests/test_watcher_decision.py tests/test_watcher_publication.py tests/test_watcher_bout_en_bout.py tests/test_watcher_api.py
```

Aucun message réel n'est envoyé : le publieur reçoit une fonction d'envoi
injectée qui enregistre les textes. Aucun appel IA non plus : la lecture IA est
désactivée par configuration dans les tests.
