# Mode ensemble et moteur de consensus

En mode ensemble, les deux intelligences analysent **la même question,
séparément**, puis leurs conclusions sont confrontées. Aucune ne voit la
réponse de l'autre : il n'y a pas de dialogue entre les modèles, donc pas de
contamination d'une opinion par l'autre.

Fichier : `bridge/app/services/ai/ensemble/service.py`.

> **La règle qui ne se négocie pas :** on ne fait **jamais** la moyenne entre un
> `BUY` et un `SELL`. Un désaccord sur une décision financière conduit à
> `NO_TRADE` ou à une revue manuelle, jamais à un compromis inventé.

---

## 1. Comment se déroule une analyse en ensemble

```
        la même question, le même prompt
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  Moteur local            OpenRouter
  complete_json()         complete_json()
        │                       │
        ▼                       ▼
   ProviderOpinion         ProviderOpinion
   direction, confiance,   direction, confiance,
   résumé, latence         résumé, latence
        └───────────┬───────────┘
                    ▼
           AIConsensusEngine.evaluate()
                    │
                    ▼
              ConsensusResult
        (un des cinq verdicts, §3)
                    │
                    ▼
           AIConsensusEngine.recalibrate()
        confrontation aux données déterministes
                    │
                    ▼
           ai_consensus_records  (base)
           + événements WebSocket
```

Les deux appels partent **en parallèle** (`asyncio.gather`). Un moteur qui
échoue ne fait pas échouer l'autre : son exception est capturée et transformée
en un avis marqué invalide, avec le motif.

Seuls les moteurs réellement configurés sont interrogés :
`local_enabled` et `local_base_url` non vide pour le local, `openrouter_enabled`
pour le distant. Si aucun des deux ne l'est, le verdict est immédiatement
`PROVIDER_UNAVAILABLE`.

---

## 2. Comment la sortie d'un modèle est lue

Rien n'est interprété librement. Trois lectures strictes, et c'est tout.

### La direction

Cherchée dans la charge utile JSON, sous l'une de ces clés, dans l'ordre :
`direction`, puis `action`, puis `signal`.

| Valeur reçue (majuscules, espaces retirés) | Direction retenue |
|---|---|
| `BUY`, `LONG`, `STRONG_BUY` | `BUY` |
| `SELL`, `SHORT`, `STRONG_SELL` | `SELL` |
| **tout le reste** | **aucune** (`None`) |

Un `WAIT`, un `NO_TRADE`, un `HOLD`, une phrase, une valeur absente, un nombre :
tout cela produit une direction nulle, donc un avis inexploitable. **Il n'y a
aucune tolérance, aucune correspondance approximative, aucune lecture du texte
libre.**

### La confiance

Lue sous la clé `confidence`, et seulement si c'est un nombre. Les modèles
répondent tantôt `0.82`, tantôt `82` : une valeur supérieure à 1 est divisée par
100. Le résultat est ensuite borné entre 0 et 1. Toute autre forme donne `0.0`.

### Le résumé

Première clé non vide parmi `summary`, `reason`, `explanation`, `analysis`. À
défaut, le texte brut de la réponse, tronqué à 500 caractères.

---

## 3. Les cinq résultats de consensus

`ConsensusOutcome` — l'ordre des tests ci-dessous est celui du code.

Un avis est dit **exploitable** s'il est marqué valide (JSON lisible) **et**
porte une direction `BUY` ou `SELL`.

| Verdict | Condition | Direction retenue | Confiance retenue | Bloque l'automatisme |
|---|---|---|---|---|
| `PROVIDER_UNAVAILABLE` | Aucun avis du tout | aucune | 0 | **oui** |
| `INSUFFICIENT_DATA` | Des avis, mais aucun exploitable | aucune | 0 | **oui** |
| `INSUFFICIENT_DATA` | **Un seul** avis exploitable | celle de l'unique moteur | **plafonnée à 0,60** | **oui** |
| `DISAGREEMENT` | Au moins deux directions différentes | **aucune** | 0 | **oui** |
| `PARTIAL_CONSENSUS` | Même direction, mais écart de confiance **> 30 points** | la direction commune | **la plus prudente des deux** | non |
| `CONSENSUS` | Même direction, écart ≤ 30 points | la direction commune | la moyenne | non |

### Pourquoi un seul avis ne vaut pas un consensus

Si OpenRouter tombe et que seul le moteur local répond, on n'a pas un consensus :
on a une opinion. Le verdict est donc `INSUFFICIENT_DATA`, la direction est
conservée à titre indicatif, mais la confiance est **écrêtée à 0,60** même si le
modèle annonçait 0,95. Et ce verdict bloque l'exécution automatique.

### Pourquoi un désaccord ne produit aucune direction

C'est le cœur du document. Local dit `BUY` à 90 %, OpenRouter dit `SELL` à 85 % :

- on ne prend pas le plus confiant des deux ;
- on ne fait pas la moyenne des confiances ;
- on ne « penche » pas vers l'un ou l'autre ;
- **on ne retient aucune direction du tout.**

Le champ `direction` du résultat reste `None`, le détail enregistre
`LOCAL=BUY contre OPENROUTER=SELL`, et `blocks_auto_trade` vaut `True`.

Deux tests verrouillent cela : `test_desaccord_bloque_l_automatisme` et
`test_le_recalibrage_ne_cree_jamais_de_direction`.

### Pourquoi la plus prudente en consensus partiel

Même direction, mais l'un annonce 0,95 et l'autre 0,40 : les deux modèles ne
voient manifestement pas la même chose. Le seuil est fixé à **30 points
d'écart** (`PARTIAL_CONSENSUS_GAP = 0.30`). La confiance retenue est le
**minimum**, jamais la moyenne, jamais le maximum.

---

## 4. Le recalibrage contre les données déterministes

Une confiance annoncée par un modèle ne vaut rien en soi. Un modèle qui dit
« 90 % » dit seulement qu'il a produit le caractère `9` puis `0`. Le recalibrage
confronte cette confiance à ce qui a été **mesuré**.

`AIConsensusEngine.recalibrate(result, direction_déterministe, score_déterministe)`
applique exactement trois règles.

### Règle 1 — Sans référence, rien ne change

Si le consensus n'a retenu aucune direction, ou si aucune direction
déterministe n'est fournie, le résultat est renvoyé tel quel. **Le recalibrage
ne crée jamais une direction là où il n'y en avait pas.**

### Règle 2 — Contradiction : la confiance chute

Si la direction déterministe est l'inverse de celle des modèles :

- la confiance est **ramenée à 0,55 au maximum** ;
- le détail est complété : *« Contradiction avec l'analyse technique (SELL). »* ;
- un `CONSENSUS` est **rétrogradé en `PARTIAL_CONSENSUS`**.

C'est l'exemple du cahier des charges : deux modèles d'accord à 90 % et 92 %,
contredits par l'analyse technique, ressortent à 0,55 au plus. Vérifié par
`test_contradiction_technique_fait_chuter_la_confiance`.

### Règle 3 — Accord franc : une prime minuscule

Si la direction déterministe est la même **et** que le score déterministe
atteint 0,70, la confiance gagne **0,05**, plafonnée à **0,95**.

Cinq centièmes, et jamais la certitude. Le plafond de 0,95 est absolu : aucune
combinaison de signaux concordants ne produit une confiance de 1.

**Ce sont les données mesurées qui ont le dernier mot, jamais le modèle.**

---

## 5. Ce qui bloque une exécution automatique

Deux niveaux, à ne pas confondre.

### Niveau 1 — `blocks_auto_trade` (propriété du résultat)

Vrai pour `DISAGREEMENT`, `INSUFFICIENT_DATA` et `PROVIDER_UNAVAILABLE`.
**Faux** pour `PARTIAL_CONSENSUS` et `CONSENSUS`.

### Niveau 2 — `ai_service.requires_manual_review(result)`

C'est cette méthode qu'un moteur de décision doit appeler. Elle est plus
stricte :

```python
if not settings.require_consensus_for_auto_trade:
    return False                       # le garde-fou est désactivé
return result.blocks_auto_trade or result.outcome is PARTIAL_CONSENSUS
```

Autrement dit, quand `requireConsensus` est actif — **c'est le réglage par
défaut** — seul un `CONSENSUS` franc autorise une exécution automatique. Un
consensus partiel exige une revue manuelle.

| Verdict | Exécution automatique possible avec `requireConsensus = true` |
|---|---|
| `CONSENSUS` | oui |
| `PARTIAL_CONSENSUS` | **non** — revue manuelle |
| `DISAGREEMENT` | **non** |
| `INSUFFICIENT_DATA` | **non** |
| `PROVIDER_UNAVAILABLE` | **non** |

Désactiver `requireConsensus` fait retourner `False` à cette méthode dans tous
les cas — y compris en plein désaccord. **Ne le désactivez pas si vous comptez
laisser le système exécuter seul.** Et rappelez-vous que même alors, le
`RiskManager` conserve son droit de veto : voir
[AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md).

---

## 6. Ce qui est conservé, et ce qui ne l'est pas

Chaque confrontation est enregistrée dans `ai_consensus_records` :

| Pour chaque moteur | Conclusion commune |
|---|---|
| modèle utilisé | direction finale |
| direction | confiance finale |
| confiance | détail lisible |
| latence en millisecondes | verdict |
| résumé synthétique | horodatage, décision rattachée |

**Le raisonnement interne des modèles n'est jamais stocké.** Seules les sorties
structurées et les explications synthétiques le sont. La route de consultation
le rappelle explicitement dans sa réponse :

```
GET /api/v1/ai/consensus/{decisionId}
```

```json
{
  "decisionId": 412,
  "task": "OPPORTUNITY_REVIEW",
  "outcome": "PARTIAL_CONSENSUS",
  "local":      { "model": "qwen2.5:7b-instruct", "direction": "BUY", "confidence": 0.95, "latencyMs": 910, "summary": "…" },
  "openRouter": { "model": "…:free",              "direction": "BUY", "confidence": 0.40, "latencyMs": 1840, "summary": "…" },
  "final":      { "direction": "BUY", "confidence": 0.40, "detail": "Même direction, écart de confiance de 55 %." },
  "note": "Seules les conclusions structurées sont conservées : le raisonnement interne des modèles n'est jamais stocké."
}
```

Un désaccord incrémente aussi le compteur `disagreements` **des deux moteurs**
dans `ai_provider_metrics` : personne n'a raison tant qu'on ne sait pas qui
avait raison.

### Événements diffusés

| Événement | Quand |
|---|---|
| `ai.disagreement` | Uniquement en cas de `DISAGREEMENT` |
| `ai.consensus` | À chaque confrontation, quel qu'en soit le verdict |

---

## 7. Réglages

| Clé JSON | Défaut | Effet |
|---|---|---|
| `ensembleEnabled` | `false` | Drapeau destiné aux appelants qui décident de passer en ensemble |
| `requireConsensus` | `true` | Exige un consensus franc pour toute exécution automatique |
| `disagreementBehaviour` | `"NO_TRADE"` | Conduite à tenir en cas de désaccord |
| `mode` | `"AUTO"` | Mettre `"ENSEMBLE"` pour signaler l'intention |

Modification :

```powershell
$corps = @{ ensembleEnabled = $true; requireConsensus = $true } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$bridge/ai/router/settings" -Headers $entetes -Body $corps
```

> **Note sur `ensembleEnabled`.** `AIEnsembleService.analyse` ne consulte pas ce
> réglage : il interroge les deux moteurs dès qu'on l'appelle. C'est à
> l'appelant — le futur moteur de décision — de décider s'il passe par le
> consensus ou par un simple appel routé. Le réglage est un drapeau
> d'intention, pas un interrupteur de sécurité.

> **Note sur `disagreementBehaviour`.** La valeur est stockée et exposée, mais
> aucun code ne la lit encore : aujourd'hui, un désaccord bloque
> systématiquement l'automatisme via `blocks_auto_trade`. La distinction fine
> entre `NO_TRADE` et `NEEDS_REVIEW` sera faite par le moteur de décision, en
> cours d'écriture.

---

## 8. Les comportements garantis par les tests

`bridge/tests/test_ai_consensus.py` — 9 tests.

| Test | Ce qu'il verrouille |
|---|---|
| `test_deux_moteurs_d_accord_donnent_un_consensus` | BUY 0,78 + BUY 0,82 → `CONSENSUS`, confiance ≈ 0,80 |
| `test_desaccord_bloque_l_automatisme` | BUY + SELL → `DISAGREEMENT`, **direction nulle** |
| `test_meme_direction_mais_convictions_eloignees` | BUY 0,95 + BUY 0,40 → `PARTIAL_CONSENSUS`, confiance **0,40** |
| `test_un_seul_moteur_ne_vaut_pas_un_consensus` | Un seul avis → `INSUFFICIENT_DATA`, confiance ≤ 0,60 |
| `test_aucun_moteur_disponible` | Liste vide → `PROVIDER_UNAVAILABLE` |
| `test_sorties_illisibles_ne_produisent_aucune_direction` | Deux sorties illisibles → aucune direction |
| `test_contradiction_technique_fait_chuter_la_confiance` | Recalibrage à la baisse, rétrogradation du verdict |
| `test_accord_avec_la_technique_donne_une_petite_prime` | Prime, plafonnée à 0,95 |
| `test_le_recalibrage_ne_cree_jamais_de_direction` | Un désaccord reste un désaccord après recalibrage |

```powershell
bridge\.venv\Scripts\python.exe -m pytest bridge\tests\test_ai_consensus.py -q
```

---

## 9. État au 11 septembre 2026

`AIEnsembleService` et `AIConsensusEngine` sont **écrits, testés et prêts**,
mais **aucun code de production ne les appelle encore**. Le moteur de décision
qui doit interroger le consensus avant de proposer une opportunité est en cours
d'écriture par une autre équipe.

Ce qui existe aujourd'hui :

- la mécanique complète de confrontation et de recalibrage ;
- la persistance dans `ai_consensus_records` et la route de consultation ;
- les événements `ai.disagreement` et `ai.consensus` ;
- les réglages, exposés par l'API.

Ce qui manque :

- un appelant en production ;
- l'exploitation de `disagreementBehaviour` ;
- l'écran mobile de comparaison des deux avis.

---

Le trading comporte un risque de perte. Deux modèles d'accord ne sont pas deux
preuves : ce sont deux avis, éventuellement faux de la même manière. C'est
précisément pourquoi le recalibrage contre les données mesurées existe, et
pourquoi le `RiskManager` garde le dernier mot.
