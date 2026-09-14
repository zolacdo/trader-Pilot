"""Suivi des signaux publies (CDC3 sections 31 et 32).

Un signal ne s'arrete pas a sa publication : le systeme continue de le suivre
et annonce ce qui lui arrive — TP atteint, SL touche, invalidation, expiration.
Sans ce module, les statistiques n'existeraient pas et personne ne saurait si
les signaux valent quelque chose.

Le suivi se fait sur les bougies M1 reelles, jamais sur une cotation
instantanee : une cotation dit ou le prix est maintenant, pas ou il est passe
entre deux tours.

Deux choix assumes, tous deux pessimistes :

* quand une meme bougie contient le stop ET un objectif, on retient le stop.
  On ne sait pas lequel a ete touche en premier, et supposer le contraire
  gonflerait artificiellement les statistiques ;
* le resultat est mesure sur position entiere. Un signal qui touche TP1 puis
  revient au stop est compte -1 R, meme si le suivi montre qu'il etait passe
  en gain. Le maximum favorable atteint est conserve a part.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.models.enums import Direction
from app.models.intelligence import Timeframe
from app.services.market_data.engine import MAX_BARS, MarketDataEngine
from app.services.mt5.interface import Candle
from app.watcher import formatter, repository
from app.watcher.config import WatcherConfig
from app.watcher.models import (
    EntryType,
    WatcherSignal,
    WatcherStatus,
)
from app.watcher.publisher import TelegramPublisher

logger = get_logger(__name__)

# Types d'entree qui ne sont pas immediatement en position : il faut que le
# prix vienne chercher le declenchement.
PENDING_ENTRIES = frozenset({EntryType.STOP, EntryType.LIMIT})

# Etapes franchissables, dans l'ordre.
_TARGET_STATUSES = (WatcherStatus.TP1_HIT, WatcherStatus.TP2_HIT, WatcherStatus.TP3_HIT)
_TARGET_RANK = {status: index for index, status in enumerate(_TARGET_STATUSES)}


@dataclass(slots=True)
class SignalUpdate:
    """Changement constate sur un signal."""

    signal: WatcherSignal
    status: WatcherStatus
    price: float | None
    detail: str
    published: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "signalId": self.signal.id,
            "symbol": self.signal.symbol,
            "status": self.status.value,
            "price": self.price,
            "detail": self.detail,
            "published": self.published,
        }


@dataclass(slots=True)
class LifecycleReport:
    """Bilan d'un tour de suivi."""

    checked: int = 0
    updated: int = 0
    closed: int = 0
    published: int = 0
    errors: int = 0
    updates: list[SignalUpdate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "updated": self.updated,
            "closed": self.closed,
            "published": self.published,
            "errors": self.errors,
            "updates": [update.to_dict() for update in self.updates],
        }


class LifecycleTracker:
    """Fait avancer chaque signal ouvert au rythme des bougies reelles."""

    def __init__(self, publisher: TelegramPublisher) -> None:
        self._publisher = publisher

    async def run_once(
        self,
        session: AsyncSession,
        engine: MarketDataEngine,
        config: WatcherConfig,
        now: datetime | None = None,
    ) -> LifecycleReport:
        """Passe en revue tous les signaux encore ouverts."""
        moment = now or utcnow()
        report = LifecycleReport()
        signals = await repository.open_signals(session)
        report.checked = len(signals)

        for signal in signals:
            try:
                updates = await self._advance(session, engine, signal, config, moment)
            except Exception as exc:
                # La panne d'un instrument ne doit pas suspendre le suivi des
                # autres signaux.
                report.errors += 1
                logger.warning("Suivi du signal %s impossible : %s", signal.id, exc)
                continue

            for update in updates:
                report.updated += 1
                if update.status in (
                    WatcherStatus.TP3_HIT,
                    WatcherStatus.SL_HIT,
                    WatcherStatus.INVALIDATED,
                    WatcherStatus.EXPIRED,
                ):
                    report.closed += 1
                if update.published:
                    report.published += 1
                report.updates.append(update)
        return report

    # ------------------------------------------------------------------
    # Avancement d'un signal
    # ------------------------------------------------------------------
    async def _advance(
        self,
        session: AsyncSession,
        engine: MarketDataEngine,
        signal: WatcherSignal,
        config: WatcherConfig,
        now: datetime,
    ) -> list[SignalUpdate]:
        created = as_utc(signal.created_at) or now
        minutes = max(5, int((now - created).total_seconds() // 60) + 5)
        candles = await engine.candles(
            signal.broker_symbol, Timeframe.M1, min(MAX_BARS, minutes)
        )
        relevant = [candle for candle in candles if (as_utc(candle.time) or now) >= created]

        updates: list[SignalUpdate] = []
        if relevant:
            self._update_extremes(signal, relevant)
            transition = self._next_transition(signal, relevant)
            if transition is not None:
                status, price, detail = transition
                updates.append(await self._apply(session, signal, status, price, detail, config))

        # L'expiration ne se constate qu'en l'absence d'autre changement : un
        # signal qui vient de toucher son objectif n'est pas « expire ».
        if not updates and signal.is_open and self._expired(signal, now):
            updates.append(
                await self._apply(
                    session,
                    signal,
                    WatcherStatus.EXPIRED,
                    None,
                    "Duree de validite ecoulee sans declenchement ni objectif atteint.",
                    config,
                )
            )
        if updates:
            session.add(signal)
        return updates

    def _expired(self, signal: WatcherSignal, now: datetime) -> bool:
        expires = as_utc(signal.expires_at)
        return expires is not None and now >= expires

    def _update_extremes(self, signal: WatcherSignal, candles: list[Candle]) -> None:
        """Excursion maximale, en unites de risque, depuis la creation."""
        if signal.risk_distance <= 0:
            return
        buy = signal.direction is Direction.BUY
        best = max(candle.high for candle in candles)
        worst = min(candle.low for candle in candles)
        favourable = (best - signal.entry) if buy else (signal.entry - worst)
        adverse = (signal.entry - worst) if buy else (best - signal.entry)
        signal.max_favorable_r = round(max(signal.max_favorable_r, favourable / signal.risk_distance), 3)
        signal.max_adverse_r = round(max(signal.max_adverse_r, adverse / signal.risk_distance), 3)

    def _next_transition(
        self, signal: WatcherSignal, candles: list[Candle]
    ) -> tuple[WatcherStatus, float | None, str] | None:
        """Premier changement d'etat constate, en parcourant les bougies dans l'ordre."""
        buy = signal.direction is Direction.BUY
        status = signal.status
        pending = signal.entry_type in PENDING_ENTRIES and status in (
            WatcherStatus.CREATED,
            WatcherStatus.CONFIRMED,
        )

        for candle in candles:
            touched_entry = candle.low <= signal.entry <= candle.high
            if pending:
                if touched_entry:
                    return (
                        WatcherStatus.ACTIVE,
                        signal.entry,
                        "Le prix a atteint le niveau de declenchement.",
                    )
                # Tant que l'entree n'est pas touchee, un depassement du stop
                # invalide le scenario : le setup n'existe plus.
                invalidated = candle.low <= signal.stop_loss if buy else candle.high >= signal.stop_loss
                if invalidated:
                    return (
                        WatcherStatus.INVALIDATED,
                        signal.stop_loss,
                        "Le stop a ete franchi avant meme le declenchement de l'entree.",
                    )
                continue

            # En position : le stop prime sur l'objectif dans une meme bougie.
            hit_stop = candle.low <= signal.stop_loss if buy else candle.high >= signal.stop_loss
            if hit_stop:
                return (WatcherStatus.SL_HIT, signal.stop_loss, "Stop loss touche.")

            target = self._next_target(signal, candle, status)
            if target is not None:
                return target
        return None

    def _next_target(
        self, signal: WatcherSignal, candle: Candle, status: WatcherStatus
    ) -> tuple[WatcherStatus, float, str] | None:
        """Prochain objectif franchi, en respectant l'ordre TP1 -> TP2 -> TP3."""
        buy = signal.direction is Direction.BUY
        reached = _TARGET_RANK.get(status, -1)
        rewards = [signal.risk_reward_1, signal.risk_reward_2, signal.risk_reward_3]
        for index, target in enumerate(
            (signal.take_profit_1, signal.take_profit_2, signal.take_profit_3)
        ):
            if target is None or index <= reached:
                continue
            hit = candle.high >= target if buy else candle.low <= target
            if hit:
                reward = rewards[index] if index < len(rewards) else None
                suffix = f" ({reward} R)" if reward else ""
                return (
                    _TARGET_STATUSES[index],
                    target,
                    f"Objectif TP{index + 1} atteint{suffix}.",
                )
            # Les objectifs sont ordonnes : si TP(n) n'est pas atteint,
            # TP(n+1) ne peut pas l'etre.
            break
        return None

    async def _apply(
        self,
        session: AsyncSession,
        signal: WatcherSignal,
        status: WatcherStatus,
        price: float | None,
        detail: str,
        config: WatcherConfig,
    ) -> SignalUpdate:
        """Applique le changement, l'enregistre, et le publie si demande."""
        previous = signal.status
        signal.status = status
        if status in (
            WatcherStatus.TP3_HIT,
            WatcherStatus.SL_HIT,
            WatcherStatus.INVALIDATED,
            WatcherStatus.EXPIRED,
        ):
            signal.closed_at = utcnow()
            signal.result_r = _result_in_r(signal, status, previous)

        if signal.id is not None:
            await repository.add_event(session, signal.id, status, price=price, detail=detail)

        update = SignalUpdate(signal=signal, status=status, price=price, detail=detail)
        if config.send_signal_updates:
            text = formatter.lifecycle_message(signal, status, price, detail)
            result = await self._publisher.publish(session, text, config)
            update.published = result.sent
            if result.sent and signal.id is not None:
                await repository.add_event(
                    session,
                    signal.id,
                    status,
                    price=price,
                    detail="Mise a jour publiee sur Telegram.",
                    published=True,
                )
        logger.info(
            "Signal %s (%s) : %s", signal.id, signal.symbol, status.value
        )
        return update


def _result_in_r(
    signal: WatcherSignal, status: WatcherStatus, previous: WatcherStatus
) -> float | None:
    """Resultat en unites de risque au moment de la cloture.

    Un signal jamais declenche n'a pas de resultat : il rend ``None``, pas
    zero. Compter un signal invalide comme une operation a zero fausserait le
    taux de reussite.

    Un signal qui expire apres avoir touche TP1 ou TP2 garde en revanche le
    gain de l'objectif reellement atteint : l'objectif a bien ete touche, et
    l'oublier sous-estimerait la performance.
    """
    if status is WatcherStatus.SL_HIT:
        return -1.0
    if status is WatcherStatus.TP3_HIT:
        return signal.risk_reward_3 or signal.risk_reward_2 or signal.risk_reward_1
    if status is WatcherStatus.EXPIRED:
        if previous is WatcherStatus.TP2_HIT:
            return signal.risk_reward_2 or signal.risk_reward_1
        if previous is WatcherStatus.TP1_HIT:
            return signal.risk_reward_1
    return None


__all__ = ["LifecycleReport", "LifecycleTracker", "SignalUpdate"]
