# AIRouter — quel moteur traite quelle tâche

Le routeur est l'arbitre entre le moteur local et OpenRouter. Il n'a **aucune
opinion sur les marchés** : il ne sait rien des prix, des positions ni du
risque. Il répond à une seule question — *à qui poser cette question, et dans
quel ordre si le premier ne répond pas ?*

Fichier : `bridge/app/services/ai/router/router.py`.

Principe directeur inscrit dans le code : **le moteur local traite tout ce
qu'il sait faire, parce qu'il est gratuit, rapide et privé. OpenRouter est
réservé à ce qui le dépasse.**

---

## 1. Les six modes

Le mode est stocké dans `ai_settings.mode` et se change par
`PUT /api/v1/ai/router/settings`.

| Mode | Comportement exact |
|---|---|
| `AUTO` | **Défaut.** Le routeur décide selon la nature de la tâche, les capacités requises et la fiabilité mesurée |
| `LOCAL_ONLY` | Le moteur local, et rien d'autre. Si le local est indisponible, **l'appel échoue** : aucun repli vers OpenRouter |
| `OPENROUTER_ONLY` | OpenRouter seul. Si OpenRouter est désactivé, l'appel échoue |
| `LOCAL_FIRST` | Local d'abord, OpenRouter en repli |
| `OPENROUTER_FIRST` | OpenRouter d'abord, local en repli |
| `ENSEMBLE` | Destiné au mode ensemble ([AI_ENSEMBLE.md](AI_ENSEMBLE.md)). **Pour un appel simple passant par le routeur, il se comporte exactement comme `AUTO`** |

> **Précision sur `ENSEMBLE`.** `AIRouter.plan` traite `AUTO` et `ENSEMBLE`
> dans la même branche. Le mode ensemble n'est pas produit par le routeur : il
> est produit par `AIEnsembleService`, qui interroge les deux moteurs en
> parallèle sans passer par `plan`. Le mode `ENSEMBLE` sert donc de drapeau
> pour l'appelant, pas de règle de routage.

### Un moteur n'est éligible que s'il est réellement configuré

| Moteur | Condition d'éligibilité |
|---|---|
| Local | `local_enabled` **et** `local_base_url` non vide après nettoyage des espaces |
| OpenRouter | `openrouter_enabled` |

Un mode exclusif dont le moteur n'est pas éligible produit une liste vide, et
l'appel lève `AIProviderUnavailable` avec ce message :

> Aucun moteur d'intelligence artificielle disponible pour cette tâche.

---

## 2. Les règles de routage en mode AUTO

Le routeur classe les tâches en deux familles, définies en dur dans le code.

```python
LOCAL_FRIENDLY_TASKS = {SIGNAL_PARSE, NEWS_CLASSIFY, NEWS_SUMMARY}
REMOTE_PREFERRED_TASKS = {MACRO_ANALYSIS, OPPORTUNITY_REVIEW}
```

L'algorithme, dans l'ordre où il s'exécute :

1. **Point de départ** — on préfère OpenRouter si l'une de ces trois conditions
   est vraie : contexte large demandé (`large_context`), image à traiter
   (`needs_vision`), ou tâche dans `REMOTE_PREFERRED_TASKS`.
2. **Rappel du local** — si la tâche est dans `LOCAL_FRIENDLY_TASKS` **et**
   qu'aucune image n'est en jeu, on repasse au local, même si `large_context`
   était demandé.
3. **Correction par la fiabilité** — voir §3.
4. **Construction de la liste** — le moteur préféré d'abord s'il est éligible,
   puis l'autre s'il l'est aussi.

Les tâches `MARKET_ANALYSIS` et `VISION` ne figurent dans aucune des deux
listes : elles sont donc arbitrées uniquement par les critères de l'étape 1.
`VISION` implique en pratique `needs_vision`, ce qui l'oriente vers OpenRouter
sauf si le moteur local déclare la vision.

### Cas particulier : la vision

Avant tout le reste, si une image doit être traitée et que le moteur local ne
déclare pas `local_supports_vision`, **le local est retiré de la liste**, quel
que soit le mode — y compris `LOCAL_ONLY`, où l'appel échouera alors
proprement plutôt que de partir vers un modèle incapable.

### Le motif est toujours dit

Chaque décision porte une raison lisible, enregistrée dans
`ai_routing_events.reason` et visible dans `GET /api/v1/ai/status` sous
`lastRouting` :

| Motif | Quand |
|---|---|
| `Mode local exclusif` | `LOCAL_ONLY` |
| `Mode OpenRouter exclusif` | `OPENROUTER_ONLY` |
| `Local d'abord, OpenRouter en repli` | `LOCAL_FIRST` |
| `OpenRouter d'abord, local en repli` | `OPENROUTER_FIRST` |
| `Tâche traitable localement : quota externe préservé` | AUTO, choix du local |
| `Tâche exigeant un contexte large ou la vision` | AUTO, à cause de `large_context` ou d'une image |
| `Analyse complexe orientée vers OpenRouter` | AUTO, à cause de `REMOTE_PREFERRED_TASKS` |

---

## 3. La fiabilité mesurée

C'est le point qui distingue ce routeur d'un simple aiguillage statique : il
tient compte de ce que les moteurs ont **réellement** produit jusqu'ici.

### 3.1 D'où viennent les chiffres

La table `ai_provider_metrics` compte, pour chaque couple **(moteur, tâche)** :

appels, succès, JSON valides, délais dépassés, erreurs, désaccords,
hallucinations bloquées, latence cumulée et dernière erreur.

Elle est alimentée par `AIService._trace_call` après chaque appel routé : le
moteur retenu enregistre un succès, **et chaque moteur écarté en chemin
enregistre un échec** avec son motif.

À chaque `ai_service.configure(session)` — donc à chaque appel des routes IA —
ces mesures sont réinjectées dans le routeur par `record_reliability`.

### 3.2 Comment elles sont utilisées

Deux constantes seulement :

```python
RELIABILITY_FLOOR = 0.5          # taux de succès plancher
MIN_CALLS_FOR_RELIABILITY = 8    # en deçà, on ne juge pas
```

Un moteur est considéré comme fiable pour une tâche si :

- il a été appelé **moins de 8 fois** pour cette tâche — dans le doute, on lui
  laisse sa chance ; ou
- son taux de succès est **supérieur ou égal à 50 %**.

Un moteur jugé peu fiable **perd la priorité, il n'est jamais exclu**. Il reste
dans la liste, en second. Un moteur qui redevient fiable remonte tout seul :
rien n'est définitif, rien n'est à réarmer à la main.

Exemple vérifié par le test `test_un_moteur_peu_fiable_perd_la_priorite` :

```
Tâche SIGNAL_PARSE, mode AUTO.
Normalement : LOCAL en premier.
Mais le local affiche 20 % de succès sur 50 appels pour cette tâche.
Résultat : [OPENROUTER, LOCAL]
```

Le taux de succès est calculé par la propriété `success_rate` de
`AIProviderMetric` : `successes / calls`, arrondi à trois décimales.

### 3.3 Une nuance à connaître

La correction par la fiabilité s'applique **une seule fois**, et dans un ordre
fixe : on teste d'abord la fiabilité du moteur préféré, et si elle est
insuffisante, on bascule sur l'autre — **sans vérifier que l'autre est meilleur**.

Si les deux moteurs sont peu fiables pour une même tâche, la bascule a donc
quand même lieu. C'est un choix conservateur assumé : il vaut mieux essayer
l'autre moteur que de s'entêter, et de toute façon le repli à l'exécution
(§4) rattrapera un échec.

---

## 4. L'exécution et les règles de repli

`AIRouter.complete` parcourt la liste produite par `plan`, du premier au
dernier.

Un moteur est **écarté et l'on passe au suivant** dans deux cas :

| Situation | Trace enregistrée |
|---|---|
| Le moteur lève `AIProviderError` ou `AIProviderUnavailable` | Le message d'erreur, tronqué à 160 caractères |
| `json_mode` était demandé et la sortie n'est pas un JSON exploitable | `JSON invalide` |

Le second cas est important : **une réponse qui arrive mais qui n'est pas
structurée est traitée comme un échec**. Le routeur ne tente pas de
l'interpréter, ne cherche pas un `BUY` dans le texte libre, n'appelle aucune
heuristique de secours. Il passe au moteur suivant.

Quand un moteur répond correctement, le routeur renvoie une `RoutedResponse`
qui porte toute la trace du chemin suivi :

| Champ | Contenu |
|---|---|
| `response` | La réponse normalisée |
| `provider` | Le moteur qui a effectivement répondu |
| `fallback_used` | Vrai si ce n'était pas le premier de la liste |
| `routing` | Le plan initial et son motif |
| `attempts` | La liste des moteurs écartés, avec leur motif |

### Quand plus rien ne répond

Si tous les moteurs de la liste ont échoué, le routeur lève
`AIProviderUnavailable` avec le détail complet :

```
Aucun moteur n'a pu répondre. LOCAL: local éteint | OPENROUTER: indisponible
```

**Il ne retourne jamais une réponse vide, une réponse par défaut, ou une
direction arbitraire.** C'est le point de sécurité central : l'appelant est mis
face à l'absence d'IA et doit décider — se rabattre sur le déterministe, ou
refuser d'agir. La façade `ai_service.complete_json` traduit cette exception en
un simple `None`, pour la même raison.

---

## 5. Les comportements garantis par les tests

`bridge/tests/test_ai_router.py` — 12 tests, sans aucun appel réseau : les deux
moteurs sont des doubles dont on choisit le comportement.

| Test | Ce qu'il verrouille |
|---|---|
| `test_une_tache_simple_reste_locale` | `SIGNAL_PARSE` part au local |
| `test_analyse_macro_part_vers_openrouter` | `MACRO_ANALYSIS` part chez OpenRouter |
| `test_la_vision_evite_un_local_incapable` | Un local sans vision n'est jamais sollicité pour une image |
| `test_mode_local_exclusif_ignore_openrouter` | `LOCAL_ONLY` ne produit que `[LOCAL]`, même pour une analyse macro |
| `test_un_moteur_peu_fiable_perd_la_priorite` | La fiabilité mesurée renverse l'ordre |
| `test_local_hors_service_bascule_sur_openrouter` | Repli local → OpenRouter, `fallback_used = True` |
| `test_openrouter_hors_service_laisse_travailler_le_local` | Repli OpenRouter → local |
| `test_les_deux_hors_service_leve_une_erreur_explicite` | Les deux muets : exception, et le motif d'origine est conservé |
| `test_json_invalide_declenche_le_repli` | Une réponse non structurée vaut un échec |
| `test_aucun_moteur_actif_est_refuse` | Deux moteurs désactivés : refus, pas de valeur par défaut |
| `test_json_entoure_de_texte_est_recupere` / `test_texte_sans_json_ne_produit_rien` | Lecture des sorties de modèles |

Pour les relancer :

```powershell
bridge\.venv\Scripts\python.exe -m pytest bridge\tests\test_ai_router.py -q
```

---

## 6. Ce que le routeur ne fait pas

Le cahier des charges liste dix critères de routage. Voici ce qui est
réellement codé, et ce qui ne l'est pas.

| Critère | État |
|---|---|
| Type de tâche | **Codé** — les deux familles de tâches |
| Capacités nécessaires | **Codé** — la vision retire un moteur incapable |
| Disponibilité | **Codé** — éligibilité, puis repli à l'exécution |
| Taille du contexte | **Codé** — via le drapeau `large_context` fourni par l'appelant |
| Besoin vision | **Codé** |
| Fiabilité récente | **Codé** — plancher de 50 % au-delà de 8 appels |
| Besoin de raisonnement avancé | **Codé** indirectement, par `REMOTE_PREFERRED_TASKS` |
| Confidentialité | **Implicite** — le local est prioritaire par construction |
| Coût | **Implicite** — le local est gratuit, et OpenRouter est déjà restreint aux modèles gratuits |
| **Latence** | **Non codé.** Les latences sont mesurées, stockées et exposées, mais `plan` ne s'en sert pas pour arbitrer |

Le routeur ne fait pas non plus :

- de retentative sur le **même** moteur — un échec fait passer au suivant ;
- de mise en cache des réponses ;
- de découpage d'une demande trop grande pour le contexte disponible ;
- de vérification que le contenu de la réponse est *juste*. Il vérifie qu'elle
  est **structurée**, pas qu'elle a raison. La vérification du fond appartient
  au consensus ([AI_ENSEMBLE.md](AI_ENSEMBLE.md)) et aux barrières
  déterministes ([AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md)).

---

## 7. Observer le routeur en fonctionnement

```powershell
$entetes = @{ "X-Device-Token" = $jeton }
$bridge  = "http://127.0.0.1:8787/api/v1"

# Mode courant, état des deux moteurs, dernier routage effectué
Invoke-RestMethod -Uri "$bridge/ai/status" -Headers $entetes

# Fiabilité mesurée, par moteur et par tâche
Invoke-RestMethod -Uri "$bridge/ai/metrics" -Headers $entetes
```

`GET /ai/metrics` renvoie pour chaque couple (moteur, tâche) :

```json
{
  "provider": "LOCAL",
  "task": "SIGNAL_PARSE",
  "model": "qwen2.5:7b-instruct",
  "calls": 42,
  "successRate": 0.952,
  "validJsonRate": 0.929,
  "averageLatencyMs": 780,
  "timeouts": 1,
  "errors": 1,
  "disagreements": 0,
  "hallucinationsBlocked": 0,
  "lastError": null,
  "lastUsedAt": "2026-09-11T09:14:22+00:00"
}
```

Deux colonnes méritent votre attention :

- **`validJsonRate`** — s'il est bas alors que `successRate` est correct, votre
  modèle local répond mais ne respecte pas le format. Changez de modèle ou
  vérifiez `localSupportsJson`.
- **`hallucinationsBlocked`** — une valeur inventée a été rejetée avant
  d'atteindre le trading. Ce compteur doit rester bas ; s'il grimpe, le modèle
  concerné n'est pas adapté à la tâche.

---

## 8. État au 11 septembre 2026

Le routeur est **complet et testé**, mais peu appelé : le pipeline d'analyse
des messages Telegram
(`app/services/signals/pipeline.py`) appelle encore directement
`openrouter_service.parse_signal` et **ne passe pas par le routeur**. Le
basculement de ce pipeline vers `ai_service` fait partie des chantiers en
cours, menés par d'autres équipes.

Concrètement : régler `mode = LOCAL_ONLY` aujourd'hui n'empêche pas le repli IA
du parsing Telegram d'utiliser OpenRouter. Les routes `/ai/*`, le statut et les
métriques sont en revanche pleinement opérationnels.

---

Le trading comporte un risque de perte. Un routage bien choisi améliore la
disponibilité et la confidentialité du système ; il ne rend aucune analyse plus
juste.
