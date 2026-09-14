# Connexion du compte Telegram

TradePilot lit les messages des canaux que vous suivez avec **votre propre
compte Telegram**, via le protocole MTProto (bibliothèque Telethon). Ce n'est pas
un bot.

Ce document explique comment obtenir les identifiants nécessaires, comment se
connecter, où la session est stockée, comment se déconnecter, et comment se
comporter face aux limitations imposées par Telegram.

---

## 1. Obtenir `api_id` et `api_hash`

1. Ouvrez <https://my.telegram.org> dans un navigateur.
2. Saisissez votre numéro de téléphone au format international
   (`+33612345678`). Telegram envoie un code **dans l'application Telegram**,
   pas par SMS.
3. Saisissez ce code pour vous connecter au portail.
4. Cliquez sur **API development tools**.
5. Remplissez le petit formulaire :
   - *App title* : `TradePilot`
   - *Short name* : `tradepilot`
   - *Platform* : *Desktop*
   - *URL* et *Description* : facultatifs
6. Validez. La page affiche ensuite :
   - **`App api_id`** — un nombre, par exemple `1234567` ;
   - **`App api_hash`** — une chaîne hexadécimale de 32 caractères.

Ces deux valeurs identifient l'application, pas le compte. Elles sont créées une
seule fois et restent valables. **L'`api_hash` est un secret** : ne le publiez
nulle part et ne le partagez pas.

### 1.1 Où les renseigner

Deux possibilités, au choix.

**Dans `bridge\.env`** — pratique pour préremplir la première connexion :

```
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
TELEGRAM_PHONE=+33612345678
```

**Directement à la connexion** — les trois valeurs sont transmises dans le corps
de `POST /api/v1/telegram/login/start` et l'`api_hash` est alors chiffré en base
dès que la connexion aboutit. C'est la voie utilisée par l'application mobile.

Les scripts et les journaux du Bridge n'affichent jamais ces valeurs : le
`api_hash` est enregistré comme secret connu au démarrage et remplacé par
`***REDACTED***` partout où il pourrait apparaître.

---

## 2. Pourquoi une session utilisateur et non un bot

C'est un choix technique contraint, pas une préférence.

| Besoin | Bot Telegram | Session utilisateur (MTProto) |
|---|---|---|
| Lire les messages d'un canal public que vous suivez | non, sauf à être administrateur du canal | oui |
| Rejoindre un canal public à la demande | non | oui |
| Rechercher des canaux publics par mots-clés | non, l'API bot n'expose pas la recherche globale | oui (`contacts.SearchRequest`) |
| Relire l'historique d'un canal pour l'analyser | non | oui (`iter_messages`) |
| Recevoir les messages en temps réel de plusieurs canaux | seulement là où le bot est présent et autorisé | oui |

Les canaux de signaux ne vous donneront jamais un accès administrateur, et
l'API bot ne permet pas de chercher des canaux. Une session utilisateur est donc
le seul moyen de faire ce que fait TradePilot.

### 2.1 Ce que cela implique

- Le Bridge agit **en votre nom** sur Telegram. Il peut lire ce que vous pouvez
  lire, et rien de plus.
- Il n'envoie **aucun message**, ne répond à personne, ne publie rien.
- Il ne rejoint **jamais** un canal automatiquement : `join_channel` et
  `leave_channel` ne sont appelées que sur une action explicite de votre part.
- Une session Telegram détournée donnerait accès à votre compte. C'est pour cela
  qu'elle est chiffrée au repos et qu'elle ne quitte jamais le PC.
- Telegram applique des limites de débit à tous les comptes. Une automatisation
  trop agressive peut déclencher des temporisations (voir la section 6).

Le client se déclare auprès de Telegram avec `device_model = "TradePilot Bridge"`,
`system_version = "Windows"` et `app_version` égale à la version du Bridge. Cette
session apparaîtra sous ce nom dans *Telegram → Paramètres → Appareils*.

---

## 3. Le parcours de connexion en trois étapes

La connexion se fait en trois appels REST successifs. Toutes ces routes exigent
le jeton de périphérique obtenu à l'appairage.

### Étape 1 — demander le code

```
POST /api/v1/telegram/login/start
{ "apiId": 1234567, "apiHash": "0123...", "phone": "+33612345678" }
```

Réponse :

```json
{ "status": "code_sent", "phoneCodeHash": "<identifiant opaque>", "expiresIn": 600 }
```

Telegram envoie un code à cinq chiffres, **dans l'application Telegram** sur vos
autres appareils, et par SMS uniquement si aucun autre appareil n'est connecté.

Le champ `phoneCodeHash` renvoyé n'est **pas** le vrai `phone_code_hash` de
Telegram : c'est un identifiant aléatoire opaque généré par le Bridge. Le vrai
jeton reste en mémoire du Bridge et ne circule jamais sur le réseau. La demande
est valable **600 secondes** (`LOGIN_TTL_SECONDS`) puis oubliée.

### Étape 2 — valider le code

```
POST /api/v1/telegram/login/code
{ "requestId": "<identifiant opaque>", "code": "12345" }
```

Deux réponses possibles :

```json
{ "status": "connected", "user": { "id": 111, "username": "...", "firstName": "..." } }
```

ou, si la vérification en deux étapes est activée sur votre compte :

```json
{ "status": "password_required" }
```

Dans ce second cas, la demande reste valide pour l'étape 3.

### Étape 3 — mot de passe 2FA

```
POST /api/v1/telegram/login/2fa
{ "requestId": "<identifiant opaque>", "password": "<votre mot de passe 2FA>" }
```

Il s'agit du **mot de passe de la vérification en deux étapes** de Telegram —
celui que vous avez défini dans *Telegram → Paramètres → Confidentialité et
sécurité → Verrouillage en deux étapes*. Ce n'est ni le code reçu, ni le mot de
passe d'un autre service.

Réponse en cas de succès : `{ "status": "connected", "user": { ... } }`.

### Étape 4 (automatique) — l'écoute démarre

Une fois connecté, la session chiffrée est enregistrée, le compte est marqué
`authorized` et l'écoute temps réel démarre sur les canaux marqués `monitored`.
Aux démarrages suivants, `connect_existing()` restaure la session
silencieusement : les trois étapes ne sont plus nécessaires.

### 3.1 Messages d'erreur traduits

| Erreur Telegram | Message affiché | HTTP |
|---|---|---|
| `ApiIdInvalidError` | Identifiants API Telegram invalides (api_id / api_hash). | 400 |
| `PhoneNumberInvalidError` | Numéro de téléphone invalide. | 400 |
| `PhoneCodeInvalidError` | Code de connexion invalide. | 400 |
| `PhoneCodeExpiredError` | Code de connexion expiré, relancez la connexion. | 400 |
| `PasswordHashInvalidError` | Mot de passe 2FA invalide. | 400 |
| `FloodWaitError` | Limite Telegram atteinte, réessayez dans N secondes. | 429 |
| aucune session active | Compte Telegram non connecté. | 409 |

Aucun de ces messages ne contient de secret. Le numéro de téléphone lui-même est
masqué dans les journaux et dans les réponses de statut, sous la forme
`+336...78`.

---

## 4. Où la session est stockée et comment elle est chiffrée

### 4.1 Ce qui est stocké

| Élément | Emplacement | Protection |
|---|---|---|
| Chaîne de session Telethon | table `secrets`, clé `telegram.session` | **chiffrée Fernet** avec la `MASTER_KEY` |
| `api_hash` | table `secrets`, clé `telegram.api_hash` | **chiffrée Fernet** |
| `api_id`, téléphone, identifiant utilisateur, pseudonyme, prénom, `authorized` | table `telegram_account`, ligne unique `id = 1` | en clair — ce ne sont pas des secrets |
| Mot de passe 2FA | **nulle part** | il sert une seule fois, en mémoire, et n'est jamais écrit |
| Code de connexion | **nulle part** | idem |

La base est le fichier `bridge\data\tradepilot.sqlite3`.

### 4.2 Le chiffrement

`SecretStore` (`bridge/app/services/security/crypto.py`) chiffre chaque secret
avec **Fernet** (AES-128 en mode CBC, authentifié par HMAC-SHA256), à partir de
la `MASTER_KEY`.

La clé provient, dans l'ordre :

1. de la variable `MASTER_KEY` de `bridge\.env` ;
2. sinon du fichier `bridge\data\master.key`, créé automatiquement au premier
   démarrage avec des permissions restreintes.

L'API n'expose jamais un secret en clair. Elle ne renvoie qu'un **indice
partiel** : `mask_middle` produit par exemple `+336...78` pour un téléphone.

> **Sauvegardez `bridge\.env` (ou `bridge\data\master.key`).** Si la
> `MASTER_KEY` change, les secrets existants deviennent illisibles : le Bridge
> journalise « Secret telegram.session illisible : la cle maitre a change » et il
> faut refaire la connexion Telegram. Voir [SECURITY.md](SECURITY.md).

### 4.3 Précision sur les fichiers de session

Telethon est utilisé avec une `StringSession` : **aucun fichier `.session` n'est
écrit sur le disque.** Le dossier `bridge\data\sessions\` est bien créé au
démarrage par la configuration, mais la session Telegram n'y est pas déposée —
elle vit uniquement, chiffrée, dans la table `secrets`. Le `.gitignore` couvre de
toute façon `bridge/data/`, `**/telegram.session*` et `**/*.sqlite3`.

---

## 5. Se déconnecter

Deux routes, deux effets très différents.

| Route | Effet | Session stockée | Reconnexion |
|---|---|---|---|
| `POST /api/v1/telegram/disconnect` | ferme le client, arrête l'écoute | **conservée** | automatique au prochain démarrage, ou via `POST /api/v1/telegram/reconnect` |
| `POST /api/v1/telegram/logout` | déconnexion définitive : `log_out()` côté Telegram **et** suppression de la session chiffrée | **supprimée** | il faut refaire les trois étapes |

`logout` supprime le secret `telegram.session` et repasse
`telegram_account.authorized` à faux **même si l'appel distant à Telegram
échoue** : la session locale ne survit jamais à une demande de déconnexion.

Vous pouvez aussi révoquer la session depuis Telegram lui-même :
*Paramètres → Appareils*, puis terminer la session **TradePilot Bridge**. Le
Bridge constatera au prochain essai que la session n'est plus autorisée et
affichera « Session Telegram expirée, reconnexion requise. »

Consultez l'état à tout moment avec `GET /api/v1/telegram/status`, qui renvoie
l'état de connexion (`CONNECTED`, `CONNECTING`, `DISCONNECTED`, `ERROR`,
`NOT_CONFIGURED`), le pseudonyme, le téléphone masqué et la dernière erreur.

---

## 6. Les limites Telegram (FloodWait) et la conduite à tenir

### 6.1 Ce qu'est un FloodWait

Telegram limite le débit de requêtes de chaque compte. Lorsqu'une limite est
franchie, le serveur répond par une erreur `FLOOD_WAIT_X` : il faut attendre `X`
secondes avant de réessayer ce type de requête. La durée va de quelques secondes
à plusieurs heures selon l'intensité.

### 6.2 Comment TradePilot réagit

Le Bridge **n'attend jamais** à votre place et ne réessaie jamais en boucle. Il
traduit l'erreur en `TelegramFloodError`, la remonte en **HTTP 429** avec le
délai exact :

```
Limite Telegram atteinte, reessayez dans 87 secondes.
```

Le service reste disponible pendant ce temps : seule l'opération Telegram
concernée est indisponible.

Les opérations susceptibles de déclencher un FloodWait sont toutes celles qui
interrogent Telegram activement :

| Opération | Route |
|---|---|
| Recherche de canaux | `POST /api/v1/telegram/discover` |
| Résolution d'un `@nom` ou d'un lien | `GET /api/v1/telegram/resolve` |
| Ajout d'un canal (il le résout) | `POST /api/v1/channels` |
| Récupération de l'historique pour analyse | `POST /api/v1/channels/{id}/analyze` |
| Détails complets d'un canal | interne à la recherche |

En revanche, la **réception** des messages en temps réel ne consomme rien : c'est
un flux poussé par Telegram.

### 6.3 Précautions déjà prises dans le code

- La recherche ne demande les détails complets (`GetFullChannelRequest`, une
  requête par canal) que si le résultat contient **8 canaux ou moins**
  (`DESCRIPTION_LOOKUP_THRESHOLD`). Au-delà, elle s'en passe.
- La liste des dialogues est limitée à 200 entrées (`DIALOG_SCAN_LIMIT`).
- La recherche est plafonnée à 100 résultats côté service
  (`MAX_SEARCH_LIMIT`), et à 50 côté API (`limit` entre 1 et 50).
- Un FloodWait pendant l'enrichissement optionnel d'un résultat est absorbé
  silencieusement : la recherche renvoie le résultat sans description plutôt que
  d'échouer.
- Le watchdog de reconnexion utilise un délai croissant : 5 s, 10 s, 20 s puis
  60 s au maximum, avec abandon après 12 tentatives, plutôt qu'une reconnexion
  en boucle serrée.

### 6.4 Conduite à tenir

1. **Attendez le délai annoncé.** Il est indiqué à la seconde près dans le
   message d'erreur. Réessayer avant l'échéance rallonge généralement la
   pénalité.
2. **Ne relancez pas le Bridge pour « débloquer ».** La limite est appliquée au
   compte Telegram, pas au processus. Redémarrer ne sert à rien et provoque une
   nouvelle tentative de connexion.
3. **Espacez les analyses de canaux.** Analyser 500 messages sur cinq canaux
   d'affilée est le cas le plus exposé. Analysez un canal, lisez le rapport, puis
   passez au suivant.
4. **Évitez les recherches répétées.** Une recherche large avec le maximum de
   résultats coûte plus cher qu'une recherche ciblée.
5. **Rejoignez les canaux avec parcimonie.** Rejoindre beaucoup de canaux en peu
   de temps est un déclencheur classique.
6. **Si la pénalité est longue** (plusieurs heures), c'est le signe d'un usage
   trop intense : réduisez la fréquence des analyses avant de reprendre.

Le journal (`GET /api/v1/journal`, catégorie `telegram`) conserve la trace de ces
événements.

---

## 7. Après la connexion

Une fois le compte connecté, la suite se passe dans
[CHANNEL_DISCOVERY.md](CHANNEL_DISCOVERY.md) : chercher des canaux, les ajouter à
la surveillance — toujours en mode `OBSERVE` — puis, éventuellement, les analyser
([CHANNEL_ANALYSIS.md](CHANNEL_ANALYSIS.md)).

Rappel de fonctionnement de l'écoute : un seul gestionnaire Telethon global est
enregistré, qui filtre en interne sur les canaux `monitored`. Activer ou
désactiver un canal ne nécessite donc aucun réenregistrement auprès de Telegram.
Chaque message est enregistré une seule fois, garanti par la contrainte
d'unicité `(channel_id, message_id)` : un message rejoué après une reconnexion
n'est jamais traité deux fois.

---

## 8. Ce qui n'a pas pu être vérifié sur cette machine

- **Aucune connexion Telegram réelle n'a été effectuée.** Aucun code n'a été
  demandé à Telegram, aucune session n'a été créée ni stockée.
- Le comportement réel de `contacts.SearchRequest`, de `iter_messages` et des
  erreurs `FloodWaitError` n'a pas été observé contre les serveurs Telegram.
- Les messages d'erreur traduits de la section 3.1 proviennent de la table de
  correspondance du code, pas d'échanges réellement constatés.
