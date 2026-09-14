# OpenRouter et modèles gratuits

TradePilot utilise un modèle de langage **uniquement pour lire un message
ambigu**. Le modèle ne décide jamais s'il faut trader, ne juge jamais la
rentabilité d'un signal et n'a jamais le dernier mot : sa sortie est retypée puis
revalidée localement avant toute suite.

Ce document décrit la configuration d'OpenRouter, le fonctionnement du sélecteur
de modèles gratuits, la gestion des quotas, et ce qui est réellement transmis au
modèle.

---

## 1. Créer une clé OpenRouter

1. Créez un compte sur <https://openrouter.ai>.
2. Ouvrez <https://openrouter.ai/keys>.
3. Cliquez sur **Create Key**, donnez-lui un nom (`TradePilot`), validez.
4. Copiez la clé, de la forme `sk-or-v1-…`. **Elle n'est affichée qu'une fois.**

Un compte gratuit suffit : TradePilot ne sélectionne jamais automatiquement un
modèle payant.

---

## 2. Enregistrer la clé

Deux voies, au choix.

### 2.1 Dans `bridge\.env`

```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_PREFERRED_TEXT_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_PREFERRED_VISION_MODEL=
OPENROUTER_FREE_ONLY=true
```

Au démarrage, si aucune clé n'est encore enregistrée en base, celle du fichier
`.env` est reprise **et chiffrée** dans la table `secrets` sous la clé
`openrouter.api_key`.

### 2.2 Depuis l'application

```
PUT /api/v1/openrouter/key
{ "apiKey": "sk-or-v1-..." }
```

La clé est immédiatement chiffrée (Fernet, avec la `MASTER_KEY`) et la liste des
modèles gratuits est rafraîchie dans la foulée. Envoyer `{"apiKey": null}`
supprime la clé.

**La clé n'est jamais renvoyée en clair.** `GET /api/v1/openrouter/status`
n'expose qu'un indice partiel dans `apiKeyHint`, de la forme `sk-o...9f2a`. Les
journaux masquent également toute chaîne commençant par `sk-or-v1-`.

### 2.3 Vérifier que ça marche

```
POST /api/v1/openrouter/test
```

ou, depuis l'écran de diagnostic :

```
POST /api/v1/diagnostics/test/openrouter
```

La réponse contient `ok`, le modèle utilisé, la latence en millisecondes et
l'erreur éventuelle. Le test consiste en un échange minimal — deux messages,
`max_tokens = 8`, délai maximal 25 secondes — qui ne consomme presque rien.

### 2.4 Les réglages `PREFERRED`

| Variable | Rôle |
|---|---|
| `OPENROUTER_PREFERRED_TEXT_MODEL` | modèle texte que vous **préférez**, s'il est disponible et gratuit. Par défaut `nvidia/nemotron-3-ultra-550b-a55b:free`. |
| `OPENROUTER_PREFERRED_VISION_MODEL` | même chose pour l'analyse d'images. Vide par défaut : le sélecteur choisit seul. |
| `OPENROUTER_FREE_ONLY` | `true` par défaut. Documente et confirme la règle : aucun modèle payant n'est jamais sélectionné automatiquement. |

Un modèle préféré indisponible ou devenu payant n'est **pas** utilisé : le
sélecteur journalise « Modele prefere … indisponible ou payant : repli gratuit »
et retombe sur le meilleur candidat gratuit.

---

## 3. Le sélecteur de modèles gratuits

Classe `FreeModelSelector`, fichier
`bridge/app/services/openrouter/model_selector.py`.

Les modèles gratuits d'OpenRouter apparaissent et disparaissent régulièrement.
Le système ne doit donc jamais dépendre d'un identifiant figé.

### 3.1 Comment un modèle est reconnu comme gratuit

`is_free_model` examine le bloc `pricing` renvoyé par OpenRouter et vérifie que
**toutes** les composantes présentes valent zéro :
`prompt`, `completion`, `request`, `image`, `input_cache_read`,
`input_cache_write`.

- Si l'une d'elles est non nulle, le modèle est payant.
- Si l'une d'elles est illisible, le modèle est considéré comme payant — le doute
  profite à la prudence.
- Si le bloc `pricing` ne contient aucune de ces clés, le modèle n'est retenu que
  si son identifiant se termine par `:free`.

### 3.2 Filtres appliqués

Un candidat est écarté si :

- il n'est pas gratuit ;
- une capacité vision est demandée et il ne la possède pas ;
- sa fenêtre de contexte est connue et inférieure à **4 000** jetons.

### 3.3 Classement

Chaque candidat gratuit reçoit un score :

| Critère | Points |
|---|---|
| Famille reconnue pour bien suivre une consigne d'extraction structurée : `nvidia/`, `deepseek/`, `qwen/`, `meta-llama/`, `mistralai/`, `google/gemini`, `z-ai/`, `moonshotai/` | `3.0` pour la première, puis `−0.2` par rang |
| Prise en charge des *tools* (appel de fonction) | `+2.0` |
| Contexte ≥ 32 000 jetons | `+1.5` |
| Contexte ≥ 8 000 jetons (sinon) | `+0.5` |
| Capacité vision, lorsqu'elle est demandée | `+4.0` |
| Identifiant contenant `:free` | `+0.5` |

Le classement final se fait par score décroissant, puis par taille de contexte.
Les 40 premiers sont conservés dans `ai_model_state.free_models` et exposés par
l'API.

Le support des *tools* est fortement valorisé parce qu'il permet d'imposer un
schéma de sortie strict (`parse_trading_signal`), bien plus fiable qu'une demande
de JSON en texte libre.

### 3.4 Sélection

1. Le modèle **préféré** est placé en tête s'il figure dans la liste des
   candidats gratuits.
2. Le sélecteur teste jusqu'aux **trois premiers** candidats avec le ping
   minimal. Le premier qui répond est retenu, avec sa latence.
3. Si aucun des trois ne répond, le meilleur candidat gratuit est **conservé
   quand même**, mais `last_error` est renseigné : « Aucun modele gratuit n'a
   repondu au test ». Le système ne prétend pas avoir validé un modèle qu'il n'a
   pas pu joindre.
4. Le modèle **vision** est choisi de la même façon mais **sans test** : un test
   d'image consommerait un quota image pour rien.

### 3.5 Mode manuel

```
PUT /api/v1/openrouter/models
{ "autoMode": false, "textModel": "<id>", "visionModel": "<id>" }
```

Le mode manuel **refuse** tout modèle absent de la liste des modèles gratuits
disponibles : l'API répond `400` avec « … n'est pas dans la liste des modèles
gratuits disponibles ». Il n'existe aucune route permettant de sélectionner un
modèle payant.

Repasser en automatique :

```
PUT /api/v1/openrouter/models
{ "autoMode": true }
```

Consulter la liste :

```
GET /api/v1/openrouter/models          # liste en cache
GET /api/v1/openrouter/models?refresh=true   # force le rafraîchissement
```

La réponse contient `freeModels`, `visionModels` (le sous-ensemble avec capacité
vision) et la note : « Seuls les modèles gratuits sont listés et sélectionnables
automatiquement. »

---

## 4. Aucun modèle payant, jamais

C'est une propriété du code, à trois niveaux :

1. `rank_free_models` **écarte** tout candidat non gratuit avant même le
   classement. La sélection automatique ne voit que des modèles gratuits.
2. Le mode manuel **valide** le choix contre la liste des modèles gratuits et le
   refuse sinon.
3. Aucune route, aucun réglage et aucun champ ne permettent de désigner un modèle
   payant. `AiRequest.is_free_model` est écrit à `true` pour toutes les requêtes
   parce qu'aucune autre situation n'est atteignable.

Conséquence à assumer : si OpenRouter ne propose plus aucun modèle gratuit
correspondant aux critères, TradePilot ne bascule pas sur un modèle payant. Il
s'arrête.

---

## 5. « Aucun modèle gratuit disponible actuellement »

C'est le message exact (`NO_FREE_MODEL_MESSAGE`) affiché lorsque le sélecteur ne
trouve aucun candidat gratuit utilisable.

### 5.1 Où il apparaît

- dans `GET /api/v1/openrouter/status`, champ `lastError` ;
- dans la réponse de `POST /api/v1/openrouter/test` ;
- dans le diagnostic système, ligne OpenRouter ;
- dans le journal, catégorie `ai`.

### 5.2 Ce que fait le système dans ce cas

Rien de dramatique : **le parser déterministe continue de fonctionner seul.**
`pipeline.analyze_text` n'appelle l'IA que si `openrouter_service.configured` est
vrai et que le repli aboutit ; sinon le signal conserve la lecture locale et
reçoit l'avertissement `ia_indisponible`.

Un message clairement structuré (`BUY XAUUSD 2400 SL 2390 TP 2420`) est lu à
`1.00` de confiance par le parser local, sans aucun appel réseau. L'absence de
modèle gratuit n'empêche donc pas le fonctionnement nominal : elle réduit
seulement la tolérance aux messages mal écrits.

### 5.3 Que faire

| Cause possible | Action |
|---|---|
| Un modèle préféré figé qui n'existe plus | videz `OPENROUTER_PREFERRED_TEXT_MODEL` dans `bridge\.env` et laissez le sélecteur choisir |
| Cache de modèles périmé | `GET /api/v1/openrouter/models?refresh=true` |
| Clé absente ou refusée | vérifiez `apiKeyHint` dans le statut, réenregistrez la clé |
| Offre gratuite momentanément vide chez OpenRouter | attendez ; le parser local reste opérationnel |

La section 6 de [TROUBLESHOOTING.md](TROUBLESHOOTING.md) détaille ce cas.

---

## 6. Quotas 429 et coupe-circuit

### 6.1 Le client ne boucle jamais

`OpenRouterClient.chat` effectue **une seule tentative**. Il n'y a aucune boucle
de réessai : une erreur remonte immédiatement à l'appelant, qui poursuit sans
l'IA.

### 6.2 Traduction des réponses HTTP

| Statut | Exception levée | Compte comme un échec du coupe-circuit ? |
|---|---|---|
| `429` | `OpenRouterRateLimited` (avec `retry_after` si l'en-tête est fourni) | oui |
| `401`, `403` | `OpenRouterAuthError` | non — une clé invalide n'est pas une panne |
| `404` | `OpenRouterError` (« Modèle introuvable ») | non |
| `5xx` | `OpenRouterUnavailable` | oui |
| délai dépassé | `OpenRouterUnavailable` | oui |
| erreur réseau | `OpenRouterUnavailable` | oui |

En cas de `429`, le pipeline reçoit l'erreur « Quota OpenRouter atteint : … », le
signal conserve sa lecture locale et l'appel est tracé dans la table
`ai_requests` avec `success = false`.

### 6.3 Le coupe-circuit

`CircuitBreaker`, dans `bridge/app/services/openrouter/client.py` :

| Paramètre | Valeur |
|---|---|
| Seuil d'ouverture | **4** échecs consécutifs |
| Durée d'ouverture | **300 secondes** (5 minutes) |
| Réarmement | automatique à l'expiration du délai |
| Remise à zéro | dès qu'un appel réussit |

Circuit ouvert, tout appel est refusé immédiatement, sans requête réseau, avec le
message « OpenRouter temporairement suspendu (N s restantes) ». `GET
/api/v1/openrouter/status` expose `circuitOpen` et `circuitResetInSeconds`, et
l'état de connexion passe à `ERROR`.

L'intérêt est double : ne pas aggraver un quota déjà dépassé, et ne pas ralentir
le pipeline avec des délais d'attente répétés. Le parser local, lui, continue.

### 6.4 Cache de la liste des modèles

`list_models` met la liste en cache pendant **900 secondes** (15 minutes).
`force_refresh=True` la contourne. Cela évite d'interroger OpenRouter à chaque
rafraîchissement d'écran.

---

## 7. Ce qui est envoyé au modèle

### 7.1 Extraction de signal

Fichier `bridge/app/services/openrouter/signal_ai.py`. Deux messages, et rien
d'autre :

1. un **prompt système** fixe, en anglais, qui impose de n'extraire que ce qui
   est explicitement présent, de mettre `null` sur toute valeur inconnue, de ne
   jamais inventer un prix, un stop, une cible, un symbole ni une direction, et
   de répondre `is_signal = false` pour un message de commentaire, de salutation,
   de résultats ou de promotion ;
2. le **texte du message Telegram**, tronqué à **4 000 caractères**.

Ce qui n'est **jamais** transmis :

- votre solde, votre equity, votre marge ;
- votre numéro de compte MetaTrader, le nom du serveur, le nom du broker ;
- vos réglages de risque, votre volume calculé, vos positions ouvertes ;
- votre identité Telegram, le nom ou l'identifiant du canal ;
- vos clés, jetons ou identifiants, quels qu'ils soient.

Le modèle ne reçoit littéralement que le texte public du message.

### 7.2 Ce qui est conservé de l'échange

La table `ai_requests` enregistre, pour l'audit et pour le suivi des quotas :
`purpose` (`signal_parse`, `chart_analysis`, `model_test`), `model`,
`is_free_model`, `success`, `http_status`, `latency_ms`, `prompt_chars`,
`response_chars`, `error` (tronquée à 255 caractères) et `signal_id`.

**Le contenu du message et la réponse du modèle ne sont pas stockés dans cette
table** — seulement leurs tailles.

### 7.3 Analyse de graphique

`POST /api/v1/ai/chart` envoie une capture d'écran à un modèle **vision gratuit**.

| Contrainte | Valeur |
|---|---|
| Taille maximale | 4 Mo |
| Formats acceptés | `image/png`, `image/jpeg`, `image/jpg`, `image/webp` |
| Champs facultatifs | `instrument` (32 caractères), `question` (500 caractères) |

Le prompt système impose de ne décrire que ce qui est visible, de ne jamais
garantir un résultat, de ne jamais donner de conseil financier, et de le dire
clairement si l'image est illisible ou n'est pas un graphique de prix.

La réponse contient toujours ce texte, ajouté par le Bridge :

> Analyse indicative produite par un modèle de langage à partir d'une image.
> Elle ne constitue pas un conseil et ne déclenche aucun ordre.

**Cette page ne déclenche jamais aucun ordre.** Aucun chemin de code ne relie
l'analyse de graphique au moteur de trading.

---

## 8. L'économie d'appels

Chaque appel évité, c'est du quota gratuit préservé, de la latence en moins et
une décision plus prévisible.

### 8.1 Le parser local passe toujours en premier

Le parser déterministe est rapide, testable et gratuit. L'IA n'est sollicitée que
si **au moins une** de ces conditions est vraie :

- le parser local n'a pas reconnu de signal ;
- la validation locale a échoué ;
- la confiance est inférieure à `AI_FALLBACK_THRESHOLD = 0.85`.

Sur un canal bien structuré, la quasi-totalité des messages est lue localement
avec une confiance de `1.00` et ne déclenche **aucun** appel.

### 8.2 Le filtre des messages sans intérêt

Même quand le repli serait justifié, `_looks_worth_recording` annule l'appel si
le message ne contient aucun des marqueurs `BUY`, `SELL`, `LONG`, `SHORT`, `TP`,
`SL`, `ENTRY`, `TARGET`, `CLOSE`, `BE`.

« Good morning family, hope you are well » ne coûte donc jamais un appel.

### 8.3 Aucun appel pendant l'analyse d'un canal

`analyze_channel` rejoue le parser sur l'historique avec `allow_ai=False`.
Analyser 500 messages avec un modèle gratuit épuiserait la totalité du quota
disponible pour un rapport de mesures. La contrepartie est assumée : le taux de
messages interprétables mesuré correspond au **parser local seul**, ce qui est
une mesure plus honnête de la structure réelle du canal.

### 8.4 Les gabarits appris par canal

Table `channel_parser_profiles`, une ligne par canal :

| Champ | Contenu |
|---|---|
| `symbol_aliases` | les alias observés sur ce canal, par exemple `GOLD → XAUUSD`. Ils sont réinjectés dans le parser à chaque message de ce canal. |
| `known_formats` | les **20 dernières** signatures de structure rencontrées, par exemple `BUY\|ENTRY\|SL\|TP1\|TP2`. La signature ne contient que la suite des mots-clés, jamais le contenu du message. |
| `last_successful_format` | la dernière signature reconnue |
| `deterministic_success` | nombre de messages lus par le parser local |
| `ai_fallback_count` | nombre de messages ayant nécessité l'IA |
| `confidence` | `deterministic_success / (deterministic_success + ai_fallback_count)` |

Ce champ `confidence` est un indicateur direct du coût du canal : plus il est
proche de `1.0`, moins ce canal consomme de quota. Il est visible dans
`GET /api/v1/channels/{channel_id}`, bloc `parserProfile`.

Un alias appris rend souvent inutile un appel IA qui aurait été nécessaire la
première fois : un canal qui écrit `OR` pour l'or coûte un appel une fois, puis
plus jamais.

### 8.5 L'IA ne peut pas contredire le parser local

Si le parser local avait déjà identifié l'instrument et la direction, la sortie
de l'IA est réécrite avec les valeurs locales et porte les avertissements
`ia_symbole_ignore_au_profit_du_parser_local` et
`ia_direction_ignoree_au_profit_du_parser_local`. La lecture locale est également
conservée si elle était déjà valide et au moins aussi sûre que celle du modèle.

---

## 9. Le plafond de confiance de l'IA

Un signal lu par l'IA voit sa confiance calculée ainsi : `0.60` de base,
`+0.05` s'il y a une entrée, `+0.10` s'il y a un stop loss, `+0.05` s'il y a au
moins un objectif — le tout **plafonné à `0.80`**.

Or `min_confidence` vaut `0.85` par défaut.

**Conséquence pratique : avec les réglages par défaut, un signal lu par l'IA est
systématiquement refusé en mode automatique, avec le motif `LOW_CONFIDENCE`.**
C'est cohérent avec le principe « l'IA n'a jamais le dernier mot », mais il faut
le savoir.

Trois façons de traiter ces signaux :

| Approche | Effet |
|---|---|
| Laisser tel quel | les messages ambigus sont enregistrés et visibles, mais jamais exécutés automatiquement |
| Passer le canal en mode `MANUAL` | vous validez à la main ; la validation manuelle contourne le contrôle de confiance, mais **aucun autre** contrôle de risque |
| Abaisser `min_confidence` (par exemple à `0.75`) | les signaux lus par l'IA deviennent éligibles à l'exécution automatique. À ne faire qu'après avoir observé longuement, en mode `OBSERVE` puis en `PAPER`, la qualité réelle des lectures IA sur vos canaux. |

---

## 10. Ce qui n'a pas pu être vérifié sur cette machine

- **Aucun appel réel à OpenRouter n'a été effectué.** Aucune clé valide n'a été
  utilisée : ni la liste des modèles, ni le classement réel des modèles gratuits,
  ni la qualité d'extraction d'un modèle donné, ni le comportement effectif des
  réponses `429` n'ont été observés.
- Le sélecteur, le coupe-circuit et le retypage de la sortie du modèle sont
  couverts par la suite de tests locale, avec des réponses simulées.
- La disponibilité et la liste des modèles gratuits d'OpenRouter changent
  fréquemment : le modèle indiqué par défaut dans `.env.example`
  (`nvidia/nemotron-3-ultra-550b-a55b:free`) peut ne plus exister au moment où
  vous lisez ces lignes. C'est précisément pour cela que le sélecteur ne dépend
  pas d'un identifiant figé.
