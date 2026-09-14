# Notifications TradePilot

Référence du système de notifications du Bridge : catégories, priorités,
gabarits de message, anti-spam, plages de silence et repli sans Firebase.
CDC2 sections 50 à 67, 87 à 90 et 94.

La configuration de Firebase est décrite à part : [FCM_SETUP.md](FCM_SETUP.md).

---

## 1. Un seul point d'entrée

Tout passe par `NotificationService` :

```python
from app.models.intelligence import NotificationCategory, NotificationPriority
from app.services.notifications import notification_service, templates

await notification_service.notify(
    NotificationCategory.TRADE,
    NotificationPriority.HIGH,
    "🟢 ACHAT OUVERT — XAUUSD",
    "XAUUSD · ACHAT · 0.02 lot",
    data={"route": "trade", "tradeId": 12},
    symbol="XAUUSD",
)

# ou, avec un gabarit du CDC2 :
await notification_service.send(
    templates.position_opened(
        symbol="XAUUSD", direction="BUY", volume=0.02,
        entry=3512.40, stop_loss=3498.00, take_profits=[3528.00],
        risk_percent=0.5, ai_mode="ENSEMBLE", confidence=0.83,
    )
)
```

Chaque notification suit toujours le même chemin :

1. **nettoyage de sécurité** (section 7 de ce document) ;
2. **préférence de catégorie** et **anti-doublon** ;
3. **enregistrement** dans la table `notification_events` — l'inbox, qui
   survit à tout ;
4. **publication sur le bus d'événements** (`notification.created`) →
   WebSocket ;
5. **push distant** uniquement si le score de pertinence le justifie.

L'étape 5 est la seule qui dépende de Firebase. Les quatre premières
fonctionnent toujours.

## 2. Catégories (CDC2 section 51)

| Catégorie      | Contenu                                                        |
|----------------|----------------------------------------------------------------|
| `TRADE`        | Ouverture, TP, SL, fermeture, break even                       |
| `SIGNAL`       | Signal Telegram et verdict de TradePilot                       |
| `OPPORTUNITY`  | Opportunité détectée, alertes de mouvement de marché           |
| `NEWS`         | Actualité à fort impact, information boursière                 |
| `ECONOMIC`     | Calendrier économique, événement imminent                      |
| `RISK`         | Limite de perte, circuit breaker, suspension du trading        |
| `SYSTEM`       | MT5, Telegram, tunnel, flux de marché (CDC2 section 87)        |
| `DAILY_REPORT` | Journal du jour et bilan hebdomadaire                          |
| `AI_SYSTEM`    | Désaccord IA, indisponibilité d'un moteur, routage             |

## 3. Priorités et règle de push (CDC2 section 64)

| Priorité   | Comportement par défaut                                  |
|------------|-----------------------------------------------------------|
| `LOW`      | Inbox seulement                                           |
| `MEDIUM`   | Inbox + WebSocket, **pas de push** — reste dans l'application |
| `HIGH`     | Push                                                      |
| `CRITICAL` | Push, avec dérogation possible aux plages de silence      |

Le seuil est réglable par catégorie (`minimumPriority`). Une notification non
poussée n'est jamais perdue : elle est visible dans l'inbox, et le champ
`pushError` en donne la raison en clair.

## 4. Anti-spam : `NotificationRelevanceScore`

Trois garde-fous complémentaires :

**Score de pertinence** — 0 à 1, calculé à partir de la priorité (65 %), du
poids de la catégorie (35 %) et, si elle est fournie, de la confiance de la
décision. Le score est publié avec la notification (champ `relevance`) pour que
l'interface puisse trier.

**Déduplication** — la même alerte (même catégorie, même titre, même symbole)
ne repart pas dans la fenêtre suivante :

| Priorité   | Fenêtre |
|------------|---------|
| `CRITICAL` | 5 min   |
| `HIGH`     | 15 min  |
| `MEDIUM`   | 30 min  |
| `LOW`      | 60 min  |

Un doublon n'est pas enregistré du tout : `notify()` renvoie `None`.

**Limite de débit** — 12 push non critiques par heure glissante au maximum.
Au-delà, les notifications restent dans l'application. Les `CRITICAL` ne sont
jamais bridées.

### Codes de raison

| Code                         | Signification                                           |
|------------------------------|---------------------------------------------------------|
| `PUSH`                       | Envoyée en notification push                            |
| `CATEGORY_DISABLED`          | Catégorie désactivée : rien n'est enregistré            |
| `DUPLICATE`                  | Alerte identique récente                                |
| `PUSH_DISABLED`              | Push coupé pour cette catégorie                         |
| `BELOW_MINIMUM_PRIORITY`     | Priorité sous le seuil de la catégorie                  |
| `QUIET_HOURS`                | Plage de silence active                                 |
| `RATE_LIMITED`               | Trop de push récents                                    |
| `PUSH_TRANSPORT_UNAVAILABLE` | FCM non configuré : repli WebSocket et inbox            |

## 5. Plages de silence (CDC2 section 90)

Réglées par catégorie, au format `HH:MM`, sur l'heure locale du Bridge :

```json
{
  "preferences": [
    {
      "category": "NEWS",
      "quietHoursStart": "22:30",
      "quietHoursEnd": "07:00",
      "criticalBypassesQuietHours": true
    }
  ]
}
```

Les plages traversant minuit sont gérées. Une heure illisible désactive
simplement la plage, sans erreur. `criticalBypassesQuietHours` (actif par
défaut) laisse passer les `CRITICAL` — une limite de perte atteinte à 3 h du
matin doit réveiller.

## 6. Gabarits de message (CDC2 sections 52 à 63, 87)

Tous dans `app/services/notifications/templates.py`, textes en français
accentué, courts, lisibles sur un écran verrouillé :

| Fonction                    | Section CDC2 | Titre                      |
|-----------------------------|--------------|----------------------------|
| `position_opened`           | 52 / 53      | 🟢 ACHAT OUVERT / 🔴 VENTE OUVERTE |
| `opportunity_detected`      | 54           | 🤖 OPPORTUNITÉ DÉTECTÉE    |
| `telegram_signal`           | 55           | 📡 SIGNAL TELEGRAM         |
| `ai_disagreement`           | 56           | ⚠️ ANALYSE INCERTAINE      |
| `take_profit_hit`           | 57           | ✅ TP1 ATTEINT             |
| `stop_loss_hit`             | 58           | ❌ STOP LOSS               |
| `position_closed`           | 59           | 🏁 POSITION FERMÉE         |
| `break_even_applied`        | 60           | 🛡 BREAK EVEN ACTIVÉ       |
| `risk_limit_reached`        | 61           | ⚠️ LIMITE DE RISQUE        |
| `high_impact_news`          | 62           | 🌍 ACTUALITÉ — IMPACT …    |
| `market_information`        | 63           | 📈 INFORMATION DE MARCHÉ   |
| `economic_event_upcoming`   | 34 / 62      | 📅 ÉVÉNEMENT ÉCONOMIQUE    |
| `system_status`             | 87           | 🔌 <service> indisponible  |

## 7. Sécurité (CDC2 section 94)

Deux règles appliquées automatiquement à **chaque** notification, dans
`app/services/notifications/safety.py` :

1. **Aucun secret.** Le titre, le corps et la charge utile passent par le
   masqueur du projet (`redact`). Toute clé de données dont le nom évoque un
   secret (`token`, `apiKey`, `secret`, `password`, `session`, `credential`…)
   est retirée. Un identifiant de compte est réduit à ses quatre derniers
   chiffres (`***4821`), dans les données comme dans le texte.
2. **Aucune action financière déclenchable depuis une notification.** Toute clé
   évoquant un ordre (`placeOrder`, `closePosition`, `confirm`, `execute`,
   `command`…) est retirée. La charge utile ne sert qu'à ouvrir un écran :
   `route`, `notificationId`, `symbol`, `category`, `priority`, plus un
   identifiant d'entité.

## 8. Repli sans Firebase

Quand FCM n'est pas configuré — ou volontairement désactivé — rien ne casse :

- la notification est **enregistrée** dans l'inbox ;
- elle est **diffusée en temps réel** sur le WebSocket
  (`notification.created`), ce qui permet à l'application au premier plan
  d'afficher une notification **locale** ;
- `pushError` vaut `PUSH_TRANSPORT_UNAVAILABLE` ;
- `GET /api/v1/notifications/push/status` le dit explicitement.

Seul cas non couvert par le repli : application **fermée**. C'est précisément
ce que FCM apporte, et la seule raison de le configurer.

## 9. Routes HTTP

Toutes protégées par `require_device`.

| Méthode | Route                                | Rôle                                             |
|---------|--------------------------------------|--------------------------------------------------|
| GET     | `/api/v1/notifications`              | Inbox paginée (`limit`, `offset`, `category`, `priority`, `symbol`, `unreadOnly`) |
| GET     | `/api/v1/notifications/unread-count` | Compteurs non lus, global et par catégorie       |
| GET     | `/api/v1/notifications/{id}`         | Détail d'une notification                        |
| POST    | `/api/v1/notifications/{id}/read`    | Marquer comme lue                                |
| POST    | `/api/v1/notifications/read-all`     | Tout marquer comme lu (catégorie facultative)    |
| GET     | `/api/v1/notifications/preferences`  | Réglages de toutes les catégories                |
| PUT     | `/api/v1/notifications/preferences`  | Modifier une ou plusieurs catégories             |
| POST    | `/api/v1/notifications/test`         | Notification d'essai                             |
| GET     | `/api/v1/notifications/push/status`  | FCM configuré ou non, appareils avec jeton       |

## 10. Alertes de mouvement (CDC2 section 65)

Six familles : mouvement anormal, volatilité soudaine, pic de spread, gap,
grande bougie, cassure. Le scanner de marché appelle une seule fonction :

```python
from app.services.notifications.movement import evaluate_market_movement

await evaluate_market_movement(
    "XAUUSD",
    change_percent=1.1,
    window_minutes=12,
    volatility_ratio=3.2,
    spread_points=18.0,
    average_spread_points=4.0,
    gap_percent=None,
    candle_range=12.0,
    atr=4.0,
    breakout_level=3520.0,
    breakout_direction="UP",
    session=session,      # facultatif
    notify=True,          # False = détection seule
)
```

`detect_movements(...)` rend les mêmes alertes sans rien écrire : c'est la
version pure, utile pour un test ou un aperçu. Les seuils par défaut
(`MovementThresholds`) : 0,8 % de variation, 2x la volatilité normale, 3x le
spread moyen, 0,5 % de gap, 2x l'ATR pour une bougie. Un dépassement du double
du seuil fait passer l'alerte en `CRITICAL`.

## 11. Rapports (CDC2 sections 88 et 89)

```python
from app.services.notifications import reports

await reports.send_daily_report()          # journal du jour
await reports.send_weekly_report()         # bilan des 7 derniers jours
draft = await reports.build_daily_report(session)   # contenu seul
```

Le **rapport quotidien** donne : trades, gagnants, perdants, résultat, taux de
réussite, ventilation par source (IA locale, OpenRouter, Ensemble, Telegram,
Manuel) et les actualités importantes du lendemain.

Le **rapport hebdomadaire** ajoute : facteur de profit, R moyen, drawdown
maximal, meilleur et pire instrument, performance par source.

La source d'un trade est déduite sans supposition : canal Telegram renseigné →
`Telegram` ; sinon la décision liée et son enregistrement de consensus
départagent `IA locale`, `OpenRouter` et `Ensemble`.

Les rapports sont de simples fonctions appelables : la planification (tâche de
fond, cron, bouton) reste libre.

## 12. Limites connues

- Les plages de silence utilisent l'heure locale de la machine qui héberge le
  Bridge, pas celle du téléphone.
- La déduplication compare le titre exact : deux formulations différentes du
  même événement comptent pour deux notifications.
- La limite de débit est globale, pas par catégorie.
- L'envoi FCM est séquentiel, un appareil après l'autre. C'est sans effet pour
  un usage personnel (un ou deux téléphones).
