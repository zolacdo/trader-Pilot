# Boucle de retour sur les pertes du Market Watcher

Date : 2026-09-15
État : validé, prêt pour le plan d'implémentation

## Ce qui a déclenché ce chantier

Le watcher publie des signaux et les suit, mais rien ne l'empêche de
reproduire une erreur qu'il vient de commettre. La demande : *« il faut que
chaque nouvelle perte soit analysée pour ne plus la commettre »*, en boucle
fermée, sans validation signal par signal.

## Ce que les mesures ont montré

Relevé du 2026-09-15 sur la base de production.

Les seuils ne sont pas le coupable. Sur 21 opérations dénouées, les perdants
notent 71,1 et les gagnants 72,3 : relever `minimum_score` n'aurait évité
aucune perte. Tout ce qui est publié tient dans la bande 70,0-74,6, et
`strong_score` (85) n'a jamais été atteint.

Les deux comptabilités se contredisent :

| Source | Population | Résultat |
| --- | --- | --- |
| `watcher_signals` | 21 dénoués | +8,34 R, 11 gagnants / 10 perdants |
| `trades` (MT5 démo) | 33 closes | −139,25 $, 12 gagnantes / 12 perdantes |

Et la machinerie de gestion **existe déjà** : `position_manager.py` applique
break-even sur TP1 (offset 5 points), `PARTIAL_CLOSE` 40/30/30 et trailing
`R_BASED`, tout cela actif dans `risk_settings`. Le suivi du watcher l'ignore
totalement : il mesure « sur position entière » et inscrit −1,00 R là où la
position réelle a encaissé 40 % à TP1 puis est sortie à l'équilibre. Trois
signaux le montrent (22 : TP1 et TP2 touchés, excursion 4,42 R, compté −1,00 R ;
7 et 10 : TP1 touché, comptés −1,00 R).

**Conséquence structurante : une boucle d'apprentissage branchée sur
`watcher_signals` apprendrait sur des chiffres faux.** L'honnêteté de la
comptabilité passe donc avant l'apprentissage lui-même.

## Étape 1 — Rendre la comptabilité du watcher honnête

Préalable non négociable aux deux étapes suivantes.

`lifecycle.py` reflète la gestion que les positions reçoivent réellement, en
lisant les **mêmes** `RiskSettings` que `position_manager` : les deux ne
doivent jamais pouvoir diverger.

À chaque objectif franchi :

- si `multi_tp_strategy is PARTIAL_CLOSE`, la fraction `split_ratios[n-1]` est
  encaissée au prix de l'objectif et cumulée dans `booked_r` ; la fraction
  restante descend dans `open_fraction` ;
- si `break_even_enabled` et `break_even_trigger is TP1_HIT` et qu'un objectif
  au moins est atteint, le `stop_loss` **suivi** remonte à l'entrée, décalée de
  `break_even_offset_points`.

Le résultat devient `booked_r + open_fraction × R(prix de sortie)`, où
`R(prix)` se mesure toujours contre `risk_distance`, figé à la création. Un
signal jamais géré garde donc exactement `-1,00 R` au stop : la valeur du stop
suivi est alors encore le stop initial. Les tests existants restent verts sans
modification, ce qui est le meilleur garde-fou contre une régression.

La docstring du module pose aujourd'hui que « le résultat est mesuré sur
position entière ». Elle est réécrite sciemment : ce choix décrivait une
stratégie sans sortie partielle, qui n'est plus celle qui s'exécute.

Deux colonnes sur `watcher_signals`, `booked_r` (défaut 0,0) et
`open_fraction` (défaut 1,0), plus la migration qui les ajoute. Le stop initial
n'a pas besoin d'être stocké : `entry` et `risk_distance` le reconstituent.

## Étape 2 — Un post-mortem par perte

Table dédiée `watcher_post_mortems`. `watcher_signal_events` ne convient pas :
il trace des transitions, pas des analyses.

Un enregistrement par clôture perdante, écrit une seule fois — index unique sur
`signal_id`. Contenu :

- l'identité du signal : symbole, sens, type d'entrée, unité de temps, score ;
- les critères qui portaient la décision, extraits du `score_breakdown` : ceux
  au-dessus de 0,75 et ceux au-dessous de 0,35, pour savoir sur quoi le
  système s'est appuyé et ce qu'il a ignoré ;
- les excursions réellement atteintes et le résultat final ;
- l'heure de session UTC ;
- **le rapprochement avec la position réelle** : `trade_id` et `realized_pnl`
  du côté `trades`, appariés par symbole, sens et fenêtre temporelle. C'est
  cette ligne qui dit ce que l'argent a fait, et elle peut rester nulle si
  aucune position n'a été prise ;
- la leçon, en clair : ce qu'une règle de gestion aurait changé.

## Étape 3 — L'apprentissage, borné

Module `bridge/app/watcher/learning.py`, appelé depuis la boucle d'entretien
horaire existante, à l'intérieur de `_guard` : une panne d'apprentissage ne
doit jamais suspendre l'entretien.

Il compte les opérations dénouées par type d'entrée et par instrument sur une
fenêtre glissante, puis applique une règle unique : **une clé qui totalise au
moins `min_sample` opérations dénouées sans un seul gain est écartée** — un
type d'entrée est désactivé, un instrument sort de la liste surveillée.

Un seul seuil, volontairement. Deux compteurs distincts — « n pertes » d'un
côté, « m observations minimum » de l'autre — finiraient par se contredire, et
le cas litigieux (bannir sur 8 pertes alors qu'il faut 10 observations pour
conclure) n'a pas de bonne réponse.

Trois règles sur lesquelles il ne transige pas :

1. **Jamais de décision sous `min_sample`.** Sur 21 opérations, tout ajustement
   fin ajusterait du bruit. `performance.py` encode déjà cette prudence avec
   `MIN_SAMPLE = 10`.
2. **Jamais hors des bornes.** Chaque paramètre ajustable déclare son min et
   son max dans `config/watcher.yaml`. L'écriture passe par `update_config`,
   après bornage. Une borne absente vaut interdiction d'écrire.
3. **Jamais en silence.** Chaque écriture est journalisée avec son chiffrage
   — combien de pertes, sur quelle fenêtre — puis publiée dans le canal.

Une décision n'est qu'un réglage en base : elle reste défaisable depuis
l'application, sans toucher au code.

### Bornes, dans `config/watcher.yaml`

```yaml
learning:
  enabled: true
  min_sample: 10
  window_days: 30
  bounds:
    minimum_score: [65, 80]
    minimum_rr: [1.2, 2.5]
```

`bounds` est le mécanisme, pas la liste de ce qui bouge aujourd'hui : aucune
règle livrée n'écrit `minimum_score` ni `minimum_rr`. Les deux bornes sont
posées d'avance pour qu'un ajustement numérique futur trouve sa limite déjà
déclarée — et, la règle 2 le dit, un paramètre sans borne ne peut pas être
écrit du tout.

## Tests

En TDD, à écrire avant chaque implémentation.

Étape 1 : TP1 puis retour à l'entrée vaut 0 et non −1 ; la fraction encaissée
se retrouve dans `result_r` ; un signal jamais géré vaut toujours −1,00 R au
stop ; la migration ajoute les colonnes sans perdre de ligne.

Étape 2 : un post-mortem est écrit exactement une fois par perte ; une
deuxième clôture ne le duplique pas ; les critères hauts et bas sont extraits
du `score_breakdown` réel ; l'appariement avec `trades` trouve la position
quand elle existe et reste nul sinon.

Étape 3 : sous `min_sample` la boucle ne décide rien ; aucun paramètre ne sort
jamais de ses bornes ; un paramètre sans borne déclarée n'est pas écrit ; un
bannissement est journalisé et publié ; une panne du module n'interrompt pas la
boucle d'entretien.

## Hors périmètre

Réécrire la gestion de position : elle existe et fonctionne dans
`position_manager.py`. Le watcher s'y aligne, il ne la duplique pas.

Ajuster les poids des critères du score : la matière manque, et les mesures
montrent que le score ne discrimine pas à ce niveau. À rouvrir quand
l'échantillon le permettra.
