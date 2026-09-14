# Trouver et surveiller des canaux Telegram

Ce document s'adresse à quelqu'un qui **ne suit encore aucun canal de signaux**.
Il décrit comment en chercher, ce que TradePilot affiche, ce qu'il ne fait
jamais tout seul, et les trois modes de fonctionnement d'un canal surveillé.

Prérequis : un compte Telegram connecté au Bridge
(voir [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md)).

---

## 1. Chercher ses premiers canaux

La recherche interroge l'annuaire public de Telegram avec votre session
utilisateur. Elle ne remonte que des **canaux publics**.

```
GET  /api/v1/telegram/discover/suggestions
POST /api/v1/telegram/discover      { "query": "gold signals", "limit": 30 }
```

### 1.1 Les recherches suggérées

`GET /api/v1/telegram/discover/suggestions` renvoie la liste exacte suivante :

| Recherche suggérée |
|---|
| `gold signals` |
| `XAUUSD` |
| `forex signals` |
| `forex trading` |
| `gold trading` |
| `scalping gold` |
| `EURUSD signals` |
| `GBPUSD signals` |
| `NASDAQ signals` |
| `indices signals` |

Ces suggestions ne sont pas des recommandations de canaux : ce sont des points de
départ pour la barre de recherche.

Quelques conseils de formulation :

- l'instrument seul (`XAUUSD`, `EURUSD`, `US30`) remonte souvent des canaux très
  ciblés ;
- ajouter `signals`, `vip` ou `free` change fortement les résultats ;
- la recherche accepte 2 à 64 caractères et jusqu'à 50 résultats par requête ;
- chaque recherche consomme du quota Telegram : évitez de relancer la même
  requête en boucle (voir la section FloodWait de
  [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md)).

### 1.2 Chercher un canal précis

Si vous connaissez déjà un canal, inutile de passer par la recherche :

```
GET /api/v1/telegram/resolve?reference=@nom_du_canal
```

Le paramètre `reference` accepte quatre formes :

| Forme | Exemple |
|---|---|
| pseudonyme | `@goldsignalspro` ou `goldsignalspro` |
| lien complet | `https://t.me/goldsignalspro` |
| lien court | `t.me/goldsignalspro` |
| identifiant numérique | `-1001234567890` ou `1234567890` |

Réponse `404` si le canal est introuvable ou inaccessible avec votre compte.

Les **liens d'invitation privés** (`t.me/+AbCdEf…`) ne sont pas gérés par cette
route : rejoignez d'abord le canal depuis l'application Telegram, il apparaîtra
ensuite comme un canal déjà rejoint.

---

## 2. Ce qu'affiche chaque résultat

Chaque canal renvoyé par la recherche ou par la résolution porte exactement ces
champs :

| Champ | Contenu | À quoi il sert |
|---|---|---|
| `id` | identifiant Telegram du canal, sous forme marquée (`-100…`) | référence stable, à utiliser pour l'ajout |
| `username` | pseudonyme public, sans `@`, ou `null` | permet de vérifier le canal dans Telegram |
| `title` | titre affiché du canal | identification humaine |
| `description` | description publique, ou `null` | donne souvent le type de signaux, la fréquence annoncée, les conditions d'accès |
| `membersCount` | nombre d'abonnés, ou `null` | ordre de grandeur ; un gros canal n'est pas un bon canal |
| `isPublic` | vrai si le canal a un pseudonyme public | un canal non public ne peut pas être résolu par nom |
| `alreadyJoined` | vrai si vous suivez déjà ce canal | évite les doublons |
| `lastMessageAt` | date du dernier message, **seulement si vous suivez déjà le canal** | signe de vie ; `null` sur un canal non rejoint |
| `estimatedMessages` | estimation grossière du volume de messages | indication de l'historique disponible pour une analyse |

### 2.1 Pourquoi certains champs sont vides

La description, le nombre d'abonnés précis et l'estimation de volume proviennent
d'une requête supplémentaire par canal (`GetFullChannelRequest`). Elle est
**coûteuse en quota Telegram** : le Bridge ne la lance que si le résultat
contient **8 canaux ou moins**.

Au-delà, les canaux sont renvoyés sans description. C'est un choix assumé : mieux
vaut une liste complète et rapide qu'une recherche qui déclenche une
temporisation Telegram. Pour obtenir les détails d'un canal précis, utilisez
`GET /api/v1/telegram/resolve`, qui les récupère toujours.

`lastMessageAt` et `alreadyJoined` viennent de vos dialogues Telegram (les 200
derniers). Un canal que vous ne suivez pas n'a donc pas de date de dernier
message : cette information n'est pas publique.

### 2.2 Ce que la recherche ne dit pas

La recherche ne mesure **aucune performance**. Elle ne dit pas si un canal publie
des signaux exploitables, s'il met des stop loss, ni à quelle fréquence il
publie. Ces mesures viennent de l'analyse du canal, décrite dans
[CHANNEL_ANALYSIS.md](CHANNEL_ANALYSIS.md).

---

## 3. Un canal n'est jamais rejoint automatiquement

C'est une règle stricte du code.

Les fonctions `join_channel` et `leave_channel`
(`bridge/app/services/telegram/discovery.py`) portent toutes les deux un
avertissement explicite : elles ne doivent **jamais** être appelées
automatiquement — ni par la recherche, ni par l'analyse, ni au démarrage.

| Action | Rejoint le canal ? |
|---|---|
| `POST /api/v1/telegram/discover` | non |
| `GET /api/v1/telegram/resolve` | non |
| `POST /api/v1/channels` sans `join` | non |
| `POST /api/v1/channels` avec `"join": true` | **oui**, sur votre demande explicite |
| `POST /api/v1/channels/{id}/analyze` | non |
| démarrage du Bridge | non |

Le champ `join` de la requête d'ajout vaut `false` par défaut.

### 3.1 Faut-il rejoindre un canal pour le surveiller ?

Pas toujours. Pour un canal **public**, Telegram permet de lire l'historique et
souvent de recevoir les messages sans y être abonné. Mais l'écoute temps réel
repose sur vos dialogues Telegram : en pratique, **si vous voulez recevoir les
messages au fil de l'eau de façon fiable, il faut suivre le canal**.

Approche recommandée :

1. cherchez le canal, lisez sa description ;
2. ajoutez-le **sans le rejoindre** et lancez une analyse de son historique ;
3. lisez le rapport ;
4. si le canal vous intéresse, rejoignez-le — depuis l'application Telegram, ou
   en ajoutant le canal avec `"join": true`.

---

## 4. Ajouter un canal à la surveillance

```
POST /api/v1/channels
{ "username": "goldsignalspro" }
```

ou

```
POST /api/v1/channels
{ "telegramId": -1001234567890, "join": false }
```

Réponse `201`. Ce que fait cette route :

1. elle **résout** le canal auprès de Telegram (elle échoue en `404` s'il est
   introuvable) ;
2. elle le rejoint **uniquement** si `join` vaut `true` et que vous ne le suivez
   pas déjà ;
3. elle enregistre ou met à jour la ligne dans la table `channels` avec
   `monitored = true` ;
4. elle crée les réglages du canal — **toujours en mode `OBSERVE`** ;
5. elle écrit dans le journal : « Canal ajouté à la surveillance en mode
   observation : … » ;
6. elle recharge la liste des canaux écoutés, sans reconfigurer Telegram.

### 4.1 Le mode de départ est toujours OBSERVE

Il n'existe **aucun moyen** de créer un canal directement en `MANUAL` ou en
`AUTO`. Le corps de `POST /api/v1/channels` n'accepte que `telegramId`,
`username` et `join` : le mode n'y figure pas. Les réglages sont créés avec
`mode = ChannelMode.OBSERVE`.

Changer de mode est donc **toujours** une action séparée et explicite :

```
PATCH /api/v1/channels/{channel_id}/settings
{ "mode": "MANUAL" }
```

### 4.2 Autres opérations sur un canal

| Route | Effet |
|---|---|
| `GET /api/v1/channels` | liste des canaux ; `?monitoredOnly=true` pour ne voir que les canaux surveillés |
| `GET /api/v1/channels/{id}` | détail : réglages, profil de parser appris, dernière analyse, 20 derniers signaux |
| `PATCH /api/v1/channels/{id}/settings` | mode, activation, sens copiés, surcharges de risque |
| `POST /api/v1/channels/{id}/monitor?enabled=false` | suspend l'écoute sans supprimer le canal ni ses données |
| `DELETE /api/v1/channels/{id}` | retire le canal |
| `POST /api/v1/channels/{id}/analyze` | analyse son historique — voir [CHANNEL_ANALYSIS.md](CHANNEL_ANALYSIS.md) |
| `GET /api/v1/channels/compare/table` | tableau de comparaison de tous les canaux |

Retirer un canal de la surveillance (`monitor?enabled=false`) et supprimer un
canal sont deux choses différentes : la première conserve l'historique, les
analyses et les signaux passés.

---

## 5. Les trois modes d'un canal

Réglage `mode` de la table `channel_settings`, valeurs de l'énumération
`ChannelMode`. Le mode détermine exactement ce qui se passe quand un message
arrive.

### 5.1 Vue d'ensemble

| | `OBSERVE` (défaut) | `MANUAL` | `AUTO` |
|---|---|---|---|
| Reçoit le message | oui | oui | oui |
| Enregistre le message | oui | oui | oui |
| Interprète le message | oui | oui | oui |
| Valide la cohérence | oui | oui | oui |
| Résout le symbole broker | non | oui | oui |
| Applique le `RiskManager` | non | oui, à la validation | oui |
| Calcule le volume | non | oui, à la validation | oui |
| Envoie un ordre | **jamais** | seulement après votre confirmation | oui, si tous les contrôles passent |
| Statut final du signal | `OBSERVED` | `NEEDS_REVIEW`, puis votre décision | `SENT`, `OPEN`, `REJECTED` ou `FAILED` |

### 5.2 `OBSERVE` — observation

Le mode par défaut, et le seul mode possible pour un canal qui vient d'être
ajouté.

Ce qui se passe exactement (`TradingEngine.process_signal`) : le message est reçu,
enregistré, normalisé, interprété par le parser, validé, un signal est créé — puis
le traitement s'arrête avec le statut `OBSERVED` et le message « Canal en mode
observation : signal enregistré sans exécution ».

- Aucune résolution de symbole n'est tentée.
- Le `RiskManager` n'est pas appelé.
- Aucun volume n'est calculé.
- Aucun `order_check`, aucun `order_send`.

Le `RiskManager` possède **en plus** son propre garde-fou : si on l'appelle
malgré tout sur un canal en `OBSERVE` sans validation manuelle, il refuse avec le
motif `CHANNEL_OBSERVE_MODE`.

À quoi ce mode sert :

- voir ce que le canal publie réellement, jour après jour ;
- vérifier que le parser lit correctement le format de ce canal ;
- constater le score de confiance obtenu message après message ;
- laisser le canal apprendre ses alias de symboles et ses gabarits ;
- décider en connaissance de cause s'il mérite d'aller plus loin.

Restez en `OBSERVE` aussi longtemps que nécessaire. C'est gratuit et sans risque.

### 5.3 `MANUAL` — proposition et confirmation

Le message est reçu, interprété et validé, puis le signal passe en
`NEEDS_REVIEW` avec une **date d'expiration** :

```
expires_at = maintenant + max(60, max_signal_age_seconds)
```

soit 300 secondes avec les réglages par défaut. Un événement
`signal.needs_review` est poussé sur le WebSocket, ce qui déclenche une
notification sur le téléphone.

Vous décidez ensuite :

| Route | Effet |
|---|---|
| `GET /api/v1/signals/pending` | liste les signaux en attente, non encore expirés |
| `POST /api/v1/signals/{id}/approve` | relance le traitement complet avec `manual_override = true` |
| `POST /api/v1/signals/{id}/reject` | refuse le signal, motif `MANUAL_REJECTION` |
| aucune action | le signal passe en `EXPIRED` à l'échéance, silencieusement |

**Ce que la validation manuelle contourne** — trois contrôles, et uniquement
ceux-là :

| Contrôle contourné | Pourquoi |
|---|---|
| `AUTO_TRADING_OFF` | vous agissez explicitement, l'interrupteur général ne vous concerne pas |
| `CHANNEL_OBSERVE_MODE` | vous pouvez valider à la main un signal d'un canal en observation |
| `LOW_CONFIDENCE` | c'est vous qui jugez la lecture du message |

**Tout le reste s'applique intégralement** : type de compte, fraîcheur du signal,
fenêtres horaires, spread, cohérence du stop loss, limites journalières,
drawdown, pertes consécutives, exposition, volume, marge, `order_check`. Une
validation manuelle n'est pas un passe-droit.

Si le signal a expiré entre-temps, `approve` le fait passer en `EXPIRED` et
répond avec le motif `SIGNAL_EXPIRED` : un vieux signal ne part jamais.

### 5.4 `AUTO` — exécution automatique

Le pipeline complet se déroule sans intervention :

```
message → parser → validation → résolution du symbole → RiskManager
        → order_check → order_send → suivi de la position
```

Aucune étape n'est contournable. Le signal termine en `SENT` (ordre en attente),
`OPEN` (position ouverte), `REJECTED` (refusé par le `RiskManager`) ou `FAILED`
(refusé par le broker), avec dans tous les cas un motif journalisé et une
timeline complète consultable par `GET /api/v1/signals/{id}`.

Le mode `AUTO` d'un canal **ne suffit pas** à déclencher une exécution. Il faut
aussi :

- `auto_trading_enabled = true` (route `POST /api/v1/trading/auto?enabled=true`) ;
- l'automatisation non mise en pause ;
- un mode d'exécution choisi : `PAPER`, `MT5_DEMO` ou `MT5_LIVE`.

Ces trois éléments sont globaux et indépendants du mode du canal.

---

## 6. Progression recommandée

| Étape | Mode du canal | Mode d'exécution | Ce que vous vérifiez |
|---|---|---|---|
| 1 | `OBSERVE` | `PAPER` | Le parser lit-il correctement ce canal ? Quelle confiance ? Quels instruments ? |
| 2 | `OBSERVE` | `PAPER` | Analysez l'historique du canal et lisez le rapport de mesures |
| 3 | `MANUAL` | `PAPER` | Les volumes calculés sont-ils cohérents ? Les refus du `RiskManager` sont-ils compréhensibles ? |
| 4 | `AUTO` | `PAPER` | Le cycle complet fonctionne-t-il sans intervention ? Les messages de suivi sont-ils bien rattachés ? |
| 5 | `AUTO` | `MT5_DEMO` | Le broker accepte-t-il les ordres ? Les symboles sont-ils bien résolus ? Le break even se déclenche-t-il ? |
| 6 | — | `MT5_LIVE` | Uniquement après la checklist complète : [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) |

Chaque étape se change indépendamment : rien n'oblige à passer tous les canaux au
même mode. Un canal peut rester en `OBSERVE` pendant qu'un autre est en `AUTO`.

---

## 7. Surcharger les réglages d'un canal

`PATCH /api/v1/channels/{channel_id}/settings` accepte, en plus du `mode` :

| Champ | Effet |
|---|---|
| `enabled` | désactive le canal sans changer son mode |
| `copyBuy`, `copySell` | ne copier que les achats, ou que les ventes |
| `riskPercent`, `maxLot`, `maxPositions` | risque plus faible pour un canal moins éprouvé |
| `maxSpreadPoints`, `maxSignalAgeSeconds` | exigences de marché propres au canal |
| `minConfidence` | seuil de confiance spécifique |
| `requireStopLoss`, `requireTakeProfit` | exigences sur le contenu du signal |
| `multiTpStrategy` | stratégie de take profits pour ce canal |
| `allowedSymbols` | liste blanche d'instruments pour ce canal |

**Tout champ omis ou mis à `null` signifie : utiliser le réglage global.** Le
détail de la fusion et la liste des réglages non surchargeables figurent dans
[RISK_MANAGEMENT.md](RISK_MANAGEMENT.md), section 2.

Un changement de mode est journalisé et écrit dans le journal d'audit
(`channel_mode_changed`), avec l'acteur `user`.

---

## 8. Ce qui n'a pas pu être vérifié sur cette machine

- Aucune recherche Telegram réelle n'a été effectuée : la forme des résultats
  décrite en section 2 provient du code de normalisation
  (`_describe_chat`), pas d'une réponse réellement observée.
- Aucun canal n'a été rejoint, ni analysé sur un historique réel.
- L'écran **Découvrir** de l'application est implémenté, mais son comportement
  face à de vrais résultats Telegram n'a pas été observé. Les routes décrites ici
  peuvent aussi être appelées directement (voir
  [DEMO_TESTING.md](DEMO_TESTING.md) pour la forme des appels authentifiés).
