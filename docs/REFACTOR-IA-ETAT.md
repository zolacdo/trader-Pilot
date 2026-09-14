# Retrait de l'IA locale — état du refactor

> Note de passation, écrite le 2026-09-11 à 21:15.
> Le refactor a été commencé par deux agents en parallèle, puis confié à un seul.
> Ce document dit ce qui est fait, ce qui est cassé, et les deux pièges à ne pas rater.

---

## 1. Le piège principal : le consensus bloque tout trade automatique

**À lire avant de toucher à `app/services/ai/ensemble/service.py`.**

Supprimer le moteur local ne supprime pas du code mort. Il ne reste qu'un seul
avis, et `AIConsensusEngine.evaluate()` traite un avis unique comme une absence
de consensus :

```python
if len(usable) == 1:
    return ConsensusResult(
        ConsensusOutcome.INSUFFICIENT_DATA,   # -> blocks_auto_trade == True
        confidence=min(single.confidence, 0.6),
        ...
    )
```

La chaîne est réelle et porteuse :

```
services/intelligence/cycle.py:179   ai_service.consensus(...)
  -> services/ai/service.py:244      requires_manual_review()
     -> services/decision/guards.py:143   if consensus.blocks_auto_trade: BLOQUE
```

Et `AISettings.require_consensus_for_auto_trade` vaut `True` par défaut.

**Conséquence si on se contente de retirer la branche locale : plus aucun trade
automatique ne passe, en silence.** Ce n'est pas une erreur qui se voit dans les
tests unitaires — le bot se tait, simplement.

**Solution retenue avec l'utilisateur : confronter deux modèles OpenRouter.**
`model_selector.rank_free_models()` classe déjà jusqu'à 40 modèles gratuits
(`AiModelState.free_models`). L'ensemble doit interroger les deux meilleurs
modèles distincts au lieu de « local vs OpenRouter ». Toute la logique
`DISAGREEMENT` / `PARTIAL_CONSENSUS` / `blocks_auto_trade` reste alors valable
telle quelle, sans modification.

Si aucun second modèle distinct n'est disponible, il faut **renoncer à la
confrontation et le dire**, jamais interroger deux fois le même modèle et
appeler cela un consensus.

## 2. Bug présent dans le routeur actuel

`app/services/ai/router/router.py` référence un réglage qui n'existe pas :

```python
if needs_vision and not settings.openrouter_supports_vision:
```

`grep -rn "openrouter_supports_vision" app/` ne retourne **rien**.
`AttributeError` garanti sur toute tâche vision.

Soit on ajoute le champ à `AISettings`, soit on lit la capacité réelle depuis
`AiModelState.vision_model_ok`, qui existe déjà et est tenu à jour par le
sélecteur. La seconde option est la bonne : elle ne duplique pas un état.

## 3. Correction d'une affirmation fausse dans les commentaires

L'en-tête actuel de `router.py` affirme que le moteur local « saturait la
mémoire de la machine ». **C'est faux et mesuré comme tel.**

`LocalAIProvider` était un client HTTP `httpx` : il n'a jamais chargé de modèle
en mémoire. Aucun moteur d'inférence (Ollama, LM Studio, llama.cpp, vLLM,
GPT4All) n'était installé ni en cours d'exécution sur la machine, et
`local_enabled` valait `False` par défaut.

La saturation RAM venait d'ailleurs (voir section 6). La justification honnête
du retrait est : **un seul fournisseur à maintenir, pas de serveur d'inférence à
héberger.** Pas un gain mémoire.

---

## 4. Ce qui est fait

| Fichier | État |
|---|---|
| `app/services/ai/local/` | **supprimé** |
| `app/models/intelligence.py` | `AIProviderKind` → `OPENROUTER` seul ; `AIMode` → `SINGLE` / `ENSEMBLE` ; 12 champs `local_*` retirés de `AISettings` ; `ensemble_secondary_model` ajouté ; `AIConsensusRecord.local_*`/`openrouter_*` → `primary_*`/`secondary_*` ; `AIRoutingEvent.chosen_model` ajouté |
| `app/services/ai/base.py` | `complete()` et `complete_json()` acceptent `model: str \| None` |
| `app/services/ai/openrouter_provider.py` | `complete()` honore le modèle imposé, sinon retombe sur la sélection automatique |
| `mobile/android/gradle.properties` | `-Xmx8G`/Metaspace 4G → `-Xmx3G`/Metaspace 1G |

`AISettings.mode` vaut désormais `ENSEMBLE` par défaut — délibérément, à cause
du piège de la section 1.

## 5. Ce qui reste — le bridge ne démarre pas

```
ModuleNotFoundError: No module named 'app.services.ai.local'
  app/services/ai/service.py:35
```

Références mortes à traiter :

| Emplacement | Problème |
|---|---|
| `app/services/ai/service.py:35,49` | importe et instancie `LocalAIProvider` |
| `app/services/ai/service.py:302` | lit les opinions via `AIProviderKind.LOCAL` |
| `app/services/ai/ensemble/service.py:259,266` | `AIMode.LOCAL_ONLY`, `AIProviderKind.LOCAL` |
| `app/repositories/ai_repo.py:108` | boucle sur `AIProviderKind.LOCAL` |
| `app/services/signals/pipeline.py:136` | `AIMode.LOCAL_ONLY` |

Puis, non commencés :

- `app/api/v1/ai.py` — 31 occurrences (endpoints de config locale, `test_local`, `local_models`)
- `app/schemas/requests.py` — 13 occurrences
- `app/services/ai/service.py` — `test_local()`, `local_models()`, `_persist_consensus()`
- **Migration** — `AIMode` ne connaît plus `AUTO`/`LOCAL_ONLY`/`LOCAL_FIRST`/`OPENROUTER_FIRST` : les lignes existantes en base portent ces valeurs et lèveront à la lecture. `SCHEMA_VERSION` est à `1` dans `app/database/migrations.py` ; il faut un `_migration_002` qui remappe `mode` et recopie `local_*`/`openrouter_*` vers `primary_*`/`secondary_*`.
- **Tests** — `test_ai_router.py` (23 occ.), `test_ai_routing_fixes.py` (27), `test_ai_consensus.py`, `test_shadow_mode.py`, `test_learning.py`, `test_notifications.py`
- **Flutter** — `mobile/lib/features/ai_config/` : supprimer `widgets/ai_local_section.dart`, nettoyer `ai_config_providers.dart`, `ai_diagnostic_screen.dart`, `ai_labels.dart`, `models/ai_settings.dart`, `models/ai_status.dart`, `widgets/ai_diagnostic_sections.dart`

Attention aux faux positifs sur `grep local` : `tunnel/ngrok_service.py`,
`news/providers.py`, `security/auth.py` (`localhost`) et plusieurs variables
locales n'ont rien à voir avec le moteur d'IA.

---

## 6. Saturation RAM — la vraie cause

Mesures du 2026-09-11 sur la machine de développement :

| Poste | Mesure |
|---|---|
| RAM physique | **7,87 Go** |
| Commit charge | **9,4 → 11,2 Go** — la machine pagine en permanence |
| VS Code | 17 processus, 1,7 Go, **7 fenêtres ouvertes** |
| svchost | 78 processus, 1,0 Go |
| Démon Gradle | 550 Mo, autorisé à **8 Go de tas + 4 Go de metaspace** |
| WhatsApp + WebView2 | 834 Mo |
| Defender (MsMpEng) | 346 Mo |

La cause corrigée : `mobile/android/gradle.properties` réclamait plus que la RAM
physique totale de la machine. Le démon Gradle PID en cours doit être arrêté
(`./gradlew --stop`) pour que le nouveau plafond s'applique.

L'IA locale n'y était pour rien.
