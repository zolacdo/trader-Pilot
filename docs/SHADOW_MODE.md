# Mode ombre

Le mode ombre laisse le système **analyser et décider sans envoyer aucun
ordre**. Il enregistre ce qu'il *aurait* fait, et vous comparez ensuite avec ce
qui s'est réellement passé.

C'est l'étape qui précède tout le reste : avant `PAPER`, avant la démonstration,
avant le réel.

> **État au 11 septembre 2026.** La structure est en place — l'énumération, la
> table, le drapeau sur les décisions, le réglage exposé par l'API. **Aucun code
> ne lit encore `shadowMode` et rien n'écrit encore dans `shadow_trades`.** Le
> moteur de décision qui produira ces enregistrements est en cours d'écriture
> par une autre équipe. Ce document décrit ce qui existe et ce à quoi cela
> servira ; il ne décrit pas un comportement actif.

---

## 1. Pourquoi un mode ombre

Un système de trading automatique ne se juge pas sur son code, mais sur ses
décisions. Le mode ombre permet de les observer **sans rien risquer** :

- il produit des décisions **datées**, qu'on ne peut pas réinterpréter
  favorablement après coup ;
- il enregistre aussi les décisions de **ne rien faire**, qui sont le vrai
  révélateur d'un système prudent ;
- il n'a aucun effet sur le compte : ni ordre, ni marge, ni spread, ni
  glissement.

La différence avec le mode `PAPER` est nette :

| | **Mode ombre** | **Mode PAPER** |
|---|---|---|
| Décide | oui | oui |
| Enregistre ce qu'il aurait fait | oui | — |
| Simule l'ouverture et le suivi d'une position | non | oui |
| Envoie un ordre | non | non |
| Touche au compte réel | non | non |

Le mode ombre est en amont : il observe la **décision**. Le mode `PAPER`
observe l'**exécution** simulée.

---

## 2. Ce qui est enregistré

### `ShadowOutcome` — trois issues

| Valeur | Sens |
|---|---|
| `WOULD_BUY` | Le système aurait acheté |
| `WOULD_SELL` | Le système aurait vendu |
| `WOULD_SKIP` | Le système n'aurait rien fait — **valeur par défaut** |

Le fait que `WOULD_SKIP` soit la valeur par défaut n'est pas anodin : ne rien
faire est une décision à part entière, et elle mérite d'être comptée.

### `shadow_trades` — la table

| Champ | Contenu |
|---|---|
| `decision_id` | Rattachement à la décision qui l'a produite |
| `symbol` | Instrument |
| `outcome` | L'une des trois issues ci-dessus |
| `direction` | `BUY` ou `SELL`, si applicable |
| `entry_price`, `stop_loss`, `take_profit`, `volume` | Les niveaux qui auraient été utilisés |
| `opened_at`, `closed_at`, `close_price` | Horodatage du cycle simulé |
| `r_multiple` | Résultat exprimé en multiples du risque |
| `result` | Issue lisible |
| `source` | `AI_GENERATED`, `TELEGRAM` ou `MANUAL` |

Le champ `source` est ce qui rendra la comparaison intéressante : il permettra
de mesurer séparément les décisions issues des canaux Telegram et celles
produites par le système lui-même.

Le résultat est exprimé en **multiples du risque** (`r_multiple`) plutôt qu'en
devise. Un `+2R` reste un `+2R` quelle que soit la taille du compte, ce qui rend
les périodes comparables entre elles.

### Le drapeau sur les décisions

La table `decision_records` porte un champ `shadow`, indexé. Une décision prise
en mode ombre est donc marquée comme telle et **n'est jamais confondue** avec
une décision exécutée. Le champ `executed` la complète.

Concrètement, les décisions ne sont pas rangées dans une base séparée : elles
coexistent, distinguées par ces deux drapeaux. On peut ainsi relire la même
journée sous les deux angles.

---

## 3. Le réglage

| Clé JSON | Défaut | Effet prévu |
|---|---|---|
| `shadowMode` | **`true`** | Le système décide, mais n'envoie aucun ordre |

Lecture et modification :

```powershell
$entetes = @{ "X-Device-Token" = $jeton; "Content-Type" = "application/json" }
$bridge  = "http://127.0.0.1:8787/api/v1"

# Lecture
Invoke-RestMethod -Uri "$bridge/ai/router/settings" -Headers $entetes

# Modification
$corps = @{ shadowMode = $true } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "$bridge/ai/router/settings" -Headers $entetes -Body $corps
```

La valeur apparaît aussi dans `GET /api/v1/ai/status`, sous `shadowMode`.

**Le défaut est `true`** : à l'installation, le système est en mode ombre. C'est
volontaire — il faut une action explicite pour en sortir, jamais l'inverse.

> **Rappel important.** Ce réglage est aujourd'hui **stocké et exposé, mais lu
> par personne**. Ne comptez pas dessus comme sur un garde-fou actif : le
> garde-fou réel, aujourd'hui, ce sont `aiTradingEnabled = false`
> (défaut), l'absence de générateur d'opportunités, le mode d'exécution `PAPER`
> par défaut, et le `RiskManager`.

---

## 4. Ce que la comparaison devra montrer

Le cahier des charges demande, pour l'écran de comparaison à venir :

| Mesure | Lecture |
|---|---|
| Trades simulés | Volume d'activité. Trop élevé est un mauvais signe |
| Taux de gain / taux de perte | À lire toujours avec le R moyen |
| **R moyen** | La mesure qui compte réellement |
| Drawdown maximal | La pire série, pas la moyenne |
| Facteur de profit | Rapport gains bruts / pertes brutes |
| Performance de l'IA locale | Par moteur |
| Performance d'OpenRouter | Par moteur |
| Performance de l'ensemble | Les deux confrontés |

La table `strategy_performance` est prévue pour porter ces agrégats, par jour,
par stratégie et par origine.

**Trois précautions de lecture**, qui vaudront le jour où ces chiffres
existeront :

1. **Un taux de gain élevé ne veut rien dire seul.** Gagner huit fois sur dix
   avec un R moyen négatif reste une méthode perdante.
2. **Une période courte ne prouve rien.** Quelques dizaines de décisions sur
   quelques jours relèvent du bruit.
3. **Le mode ombre est plus favorable que la réalité.** Il ignore le
   glissement, l'élargissement du spread aux heures creuses, les rejets du
   broker et les coupures réseau. Un résultat en ombre est un plafond, pas une
   prévision.

---

## 5. La place du mode ombre dans la progression

```
  Mode ombre          →  PAPER          →  MT5_DEMO        →  MT5_LIVE
  on observe             on simule         argent fictif      argent réel
  les décisions          l'exécution       chez le broker     déverrouillage
                                                              explicite requis
```

Chaque étape se franchit **dans ce sens uniquement**, et rien ne presse. Le
Bridge y aide déjà : au démarrage, un mode réel non déverrouillé retombe
systématiquement en `MT5_DEMO`.

Voir [DEMO_TESTING.md](DEMO_TESTING.md) pour les scénarios de test, puis
[GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) avant toute bascule en réel.

---

## 6. Récapitulatif honnête

| Élément | État au 11 septembre 2026 |
|---|---|
| Énumération `ShadowOutcome` | **Définie** |
| Table `shadow_trades` | **Créée**, avec tous ses champs |
| Champ `shadow` sur `decision_records` | **Défini et indexé** |
| Réglage `shadowMode` | **Défini, exposé par l'API, défaut `true`** |
| Table `strategy_performance` | **Créée** |
| Lecture de `shadowMode` par le code d'exécution | **Aucune** |
| Écriture dans `shadow_trades` | **Aucune** |
| Écran de comparaison mobile | **Non écrit** |

---

Le trading comporte un risque de perte. Le mode ombre ne réduit pas ce risque :
il vous laisse constater, sans payer pour l'apprendre, à quel point un système
automatique peut se tromper.
