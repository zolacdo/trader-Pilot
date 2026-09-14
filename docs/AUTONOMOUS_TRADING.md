# Trading autonome

Le trading autonome désigne la capacité du système à **produire lui-même une
proposition de trade**, au lieu de se contenter de copier un signal Telegram.

> **État au 11 septembre 2026.** Cette capacité **n'est pas encore
> opérationnelle**. La table qui accueillera les opportunités existe, les
> garde-fous qui les borneront sont définis et exposés par l'API, mais
> **le générateur d'opportunités n'est pas écrit** : le paquet
> `app/services/opportunities` est un emplacement vide. Aucun code du Bridge ne
> peut aujourd'hui initier un trade de lui-même.
>
> Ce document décrit ce qui est réellement en place, et sert de contrat pour ce
> qui viendra. Il sera complété quand le moteur de décision et le générateur
> seront livrés.

---

## 1. La règle non négociable

Le cahier des charges est explicite, et c'est la règle autour de laquelle tout
le reste s'organise :

> **Les niveaux d'entrée, de stop loss et de take profit doivent être calculés**
> à partir de la structure du marché, de la volatilité, des supports et
> résistances, de l'ATR et d'une stratégie déterministe.
>
> **Les intelligences artificielles servent à interpréter, contextualiser et
> expliquer. Elles n'inventent aucun chiffre.**

Autrement dit : un modèle n'écrit jamais « stop loss à 2640 ». Un calcul écrit
2640, et le modèle peut expliquer pourquoi ce niveau a du sens. Si le calcul ne
produit pas de niveau, il n'y a pas d'opportunité — le modèle ne comble pas le
vide.

La raison est développée dans [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md).

---

## 2. La structure d'une opportunité

Table `ai_opportunities`, définie dans `app/models/intelligence.py`.

| Champ | Rôle |
|---|---|
| `symbol`, `broker_symbol` | Instrument canonique et son nom réel chez le broker |
| `created_at`, `expires_at` | **Une opportunité périme.** Un niveau calculé il y a trois heures ne vaut plus rien |
| `direction` | `BUY` ou `SELL` |
| `strategy` | Famille de stratégie à l'origine du calcul |
| `entry_min`, `entry_max`, `entry_price` | Zone d'entrée, ou prix unique |
| `stop_loss`, `take_profits` | Niveaux calculés |
| `expected_rr` | Rapport gain/risque attendu |
| `confidence` | Confiance recalibrée |
| `status` | `PENDING` par défaut |
| `reasons` | Arguments favorables |
| `negative_factors` | **Arguments défavorables** |
| `snapshot_id`, `decision_id`, `signal_id` | Rattachement à la photographie de marché, à la décision et à un éventuel signal |

Deux détails de conception méritent d'être relevés.

**`negative_factors` est au même niveau que `reasons`.** Une opportunité qui
n'énumère que ce qui la soutient n'est pas une analyse. Le modèle de données
oblige à conserver les arguments contraires.

**`snapshot_id` rattache l'opportunité à une photographie de marché précise.**
On saura toujours sur quelles données chiffrées une proposition reposait, et on
pourra la relire après coup. C'est ce qui permettra de mesurer honnêtement la
qualité de ce que le système produit, plutôt que de s'en souvenir
favorablement.

---

## 3. Les garde-fous, déjà définis

Table `ai_settings`, modifiable par `PUT /api/v1/ai/router/settings`.

| Clé | Défaut | Rôle |
|---|---|---|
| `aiTradingEnabled` | **`false`** | Interrupteur général du trading initié par le système |
| `telegramTradingEnabled` | `true` | Interrupteur, séparé, de la copie Telegram |
| `shadowMode` | **`true`** | Analyser et décider sans envoyer d'ordre |
| `maxAiTradesPerDay` | `3` | Plafond journalier de trades initiés par le système |
| `maxTelegramTradesPerDay` | `10` | Plafond journalier de trades issus de Telegram |
| `maxTradesPerSymbolPerDay` | `2` | Plafond journalier par instrument |
| `minOpportunityConfidence` | `0.75` | Confiance minimale d'une opportunité |
| `requireConsensus` | `true` | Exige un consensus franc des deux IA |
| `disagreementBehaviour` | `"NO_TRADE"` | Conduite en cas de désaccord |

À quoi s'ajoute, **par instrument**, le champ `allow_ai_trading` de la table
`watchlist`, **à `false` par défaut**. Autrement dit, même avec
`aiTradingEnabled = true`, le système ne pourra initier un trade que sur les
instruments que vous aurez explicitement autorisés, un par un.

Trois niveaux d'autorisation doivent donc être réunis :

```
   aiTradingEnabled = true          (interrupteur global)
              ET
   shadowMode = false               (on sort du mode ombre)
              ET
   watchlist.allow_ai_trading       (instrument par instrument)
```

Et même alors, le `RiskManager` conserve son droit de veto sur chaque ordre.

**Les valeurs par défaut sont volontairement inertes** : à l'installation, le
trading autonome est désactivé, le mode ombre est actif, et aucun instrument
n'est autorisé.

---

## 4. Le chemin prévu

Quand les moteurs manquants seront livrés, une opportunité devra suivre ce
chemin. Les étapes ⑤ à ⑧ existent déjà et sont en production pour les signaux
Telegram.

```
   ① Scrutation de la watchlist
        instruments activés, par priorité
                  │
   ② Photographie de marché  →  market_snapshots
        prix, régime, tendances, caractéristiques
                  │
   ③ Scores déterministes
        technique, historique, régime, inter-marchés, news, Telegram
                  │
   ④ Calcul des niveaux
        structure, volatilité, supports/résistances, ATR
        ─── AUCUN chiffre ne vient d'un modèle ───
                  │
   ⑤ Avis des IA, en ensemble sur les cas sensibles
        confrontation, puis recalibrage sur les scores ci-dessus
                  │
   ⑥ Décision  →  decision_records + decision_factors
        y compris NO_TRADE et NEEDS_REVIEW
                  │
   ⑦ Filtres d'opportunité
        minOpportunityConfidence, plafonds journaliers,
        allow_ai_trading, expiration
                  │
   ⑧ RISKMANAGER — droit de veto absolu
                  │
   ⑨ order_check  →  order_send
```

Points de passage obligés, déjà garantis par le code existant :

- une décision qui exigeait l'IA alors qu'aucune n'est disponible sort en
  **`NEEDS_REVIEW`**, jamais en action de trading ;
- un désaccord entre les deux moteurs **ne produit aucune direction** ;
- la confiance, quelle qu'elle soit, **ne modifie jamais le volume**. Elle sert
  de seuil d'admission, rien de plus.

---

## 5. Avant d'activer quoi que ce soit, un jour

Cette section anticipe. Elle n'est pas applicable aujourd'hui, puisqu'il n'y a
rien à activer — mais l'ordre des étapes, lui, ne changera pas.

1. **Rester en mode ombre** aussi longtemps que possible, et comparer ce que le
   système *aurait* fait avec ce qui s'est réellement passé. Voir
   [SHADOW_MODE.md](SHADOW_MODE.md).
2. **Passer en `PAPER`** ensuite, jamais directement en démo.
3. **Puis en `MT5_DEMO`**, plusieurs semaines, sur un seul instrument autorisé.
4. **Relire [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md)** avant toute bascule
   en réel — le mode réel exige de toute façon un déverrouillage explicite, et
   un mode réel non déverrouillé retombe automatiquement en démo au démarrage.
5. **Laisser les plafonds bas.** Trois trades par jour, deux par instrument :
   ces valeurs par défaut ne sont pas des suggestions timides, ce sont des
   bornes utiles.

---

## 6. Récapitulatif honnête

| Élément | État |
|---|---|
| Table `ai_opportunities` | **Créée**, avec tous ses champs |
| Réglages et garde-fous | **Définis**, exposés et modifiables par l'API |
| `watchlist.allow_ai_trading` | **Défini**, `false` par défaut |
| Générateur d'opportunités | **Non écrit** — `app/services/opportunities` est vide |
| Moteur de décision | **Non écrit** — `app/services/decision` est vide |
| Moteur de confiance et pondérations | **Non écrit** — `app/services/confidence` est vide |
| Familles de stratégies | **Non écrites** — `app/services/strategies` est vide |
| Lecture de `aiTradingEnabled` par le code d'exécution | **Aucune** aujourd'hui |
| Lecture de `shadowMode` par le code d'exécution | **Aucune** aujourd'hui |
| `RiskManager`, `order_check`, résolution de symbole | **En production** |

Le seul chemin de trading réellement actif reste celui du cahier des charges
initial : message Telegram → parser déterministe → repli IA si ambigu →
validateur strict → `RiskManager` → `order_check` → `order_send`.

---

Le trading comporte un risque de perte. Un système qui produit ses propres
propositions ne se trompe pas moins qu'un canal Telegram : il se trompe
différemment, et plus régulièrement. C'est précisément pourquoi le mode ombre,
les plafonds journaliers, l'autorisation par instrument et le veto du
`RiskManager` existent avant la première ligne du générateur.
