# Configurer les notifications push (Firebase Cloud Messaging)

CDC2 section 50 : recevoir les informations importantes sur le téléphone Android
**même application fermée**. C'est Firebase Cloud Messaging (FCM) qui permet
cela : le Bridge envoie, l'application Flutter reçoit.

Ce document décrit la marche à suivre complète, et dit franchement ce qui **ne
peut pas** être fait à votre place.

---

## 1. Ce qui est déjà fait dans le Bridge

- Envoi via l'**API HTTP v1** de Firebase (`/v1/projects/<projet>/messages:send`).
- Authentification par **compte de service Google** : le Bridge signe lui-même
  une assertion JWT RS256 et l'échange contre un jeton d'accès. Aucune
  dépendance supplémentaire n'est nécessaire.
- Aucun secret en dur, aucun secret journalisé : la clé privée est enregistrée
  auprès du masqueur de secrets dès son chargement.
- **Repli automatique** si Firebase n'est pas configuré : WebSocket,
  notifications locales et inbox interne. Le système reste utilisable, et le
  diagnostic le dit clairement.

## 2. Ce que personne ne peut faire à votre place

Ces étapes exigent votre compte Google et votre acceptation des conditions
d'utilisation. Elles ne peuvent être ni automatisées, ni réalisées par le
Bridge :

1. **Créer le projet Firebase** et accepter les CGU Google.
2. **Télécharger la clé du compte de service** (fichier JSON). Google ne
   l'affiche qu'une seule fois, au moment de la création.
3. **Télécharger `google-services.json`** et le placer dans le projet Flutter.
4. **Compiler et installer** l'application Android signée avec le bon
   identifiant de paquet.
5. **Accorder la permission de notification** sur le téléphone (Android 13+
   demande `POST_NOTIFICATIONS` à l'utilisateur).

Tant que ces cinq points ne sont pas faits, le push distant reste indisponible —
et c'est normal.

---

## 3. Créer le projet Firebase

1. Ouvrir <https://console.firebase.google.com> et se connecter.
2. **Ajouter un projet** → nom au choix (par exemple `tradepilot`).
   Google Analytics est facultatif : vous pouvez le refuser.
3. Dans le projet, ouvrir **Paramètres du projet → Général** et noter
   l'**ID du projet** (par exemple `tradepilot-4f2a1`). Ce n'est pas le nom
   affiché, c'est l'identifiant technique.

## 4. Déclarer l'application Android

1. **Paramètres du projet → Général → Vos applications → Android**.
2. Nom du paquet : `com.tradepilot.tradepilot`
   (c'est l'`applicationId` de `mobile/android/app/build.gradle.kts` ; s'il est
   modifié, la valeur déclarée dans Firebase doit suivre).
3. Télécharger **`google-services.json`** et le placer dans
   `mobile/android/app/google-services.json`.
4. Ce fichier ne doit **pas** être versionné : il identifie votre projet
   Firebase.

## 5. Créer la clé de compte de service (côté Bridge)

1. **Paramètres du projet → Comptes de service**.
2. Choisir **Firebase Admin SDK**, puis **Générer une nouvelle clé privée**.
3. Confirmer : un fichier JSON est téléchargé. Il contient `project_id`,
   `client_email` et `private_key`.
4. **Ce fichier est un secret complet** : quiconque le possède peut envoyer des
   notifications au nom de votre projet. Ne l'envoyez jamais par message, ne le
   mettez jamais dans Git.

## 6. Installer la clé sur le Bridge

Placez le fichier ici :

```
bridge/data/fcm-service-account.json
```

`bridge/data/` est déjà ignoré par Git (voir `.gitignore`), c'est l'emplacement
prévu. Le Bridge le trouvera sans aucune configuration supplémentaire.

### Variables d'environnement (facultatives)

À définir dans `bridge/.env` si vous voulez un autre emplacement ou un autre
comportement :

| Variable                    | Rôle                                                                 | Défaut                                   |
|-----------------------------|----------------------------------------------------------------------|------------------------------------------|
| `FCM_ENABLED`               | `false` désactive volontairement le push distant                     | `true`                                   |
| `FCM_SERVICE_ACCOUNT_FILE`  | Chemin complet du fichier JSON du compte de service                  | `bridge/data/fcm-service-account.json`   |
| `FCM_SERVICE_ACCOUNT_JSON`  | Contenu JSON en ligne (utile en conteneur, déconseillé sur poste)    | vide                                     |
| `FCM_PROJECT_ID`            | Force l'ID de projet au lieu de celui lu dans le fichier             | valeur du fichier                        |

Exemple de `.env` :

```dotenv
FCM_ENABLED=true
FCM_SERVICE_ACCOUNT_FILE=C:\TradePilot\secrets\fcm-service-account.json
```

Redémarrez le Bridge après modification.

## 7. Côté Flutter (application Android)

Ces réglages appartiennent au projet mobile. Ils sont rappelés ici pour que la
chaîne complète soit compréhensible :

- ajouter `firebase_core` et `firebase_messaging` aux dépendances ;
- déclarer le plugin Google Services dans Gradle et fournir
  `google-services.json` ;
- créer le canal de notification Android **`tradepilot_alerts`** : c'est le
  `channel_id` utilisé par le Bridge ; sans ce canal, Android range les
  notifications dans un canal par défaut silencieux ;
- demander la permission `POST_NOTIFICATIONS` (Android 13 et suivants) ;
- récupérer le jeton d'appareil (`FirebaseMessaging.instance.getToken()`) et
  l'envoyer au Bridge :

```
POST /api/v1/devices/push-token
Authorization: Bearer <jeton d'appareil TradePilot>
{ "token": "<jeton FCM>" }
```

- répéter cet envoi à chaque `onTokenRefresh` : un jeton FCM change (mise à
  jour, réinstallation, effacement des données).

Les notifications transportent une charge utile `data` purement descriptive
(`route`, `notificationId`, `symbol`, `category`, `priority`). Elle sert à
ouvrir le bon écran. **Aucune action financière ne doit être déclenchée depuis
une notification** (CDC2 section 94).

## 8. Vérifier que tout fonctionne

Depuis l'application appairée, ou avec un jeton d'appareil valide :

```bash
curl -H "Authorization: Bearer <jeton>" http://127.0.0.1:8787/api/v1/notifications/push/status
```

Réponse attendue une fois tout en place :

```json
{
  "configured": true,
  "projectId": "tradepilot-4f2a1",
  "devicesWithToken": 1,
  "pushPossible": true,
  "message": "Notifications push actives."
}
```

Puis l'essai réel :

```bash
curl -X POST -H "Authorization: Bearer <jeton>" http://127.0.0.1:8787/api/v1/notifications/test
```

La notification doit apparaître sur le téléphone, application fermée.

## 9. Diagnostic des cas fréquents

| Ce que dit le Bridge                                | Cause probable                                                        |
|-----------------------------------------------------|-----------------------------------------------------------------------|
| `Fichier de compte de service introuvable`          | Le JSON n'est pas à l'emplacement attendu, ou le chemin est faux.      |
| `Compte de service incomplet`                       | Le fichier téléchargé n'est pas une clé de compte de service.          |
| `OAuth Google a refusé le compte de service`        | Clé révoquée, horloge du PC décalée, ou API Messaging non activée.     |
| `FCM HTTP 404 (UNREGISTERED)`                       | Jeton d'appareil périmé : le Bridge l'efface, l'application le renvoie.|
| `FCM HTTP 403 (SENDER_ID_MISMATCH)`                 | `google-services.json` et compte de service viennent de projets différents. |
| `devicesWithToken: 0`                               | L'application n'a pas encore appelé `/devices/push-token`.             |
| `FCM non configuré`                                 | Aucun compte de service : le repli WebSocket + inbox reste actif.      |

## 10. Sécurité et rotation

- Le fichier de compte de service ne quitte jamais la machine du Bridge.
- Pour révoquer : **Console Google Cloud → IAM et administration → Comptes de
  service → Clés → Supprimer**. Générez ensuite une nouvelle clé et remplacez
  le fichier.
- Les notifications ne contiennent jamais de clé, de jeton, de mot de passe ni
  de numéro de compte complet : le numéro est masqué (`***4821`).
- En cas de doute sur une fuite : supprimez la clé côté Google **d'abord**, le
  Bridge signalera simplement que le push n'est plus configuré.
