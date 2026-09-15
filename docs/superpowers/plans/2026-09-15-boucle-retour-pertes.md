# Boucle de retour sur les pertes — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Le watcher compte ses résultats comme ils se produisent vraiment, analyse chaque perte, et écarte de lui-même ce qui ne gagne jamais.

**Architecture:** Trois couches empilées, dans cet ordre obligatoire. La comptabilité de `lifecycle.py` s'aligne d'abord sur la gestion que `position_manager.py` applique déjà aux positions réelles ; un post-mortem est ensuite écrit à chaque perte, rapproché de la position réelle ; un module d'apprentissage lit enfin ces post-mortems et écrit ses décisions dans les réglages, bornes en main.

**Tech Stack:** Python 3.13, SQLModel / SQLAlchemy async, PostgreSQL (SQLite en test), pytest avec `asyncio_mode = "auto"`.

**Spec:** `docs/superpowers/specs/2026-09-15-boucle-retour-pertes-design.md`

## Global Constraints

- Le watcher n'importe JAMAIS le moteur d'exécution depuis `lifecycle.py` ni `learning.py`. Seul `execution.py` y touche (CDC3 section 44).
- Aucune migration à écrire : `_sync_missing_columns` dans `bridge/app/database/migrations.py` ajoute automatiquement toute colonne présente dans un modèle et absente en base, et `create_all` crée les tables nouvelles.
- `MIN_SAMPLE = 10` existe déjà dans `bridge/app/watcher/performance.py` : le réutiliser, ne pas en créer un second.
- Les commentaires et docstrings du dépôt sont en français sans accents dans le code (`Duree`, `declenchement`). Les tests portent des noms français explicites.
- Chaque tâche finit par un commit ET un push (`git push origin main`), sans ligne d'attribution ni co-auteur.
- Commande de test : `cd bridge && ./.venv/Scripts/python.exe -m pytest <chemin> -q`.

---

### Task 1: Comptabilité honnête du cycle de vie

**Files:**
- Modify: `bridge/app/watcher/models.py` (classe `WatcherSignal`, vers la ligne 205)
- Modify: `bridge/app/watcher/lifecycle.py` (`run_once`, `_advance`, `_apply`, `_result_in_r`)
- Test: `bridge/tests/test_gestion_suivie_comme_executee.py` (créer)

**Interfaces:**
- Consomme : `settings_repo.get_risk_settings(session) -> RiskSettings`, avec les champs `multi_tp_strategy`, `split_ratios`, `break_even_enabled`, `break_even_trigger`, `break_even_offset_points`.
- Produit : `WatcherSignal.booked_r: float`, `WatcherSignal.open_fraction: float`, et `_result_in_r(signal, status, previous, price) -> float | None` dont la formule est `booked_r + open_fraction × R(prix de sortie)`.

- [ ] **Step 1: Écrire le test qui échoue**

Dans `bridge/tests/test_gestion_suivie_comme_executee.py`. Les réglages par défaut sont déjà `PARTIAL_CLOSE` 40/30/30 et break-even sur TP1 (`bridge/app/models/core.py:188-196`), donc aucun réglage à poser.

```python
"""La comptabilite du watcher doit refleter la gestion reellement appliquee.

Mesure du 15/09/2026 : les signaux 22, 7 et 10 avaient touche TP1 -- le 22
aussi TP2, avec 4,42 R d'excursion favorable -- et etaient comptes -1,00 R
plein. La position reelle, elle, avait encaisse 40 % a TP1 puis vu son stop
remonter a l'entree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import Direction
from app.services.mt5.interface import Candle
from app.watcher import repository
from app.watcher.config import WatcherConfig
from app.watcher.lifecycle import LifecycleTracker
from app.watcher.models import EntryType, WatcherDecision, WatcherSignal, WatcherStatus
from app.watcher.publisher import TelegramPublisher

BASE = datetime(2024, 1, 1, tzinfo=UTC)


class Recorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, text: str) -> int:
        self.messages.append(text)
        return len(self.messages)


class FakeCandleEngine:
    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self.service = None

    async def candles(self, symbol: str, timeframe, bars: int) -> list[Candle]:
        return list(self._candles)


def make_signal(**overrides: object) -> WatcherSignal:
    """Achat : entree 100, stop 98, objectifs 102 / 104 / 106, risque 2."""
    values: dict[str, object] = {
        "symbol": "TESTUSD",
        "broker_symbol": "TESTUSD",
        "direction": Direction.BUY,
        "decision": WatcherDecision.BUY,
        "status": WatcherStatus.CONFIRMED,
        "timeframe": "M15",
        "entry_type": EntryType.MARKET,
        "entry": 100.0,
        "stop_loss": 98.0,
        "digits": 2,
        "take_profit_1": 102.0,
        "take_profit_2": 104.0,
        "take_profit_3": 106.0,
        "risk_distance": 2.0,
        "risk_reward_1": 1.0,
        "risk_reward_2": 2.0,
        "risk_reward_3": 3.0,
        "score": 78.0,
        "confidence": 78,
        "created_at": BASE,
        "expires_at": BASE + timedelta(hours=4),
    }
    values.update(overrides)
    return WatcherSignal(**values)  # type: ignore[arg-type]


def candle(high: float, low: float, close: float, minute: int = 1) -> Candle:
    return Candle(
        time=BASE + timedelta(minutes=minute),
        open=100.0,
        high=high,
        low=low,
        close=close,
        tick_volume=10,
    )


async def _suivre(session, signal, candles, config, minutes: int = 30):
    recorder = Recorder()
    tracker = LifecycleTracker(TelegramPublisher(sender=recorder))
    report = await tracker.run_once(
        session, FakeCandleEngine(candles), config, now=BASE + timedelta(minutes=minutes)
    )
    return report, recorder


@pytest.fixture
def config() -> WatcherConfig:
    return WatcherConfig()


async def test_tp1_encaisse_la_fraction_prevue(session, config: WatcherConfig) -> None:
    """40 % a TP1 sur un objectif a 1 R : 0,40 R acquis, 60 % encore en jeu."""
    signal = make_signal()
    await repository.add_signal(session, signal)

    await _suivre(session, signal, [candle(high=102.5, low=99.5, close=102.0)], config)

    assert signal.status is WatcherStatus.TP1_HIT
    assert signal.booked_r == pytest.approx(0.4)
    assert signal.open_fraction == pytest.approx(0.6)


async def test_stop_apres_tp1_ne_vaut_plus_moins_un(session, config: WatcherConfig) -> None:
    """Le gain encaisse reste acquis, et le stop remonte protege le reste."""
    signal = make_signal()
    await repository.add_signal(session, signal)

    await _suivre(session, signal, [candle(high=102.5, low=99.5, close=102.0)], config)
    await _suivre(
        session,
        signal,
        [candle(high=102.0, low=99.0, close=99.5, minute=5)],
        config,
        minutes=40,
    )

    assert signal.status is WatcherStatus.SL_HIT
    # 0,40 R encaisse + 60 % sortis a 100,05 (entree + 5 points) = +0,415 R.
    assert signal.result_r == pytest.approx(0.415, abs=0.001)


async def test_un_signal_jamais_gere_vaut_toujours_moins_un(
    session, config: WatcherConfig
) -> None:
    """Sans objectif touche, rien ne bouge : le stop initial vaut -1 R."""
    signal = make_signal()
    await repository.add_signal(session, signal)

    await _suivre(session, signal, [candle(high=100.5, low=97.0, close=97.5)], config)

    assert signal.status is WatcherStatus.SL_HIT
    assert signal.result_r == pytest.approx(-1.0)
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `cd bridge && ./.venv/Scripts/python.exe -m pytest tests/test_gestion_suivie_comme_executee.py -q`
Expected: FAIL sur `booked_r` — `AttributeError` ou `TypeError`, le champ n'existe pas encore.

- [ ] **Step 3: Ajouter les deux champs au modèle**

Dans `bridge/app/watcher/models.py`, juste après `max_adverse_r` :

```python
    # Fraction deja encaissee, en unites de risque, et part encore ouverte.
    # Sans ces deux champs le suivi mesure « sur position entiere » alors que
    # le courtier a ferme 40 % a TP1 : il inscrit -1 R sur une operation qui
    # avait protege son gain.
    booked_r: float = Field(default=0.0)
    open_fraction: float = Field(default=1.0)
```

- [ ] **Step 4: Lire les réglages de risque une fois par tour**

Dans `bridge/app/watcher/lifecycle.py`, importer `from app.repositories import settings_repo` et `from app.models.core import RiskSettings`, puis charger les réglages en tête de `run_once` et les passer à `_advance` puis `_apply` par un paramètre `risk: RiskSettings`.

- [ ] **Step 5: Encaisser et armer le break even dans `_apply`**

Dans `_apply`, avant le calcul du résultat :

```python
        if status in _TARGET_STATUSES and price is not None:
            _book_partial(signal, status, price, risk)
            _arm_break_even(signal, risk)
```

Et au niveau du module :

```python
def _book_partial(
    signal: WatcherSignal, status: WatcherStatus, price: float, risk: RiskSettings
) -> None:
    """Encaisse la fraction que la strategie ferme a cet objectif."""
    if risk.multi_tp_strategy is not MultiTpStrategy.PARTIAL_CLOSE:
        return
    if signal.risk_distance <= 0:
        return
    ratios = list(risk.split_ratios or [])
    index = _TARGET_RANK[status]
    if index >= len(ratios):
        return
    fraction = min(signal.open_fraction, max(0.0, ratios[index] / 100.0))
    if fraction <= 0:
        return
    buy = signal.direction is Direction.BUY
    gain = (price - signal.entry) if buy else (signal.entry - price)
    signal.booked_r = round(signal.booked_r + fraction * gain / signal.risk_distance, 3)
    signal.open_fraction = round(signal.open_fraction - fraction, 3)


def _arm_break_even(signal: WatcherSignal, risk: RiskSettings) -> None:
    """Remonte le stop suivi a l'entree, comme le fait le gestionnaire reel.

    Le decalage se calcule depuis ``digits`` plutot que depuis un
    ``SymbolInfo`` : le suivi ne doit pas avoir besoin d'interroger
    MetaTrader pour tenir ses comptes.
    """
    if not risk.break_even_enabled:
        return
    if risk.break_even_trigger is not BreakEvenTrigger.TP1_HIT:
        return
    offset = risk.break_even_offset_points * (10.0 ** -signal.digits)
    buy = signal.direction is Direction.BUY
    cible = round(signal.entry + offset, signal.digits) if buy else round(
        signal.entry - offset, signal.digits
    )
    deja_protecteur = (cible <= signal.stop_loss) if buy else (cible >= signal.stop_loss)
    if deja_protecteur:
        return
    signal.stop_loss = cible
```

- [ ] **Step 6: Réécrire le calcul du résultat**

Remplacer `_result_in_r` par la formule unique, et ajouter `_exit_r` :

```python
def _exit_r(
    signal: WatcherSignal, status: WatcherStatus, price: float | None
) -> float | None:
    """R de la fraction encore ouverte, mesure au prix de sortie."""
    if signal.risk_distance <= 0:
        return None
    if status is WatcherStatus.SL_HIT:
        cible: float | None = signal.stop_loss
    elif status is WatcherStatus.TP3_HIT:
        cible = signal.take_profit_3 or signal.take_profit_2 or signal.take_profit_1
    else:
        cible = price
    if cible is None:
        return None
    buy = signal.direction is Direction.BUY
    gain = (cible - signal.entry) if buy else (signal.entry - cible)
    return gain / signal.risk_distance


def _result_in_r(
    signal: WatcherSignal,
    status: WatcherStatus,
    previous: WatcherStatus,
    price: float | None = None,
) -> float | None:
    """Resultat en unites de risque : ce qui est acquis, plus ce qui reste.

    Un signal jamais declenche n'a pas de resultat : il rend ``None``, pas
    zero. Compter un signal invalide comme une operation a zero fausserait le
    taux de reussite.

    Pour tout le reste, le resultat vaut ``booked_r + open_fraction x R(prix
    de sortie)``. Un signal qu'aucune gestion n'a touche a garde son stop
    initial et sa position entiere : il vaut donc exactement -1 R au stop,
    comme avant. Un signal gere garde le gain encaisse a TP1 et sort le reste
    au stop deplace -- ce que le compte a reellement fait.
    """
    if status is WatcherStatus.INVALIDATED:
        return None
    if _pending(signal, previous) and signal.booked_r == 0.0:
        return None
    sortie = _exit_r(signal, status, price)
    if sortie is None:
        return None
    return round(signal.booked_r + signal.open_fraction * sortie, 3)
```

Importer `MultiTpStrategy` et `BreakEvenTrigger` depuis `app.models.enums`.

- [ ] **Step 7: Réécrire la docstring du module**

Dans `bridge/app/watcher/lifecycle.py`, le troisième point des « choix assumés » dit aujourd'hui que le résultat est mesuré sur position entière et qu'un signal touchant TP1 puis revenant au stop vaut −1 R. Le remplacer par :

```
* le resultat suit la gestion reellement appliquee. Les memes reglages que
  ``position_manager`` -- fermeture partielle aux objectifs, break even sur
  TP1 -- sont lus ici, et un signal qui touche TP1 puis revient au stop garde
  le gain encaisse au lieu d'etre compte -1 R. Mesurer « sur position
  entiere » decrivait une strategie sans sortie partielle, qui n'est plus
  celle qui s'execute.
```

- [ ] **Step 8: Vérifier que tout passe**

Run: `cd bridge && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tous verts, y compris `test_watcher_publication.py` inchangé — c'est le garde-fou de non-régression.

- [ ] **Step 9: Commit et push**

```bash
git add bridge/app/watcher/models.py bridge/app/watcher/lifecycle.py bridge/tests/test_gestion_suivie_comme_executee.py
git commit -m "Count a watcher signal the way the position is really managed"
git push origin main
```

---

### Task 2: Un post-mortem par perte

**Files:**
- Modify: `bridge/app/watcher/models.py` (nouvelle classe `WatcherPostMortem`)
- Modify: `bridge/app/watcher/repository.py` (`record_post_mortem`)
- Modify: `bridge/app/watcher/lifecycle.py` (`_apply`, à la clôture)
- Test: `bridge/tests/test_post_mortem_des_pertes.py` (créer)

**Interfaces:**
- Consomme : `WatcherSignal.booked_r`, `open_fraction`, `result_r` de la tâche 1.
- Produit : `WatcherPostMortem` (table `watcher_post_mortems`) et `repository.record_post_mortem(session, signal, trade=None) -> WatcherPostMortem | None`, qui rend `None` si un post-mortem existe déjà pour ce signal.

- [ ] **Step 1: Écrire le test qui échoue**

```python
"""Chaque perte laisse une trace analysable, une seule fois."""

from __future__ import annotations

import pytest

from app.watcher import repository
from app.watcher.models import WatcherStatus

from tests.test_gestion_suivie_comme_executee import BASE, make_signal


async def test_une_perte_ecrit_un_post_mortem(session) -> None:
    signal = make_signal(
        status=WatcherStatus.SL_HIT,
        result_r=-1.0,
        max_favorable_r=1.34,
        max_adverse_r=1.0,
        score_breakdown={
            "criteria": [
                {"key": "market_structure", "ratio": 0.95},
                {"key": "volume", "ratio": 0.20},
            ]
        },
    )
    await repository.add_signal(session, signal)

    trace = await repository.record_post_mortem(session, signal)

    assert trace is not None
    assert trace.symbol == "TESTUSD"
    assert trace.result_r == pytest.approx(-1.0)
    assert trace.max_favorable_r == pytest.approx(1.34)
    assert "market_structure" in trace.criteria_high
    assert "volume" in trace.criteria_low
    assert trace.session_hour == BASE.hour


async def test_un_second_passage_ne_duplique_rien(session) -> None:
    signal = make_signal(status=WatcherStatus.SL_HIT, result_r=-1.0)
    await repository.add_signal(session, signal)

    premier = await repository.record_post_mortem(session, signal)
    second = await repository.record_post_mortem(session, signal)

    assert premier is not None
    assert second is None
    assert len(await repository.post_mortems(session)) == 1


async def test_un_gain_ne_laisse_aucun_post_mortem(session) -> None:
    signal = make_signal(status=WatcherStatus.TP3_HIT, result_r=3.0)
    await repository.add_signal(session, signal)

    assert await repository.record_post_mortem(session, signal) is None
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `cd bridge && ./.venv/Scripts/python.exe -m pytest tests/test_post_mortem_des_pertes.py -q`
Expected: FAIL avec `AttributeError: module 'app.watcher.repository' has no attribute 'record_post_mortem'`.

- [ ] **Step 3: Créer la table**

Dans `bridge/app/watcher/models.py` :

```python
class WatcherPostMortem(SQLModel, table=True):
    """Analyse d'une perte, pour ne pas la reproduire (CDC3 section 41).

    Une table a part, et non un ``WatcherSignalEvent`` : les evenements
    tracent des transitions, pas des analyses. L'unicite sur ``signal_id``
    garantit qu'une perte n'est comptee qu'une fois, meme si le suivi repasse
    sur un signal deja clos.
    """

    __tablename__ = "watcher_post_mortems"

    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="watcher_signals.id", unique=True, index=True)
    symbol: str = Field(max_length=32, index=True)
    direction: Direction
    entry_type: EntryType
    timeframe: str = Field(max_length=8)
    score: float = Field(default=0.0)
    # Sur quoi la decision s'appuyait, et ce qu'elle a ignore.
    criteria_high: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    criteria_low: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    max_favorable_r: float = Field(default=0.0)
    max_adverse_r: float = Field(default=0.0)
    result_r: float | None = Field(default=None)
    session_hour: int = Field(default=0)
    # La position reelle, quand il y en a eu une : c'est elle qui dit ce que
    # l'argent a fait. Nulle si aucun ordre n'est parti.
    trade_id: int | None = Field(default=None, index=True)
    trade_pnl: float | None = Field(default=None)
    lesson: str | None = Field(default=None, max_length=300)
    created_at: datetime = Field(default_factory=utcnow, index=True)
```

- [ ] **Step 4: Écrire l'enregistrement**

Dans `bridge/app/watcher/repository.py` :

```python
CRITERION_HIGH = 0.75
CRITERION_LOW = 0.35


def _criteria_split(breakdown: Any) -> tuple[list[str], list[str]]:
    """Criteres qui portaient la decision, et ceux qui alertaient."""
    hauts: list[str] = []
    bas: list[str] = []
    criteria = (breakdown or {}).get("criteria") or []
    for item in criteria:
        key = str(item.get("key") or "")
        ratio = item.get("ratio")
        if not key or not isinstance(ratio, (int, float)):
            continue
        if ratio >= CRITERION_HIGH:
            hauts.append(key)
        elif ratio <= CRITERION_LOW:
            bas.append(key)
    return hauts, bas


async def record_post_mortem(
    session: AsyncSession,
    signal: WatcherSignal,
    trade: Any | None = None,
) -> WatcherPostMortem | None:
    """Analyse une perte, une seule fois. Rend None si rien a analyser."""
    if signal.id is None:
        return None
    if signal.result_r is None or signal.result_r >= 0:
        return None
    existant = await session.scalar(
        select(WatcherPostMortem).where(WatcherPostMortem.signal_id == signal.id)
    )
    if existant is not None:
        return None

    hauts, bas = _criteria_split(signal.score_breakdown)
    moment = as_utc(signal.created_at) or utcnow()
    trace = WatcherPostMortem(
        signal_id=signal.id,
        symbol=signal.symbol,
        direction=signal.direction,
        entry_type=signal.entry_type,
        timeframe=signal.timeframe,
        score=signal.score,
        criteria_high=hauts,
        criteria_low=bas,
        max_favorable_r=signal.max_favorable_r,
        max_adverse_r=signal.max_adverse_r,
        result_r=signal.result_r,
        session_hour=moment.hour,
        trade_id=getattr(trade, "id", None),
        trade_pnl=getattr(trade, "realized_pnl", None),
        lesson=_lesson(signal),
    )
    session.add(trace)
    await session.flush()
    return trace


def _lesson(signal: WatcherSignal) -> str:
    """Ce que la perte apprend, en clair."""
    if signal.max_favorable_r >= 1.0:
        return (
            f"Etait monte a {signal.max_favorable_r:.2f} R avant de revenir : "
            "la sortie merite d'etre resserree."
        )
    if signal.max_favorable_r <= 0.1:
        return "N'a jamais travaille : l'entree etait prise trop tard ou a contresens."
    return f"Excursion favorable limitee a {signal.max_favorable_r:.2f} R."


async def post_mortems(
    session: AsyncSession, since: datetime | None = None
) -> list[WatcherPostMortem]:
    """Post-mortems, du plus recent au plus ancien."""
    statement = select(WatcherPostMortem)
    if since is not None:
        statement = statement.where(WatcherPostMortem.created_at >= since)
    result = await session.execute(statement.order_by(WatcherPostMortem.created_at.desc()))
    return list(result.scalars())
```

- [ ] **Step 5: Apparier la position réelle**

Le spec l'exige : c'est la position qui dit ce que l'argent a fait. Dans
`bridge/app/watcher/repository.py` :

```python
async def matching_trade(session: AsyncSession, signal: WatcherSignal) -> Any | None:
    """Position reelle nee de ce signal, si elle existe.

    L'appariement se fait sur le symbole courtier, le sens, et une fenetre qui
    commence a la creation du signal : le watcher ne pose pas de reference
    croisee sur ``trades``, et une position ouverte avant le signal ne peut pas
    en venir. La premiere position qui suit est la bonne -- le watcher ne
    publie jamais deux signaux de meme sens sur un instrument tant que le
    precedent vit (garde-fou « aucun doublon ne sera publie »).
    """
    from app.models.trading import TradeRecord

    depuis = as_utc(signal.created_at) or utcnow()
    statement = (
        select(TradeRecord)
        .where(TradeRecord.symbol == signal.broker_symbol)
        .where(TradeRecord.direction == signal.direction)
        .where(TradeRecord.opened_at >= depuis)
        .order_by(TradeRecord.opened_at)
        .limit(1)
    )
    return await session.scalar(statement)
```

L'import est local à la fonction : `models.trading` n'a pas à devenir une
dépendance de module du watcher pour une seule lecture.

Ajouter le test correspondant dans `bridge/tests/test_post_mortem_des_pertes.py` :

```python
async def test_la_position_reelle_est_rattachee_quand_elle_existe(session) -> None:
    from app.models.enums import Direction, ExecutionMode, PositionState
    from app.models.trading import TradeRecord

    signal = make_signal(status=WatcherStatus.SL_HIT, result_r=-1.0)
    await repository.add_signal(session, signal)
    position = TradeRecord(
        ticket=99001,
        symbol="TESTUSD",
        direction=Direction.BUY,
        state=PositionState.CLOSED,
        execution_mode=ExecutionMode.MT5_DEMO,
        realized_pnl=-43.18,
        opened_at=BASE,
    )
    session.add(position)
    await session.flush()

    trouvee = await repository.matching_trade(session, signal)
    trace = await repository.record_post_mortem(session, signal, trouvee)

    assert trace is not None
    assert trace.trade_pnl == pytest.approx(-43.18)
```

- [ ] **Step 6: Brancher sur la clôture**

Dans `_apply` de `bridge/app/watcher/lifecycle.py`, juste après `signal.result_r = _result_in_r(...)` :

```python
            # Une perte laisse sa trace analysable. Jamais bloquant : le suivi
            # des autres signaux ne doit pas dependre de cette ecriture.
            with contextlib.suppress(Exception):
                position = await repository.matching_trade(session, signal)
                await repository.record_post_mortem(session, signal, position)
```

Importer `contextlib` en tête de fichier.

- [ ] **Step 7: Vérifier que tout passe**

Run: `cd bridge && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tous verts.

- [ ] **Step 8: Commit et push**

```bash
git add bridge/app/watcher/models.py bridge/app/watcher/repository.py bridge/app/watcher/lifecycle.py bridge/tests/test_post_mortem_des_pertes.py
git commit -m "Analyse every losing watcher signal exactly once"
git push origin main
```

---

### Task 3: L'apprentissage, borné

**Files:**
- Create: `bridge/app/watcher/learning.py`
- Modify: `bridge/app/watcher/config.py` (champs `learning_*` et `disabled_entry_types`)
- Modify: `config/watcher.yaml` (section `learning`)
- Modify: `bridge/app/watcher/scheduler.py` (`run_maintenance_once`)
- Test: `bridge/tests/test_apprentissage_borne.py` (créer)

**Interfaces:**
- Consomme : `repository.post_mortems(session, since)` de la tâche 2, `performance.MIN_SAMPLE`, `config.update_config(session, changes)`.
- Produit : `learning.review(session, config) -> list[Decision]` où `Decision` est un `dataclass(slots=True)` avec `key: str`, `kind: str` (`"entry_type"` ou `"symbol"`), `losses: int`, `message: str`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
"""L'apprentissage decide peu, et jamais hors de ses bornes."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.core import utcnow
from app.watcher import learning, repository
from app.watcher.config import WatcherConfig, load_config
from app.watcher.models import WatcherStatus

from tests.test_gestion_suivie_comme_executee import make_signal


async def _perte(session, symbol: str, entry_type, moment=None) -> None:
    signal = make_signal(
        symbol=symbol,
        broker_symbol=symbol,
        entry_type=entry_type,
        status=WatcherStatus.SL_HIT,
        result_r=-1.0,
        created_at=moment or utcnow(),
    )
    await repository.add_signal(session, signal)
    await repository.record_post_mortem(session, signal)


async def test_sous_le_minimum_rien_n_est_decide(session) -> None:
    """Neuf pertes ne suffisent pas : on ne conclut pas sur du bruit."""
    from app.watcher.models import EntryType

    for _ in range(9):
        await _perte(session, "BREAKUSD", EntryType.BREAKOUT)

    assert await learning.review(session, WatcherConfig()) == []


async def test_dix_pertes_sans_un_gain_ecartent_le_type_d_entree(session) -> None:
    from app.watcher.models import EntryType

    for _ in range(10):
        await _perte(session, "BREAKUSD", EntryType.BREAKOUT)

    decisions = await learning.review(session, WatcherConfig())

    assert [decision.key for decision in decisions] == ["BREAKOUT"]
    assert decisions[0].kind == "entry_type"
    assert decisions[0].losses == 10
    config = await load_config(session, refresh=True)
    assert "BREAKOUT" in config.disabled_entry_types


async def test_un_parametre_sans_borne_declaree_n_est_pas_ecrit(session) -> None:
    """Regle 2 du spec : une borne absente vaut interdiction d'ecrire."""
    config = WatcherConfig()
    config.learning_bounds = {}

    assert learning.clamp(config, "minimum_score", 95.0) is None


async def test_une_valeur_est_ramenee_dans_ses_bornes(session) -> None:
    config = WatcherConfig()
    config.learning_bounds = {"minimum_score": [65.0, 80.0]}

    assert learning.clamp(config, "minimum_score", 95.0) == pytest.approx(80.0)
    assert learning.clamp(config, "minimum_score", 10.0) == pytest.approx(65.0)
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `cd bridge && ./.venv/Scripts/python.exe -m pytest tests/test_apprentissage_borne.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'app.watcher.learning'`.

- [ ] **Step 3: Ajouter les réglages**

Dans `bridge/app/watcher/config.py`, sur `WatcherConfig` :

```python
    # Apprentissage : il n'ajuste que ce dont la borne est ecrite ici.
    learning_enabled: bool = True
    learning_window_days: int = 30
    learning_bounds: dict[str, list[float]] = field(
        default_factory=lambda: {"minimum_score": [65.0, 80.0], "minimum_rr": [1.2, 2.5]}
    )
    disabled_entry_types: list[str] = field(default_factory=list)
```

Les déclarer dans `_FIELD_TYPES` pour qu'ils soient lisibles et écrivables en base, et ajouter la section correspondante à `config/watcher.yaml` :

```yaml
# --- apprentissage sur les pertes --------------------------------------------
# Il n'ecarte qu'une clef qui totalise learning_min_sample operations denouees
# sans un seul gain. Un parametre absent de bounds ne peut pas etre ecrit.
learning_enabled: true
learning_window_days: 30
learning_bounds:
  minimum_score: [65, 80]
  minimum_rr: [1.2, 2.5]
```

- [ ] **Step 4: Écrire le module**

`bridge/app/watcher/learning.py` :

```python
"""Apprentissage sur les pertes (CDC3 section 41).

Trois regles dont il ne sort jamais : aucune decision sous ``MIN_SAMPLE``,
aucune ecriture hors des bornes declarees dans la configuration, aucune
decision silencieuse. Une decision n'est qu'un reglage en base : elle reste
defaisable depuis l'application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import utcnow
from app.services import journal
from app.watcher import repository
from app.watcher.config import WatcherConfig, update_config
from app.watcher.performance import MIN_SAMPLE

logger = get_logger(__name__)


@dataclass(slots=True)
class Decision:
    """Ce que l'apprentissage a decide, et sur quels chiffres."""

    key: str
    kind: str
    losses: int
    message: str


def clamp(config: WatcherConfig, name: str, value: float) -> float | None:
    """Ramene une valeur dans ses bornes, ou refuse de l'ecrire.

    Un parametre dont la borne n'est pas declaree ne peut pas etre ajuste :
    sans limite ecrite, rien ne dit jusqu'ou la boucle aurait le droit
    d'aller.
    """
    bounds = (config.learning_bounds or {}).get(name)
    if not bounds or len(bounds) != 2:
        return None
    low, high = float(bounds[0]), float(bounds[1])
    return min(max(value, low), high)


async def review(session: AsyncSession, config: WatcherConfig) -> list[Decision]:
    """Ecarte ce qui ne gagne jamais. Ne decide rien sous MIN_SAMPLE."""
    if not config.learning_enabled:
        return []

    since = utcnow() - timedelta(days=config.learning_window_days)
    traces = await repository.post_mortems(session, since=since)
    closed = await repository.closed_signals(session, since=since)

    decisions: list[Decision] = []
    decisions.extend(_sterile(traces, closed, "entry_type"))
    decisions.extend(_sterile(traces, closed, "symbol"))
    if not decisions:
        return []

    changes: dict[str, object] = {}
    types = [d.key for d in decisions if d.kind == "entry_type"]
    if types:
        changes["disabled_entry_types"] = sorted(
            set(config.disabled_entry_types or []) | set(types)
        )
    symbols = [d.key for d in decisions if d.kind == "symbol"]
    if symbols:
        changes["symbols"] = [s for s in config.symbols if s not in set(symbols)]
    await update_config(session, changes)

    for decision in decisions:
        logger.info("Apprentissage : %s", decision.message)
        await journal.log(
            event="watcher_learning",
            message=decision.message,
            category="system",
        )
    return decisions


def _sterile(traces: list, closed: list, kind: str) -> list[Decision]:
    """Clefs totalisant MIN_SAMPLE operations denouees sans un seul gain."""
    pertes: dict[str, int] = {}
    total: dict[str, int] = {}
    gains: dict[str, int] = {}
    for signal in closed:
        key = _key_of(signal, kind)
        total[key] = total.get(key, 0) + 1
        if (signal.result_r or 0.0) > 0:
            gains[key] = gains.get(key, 0) + 1
    for trace in traces:
        pertes[_key_of(trace, kind)] = pertes.get(_key_of(trace, kind), 0) + 1

    decisions: list[Decision] = []
    for key, compte in sorted(total.items()):
        if compte < MIN_SAMPLE or gains.get(key, 0) > 0:
            continue
        libelle = "type d'entree" if kind == "entry_type" else "instrument"
        decisions.append(
            Decision(
                key=key,
                kind=kind,
                losses=pertes.get(key, compte),
                message=(
                    f"{libelle} {key} ecarte : {compte} operation(s) denouee(s) "
                    f"sans un seul gain."
                ),
            )
        )
    return decisions


def _key_of(item: object, kind: str) -> str:
    valeur = getattr(item, kind)
    return str(getattr(valeur, "value", valeur))
```

- [ ] **Step 5: Ajouter la lecture des signaux clos**

`_sterile` a besoin des opérations dénouées, pas seulement des pertes. Dans `bridge/app/watcher/repository.py` :

```python
async def closed_signals(
    session: AsyncSession, since: datetime | None = None
) -> list[WatcherSignal]:
    """Signaux reellement denoues : ceux qui portent un resultat."""
    statement = select(WatcherSignal).where(WatcherSignal.result_r.is_not(None))
    if since is not None:
        statement = statement.where(WatcherSignal.created_at >= since)
    result = await session.execute(statement.order_by(WatcherSignal.created_at.desc()))
    return list(result.scalars())
```

- [ ] **Step 6: Brancher sur la boucle d'entretien**

Dans `run_maintenance_once` de `bridge/app/watcher/scheduler.py`, après la purge et dans la même session :

```python
            config = await load_config(session)
            # Une panne d'apprentissage ne doit pas suspendre l'entretien.
            with contextlib.suppress(Exception):
                decisions = await learning.review(session, config)
                for decision in decisions:
                    await self._publisher.publish(session, decision.message, config)
```

Importer `from app.watcher import learning`.

- [ ] **Step 7: Vérifier que tout passe**

Run: `cd bridge && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tous verts.

- [ ] **Step 8: Commit et push**

```bash
git add bridge/app/watcher/learning.py bridge/app/watcher/config.py bridge/app/watcher/repository.py bridge/app/watcher/scheduler.py config/watcher.yaml bridge/tests/test_apprentissage_borne.py
git commit -m "Let the watcher drop what has never once won"
git push origin main
```
