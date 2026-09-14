# Modèle de sécurité

Ce document décrit qui peut accéder à quoi, où sont les secrets, comment ils sont
protégés, ce qui quitte le PC et ce qui n'en sort jamais.

Sources : `bridge/app/services/security/auth.py`,
`bridge/app/services/security/crypto.py`,
`bridge/app/config/logging_config.py`, `bridge/app/main.py`,
`bridge/app/api/v1/websocket.py`, `bridge/app/services/tunnel/ngrok_service.py`,
`mobile/lib/core/security/secure_store.dart`,
`mobile/android/app/src/main/res/xml/network_security_config.xml`.

---

## 1. Le modèle en une phrase

Tout ce qui a de la valeur — clés d'API, session Telegram, base de données,
identifiants MetaTrader — **reste sur le PC**. Le téléphone ne détient qu'une
adresse et un jeton révocable, et le Bridge n'accepte aucune requête sensible
sans ce jeton.

---

## 2. Appairage : du code au jeton

### 2.1 Le code d'appairage

Au démarrage, le Bridge émet un code et l'affiche dans la console :

```
Code d'appairage : XKQP-7M4T   (valable 15 minutes)
```

| Propriété | Valeur |
|---|---|
| Origine | `PAIRING_CODE` de `bridge\.env` s'il est renseigné, sinon un code aléatoire |
| Format | `XXXX-XXXX` |
| Alphabet | `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` — sans `I`, `O`, `0` ni `1`, pour éviter les confusions de lecture |
| Entropie | 8 caractères sur 32 possibles, soit 40 bits |
| Durée de vie | **15 minutes** (`PAIRING_TTL_MINUTES`) |
| Stockage | **mémoire du processus uniquement** — jamais écrit en base, jamais dans un fichier |
| Usage | **une seule fois** : la consommation efface le code courant |
| Comparaison | à temps constant (`hmac.compare_digest`), insensible à la casse et aux espaces |

`GET /api/v1/pairing/status` indique seulement si un code est actif, le temps
restant et s'il existe déjà un appareil appairé. **Le code lui-même n'est jamais
renvoyé par l'API.**

Un `PAIRING_CODE` fixe dans `.env` est pratique mais réduit la sécurité : le code
devient réutilisable après chaque redémarrage. Laissez la variable vide pour un
code aléatoire à chaque démarrage.

### 2.2 L'échange

```
POST /api/v1/pairing
{ "code": "XKQP7M4T", "deviceId": "<identifiant du téléphone>", "name": "Android", "platform": "android" }
```

Réponse `201` :

```json
{ "deviceId": "...", "token": "<jeton>", "bridgeVersion": "1.0.0", "publicUrl": null }
```

Un code invalide ou expiré donne un `403`, et l'échec est écrit dans le journal
(`pairing_failed`, catégorie `security`). Un appairage réussi est écrit dans le
journal **et** dans le journal d'audit (`device_paired`, acteur `user`).

### 2.3 Le jeton de périphérique

| Propriété | Valeur |
|---|---|
| Génération | 32 octets aléatoires (`os.urandom`) encodés en base64 URL-safe, sans remplissage |
| Entropie | 256 bits |
| Stockage côté Bridge | **uniquement le SHA-256** du jeton, dans `devices.token_hash` |
| Stockage côté téléphone | `flutter_secure_storage`, avec `EncryptedSharedPreferences` sur Android |
| Transmission | en-tête `Authorization: Bearer <jeton>` ou `X-Device-Token` |
| Durée de vie | illimitée, jusqu'à révocation ou rotation |

Le jeton en clair n'existe qu'une fois, dans la réponse à l'appairage. Le Bridge
lui-même ne peut plus le retrouver ensuite. Perdre le jeton oblige à refaire un
appairage — il n'y a pas de récupération.

---

## 3. Authentification des routes

### 3.1 Ce qui est protégé

La dépendance FastAPI `require_device` protège **toutes** les routes de l'API,
sauf ces trois-là :

| Route publique | Pourquoi |
|---|---|
| `GET /api/v1/health` | sonde de disponibilité. Ne renvoie que `status`, la version, la version d'API et la durée de fonctionnement. Aucune donnée de compte. |
| `GET /api/v1/pairing/status` | permet au téléphone de savoir si un appairage est possible. Ne renvoie jamais le code. |
| `POST /api/v1/pairing` | l'échange lui-même, protégé par le code à durée limitée. |

Tout le reste — soit 81 des 84 opérations — exige un jeton valide et non révoqué.
Cela couvre les positions, les ordres, les réglages de risque, le mode
d'exécution, l'arrêt d'urgence, la connexion Telegram, la clé OpenRouter, le
journal et le diagnostic.

Un jeton manquant ou invalide donne un `401` avec l'en-tête
`WWW-Authenticate: Bearer` et un message explicite (« Jeton de périphérique
manquant » ou « Jeton de périphérique invalide ou révoqué »). Côté application,
un `401` fait repasser l'utilisateur par l'écran d'appairage.

Chaque requête authentifiée met à jour `devices.last_seen_at`.

### 3.2 Le WebSocket

`/api/v1/ws` exige le même jeton, transmis de deux façons possibles :

1. en paramètre de requête : `?token=<jeton>` — simple, mais le jeton peut
   apparaître dans les journaux d'accès d'un intermédiaire ;
2. dans le **premier message JSON** : `{"token": "<jeton>"}` — préférable, le
   jeton ne figure alors dans aucune URL.

Un jeton absent, expiré au bout de 10 secondes ou invalide ferme la connexion
avec le code applicatif **4401**.

### 3.3 Rotation et révocation

| Route | Effet |
|---|---|
| `GET /api/v1/devices` | liste des appareils : nom, plateforme, date de création, dernière activité, état de révocation |
| `POST /api/v1/devices/revoke` `{ "deviceId": "…" }` | marque l'appareil comme révoqué. Son jeton cesse immédiatement d'être accepté. Irréversible sans nouvel appairage. |
| `POST /api/v1/devices/rotate` `{ "deviceId": "…" }` | génère un **nouveau** jeton, remplace l'empreinte stockée et lève la révocation. L'ancien jeton devient invalide. |
| `POST /api/v1/devices/push-token` | enregistre un jeton de notification pour cet appareil |

Les deux premières actions sont écrites dans le journal d'audit
(`device_revoked`, `device_token_rotated`).

Quand révoquer :

- téléphone perdu, volé ou revendu ;
- doute sur l'exposition du jeton (partage d'écran, réseau non fiable) ;
- appareil de test dont vous ne vous servez plus.

Quand faire tourner le jeton :

- après avoir utilisé le Bridge sur un réseau public en HTTP clair ;
- périodiquement, par précaution.

---

## 4. Chiffrement des secrets au repos

### 4.1 Ce qui est chiffré

Table `secrets` du fichier `bridge\data\tradepilot.sqlite3`. Chaque valeur est
chiffrée avec **Fernet** (AES-128-CBC + HMAC-SHA256), accompagnée d'un **indice
partiel** en clair destiné à l'affichage.

| Clé | Contenu | Utilisée aujourd'hui |
|---|---|---|
| `openrouter.api_key` | clé OpenRouter | oui |
| `telegram.api_hash` | `api_hash` de l'application Telegram | oui |
| `telegram.session` | chaîne de session Telethon | oui |
| `telegram.2fa_hint` | — | déclarée dans le code, **non utilisée** |
| `pairing.code` | — | déclarée, **non utilisée** : le code vit uniquement en mémoire |
| `mt5.password` | — | déclarée, **non utilisée** : le mot de passe MT5, s'il est renseigné, reste dans `bridge\.env` |

L'indice (`hint`) est produit par `mask_middle` : `sk-o...9f2a`. C'est la seule
forme sous laquelle un secret peut être renvoyé par l'API.

### 4.2 La `MASTER_KEY`

C'est la clé qui chiffre tout le reste. Elle provient, dans cet ordre :

1. de la variable `MASTER_KEY` de `bridge\.env` ;
2. sinon du fichier `bridge\data\master.key`, **créé automatiquement au premier
   démarrage** avec des permissions restreintes au seul propriétaire (l'appel
   est sans effet sur un système de fichiers sans permissions POSIX, ce qui est
   le cas de certains volumes Windows).

Le Bridge journalise alors, en `WARNING` :

```
Nouvelle cle maitre generee dans ...\data\master.key - sauvegardez ce fichier
```

Une `MASTER_KEY` fournie mais invalide fait échouer le démarrage du chiffrement
avec un message indiquant la commande de génération :

```powershell
.\bridge\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4.3 Sauvegardez la `MASTER_KEY`

**C'est le point le plus important de ce document.**

Si la `MASTER_KEY` est perdue ou modifiée :

- les secrets stockés deviennent **définitivement illisibles** ;
- le Bridge journalise « Secret … illisible : la cle maitre a change » ;
- il faut refaire la connexion Telegram et ressaisir la clé OpenRouter.

Aucune donnée de trading n'est perdue — les tables `signals`, `trades`,
`journal_entries` ne sont pas chiffrées — mais toutes les connexions externes
doivent être refaites.

Que sauvegarder, et où :

| Élément | Contenu | Où le mettre |
|---|---|---|
| `bridge\.env` | la `MASTER_KEY` et toute la configuration | gestionnaire de mots de passe, ou clé USB conservée hors ligne |
| `bridge\data\master.key` | la clé, si elle n'est pas dans `.env` | idem |
| `bridge\data\tradepilot.sqlite3` | base complète | sauvegarde périodique, à conserver aussi soigneusement que la clé |

Ne mettez **jamais** ces fichiers dans un dépôt Git, un partage cloud non chiffré
ou une pièce jointe. Le `.gitignore` racine exclut déjà `.env`, `*.env`,
`bridge/data/`, `**/*.sqlite3`, `**/telegram.session*`, `*.jks`, `*.keystore` et
`mobile/android/key.properties`.

Sauvegarder la clé **et** la base au même endroit revient à tout perdre en cas de
compromission de cet endroit : idéalement, séparez-les.

---

## 5. Masquage des secrets dans les journaux

`bridge/app/config/logging_config.py` installe un filtre `RedactingFilter` sur
**la console et sur le fichier de log**. Rien n'est écrit sans passer par lui.

### 5.1 Deux mécanismes complémentaires

**Les secrets connus.** `register_secret(valeur)` enregistre une valeur exacte
(au moins 6 caractères) qui sera remplacée par `***REDACTED***` partout où elle
apparaît. Sont enregistrés au fil de l'exécution : la clé OpenRouter,
l'`api_hash` Telegram, le token ngrok, la chaîne de session Telethon, le code
d'appairage, chaque jeton de périphérique généré, le code de connexion Telegram
et le mot de passe 2FA, ainsi que la `MASTER_KEY`.

**Les motifs génériques.** Sept expressions régulières masquent, même pour une
valeur jamais enregistrée :

| Motif | Ce qu'il attrape |
|---|---|
| `sk-or-v1-…` | clés OpenRouter |
| `12345678:AAA…` | jetons de bot Telegram |
| `api_hash: <hex>` | hash d'API |
| `password: …`, `pwd: …`, `mot_de_passe: …` | mots de passe |
| `token: …`, `secret: …`, `api_key: …`, `authtoken: …` | jetons et clés génériques |
| `code: 12345`, `otp: …` | codes à usage unique |
| `1AbCdEf…` (40+ caractères) | chaînes de session Telethon |

### 5.2 Où le masquage s'applique

- console et fichier `bridge\data\logs\bridge.log` (JSON, rotation à 5 Mo,
  7 archives) ;
- messages du journal fonctionnel avant écriture en base
  (`journal.record` applique `redact`) ;
- corps des réponses d'erreur `422` et `500` de l'API (`main.py`) ;
- export de diagnostic `GET /api/v1/diagnostics/export`, qui reprend des données
  déjà masquées à la source.

Le filtre ne touche que les chaînes : convertir un nombre en texte casserait les
formats `%.1f` ou `%d`. Il ne peut jamais faire échouer une écriture de journal,
toute exception y étant capturée.

### 5.3 Précautions volontaires dans le code

- Une connexion MT5 explicite ne journalise que les **trois derniers chiffres**
  du numéro de compte, jamais le mot de passe.
- Le numéro de téléphone Telegram est masqué en `+336...78` dans le statut et
  dans les journaux.
- Le compte Telegram est désigné par `@pseudonyme` ou `id <n>`, jamais par une
  donnée sensible.
- Les erreurs Telethon sont journalisées par **type d'exception**, pas par
  message, précisément parce qu'un message d'erreur peut contenir un identifiant.

---

## 6. Ce qui ne quitte jamais le Bridge

| Donnée | Quitte le PC ? |
|---|---|
| Clé OpenRouter | non — seul un indice `sk-o...9f2a` est exposé |
| `api_hash` Telegram | non — même règle |
| Session Telethon | non |
| Mot de passe 2FA Telegram | non — il n'est même pas stocké |
| Code de connexion Telegram | non |
| `MASTER_KEY` | non |
| Identifiants et mot de passe MetaTrader | non |
| Base SQLite | non |
| Contenu des messages Telegram | **oui, partiellement** : le texte d'un message ambigu est envoyé à OpenRouter, tronqué à 4 000 caractères. Rien d'autre. |
| Solde, equity, positions, réglages de risque | non — jamais transmis à OpenRouter |
| Nom du canal, identité Telegram | non — jamais transmis à OpenRouter |
| Jeton de périphérique | **oui**, vers votre téléphone, une seule fois, à l'appairage |

Le `phone_code_hash` de Telegram lui-même ne circule pas : le Bridge renvoie un
identifiant opaque aléatoire et conserve la vraie valeur en mémoire.

Détail complet de ce qui est transmis au modèle de langage :
[OPENROUTER_SETUP.md](OPENROUTER_SETUP.md), section 7.

---

## 7. Exposition réseau

### 7.1 Écoute locale par défaut

`BRIDGE_HOST` vaut `127.0.0.1` par défaut : le Bridge n'écoute que sur la boucle
locale et **n'est joignable que depuis le PC lui-même**. C'est le réglage le plus
sûr.

Pour y accéder depuis le téléphone sur le réseau local, il faut :

1. passer `BRIDGE_HOST=0.0.0.0` dans `bridge\.env` ;
2. ouvrir le port 8787 dans le pare-feu Windows, en profil **Privé** uniquement.

Le détail de ces deux opérations figure dans
[BRIDGE_WINDOWS_SETUP.md](BRIDGE_WINDOWS_SETUP.md) et
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### 7.2 Trafic en clair sur le réseau local

Le Bridge ne présente **aucun certificat TLS**. En réseau local, la liaison se
fait donc en HTTP clair vers une adresse privée.

L'application Android l'autorise via `network_security_config.xml`, avec
`cleartextTrafficPermitted="true"` sur la configuration de base. La raison est
simple : l'adresse du Bridge est une IP privée inconnue à l'avance
(`192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`) et Android ne sait pas déclarer une
plage d'adresses dans ce fichier — seulement des noms de domaine précis.

**Ce qui circule en clair sur ce réseau :** le jeton de périphérique, dans
l'en-tête `Authorization`, ainsi que les données affichées par l'application
(soldes, positions, signaux).

**Ce qui ne circule pas :** aucun secret métier. La clé OpenRouter, la session
Telegram et les identifiants MetaTrader ne sont jamais envoyés au téléphone.

**Recommandation :** sur un réseau Wi-Fi que vous ne maîtrisez pas — lieu public,
réseau partagé, hébergement — utilisez l'adresse HTTPS du tunnel, pas l'adresse
IP locale. Le client HTTP de l'application préfixe automatiquement `https://`
toute adresse qui n'est ni une IP ni `localhost`.

### 7.3 Le tunnel ngrok

Quand `NGROK_ENABLED=true`, le Bridge lance un agent ngrok qui publie le port
local sur une URL HTTPS publique.

Ce que cela change :

| Aspect | Conséquence |
|---|---|
| Chiffrement | la liaison téléphone → ngrok est en **HTTPS** ; c'est un vrai gain par rapport au HTTP local |
| Accessibilité | **l'URL est publique.** N'importe qui la connaissant peut atteindre le Bridge depuis Internet |
| Authentification | inchangée : toutes les routes sensibles exigent toujours le jeton de périphérique. Le tunnel n'ouvre **aucun** accès anonyme |
| Surface exposée | `GET /api/v1/health`, `GET /api/v1/pairing/status` et `POST /api/v1/pairing` deviennent accessibles depuis Internet |
| Terminaison TLS | ngrok déchiffre le trafic chez lui avant de le renvoyer au PC. Vous faites confiance à ngrok. |
| Documentation interactive | `/docs` est servie par FastAPI et devient elle aussi accessible publiquement |

Le risque réel se concentre sur `POST /api/v1/pairing` : un attaquant qui
devinerait un code d'appairage actif obtiendrait un jeton. Les protections sont
la durée de vie de 15 minutes, l'usage unique, les 40 bits d'entropie du code
aléatoire et le fait qu'un code n'existe que si le Bridge vient de démarrer ou
qu'un code a été émis. **Ne laissez pas un `PAIRING_CODE` fixe et court dans
`bridge\.env`** si vous exposez le Bridge sur Internet.

Le token ngrok est enregistré comme secret masqué avant tout usage et n'apparaît
jamais dans un journal.

Coupez le tunnel quand vous n'en avez pas besoin :

```powershell
# dans bridge\.env
NGROK_ENABLED=false
```

puis redémarrez le Bridge, ou lancez-le pour cette fois sans tunnel :

```powershell
.\scripts\start_bridge.ps1 -NoNgrok
```

### 7.4 CORS et en-têtes

Le middleware CORS n'est installé **que si** `CORS_ORIGINS` est renseigné, ce qui
n'est pas le cas par défaut. L'application mobile n'est pas un navigateur : elle
n'a pas besoin de CORS. Laissez la variable vide.

Quatre en-têtes de sécurité sont ajoutés à chaque réponse :
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Cache-Control: no-store`.

---

## 8. Export, import et sauvegarde

| Route | Contient des secrets ? |
|---|---|
| `GET /api/v1/settings/export` | **non.** Uniquement les réglages de risque et les correspondances de symboles. La réponse porte la note « Cet export ne contient aucun secret (ni clé API, ni session Telegram). » |
| `POST /api/v1/settings/import` | n'accepte aucun secret. Les trois champs dangereux `autoTradingEnabled`, `executionMode` et `liveUnlocked` sont **retirés** de la charge avant application : un import ne peut pas activer le trading ni changer de mode. |
| `GET /api/v1/diagnostics/export` | journal (500 dernières entrées), état des connexions, 50 derniers signaux. Les secrets sont déjà masqués à la source. **Relisez-le quand même avant de l'envoyer à quelqu'un** : il contient les noms de vos canaux, vos instruments et vos montants. |

---

## 9. Checklist avant d'exposer le Bridge sur Internet

À parcourir **avant** d'activer ngrok ou d'ouvrir un port sur votre box.

### Secrets

- [ ] `bridge\.env` est sauvegardé hors du PC, dans un endroit sûr.
- [ ] La `MASTER_KEY` est sauvegardée séparément de la base de données.
- [ ] `bridge\.env` n'est pas versionné ni synchronisé vers un cloud non chiffré.
- [ ] `PAIRING_CODE` est **vide** dans `bridge\.env`, pour un code aléatoire à
      chaque démarrage.
- [ ] Aucun mot de passe MetaTrader n'est renseigné dans `bridge\.env` : la
      session ouverte manuellement dans MT5 Desktop suffit.

### Accès

- [ ] Un seul appareil est appairé. `GET /api/v1/devices` ne montre aucun
      appareil inconnu ni oublié.
- [ ] Tous les anciens appareils sont révoqués (`POST /api/v1/devices/revoke`).
- [ ] Le jeton du téléphone a été renouvelé si vous avez utilisé le Bridge en
      HTTP clair sur un réseau non fiable.

### Configuration réseau

- [ ] `NGROK_DOMAIN` pointe sur un **domaine réservé**, pas une URL aléatoire qui
      change à chaque démarrage.
- [ ] `NGROK_AUTHTOKEN` est renseigné et n'a jamais été partagé.
- [ ] `CORS_ORIGINS` est vide.
- [ ] Aucune redirection de port n'a été ouverte sur la box vers le port 8787 —
      le tunnel ngrok rend cela inutile et une redirection expose directement le
      PC.
- [ ] Si `BRIDGE_HOST=0.0.0.0`, la règle de pare-feu est limitée au profil
      **Privé**.

### Trading

- [ ] `execution_mode` est `PAPER` ou `MT5_DEMO`.
- [ ] `live_unlocked` est `false` (`GET /api/v1/trading/state`).
- [ ] Les limites de risque sont configurées et volontaires :
      `risk_percent`, `max_daily_loss_percent`, `max_lot`, `max_positions`.
- [ ] Vous savez déclencher l'arrêt d'urgence
      (`POST /api/v1/emergency/close-all`, phrase exacte
      `FERMER TOUTES LES POSITIONS`).

### Poste

- [ ] Le compte Windows utilisé a un mot de passe et la session se verrouille.
- [ ] Le disque est chiffré (BitLocker), ce qui protège la base et la
      `MASTER_KEY` en cas de vol du PC.
- [ ] Windows et MetaTrader 5 sont à jour.
- [ ] Le tunnel est coupé quand vous n'en avez pas besoin.

### Après l'ouverture

- [ ] `GET /api/v1/journal?category=security` ne montre aucun `pairing_failed`
      inattendu.
- [ ] `GET /api/v1/devices` ne montre aucun appareil que vous ne reconnaissez
      pas.
- [ ] `GET /api/v1/journal/audit` ne montre aucune action que vous n'avez pas
      faite : `live_unlocked`, `execution_mode_changed`, `auto_trading_toggled`,
      `device_paired`, `emergency_close_all`.

**Aucune de ces précautions ne rend l'exposition sur Internet sans risque.** La
solution la plus sûre reste de ne pas exposer le Bridge du tout et de l'utiliser
uniquement sur votre réseau local.

---

## 10. Journal d'audit

La table `audit_logs` conserve une trace **immuable** — aucune route ne permet de
la modifier ni de la purger — des actions sensibles :

| Action | Déclencheur |
|---|---|
| `device_paired` | un téléphone a été appairé |
| `device_revoked` | un appareil a été révoqué |
| `device_token_rotated` | un jeton a été renouvelé |
| `live_unlocked` | le mode réel a été déverrouillé |
| `execution_mode_changed` | changement de `PAPER` / `MT5_DEMO` / `MT5_LIVE` |
| `auto_trading_toggled` | activation ou désactivation du trading automatique |
| `risk_settings_updated` | modification des réglages de risque, avec la liste des champs |
| `channel_mode_changed` | changement de mode d'un canal |
| `order_sent` | ordre envoyé, avec le détail du risque et de l'exécution |
| `position_modified`, `position_closed` | intervention manuelle sur une position |
| `emergency_close_all`, `emergency_cancel_pending` | arrêt d'urgence |

Chaque entrée porte l'acteur (`user` ou `system`), la cible, l'horodatage UTC et
un bloc de détails. Consultation : `GET /api/v1/journal/audit`.

Le journal fonctionnel (`journal_entries`), lui, peut être purgé avec
`DELETE /api/v1/journal?keepLast=5000`. **Le journal d'audit n'est pas concerné
par cette purge.**

---

## 11. Ce qui n'a pas pu être vérifié sur cette machine

- Aucun appairage réel depuis un téléphone n'a été effectué.
- Aucun tunnel ngrok n'a été ouvert : le comportement de l'agent, la validité
  d'un domaine réservé et l'accessibilité publique n'ont pas été observés.
- Le comportement de `chmod` sur `master.key` dépend du système de fichiers
  Windows : la restriction de permissions est faite au mieux et peut être sans
  effet.
- Les trois clés de secrets `telegram.2fa_hint`, `pairing.code` et `mt5.password`
  sont déclarées dans le code mais ne sont écrites par aucun chemin
  d'exécution ; elles n'existent donc pas en base.
