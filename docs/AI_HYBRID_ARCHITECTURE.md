# Architecture de l'intelligence hybride

TradePilot dispose de **deux sources d'intelligence artificielle** :

- un **moteur local** qui tourne sur votre PC (Ollama, LM Studio, llama.cpp,
  vLLM, LocalAI — tout serveur compatible OpenAI) ;
- **OpenRouter**, limité aux modèles gratuits, déjà présent dans le projet.

Les deux sont interchangeables derrière un contrat unique. Le reste du Bridge
ne sait jamais lequel a répondu : il reçoit une réponse normalisée, ou rien.

> **Règle fondatrice.** Une sortie de modèle n'est jamais une vérité. Elle est
> structurée, validée, puis confrontée à des données déterministes avant de
> pouvoir influencer une décision. Le détail des barrières est dans
> [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md) — c'est le document à lire en
> premier si vous n'en lisez qu'un.

---

## 1. Vue d'ensemble

```
                       app/services/ai/service.py
                    ┌──────────────────────────────┐
   le reste du      │   ai_service  (façade)       │
   Bridge  ────────►│   • configure(session)       │
                    │   • complete_json(...)       │
                    │   • consensus(...)           │
                    │   • status() / test_local()  │
                    └───────────┬──────────────────┘
                                │
              ┌─────────────────┴──────────────────┐
              ▼                                    ▼
   ┌────────────────────────┐        ┌─────────────────────────────┐
   │ AIRouter               │        │ AIEnsembleService           │
   │ router/router.py       │        │ ensemble/service.py         │
   │ un moteur à la fois,   │        │ les deux moteurs en          │
   │ avec repli             │        │ parallèle, puis consensus   │
   └───────────┬────────────┘        └──────────────┬──────────────┘
               │                                    │
               └──────────────┬─────────────────────┘
                              ▼
                 ┌─────────────────────────┐
                 │ AIProvider (contrat)    │
                 │ services/ai/base.py     │
                 └───────┬──────────┬──────┘
                         │          │
        ┌────────────────┘          └────────────────┐
        ▼                                            ▼
┌───────────────────────┐                ┌──────────────────────────┐
│ LocalAIProvider       │                │ OpenRouterAIProvider     │
│ ai/local/provider.py  │                │ ai/openrouter_provider.py│
│ Ollama ou             │                │ enveloppe le service     │
│ compatible OpenAI     │                │ OpenRouter existant      │
└───────────────────────┘                └──────────────────────────┘
        │                                            │
        ▼                                            ▼
  votre serveur local                      https://openrouter.ai
  (127.0.0.1, hors réseau)                 (modèles gratuits seulement)
```

---

## 2. Le contrat `AIProvider`

Fichier : `bridge/app/services/ai/base.py`.

Un moteur expose quatre méthodes.

| Méthode | Rôle | Comportement en cas d'échec |
|---|---|---|
| `status()` | État courant du moteur | **Ne lève jamais.** Elle renseigne `error` / `detail` |
| `complete(...)` | Interrogation brute | Lève `AIProviderError` ou `AIProviderUnavailable` |
| `complete_json(...)` | Interrogation attendant un objet JSON | Idem, et positionne `valid_json` |
| `list_models()` | Modèles réellement disponibles | Liste vide si le moteur ne les expose pas |

Deux exceptions seulement :

- `AIProviderUnavailable` — le moteur n'est pas configuré, ou ne répond pas du
  tout (serveur éteint, adresse fausse, aucun modèle sélectionné) ;
- `AIProviderError` — le moteur a répondu, mais mal (HTTP 4xx/5xx, délai
  dépassé, corps illisible).

`AIProviderUnavailable` hérite de `AIProviderError` : un appelant qui attrape
la seconde attrape les deux.

### 2.1 `AICapabilities`

Ce que le moteur sait faire, tel que **déclaré** dans les réglages pour le
moteur local, et **déduit** pour OpenRouter.

| Champ | Défaut | Signification |
|---|---|---|
| `text` | `True` | Génération de texte |
| `json_mode` | `False` | Sait contraindre sa sortie à un objet JSON |
| `tools` | `False` | Appel d'outils |
| `vision` | `False` | Accepte une image |
| `context_size` | `8192` | Taille de contexte annoncée, en jetons |

Sérialisé en JSON sous les clés `text`, `json`, `tools`, `vision`,
`contextSize`.

Ces valeurs sont **déclaratives** pour le moteur local : TradePilot ne teste
pas si votre modèle sait vraiment produire du JSON, il vous croit sur parole.
Si vous vous trompez, cela se voit dans les métriques (`validJsonRate` en
baisse) et le routeur finit par rétrograder le moteur.

### 2.2 `AIProviderStatus` et la santé

La propriété `health` vaut :

| Valeur | Condition |
|---|---|
| `OFFLINE` | Moteur non configuré, ou injoignable et sans modèle connu |
| `DEGRADED` | Non disponible mais un modèle est bien sélectionné |
| `ONLINE` | Le moteur a répondu à la sonde |

### 2.3 `extract_json`

Les modèles entourent volontiers leur JSON de politesses et de balises
Markdown. `extract_json(text)` essaie, **dans cet ordre** :

1. le texte brut, tel quel ;
2. le contenu du premier bloc ` ```json … ``` ` (ou ` ``` … ``` `) ;
3. la première accolade équilibrée trouvée dans le texte.

Le premier candidat qui se charge en JSON **et qui est un dictionnaire** est
retenu. Sinon la fonction retourne `None` — et c'est tout. Aucune tentative de
réparation, aucune devinette, aucun repli sur une expression régulière qui
irait « comprendre » le texte. Une sortie illisible est une sortie perdue.

Deux tests verrouillent ce comportement dans `tests/test_ai_router.py` :
`test_json_entoure_de_texte_est_recupere` et
`test_texte_sans_json_ne_produit_rien`.

---

## 3. Les deux moteurs

### 3.1 Moteur local — `LocalAIProvider`

Rien n'est codé en dur : ni l'adresse, ni le modèle, ni le type de serveur.
Tout vient de la table `ai_settings`.

Deux dialectes sont reconnus :

| `localProvider` | Liste des modèles | Complétion | Mode JSON |
|---|---|---|---|
| `ollama` | `GET {baseUrl}/api/tags` | `POST {baseUrl}/api/chat` | `"format": "json"` |
| `openai_compatible` (défaut) | `GET {baseUrl}/v1/models` | `POST {baseUrl}/v1/chat/completions` | `"response_format": {"type":"json_object"}`, **si** `localSupportsJson` |

Toute valeur autre que `ollama` est traitée comme `openai_compatible`. La
lecture de la réponse accepte les deux formats (`message.content` d'Ollama,
`choices[0].message.content` ou `choices[0].text` d'OpenAI).

Installation et réglages détaillés : [LOCAL_AI_SETUP.md](LOCAL_AI_SETUP.md).

### 3.2 Moteur distant — `OpenRouterAIProvider`

Cette classe **n'est qu'une adaptation** : toute la mécanique OpenRouter
existante est conservée, notamment le sélecteur dynamique de modèles gratuits
et le coupe-circuit. Elle se contente de présenter ce service sous le même
contrat que le moteur local, pour que le routeur puisse les comparer.

Capacités annoncées : texte, JSON, outils, contexte 128 000 jetons, et vision
seulement si un modèle vision gratuit a été retenu. Le statut remonte
explicitement trois situations : OpenRouter désactivé dans les réglages,
aucune clé enregistrée, coupe-circuit ouvert après trop d'échecs.

Configuration de la clé et du sélecteur : [OPENROUTER_SETUP.md](OPENROUTER_SETUP.md).

---

## 4. Les sept natures de tâche

L'énumération `AITaskKind` sert au routeur à choisir, et aux métriques à
mesurer la fiabilité **par tâche** plutôt que globalement.

| Tâche | Usage prévu |
|---|---|
| `SIGNAL_PARSE` | Lecture d'un message Telegram ambigu |
| `NEWS_CLASSIFY` | Classement d'une actualité |
| `NEWS_SUMMARY` | Résumé court |
| `MARKET_ANALYSIS` | Analyse d'un instrument (valeur par défaut) |
| `MACRO_ANALYSIS` | Analyse macroéconomique |
| `VISION` | Lecture d'une image de graphique |
| `OPPORTUNITY_REVIEW` | Relecture d'une opportunité générée |

---

## 5. La façade `ai_service`

`bridge/app/services/ai/service.py` expose une instance unique, `ai_service`.
Le reste de l'application n'appelle qu'elle.

| Méthode | Ce qu'elle fait |
|---|---|
| `configure(session)` | Recharge `ai_settings`, synchronise les deux moteurs, **réinjecte la fiabilité mesurée** dans le routeur |
| `status()` | État des deux moteurs, mode, garde-fous, `anyAvailable` |
| `local_models()` | Modèles du serveur local, liste vide en cas d'échec |
| `test_local()` | Ping réel : demande le mot `OK`, 8 jetons, 20 secondes |
| `complete_json(...)` | Analyse structurée via le routeur — **retourne `None`** si aucune IA n'a pu répondre |
| `consensus(...)` | Mode ensemble, recalibrage, persistance, événements |
| `requires_manual_review(result)` | Le consensus autorise-t-il une exécution automatique ? |

Deux points de conception importants :

- `complete_json` retourne `None` plutôt que de lever. L'appelant est donc
  **obligé** de traiter l'absence d'IA comme un cas normal : se rabattre sur le
  déterministe, ou refuser d'agir.
- Les écritures de traces (`_trace_routing`, `_trace_call`,
  `_persist_consensus`) sont enveloppées dans un `try/except` : une trace qui
  échoue ne casse jamais une analyse, et n'invente jamais de résultat.

Si les deux moteurs sont hors service, `status()` renvoie `anyAvailable: false`
et ce message :

> Aucune intelligence disponible : les analyses déterministes continuent, mais
> toute décision exigeant l'IA passe en revue manuelle.

---

## 6. Ce qui est enregistré

Le module `app/models/intelligence.py` définit **19 tables** et les
énumérations associées.

### Données de marché

| Table | Contenu |
|---|---|
| `watchlist` | Instruments que TradePilot a le droit d'observer, avec le symbole broker réel, les autorisations par instrument (`allow_ai_trading`, `allow_telegram_trading`) et les préférences de notification |
| `market_snapshots` | Photographie chiffrée d'un instrument : prix, régime, tendances D1/H4/H1, caractéristiques normalisées, et les scores partiels (technique, historique, macro, news, cross-market, Telegram, IA locale, OpenRouter, consensus, global) |
| `market_regimes` | Historique des changements de régime, avec ATR |
| `cross_market_states` | Corrélations récentes entre instruments |

### Analyse historique

| Table | Contenu |
|---|---|
| `historical_patterns` | Résultat d'une recherche de situations comparables : nombre de correspondances, similarité moyenne, répartition positif/négatif/neutre, MAE et MFE moyens. Porte un avertissement en dur : ces statistiques ne prédisent aucune performance future |

### Actualités et calendrier

| Table | Contenu |
|---|---|
| `news_events` | Actualité qualifiée : impact, sentiment, pays, entités, actifs et devises concernés, statut de vérification, déduplication, **et le moteur IA qui a servi à la qualifier** |
| `news_asset_links` | Lien explicite actualité ↔ instrument, avec une pertinence |
| `economic_events` | Calendrier économique : échéance, devise, impact, prévision, précédent, réel |

### Opportunités et décisions

| Table | Contenu |
|---|---|
| `ai_opportunities` | Opportunité générée par le système lui-même : direction, zone d'entrée, SL, TP, RR attendu, raisons **et facteurs négatifs** |
| `decision_records` | Trace d'une décision — y compris les trades **non pris** |
| `decision_factors` | Composante chiffrée d'une décision : d'où vient chaque point (score, poids, contribution) |
| `shadow_trades` | Ce que le système aurait fait sans envoyer d'ordre |
| `strategy_performance` | Performance agrégée par stratégie et par origine |

### Intelligence artificielle

| Table | Contenu |
|---|---|
| `ai_provider_metrics` | Fiabilité mesurée par couple (moteur, tâche) : appels, succès, JSON valides, délais dépassés, erreurs, désaccords, hallucinations bloquées, latences |
| `ai_routing_events` | Pourquoi le routeur a choisi tel moteur pour telle tâche |
| `ai_consensus_records` | Confrontation des deux moteurs : modèle, direction, confiance, latence et résumé de chacun, puis la conclusion |
| `ai_settings` | Configuration de l'intelligence hybride, ligne unique `id = 1` |

### Notifications

| Table | Contenu |
|---|---|
| `notification_events` | Notification produite par le Bridge |
| `notification_preferences` | Réglages par catégorie : heures calmes, priorité minimale |

**Ce qui n'est jamais stocké** : le raisonnement interne des modèles. Seules
les sorties structurées et les explications synthétiques sont conservées. La
route `GET /api/v1/ai/consensus/{decisionId}` le rappelle dans sa réponse.

Les tables sont créées automatiquement au démarrage
(`SQLModel.metadata.create_all`), et les colonnes ajoutées par une nouvelle
version sont ajoutées à chaud. Aucune donnée ancienne n'est supprimée.

---

## 7. Les dix routes exposées

Toutes exigent un jeton de périphérique (`X-Device-Token` ou
`Authorization: Bearer …`). **Aucune ne déclenche d'ordre.**

| Méthode et chemin | Rôle |
|---|---|
| `GET /api/v1/ai/status` | État des deux moteurs, mode, garde-fous, dernier routage |
| `GET /api/v1/ai/providers` | Les deux états seuls, format tableau |
| `GET /api/v1/ai/local/models` | Modèles exposés par votre serveur local |
| `POST /api/v1/ai/local/test` | Ping réel du moteur local, journalisé |
| `GET /api/v1/ai/openrouter/models` | Modèles gratuits retenus |
| `POST /api/v1/ai/openrouter/test` | Test de la connexion OpenRouter |
| `GET /api/v1/ai/router/settings` | Réglages de routage |
| `PUT /api/v1/ai/router/settings` | Modification des réglages de routage |
| `GET /api/v1/ai/metrics` | Fiabilité mesurée, par moteur et par tâche |
| `GET /api/v1/ai/consensus/{decisionId}` | Confrontation des deux moteurs pour une décision |

Aucune clé ni aucun secret ne figure dans les réponses de ces routes.

---

## 8. Confidentialité

| Moteur | Où partent les données |
|---|---|
| Local | Nulle part. Le texte reste sur votre PC, sur `127.0.0.1` |
| OpenRouter | Chez OpenRouter et son fournisseur d'inférence |

C'est un argument concret en faveur du moteur local pour le parsing Telegram :
le contenu des canaux que vous suivez ne sort pas de la machine.

---

## 9. État réel du chantier au 11 septembre 2026

Cette section est volontairement précise : elle sépare ce qui tourne
aujourd'hui de ce qui est encore à construire. Ne partez pas du principe qu'un
module décrit dans le cahier des charges est branché.

### Ce qui existe et fonctionne

- le contrat `AIProvider`, `AICapabilities`, `extract_json` ;
- `LocalAIProvider` complet (découverte des modèles, complétion, deux
  dialectes) ;
- `OpenRouterAIProvider` ;
- `AIRouter` : six modes, règles de routage, repli, fiabilité mesurée ;
- `AIEnsembleService` et `AIConsensusEngine` : cinq verdicts, recalibrage ;
- la façade `ai_service` avec ses traces et sa persistance ;
- les 19 tables et les énumérations ;
- les 10 routes REST, protégées par jeton ;
- 21 tests automatisés (`tests/test_ai_router.py`, `tests/test_ai_consensus.py`).

### Ce qui n'est pas encore branché

- **Le pipeline Telegram n'utilise pas encore le routeur.**
  `app/services/signals/pipeline.py` appelle toujours directement
  `openrouter_service.parse_signal`. Le repli IA sur un message ambigu passe
  donc par OpenRouter, pas par le moteur local, quel que soit le mode choisi.
- **Aucun appelant de `ai_service.consensus(...)` en production.** Le moteur de
  consensus est testé et prêt, mais le moteur de décision qui doit
  l'interroger est en cours d'écriture par une autre équipe.
- **Les paquets de services suivants sont des emplacements vides** :
  `market_data`, `market_regime`, `market_scanner`, `technical_analysis`,
  `historical_patterns`, `cross_market`, `news`, `economic_calendar`,
  `decision`, `confidence`, `opportunities`, `strategies`, `learning`,
  `notifications`.
- **Les routes `market`, `patterns`, `news`, `decisions`, `notifications` sont
  déclarées mais vides** : le routeur FastAPI les enregistre, elles n'exposent
  aucun chemin.
- **Les réglages `shadowMode` et `aiTradingEnabled` ne sont lus par personne**
  aujourd'hui : ils sont stockés, exposés par l'API, mais aucun code d'exécution
  ne les consulte encore. Voir [SHADOW_MODE.md](SHADOW_MODE.md).
- **L'application Android déclare les chemins** (`aiStatus`, `aiRouterSettings`,
  `aiLocalTest`, `aiMetrics` dans `endpoints.dart`) **mais aucun écran ne les
  consomme encore.** La configuration du moteur local se fait pour l'instant en
  HTTP direct : voir [LOCAL_AI_SETUP.md](LOCAL_AI_SETUP.md), section 5.

### Écarts connus entre le cahier des charges et le code

- Le cahier des charges prévoit une **clé d'API facultative** pour le serveur
  local. La table `ai_settings` n'a pas ce champ et `LocalAIProvider` n'envoie
  aucun en-tête d'authentification. Un serveur local protégé par clé n'est donc
  pas utilisable aujourd'hui. Ollama et LM Studio en configuration par défaut
  n'en demandent pas.
- Le cahier des charges cite la **latence** et le **coût** parmi les critères
  du routeur. Les latences sont bien mesurées et stockées, mais `AIRouter.plan`
  ne s'en sert pas pour arbitrer. Le coût est traité implicitement : le local
  est gratuit et prioritaire, et OpenRouter est restreint aux modèles gratuits.
- L'adaptateur **Ollama ne transmet pas les images**. Voir
  [LOCAL_AI_SETUP.md](LOCAL_AI_SETUP.md), section 7.

---

## 10. Avertissement

TradePilot est un outil personnel d'automatisation, pas un service financier
ni un conseil en investissement. **Le trading de produits à effet de levier
comporte un risque élevé de perte totale du capital engagé.**

Ajouter une intelligence artificielle ne réduit pas ce risque : cela ajoute une
source d'erreur supplémentaire. C'est précisément pourquoi toute l'architecture
décrite ici est bâtie autour d'une seule idée — **un modèle propose, des règles
déterministes disposent**.
