# Section à insérer dans le README — intelligence hybride (CDC2)

> **Ce fichier n'est pas une documentation.** C'est un brouillon d'intégration.
> Il contient les fragments à reporter dans le `README.md` racine, pour la
> partie « intelligence hybride » du second cahier des charges.
>
> Le `README.md` n'a volontairement **pas** été modifié : d'autres chantiers
> sont en cours et l'écrasement serait garanti. Reportez les fragments
> ci-dessous quand vous jugerez le moment venu, puis supprimez ce fichier.
>
> **Périmètre.** Ces fragments ne couvrent que l'intelligence hybride : moteur
> local, routeur, ensemble, sécurité, mode ombre, trading autonome,
> intelligence de marché. Les équipes chargées des notifications, des données
> de marché, des news, du calendrier économique et du moteur de décision
> ajouteront leurs propres lignes.

---

## Fragment 1 — à ajouter dans « Ce que TradePilot fait »

*Après la puce qui commence par « Fait appel à un modèle de langage **gratuit**
via OpenRouter… ».*

```markdown
- Sait interroger **deux intelligences artificielles** : un modèle qui tourne
  sur votre PC (Ollama, LM Studio, llama.cpp, tout serveur compatible OpenAI)
  et OpenRouter. Un routeur choisit lequel selon la nature de la tâche, les
  capacités requises, la disponibilité et la **fiabilité réellement mesurée** de
  chacun, avec repli automatique sur l'autre.
- Privilégie le moteur local pour ce qu'il sait faire — lecture d'un message
  ambigu, classement d'une actualité, résumé court. C'est gratuit, sans quota,
  et le contenu des canaux que vous suivez ne quitte pas la machine.
- Peut faire analyser la même question par les deux moteurs **séparément**,
  puis confronter leurs conclusions. Une réponse structurée est exigée : une
  sortie illisible est traitée comme une panne, jamais interprétée au jugé.
- Recalibre la confiance annoncée par un modèle contre les données mesurées :
  une contradiction avec l'analyse technique la plafonne à 55 %, et aucune
  combinaison de signaux concordants ne dépasse 95 %.
- Mesure en continu la fiabilité de chaque moteur par type de tâche — taux de
  succès, taux de JSON valides, latence, délais dépassés, désaccords — et
  rétrograde automatiquement celui qui tombe sous 50 % de succès.
- Conserve la trace de chaque arbitrage : quel moteur a été choisi, pour quelle
  tâche, pourquoi, et quels moteurs ont été écartés en chemin.
```

---

## Fragment 2 — à ajouter dans « Ce que TradePilot ne fait pas »

*À la suite des puces existantes, qui disent déjà l'essentiel. Celles-ci
étendent la règle à l'IA hybride.*

```markdown
- Il **ne fait jamais la moyenne entre un `BUY` et un `SELL`.** Quand les deux
  intelligences se contredisent, aucune direction n'est retenue : ni la plus
  confiante, ni un compromis. L'exécution automatique est bloquée.
- Il **ne laisse aucun modèle chiffrer un niveau.** Entrée, stop loss et take
  profit proviennent du message d'origine ou d'un calcul déterministe. L'IA
  interprète et explique ; elle ne produit pas de prix.
- Il **ne fait jamais varier le volume selon la confiance.** La fonction de
  calcul du lot n'a pas de paramètre de confiance : celle-ci sert uniquement de
  seuil d'admission. Au-dessus du seuil, 76 % et 99 % donnent le même volume.
- Il **n'accorde aucune dérogation à l'IA devant le `RiskManager`.** Une
  opportunité produite par le système passe exactement les mêmes contrôles
  qu'un signal Telegram.
- Il **ne stocke jamais le raisonnement interne des modèles.** Seules les
  sorties structurées et les explications synthétiques sont conservées.
- Il **n'installe ni ne télécharge aucun modèle.** Le moteur local est le vôtre,
  sur votre machine, avec vos modèles.
```

---

## Fragment 3 — nouvelle section, à placer après « Architecture en une image »

```markdown
## Intelligence hybride : deux moteurs, un contrat

TradePilot sait interroger deux sources d'intelligence artificielle derrière
une interface unique. Le reste du Bridge ignore laquelle a répondu.

```
                    ai_service  (façade unique)
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
        AIRouter                   AIEnsembleService
   un moteur à la fois,         les deux en parallèle,
      avec repli                  puis consensus
              └─────────────┬─────────────┘
                            ▼
                   AIProvider (contrat)
                     │             │
        ┌────────────┘             └────────────┐
        ▼                                       ▼
  Moteur local                            OpenRouter
  Ollama, LM Studio,                      modèles gratuits
  llama.cpp, vLLM…                        uniquement
  sur votre PC                            coupe-circuit
  rien ne sort                            sélection dynamique
```

**Six modes de routage** : `AUTO` (défaut), `LOCAL_ONLY`, `OPENROUTER_ONLY`,
`LOCAL_FIRST`, `OPENROUTER_FIRST`, `ENSEMBLE`.

**Cinq verdicts de consensus** : `CONSENSUS`, `PARTIAL_CONSENSUS`,
`DISAGREEMENT`, `INSUFFICIENT_DATA`, `PROVIDER_UNAVAILABLE`. Les trois derniers
bloquent toute exécution automatique ; avec le réglage par défaut
`requireConsensus`, `PARTIAL_CONSENSUS` la bloque également.

Le moteur local est **désactivé à l'installation** : TradePilot fonctionne sans
lui. Pour l'ajouter, comptez une demi-heure et 16 Go de mémoire vive pour un
modèle de 7 milliards de paramètres —
[docs/LOCAL_AI_SETUP.md](docs/LOCAL_AI_SETUP.md) dit précisément ce que cela
coûte en mémoire et quel modèle choisir selon votre machine.

> **À lire avant d'activer quoi que ce soit d'automatique :**
> [docs/AI_TRADING_SAFETY.md](docs/AI_TRADING_SAFETY.md). Il détaille ce que
> l'IA n'a pas le droit de faire, les barrières successives, et pourquoi le
> `RiskManager` garde un droit de veto absolu.

### Ce qui n'est pas encore branché

Le socle d'intelligence hybride est écrit et testé, mais une partie des modules
qui doivent l'utiliser est en cours d'écriture :

- le pipeline d'analyse des messages Telegram appelle encore OpenRouter
  directement et **ne passe pas par le routeur** ;
- **aucun code de production n'appelle encore le consensus** : le moteur de
  décision n'est pas livré ;
- les paquets `market_data`, `technical_analysis`, `historical_patterns`,
  `news`, `economic_calendar`, `cross_market`, `decision`, `confidence`,
  `opportunities` sont des emplacements vides, et les routes `market`,
  `patterns`, `news`, `decisions`, `notifications` n'exposent aucun chemin ;
- les réglages `shadowMode` et `aiTradingEnabled` sont stockés et exposés par
  l'API, mais **aucun code d'exécution ne les lit** ;
- l'application Android déclare les chemins de l'écran de diagnostic IA, mais
  **aucun écran ne les consomme** : la configuration se fait pour l'instant en
  HTTP direct.

Le seul chemin de trading réellement actif reste celui du cahier des charges
initial : message Telegram → parser déterministe → repli IA si ambigu →
validateur strict → `RiskManager` → `order_check` → `order_send`.
```

---

## Fragment 4 — lignes à ajouter au tableau « Documentation »

```markdown
| [docs/AI_HYBRID_ARCHITECTURE.md](docs/AI_HYBRID_ARCHITECTURE.md) | Les deux moteurs et leur contrat commun, capacités, lecture des sorties, les 19 tables d'intelligence, les 10 routes, confidentialité, état réel du chantier |
| [docs/LOCAL_AI_SETUP.md](docs/LOCAL_AI_SETUP.md) | Installer Ollama ou LM Studio sur Windows, choisir un modèle, déclarer l'adresse et le modèle au Bridge, tester, coût réel en mémoire vive, dépannage |
| [docs/AI_ROUTER.md](docs/AI_ROUTER.md) | Les six modes, les règles de routage réellement codées, la fiabilité mesurée et son influence, les règles de repli, ce que le routeur ne fait pas |
| [docs/AI_ENSEMBLE.md](docs/AI_ENSEMBLE.md) | Les cinq verdicts de consensus, la règle « jamais de moyenne entre BUY et SELL », le recalibrage de la confiance, ce qui bloque une exécution automatique |
| [docs/AI_TRADING_SAFETY.md](docs/AI_TRADING_SAFETY.md) | **Ce que l'IA ne peut pas faire**, les barrières successives, le veto absolu du RiskManager, la règle NO_TRADE dans le doute, confiance ≠ taille de position |
| [docs/MARKET_INTELLIGENCE.md](docs/MARKET_INTELLIGENCE.md) | Le rapport par instrument, la structure des données de marché, régimes, analogues historiques, décisions et facteurs — et ce qui n'est pas encore écrit |
| [docs/AUTONOMOUS_TRADING.md](docs/AUTONOMOUS_TRADING.md) | Opportunités générées par le système : structure, garde-fous, triple autorisation, chemin prévu, état réel |
| [docs/SHADOW_MODE.md](docs/SHADOW_MODE.md) | Analyser et décider sans envoyer d'ordre, ce qui est enregistré, différence avec PAPER, précautions de lecture |
```

---

## Fragment 5 — corrections ponctuelles dans le texte existant

### 5.1 Nombre de tables

Dans la section « Structure du dépôt », la ligne :

```
│   │   ├── models/           23 tables SQLModel et énumérations du domaine
```

devient :

```
│   │   ├── models/           42 tables SQLModel et énumérations du domaine
```

*(Vérifié : `len(SQLModel.metadata.tables)` vaut bien 42 — les 23 tables
d'origine plus les 19 de `app/models/intelligence.py`.)*

### 5.2 Arborescence des services

Dans le même bloc, sous `services/`, ajouter après la ligne `channels/` :

```
│   │       ├── ai/           contrat, moteur local, OpenRouter, routeur, ensemble
```

> Les paquets `market_data/`, `news/`, `decision/`, `confidence/` et les autres
> emplacements encore vides ne sont volontairement **pas** listés ici : les
> équipes concernées les ajouteront quand ils auront du contenu.

### 5.3 Prérequis

Ajouter une ligne au tableau des prérequis :

```markdown
| Moteur d'IA local | Ollama, LM Studio ou tout serveur compatible OpenAI | facultatif — <https://ollama.com> |
```

### 5.4 Démarrage rapide

Après l'étape « 4. Configurer OpenRouter », ajouter une étape facultative :

```markdown
### 4 bis. (Facultatif) Ajouter un moteur d'IA local

Un modèle qui tourne sur votre PC lit les messages ambigus sans quota, sans
clé, et sans que le contenu de vos canaux ne sorte de la machine.

Installez Ollama depuis <https://ollama.com/download/windows>, puis :

```powershell
ollama pull qwen2.5:7b-instruct
ollama list
```

Déclarez ensuite l'adresse (`http://127.0.0.1:11434`) et le modèle au Bridge,
puis testez avec `POST /api/v1/ai/local/test`.

Comptez environ 6 Go de mémoire vive pour ce modèle, à quoi s'ajoutent Windows,
MetaTrader 5 et le Bridge : **16 Go de RAM sont confortables, 8 Go imposent un
modèle plus petit.** La marche à suivre complète, les alternatives et le
dépannage sont dans
[docs/LOCAL_AI_SETUP.md](docs/LOCAL_AI_SETUP.md).

Cette étape est facultative : sans moteur local, OpenRouter suffit.
```

### 5.5 État du projet

Ajouter une ligne au tableau « État du projet et limites connues » :

```markdown
| Intelligence hybride (CDC2) | Socle écrit et testé : contrat, moteur local, routeur, ensemble, consensus, 19 tables, 10 routes REST, **21 tests `pytest`**. Les modules qui doivent l'utiliser (données de marché, news, décision, opportunités) sont en cours d'écriture et **ne sont pas branchés**. |
```

Et à la liste « Ce qui n'a pas pu être vérifié sur cette machine » :

```markdown
- les appels à un moteur d'IA local réel (les tests utilisent des doubles ; aucun
  serveur Ollama ou LM Studio n'a été interrogé depuis cette machine).
```

---

## Fragment 6 — avertissement de risque

La section « Avertissement de risque » du README est déjà complète et n'a pas
besoin d'être réécrite. Une seule puce mérite d'y être ajoutée :

```markdown
- **L'ajout d'une intelligence artificielle ne réduit aucun de ces risques.**
  Un modèle de langage produit du texte plausible, ce qui n'est pas la même
  chose que du texte vrai : il peut écrire un prix qui n'existe pas ou un
  niveau absent du message d'origine, et le faire avec assurance. C'est
  pourquoi aucun chiffre produit par un modèle n'atteint le trading sans avoir
  été vérifié contre des données déterministes, et pourquoi le `RiskManager`
  garde un droit de veto absolu.
```
