# Installer et configurer un moteur d'IA local

TradePilot sait interroger un modèle de langage qui tourne **sur votre propre
PC Windows**, à côté du Bridge et de MetaTrader 5. C'est le mode privilégié
pour tout ce qu'un petit modèle sait faire correctement : lire un message
Telegram ambigu, classer une actualité, produire un résumé court.

Trois raisons concrètes :

- **gratuit** — aucun quota, aucun jeton facturé, aucune clé à renouveler ;
- **privé** — le contenu des canaux que vous suivez ne quitte pas la machine ;
- **disponible** — le moteur local continue de répondre quand OpenRouter
  est en panne, saturé, ou quand plus aucun modèle gratuit n'est proposé.

Ce document explique comment l'installer, le déclarer à TradePilot, le tester,
et choisir un modèle qui tienne dans la mémoire vive dont vous disposez
réellement.

> **Rien n'est obligatoire.** TradePilot fonctionne sans moteur local :
> OpenRouter reste actif par défaut. Le moteur local est désactivé tant que
> vous ne l'activez pas (`localEnabled = false` à l'installation).

---

## 1. Choisir entre Ollama et un serveur compatible OpenAI

TradePilot reconnaît deux dialectes réseau.

| | **Ollama** | **Compatible OpenAI** (LM Studio, llama.cpp, vLLM, LocalAI…) |
|---|---|---|
| Réglage `localProvider` | `ollama` | `openai_compatible` (valeur par défaut) |
| Port par défaut | `11434` | `1234` pour LM Studio |
| Installation | Un exécutable, un service qui démarre seul | Une application avec interface graphique |
| Téléchargement des modèles | `ollama pull` en ligne de commande | Catalogue intégré, en cliquant |
| Vision (images) | **Non transmis par TradePilot** — voir §7 | Oui |
| Bon pour | Laisser tourner en tâche de fond, sans y penser | Essayer plusieurs modèles, voir ce qui se passe |

Si vous hésitez : **Ollama**. Il démarre tout seul avec Windows et se pilote en
deux commandes.

---

## 2. Installer Ollama sur Windows

### 2.1 Installation

1. Téléchargez l'installeur sur <https://ollama.com/download/windows>.
2. Lancez `OllamaSetup.exe` et laissez les options par défaut.
3. Ouvrez **PowerShell** et vérifiez :

```powershell
ollama --version
```

L'installeur enregistre un service qui écoute sur `http://127.0.0.1:11434` et
redémarre avec Windows. Vous n'avez rien à lancer à la main.

### 2.2 Télécharger un modèle

Pour du parsing et de la classification, un modèle de 7 à 8 milliards de
paramètres en quantification 4 bits suffit largement :

```powershell
ollama pull qwen2.5:7b-instruct
```

Le téléchargement fait environ 4,5 Go. Vérifiez ensuite ce que vous avez :

```powershell
ollama list
```

```
NAME                     ID              SIZE      MODIFIED
qwen2.5:7b-instruct      a1b2c3d4e5f6    4.7 GB    2 minutes ago
```

La colonne `SIZE` est la taille réelle du fichier. Retenez-la : c'est le
plancher de ce que le modèle va occuper en mémoire (voir §6).

### 2.3 Vérifier que le serveur répond

Ces deux commandes sont exactement celles que TradePilot utilisera.

```powershell
# Liste des modèles — c'est ce que lit GET /api/v1/ai/local/models
curl.exe http://127.0.0.1:11434/api/tags
```

```powershell
# Une vraie complétion, en mode JSON
curl.exe http://127.0.0.1:11434/api/chat -H "Content-Type: application/json" -d "{\"model\":\"qwen2.5:7b-instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"Reponds uniquement par le mot OK.\"}],\"stream\":false}"
```

Si la première commande échoue, le service n'est pas démarré. Lancez
`ollama serve` dans une fenêtre PowerShell et laissez-la ouverte.

> **Le premier appel est lent.** Ollama charge le modèle en mémoire à la
> première requête : comptez 10 à 40 secondes selon votre disque. Les appels
> suivants sont rapides tant que le modèle reste chargé. C'est pour cela que le
> délai d'attente par défaut de TradePilot est de **60 secondes**.

---

## 3. Variante : LM Studio (compatible OpenAI)

1. Téléchargez LM Studio sur <https://lmstudio.ai> et installez-le.
2. Onglet **Discover** (loupe) : cherchez un modèle *instruct*, par exemple
   `Qwen2.5 7B Instruct`, et prenez une variante **GGUF Q4_K_M**.
3. Onglet **Developer** (ou **Local Server** selon la version) : chargez le
   modèle, puis cliquez sur **Start Server**.
4. LM Studio affiche l'adresse d'écoute, en général :

```
http://127.0.0.1:1234
```

Vérifiez :

```powershell
curl.exe http://127.0.0.1:1234/v1/models
```

> **Attention à l'adresse.** LM Studio affiche souvent
> `http://127.0.0.1:1234/v1`. **Ne mettez pas le `/v1`** dans le réglage
> `localBaseUrl` de TradePilot : le Bridge ajoute lui-même `/v1/models` et
> `/v1/chat/completions`. Une adresse terminée par `/v1` produirait un appel à
> `/v1/v1/models`, qui échoue avec un HTTP 404. La bonne valeur est
> `http://127.0.0.1:1234`.

La même règle vaut pour llama.cpp (`llama-server`), vLLM ou LocalAI : donnez la
racine du serveur, sans le `/v1`.

---

## 4. Quel modèle choisir

Pour ce que TradePilot demande au moteur local — **lire, extraire, classer,
résumer** — la capacité de raisonnement compte moins que la discipline à
respecter un format de sortie. Trois critères, dans cet ordre :

1. **une variante `instruct`** (ou `chat`), jamais un modèle « base » ;
2. **une quantification 4 bits** (`Q4_K_M` ou `q4_0`) : c'est le meilleur
   compromis taille/qualité sur une machine ordinaire ;
3. **au moins 8 000 jetons de contexte**, ce qui est le cas de tous les
   modèles récents.

| Modèle | Commande Ollama | Taille disque | Pour qui |
|---|---|---|---|
| Qwen 2.5 7B Instruct | `ollama pull qwen2.5:7b-instruct` | ≈ 4,7 Go | **Le choix par défaut.** Très régulier sur les sorties JSON |
| Llama 3.1 8B Instruct | `ollama pull llama3.1:8b` | ≈ 4,9 Go | Bonne alternative, un peu plus bavard |
| Mistral 7B Instruct | `ollama pull mistral:7b-instruct` | ≈ 4,4 Go | Rapide, un peu moins précis en extraction |
| Qwen 2.5 3B Instruct | `ollama pull qwen2.5:3b-instruct` | ≈ 2,0 Go | Machines à 8 Go de RAM |
| Llama 3.2 3B Instruct | `ollama pull llama3.2:3b` | ≈ 2,0 Go | Idem |
| Gemma 2 2B | `ollama pull gemma2:2b` | ≈ 1,6 Go | Dernier recours, machine très modeste |

**Ce qui est inutile ici :** un modèle de 32B ou 70B. Il sera trois à dix fois
plus lent, prendra toute votre mémoire à côté de MetaTrader 5, et ne lira pas
mieux un message de deux lignes annonçant un `BUY XAUUSD 2650 SL 2640`. Si une
tâche dépasse vraiment un modèle de 7B, le routeur l'envoie à OpenRouter — c'est
exactement son rôle. Voir [AI_ROUTER.md](AI_ROUTER.md).

**Les tailles ci-dessus sont des ordres de grandeur** relevés sur les versions
courantes de ces modèles. La valeur qui fait foi sur votre machine est celle
affichée par `ollama list`.

---

## 5. Déclarer le moteur à TradePilot

### 5.1 Aujourd'hui, en HTTP

L'application Android déclare bien les chemins de l'écran de diagnostic IA,
mais **aucun écran ne les consomme encore** : cet écran est en cours de
développement. En attendant, la configuration se fait par appel direct à l'API
du Bridge, depuis la machine qui l'héberge.

Il vous faut un **jeton de périphérique** — celui obtenu lors de l'appairage du
téléphone, ou un nouveau jeton via `.\scripts\pairing_code.ps1`.

```powershell
$jeton   = "votre-jeton-de-peripherique"
$bridge  = "http://127.0.0.1:8787/api/v1"
$entetes = @{ "X-Device-Token" = $jeton; "Content-Type" = "application/json" }

$corps = @{
    localEnabled      = $true
    localProvider     = "ollama"
    localBaseUrl      = "http://127.0.0.1:11434"
    localTextModel    = "qwen2.5:7b-instruct"
    localSupportsJson = $true
    localTimeoutSeconds = 60
    localContextSize  = 8192
    mode              = "AUTO"
} | ConvertTo-Json

Invoke-RestMethod -Method Put -Uri "$bridge/ai/router/settings" -Headers $entetes -Body $corps
```

Pour LM Studio, remplacez les deux premières lignes :

```powershell
    localProvider = "openai_compatible"
    localBaseUrl  = "http://127.0.0.1:1234"
```

### 5.2 Tous les réglages du moteur local

| Clé JSON | Type | Défaut | Rôle |
|---|---|---|---|
| `localEnabled` | booléen | `false` | Active le moteur local. **Tant qu'il est faux, le moteur est ignoré partout** |
| `localProvider` | texte | `openai_compatible` | `ollama`, ou n'importe quoi d'autre pour le dialecte OpenAI |
| `localBaseUrl` | texte (255 max) | `""` | Racine du serveur, **sans `/v1`**, sans barre oblique finale |
| `localTextModel` | texte (128 max) | `null` | Nom exact du modèle, tel que renvoyé par le serveur |
| `localVisionModel` | texte (128 max) | `null` | Modèle pour les images. Voir §7 |
| `localAutoModel` | booléen | `true` | Réservé au choix automatique du modèle |
| `localTimeoutSeconds` | nombre, 0 < v ≤ 600 | `60` | Délai maximal d'une complétion |
| `localContextSize` | entier ≥ 512 | `8192` | Contexte annoncé, en jetons |
| `localSupportsJson` | booléen | `true` | Déclare que le modèle sait contraindre sa sortie en JSON |
| `localSupportsTools` | booléen | `false` | Appel d'outils |
| `localSupportsVision` | booléen | `false` | Déclare que le modèle accepte une image |

Le moteur local n'est considéré comme configuré que si **`localEnabled` est vrai
et `localBaseUrl` n'est pas vide**. Ces deux conditions sont vérifiées partout :
dans le routeur, dans le mode ensemble, dans le statut.

Ces capacités sont **déclaratives** : TradePilot vous croit sur parole. Si vous
annoncez un mode JSON que le modèle ne sait pas tenir, les appels partiront
quand même — et le taux de JSON valides chutera dans les métriques, ce qui
finira par faire rétrograder le moteur par le routeur.

> **Aucune clé d'API n'est envoyée au serveur local.** Ollama et LM Studio en
> configuration par défaut n'en demandent pas. Un serveur local protégé par une
> clé n'est pas utilisable en l'état.

---

## 6. Ce que cela coûte en mémoire vive

Soyons précis, parce que c'est là que les mauvaises surprises arrivent.

Un modèle chargé occupe **la taille de son fichier, plus le contexte, plus une
marge de travail**. Ordre de grandeur, en quantification 4 bits :

| Taille du modèle | Fichier | Mémoire réellement occupée | RAM totale recommandée sur la machine |
|---|---|---|---|
| 2B | ≈ 1,6 Go | ≈ 2,5 Go | 8 Go |
| 3B | ≈ 2,0 Go | ≈ 3 à 4 Go | 8 Go |
| 7B – 8B | ≈ 4,5 à 5 Go | ≈ 6 à 7 Go | **16 Go** |
| 14B | ≈ 9 Go | ≈ 11 Go | 32 Go |
| 32B et plus | ≥ 19 Go | ≥ 22 Go | 64 Go, ou une carte graphique dédiée |

**Et ce n'est pas la seule chose qui tourne sur ce PC.** Comptez en plus :

- Windows 10/11 au repos : 2 à 4 Go ;
- MetaTrader 5 Desktop avec quelques graphiques : 0,5 à 1,5 Go ;
- le Bridge Python et sa base SQLite : 200 à 400 Mo ;
- votre navigateur, si vous en ouvrez un.

Conclusion pratique :

- **8 Go de RAM** : restez sur un modèle 3B. Un 7B forcera Windows à paginer
  sur le disque, et vous verrez MetaTrader 5 devenir poussif au pire moment.
- **16 Go** : un modèle 7B–8B passe confortablement à côté de MT5.
- **32 Go ou une carte graphique récente** : vous pouvez viser plus gros, mais
  relisez la fin du §4 — ce n'est probablement pas utile pour cet usage.

**Carte graphique.** Ollama et LM Studio utilisent automatiquement une carte
NVIDIA ou AMD compatible si elle est présente. Le modèle occupe alors la
mémoire de la carte plutôt que la RAM système, et les réponses sont nettement
plus rapides. Ce n'est pas une condition : un 7B tourne sur processeur seul,
simplement plus lentement — quelques secondes par réponse courte, ce qui reste
acceptable pour du parsing.

**Le modèle reste chargé en mémoire** entre deux requêtes. Ollama le décharge
après quelques minutes d'inactivité, et le rechargera à la requête suivante :
c'est ce qui explique qu'un appel isolé soit parfois beaucoup plus lent que le
suivant.

---

## 7. Vision : la limite à connaître

Le moteur local ne reçoit une image **que par le dialecte compatible OpenAI**.
Dans ce cas, l'image est jointe en base64 au message, comme le fait OpenRouter.

**L'adaptateur Ollama ne transmet pas l'image.** Le corps de requête construit
pour `/api/chat` ne contient que le texte : une demande de lecture de graphique
partirait sans son graphique, et le modèle répondrait sur du vide. C'est une
limite réelle du code actuel, pas un réglage.

En conséquence, si vous voulez de la vision en local :

- utilisez **LM Studio** ou un autre serveur compatible OpenAI, avec un modèle
  vision (`Qwen2-VL`, `LLaVA`…), et réglez `localSupportsVision = true` plus
  `localVisionModel` ;
- ou laissez la vision à OpenRouter, en gardant `localSupportsVision = false`.

Ce second choix est celui par défaut, et il est sûr : quand une tâche exige une
image et que le moteur local ne déclare pas la vision, **le routeur le retire
purement et simplement de la liste** des moteurs à essayer. Un test verrouille
ce comportement (`test_la_vision_evite_un_local_incapable`).

Par ailleurs, si vous réglez `localSupportsVision = false` et qu'une image est
tout de même passée au moteur local, celui-ci refuse explicitement plutôt que
d'ignorer l'image en silence.

---

## 8. Vérifier que tout fonctionne

Trois vérifications, dans l'ordre.

### 8.1 Les modèles sont vus

```powershell
Invoke-RestMethod -Uri "$bridge/ai/local/models" -Headers @{ "X-Device-Token" = $jeton }
```

```json
{
  "count": 1,
  "models": [{ "id": "qwen2.5:7b-instruct", "size": 4683075271, "family": "qwen2" }],
  "note": "Liste fournie par votre serveur local. Aucun modèle n'est téléchargé ni installé par TradePilot."
}
```

Une liste vide signifie que le Bridge n'a pas joint votre serveur, ou que
`localEnabled` est resté à `false`.

### 8.2 Le moteur répond vraiment

```powershell
Invoke-RestMethod -Method Post -Uri "$bridge/ai/local/test" -Headers @{ "X-Device-Token" = $jeton }
```

Le Bridge envoie une vraie requête — « Réponds uniquement par le mot OK. »,
8 jetons, 20 secondes de délai maximal — et renvoie :

```json
{ "ok": true, "latencyMs": 812, "model": "qwen2.5:7b-instruct", "reply": "OK", "error": null }
```

En cas d'échec, `ok` vaut `false` et `error` contient le motif réel. **Rien
n'est inventé** : un moteur injoignable est signalé comme tel.

Ce test est journalisé dans le journal fonctionnel (`local_ai_tested`) et
diffusé sur le WebSocket.

### 8.3 Le statut global est cohérent

```powershell
Invoke-RestMethod -Uri "$bridge/ai/status" -Headers @{ "X-Device-Token" = $jeton }
```

Regardez `local.health` :

| Valeur | Signification |
|---|---|
| `ONLINE` | Le serveur a répondu à la sonde |
| `DEGRADED` | Un modèle est sélectionné mais le serveur n'a pas répondu |
| `OFFLINE` | Moteur désactivé, adresse absente, ou rien du tout |

---

## 9. Dépannage

| Symptôme | Cause probable | Ce qu'il faut faire |
|---|---|---|
| `Serveur local injoignable sur http://… : ConnectError` | Le serveur n'est pas démarré | `ollama serve`, ou **Start Server** dans LM Studio |
| Même message avec une adresse correcte | Le pare-feu Windows bloque la boucle locale, ou l'adresse contient un nom d'hôte non résolu | Utilisez `127.0.0.1`, pas `localhost` ni le nom de la machine |
| `Moteur local : HTTP 404` | L'adresse contient `/v1` en trop | Enlevez-le : `http://127.0.0.1:1234` |
| `Moteur local : HTTP 404` avec Ollama | `localProvider` est resté à `openai_compatible` | Mettez `ollama` |
| `Aucun modèle local sélectionné` | `localTextModel` est vide | Renseignez le nom **exact** renvoyé par `/ai/local/models` |
| `Délai dépassé par le moteur local (60s)` au premier appel | Chargement initial du modèle | Normal. Relancez ; si cela persiste, prenez un modèle plus petit ou montez `localTimeoutSeconds` |
| Délais dépassés en permanence | Le modèle ne tient pas en mémoire | Passez à un modèle 3B, ou fermez des applications |
| `Moteur local désactivé ou adresse absente` | `localEnabled = false` ou `localBaseUrl = ""` | Renvoyez les réglages de la §5.1 |
| `Le moteur local ne prend pas en charge les images` | `localSupportsVision = false` et une image a été fournie | Comportement voulu. Voir §7 |
| `validJsonRate` bas dans `/ai/metrics` | Le modèle ne respecte pas le format demandé | Prenez une variante `instruct`, ou un modèle plus grand |

Le moteur local est **toujours facultatif**. S'il tombe, le routeur bascule sur
OpenRouter selon le mode choisi, et si les deux sont muets, les analyses
déterministes continuent pendant que toute décision exigeant l'IA passe en
revue manuelle. Rien n'est exécuté à l'aveugle.

---

## 10. Et ensuite

- [AI_ROUTER.md](AI_ROUTER.md) — quel moteur traite quelle tâche, et pourquoi.
- [AI_ENSEMBLE.md](AI_ENSEMBLE.md) — faire travailler les deux en parallèle.
- [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md) — ce que l'IA n'a pas le droit
  de faire. **À lire avant d'activer quoi que ce soit d'automatique.**

---

Le trading comporte un risque de perte. Un modèle local qui lit correctement un
message n'y change rien : il vous fait gagner du temps de lecture, pas de
l'argent.
