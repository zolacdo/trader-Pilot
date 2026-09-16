"""Acces aux donnees du Market Watcher.

Ce module n'ECRIT que dans les tables ``watcher_*``. C'est ce qui garantit
qu'un defaut du sous-systeme ne peut rien abimer du Bridge existant.

Une seule exception, en lecture seule et volontairement isolee dans
``matching_trade`` : le post-mortem d'une perte a besoin de la position reelle,
car c'est elle qui dit ce que l'argent a fait -- la comptabilite du suivi, non.
Lire ne menace rien ; aucune autre fonction ne sort des tables du watcher.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func

# Meme convention que les autres depots du Bridge : on annote la session
# SQLAlchemy, qui est celle que FastAPI injecte, tout en appelant ``exec()``
# fourni par la sous-classe SQLModel reellement construite a l'execution.
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import as_utc, utcnow
from app.models.enums import Direction
from app.watcher.models import (
    OPEN_STATUSES,
    RiskVerdict,
    VolatilityLevel,
    WatcherAnalysis,
    WatcherDecision,
    WatcherPostMortem,
    WatcherSignal,
    WatcherSignalEvent,
    WatcherStatus,
)
from app.watcher.risk import PortfolioState

MAX_PAGE = 200


# ---------------------------------------------------------------------------
# Signaux
# ---------------------------------------------------------------------------
async def add_signal(session: AsyncSession, signal: WatcherSignal) -> WatcherSignal:
    session.add(signal)
    await session.flush()
    return signal


async def get_signal(session: AsyncSession, signal_id: int) -> WatcherSignal | None:
    return await session.get(WatcherSignal, signal_id)


async def open_signals(
    session: AsyncSession, symbol: str | None = None
) -> list[WatcherSignal]:
    """Signaux encore suivis par la boucle de cycle de vie."""
    statement = select(WatcherSignal).where(
        WatcherSignal.status.in_(tuple(OPEN_STATUSES))  # type: ignore[attr-defined]
    )
    if symbol:
        statement = statement.where(WatcherSignal.symbol == symbol.strip().upper())
    statement = statement.order_by(WatcherSignal.created_at.asc())  # type: ignore[attr-defined]
    result = await session.exec(statement)
    return list(result.all())


async def list_signals(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    direction: Direction | None = None,
    status: WatcherStatus | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WatcherSignal]:
    statement = select(WatcherSignal)
    if symbol:
        statement = statement.where(WatcherSignal.symbol == symbol.strip().upper())
    if direction is not None:
        statement = statement.where(WatcherSignal.direction == direction)
    if status is not None:
        statement = statement.where(WatcherSignal.status == status)
    if since is not None:
        statement = statement.where(WatcherSignal.created_at >= since)
    statement = (
        statement.order_by(WatcherSignal.created_at.desc())  # type: ignore[attr-defined]
        .offset(max(0, offset))
        .limit(max(1, min(limit, MAX_PAGE)))
    )
    result = await session.exec(statement)
    return list(result.all())


async def signals_since(
    session: AsyncSession,
    since: datetime,
    shadow: bool = False,
    strategy_version: str | None = None,
) -> list[WatcherSignal]:
    """Tous les signaux crees depuis une date, clos ou non (statistiques).

    ``shadow`` choisit la population. Les deux ne se melangent jamais dans un
    meme bilan : une moyenne qui confond ce qui a ete joue et ce qui n'a ete
    que mesure ne decrit ni l'un ni l'autre.

    ``strategy_version`` restreint aux signaux mesures par la comptabilite
    courante, pour les memes raisons que ``closed_signals``.
    """
    statement = (
        select(WatcherSignal)
        .where(WatcherSignal.created_at >= since)
        .where(WatcherSignal.shadow.is_(shadow))  # type: ignore[union-attr]
    )
    if strategy_version is not None:
        statement = statement.where(WatcherSignal.strategy_version == strategy_version)
    result = await session.exec(
        statement.order_by(WatcherSignal.created_at.asc())  # type: ignore[attr-defined]
    )
    return list(result.all())


async def count_signals_since(
    session: AsyncSession, since: datetime, shadow: bool = False
) -> int:
    """Signaux d'une population depuis cette date, jamais les deux melangees."""
    result = await session.exec(
        select(func.count())
        .select_from(WatcherSignal)
        .where(WatcherSignal.created_at >= since)
        .where(WatcherSignal.shadow.is_(shadow))  # type: ignore[union-attr]
    )
    return int(result.one() or 0)


async def last_signal_at(
    session: AsyncSession, symbol: str, shadow: bool = False
) -> datetime | None:
    """Date du dernier signal de cette population sur cet instrument.

    Elle sert a tenir la cadence : un fantome ne doit pas faire croire qu'un
    vrai signal vient de partir, ni l'inverse.
    """
    result = await session.exec(
        select(WatcherSignal.created_at)
        .where(WatcherSignal.symbol == symbol.strip().upper())
        .where(WatcherSignal.shadow.is_(shadow))  # type: ignore[union-attr]
        .order_by(WatcherSignal.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return as_utc(result.first())


def _start_of_day(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def portfolio_state(
    session: AsyncSession,
    symbol: str,
    direction: Direction,
    now: datetime | None = None,
    shadow: bool = False,
) -> PortfolioState:
    """Etat courant du watcher, tel que le Risk Manager en a besoin.

    Les deux populations ont chacune leur propre etat, et ne se voient jamais.
    Un fantome compte dans l'anti-doublon des fantomes, jamais dans celui des
    vrais signaux : le melanger etoufferait la decision qu'il sert a eclairer,
    et l'oublier tout court ferait renaitre un fantome par tour de 90 secondes
    sur le meme setup.
    """
    moment = now or utcnow()
    canonical = symbol.strip().upper()
    opened = [item for item in await open_signals(session) if item.shadow is shadow]
    same_symbol = [item for item in opened if item.symbol == canonical]
    return PortfolioState(
        active_signals=len(opened),
        signals_today=await count_signals_since(session, _start_of_day(moment), shadow=shadow),
        active_same_symbol=len(same_symbol),
        active_same_direction=any(item.direction is direction for item in same_symbol),
        last_signal_at=await last_signal_at(session, canonical, shadow=shadow),
    )


# ---------------------------------------------------------------------------
# Evenements du cycle de vie
# ---------------------------------------------------------------------------
async def add_event(
    session: AsyncSession,
    signal_id: int,
    kind: WatcherStatus,
    price: float | None = None,
    detail: str | None = None,
    published: bool = False,
) -> WatcherSignalEvent:
    event = WatcherSignalEvent(
        signal_id=signal_id,
        kind=kind,
        price=price,
        detail=detail[:500] if detail else None,
        published=published,
    )
    session.add(event)
    await session.flush()
    return event


async def events_for(session: AsyncSession, signal_id: int) -> list[WatcherSignalEvent]:
    result = await session.exec(
        select(WatcherSignalEvent)
        .where(WatcherSignalEvent.signal_id == signal_id)
        .order_by(WatcherSignalEvent.created_at.asc())  # type: ignore[attr-defined]
    )
    return list(result.all())


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------
async def record_analysis(
    session: AsyncSession,
    *,
    symbol: str,
    decision: WatcherDecision,
    score: float,
    bias: str,
    price: float | None,
    volatility: VolatilityLevel,
    risk_verdict: RiskVerdict,
    blocked_reason: str | None = None,
    signal_id: int | None = None,
    watch_trigger: str | None = None,
    alert_sent: bool = False,
) -> WatcherAnalysis:
    analysis = WatcherAnalysis(
        symbol=symbol.strip().upper(),
        decision=decision,
        score=round(float(score), 2),
        bias=bias,
        price=price,
        volatility=volatility,
        risk_verdict=risk_verdict,
        blocked_reason=blocked_reason[:300] if blocked_reason else None,
        signal_id=signal_id,
        watch_trigger=watch_trigger[:200] if watch_trigger else None,
        alert_sent=alert_sent,
    )
    session.add(analysis)
    await session.flush()
    return analysis


async def last_analysis(session: AsyncSession, symbol: str) -> WatcherAnalysis | None:
    result = await session.exec(
        select(WatcherAnalysis)
        .where(WatcherAnalysis.symbol == symbol.strip().upper())
        .order_by(WatcherAnalysis.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return result.first()


async def latest_analyses(session: AsyncSession, limit: int = 50) -> list[WatcherAnalysis]:
    """Derniere analyse connue par instrument, la plus recente en tete."""
    result = await session.exec(
        select(WatcherAnalysis)
        .order_by(WatcherAnalysis.created_at.desc())  # type: ignore[attr-defined]
        .limit(max(1, min(limit, MAX_PAGE)) * 4)
    )
    seen: dict[str, WatcherAnalysis] = {}
    for analysis in result.all():
        seen.setdefault(analysis.symbol, analysis)
    return list(seen.values())[: max(1, min(limit, MAX_PAGE))]


async def last_watch_alert_at(session: AsyncSession, symbol: str) -> datetime | None:
    """Date de la derniere alerte WATCH reellement envoyee pour cet instrument."""
    result = await session.exec(
        select(WatcherAnalysis.created_at)
        .where(WatcherAnalysis.symbol == symbol.strip().upper())
        .where(WatcherAnalysis.alert_sent == True)
        .order_by(WatcherAnalysis.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return as_utc(result.first())


# Seules ces deux decisions ouvrent une surveillance.
_DECISIONS_DE_SURVEILLANCE = (WatcherDecision.WATCH_BUY, WatcherDecision.WATCH_SELL)


async def watch_still_open(session: AsyncSession, symbol: str) -> str | None:
    """La derniere surveillance annoncee sur cet instrument tient-elle encore ?

    Une surveillance n'est pas un evenement ponctuel : elle dit « ce marche
    approche d'un declencheur, je le suis ». Tant que le marche reste dans cet
    etat, repeter l'annonce n'apprend rien et noie le canal -- BTCUSD est reste
    en WATCH_BUY sans interruption de 05:31 a 06:07, une analyse toutes les
    90 secondes.

    La surveillance est consideree comme close des qu'une analyse posterieure
    a conclu autre chose : le marche a franchi son declencheur, ou il est
    retombe, ou il a change de sens. Rend la decision encore ouverte, sinon
    ``None``.
    """
    canonique = symbol.strip().upper()
    # ``alert_sent`` est vrai pour TOUTE publication, y compris celle d'un
    # signal. Sans ce filtre, un signal publie passait pour une surveillance
    # ouverte : le tour suivant annoncait une « surveillance levee » qui
    # n'avait jamais commence.
    result = await session.exec(
        select(WatcherAnalysis)
        .where(WatcherAnalysis.symbol == canonique)
        .where(WatcherAnalysis.alert_sent == True)
        .where(WatcherAnalysis.decision.in_(_DECISIONS_DE_SURVEILLANCE))  # type: ignore[attr-defined]
        .order_by(WatcherAnalysis.created_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    derniere = result.first()
    if derniere is None:
        return None

    # Une seule analyse ayant conclu autrement suffit a clore la surveillance.
    suite = await session.exec(
        select(WatcherAnalysis.id)
        .where(WatcherAnalysis.symbol == canonique)
        .where(WatcherAnalysis.created_at > derniere.created_at)
        .where(WatcherAnalysis.decision != derniere.decision)
        .limit(1)
    )
    if suite.first() is not None:
        return None
    return str(derniere.decision.value if hasattr(derniere.decision, "value") else derniere.decision)


async def purge_analyses(session: AsyncSession, older_than: datetime) -> int:
    """Efface les traces d'analyse trop anciennes pour servir a la calibration."""
    result = await session.exec(
        select(WatcherAnalysis).where(WatcherAnalysis.created_at < older_than)
    )
    rows = list(result.all())
    for row in rows:
        await session.delete(row)
    return len(rows)


async def stats_snapshot(session: AsyncSession, days: int = 30) -> dict[str, Any]:
    """Comptages bruts, utiles au diagnostic et a l'API."""
    since = utcnow() - timedelta(days=max(1, days))
    signals = await signals_since(session, since)
    opened = [item for item in signals if item.is_open]
    return {
        "windowDays": days,
        "total": len(signals),
        "open": len(opened),
        "closed": len(signals) - len(opened),
    }


# ---------------------------------------------------------------------------
# Post-mortem des pertes (CDC3 section 41)
# ---------------------------------------------------------------------------
# Au-dela de ce ratio, un critere portait la decision ; en dessous de l'autre,
# il alertait sans etre ecoute. Entre les deux, il n'apprend rien.
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


async def matching_trade(session: AsyncSession, signal: WatcherSignal) -> Any | None:
    """Position reelle nee de ce signal, si elle existe.

    L'appariement se fait sur le symbole courtier, le sens, et une fenetre qui
    commence a la creation du signal : le watcher ne pose pas de reference
    croisee sur ``trades``, et une position ouverte avant le signal ne peut pas
    en venir. La premiere position qui suit est la bonne -- le watcher ne
    publie jamais deux signaux de meme sens sur un instrument tant que le
    precedent vit.

    L'import est local : ``models.trading`` n'a pas a devenir une dependance de
    module du watcher pour une seule lecture.
    """
    from app.models.trading import TradeRecord

    depuis = as_utc(signal.created_at) or utcnow()
    statement = (
        select(TradeRecord)
        .where(TradeRecord.symbol == signal.broker_symbol)
        .where(TradeRecord.direction == signal.direction)
        .where(TradeRecord.opened_at >= depuis)
        .order_by(TradeRecord.opened_at.asc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return await session.scalar(statement)


async def closed_trades_since(session: AsyncSession, since: datetime) -> list[Any]:
    """Positions closes de la fenetre, triees par ouverture.

    Meme exception en lecture seule que ``matching_trade``, et pour la meme
    raison : savoir ce que l'argent a fait demande de lire ``trades``. Une
    seule requete sert tous les signaux -- une par signal ferait N requetes
    pour une question globale.
    """
    from app.models.enums import PositionState
    from app.models.trading import TradeRecord

    statement = (
        select(TradeRecord)
        .where(TradeRecord.state == PositionState.CLOSED)
        .where(TradeRecord.opened_at >= since)
        .order_by(TradeRecord.opened_at.asc())  # type: ignore[attr-defined]
    )
    result = await session.execute(statement)
    return list(result.scalars())


async def record_post_mortem(
    session: AsyncSession,
    signal: WatcherSignal,
    trade: Any | None = None,
) -> WatcherPostMortem | None:
    """Analyse une perte, une seule fois. Rend ``None`` s'il n'y a rien a analyser."""
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


async def post_mortems(
    session: AsyncSession, since: datetime | None = None
) -> list[WatcherPostMortem]:
    """Post-mortems, du plus recent au plus ancien."""
    statement = select(WatcherPostMortem)
    if since is not None:
        statement = statement.where(WatcherPostMortem.created_at >= since)
    result = await session.execute(
        statement.order_by(WatcherPostMortem.created_at.desc())  # type: ignore[attr-defined]
    )
    return list(result.scalars())


async def closed_signals(
    session: AsyncSession,
    since: datetime | None = None,
    strategy_version: str | None = None,
    shadow: bool = False,
) -> list[WatcherSignal]:
    """Signaux reellement denoues : ceux qui portent un resultat.

    ``strategy_version`` restreint aux signaux mesures par la comptabilite
    courante. Deux versions ne comptent pas pareil : melanger leurs resultats
    donnerait une moyenne qui ne decrit aucune des deux.

    ``shadow`` choisit la population : les vrais signaux par defaut, les
    fantomes quand on veut mesurer la bande qu'ils explorent.
    """
    statement = (
        select(WatcherSignal)
        .where(WatcherSignal.result_r.is_not(None))  # type: ignore[union-attr]
        .where(WatcherSignal.shadow.is_(shadow))  # type: ignore[union-attr]
    )
    if since is not None:
        statement = statement.where(WatcherSignal.created_at >= since)
    if strategy_version is not None:
        statement = statement.where(WatcherSignal.strategy_version == strategy_version)
    result = await session.execute(
        statement.order_by(WatcherSignal.created_at.desc())  # type: ignore[attr-defined]
    )
    return list(result.scalars())


__all__ = [
    "add_event",
    "add_signal",
    "closed_signals",
    "closed_trades_since",
    "count_signals_since",
    "events_for",
    "get_signal",
    "last_analysis",
    "last_signal_at",
    "last_watch_alert_at",
    "latest_analyses",
    "list_signals",
    "matching_trade",
    "open_signals",
    "portfolio_state",
    "post_mortems",
    "purge_analyses",
    "record_analysis",
    "record_post_mortem",
    "signals_since",
    "stats_snapshot",
    "watch_still_open",
]
