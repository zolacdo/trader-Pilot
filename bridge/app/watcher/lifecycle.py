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
* le resultat suit la gestion reellement appliquee. Les memes reglages que
  ``position_manager`` -- fermeture partielle aux objectifs, break even sur
  TP1 -- sont lus ici, et un signal qui touche TP1 puis revient au stop garde
  le gain encaisse au lieu d'etre compte -1 R. Mesurer « sur position
  entiere » decrivait une strategie sans sortie partielle, qui n'est plus
  celle qui s'execute. Le maximum favorable atteint est conserve a part.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import RiskSettings, as_utc, utcnow
from app.models.enums import BreakEvenTrigger, Direction, MultiTpStrategy
from app.models.intelligence import Timeframe
from app.repositories import settings_repo
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
        # Les memes reglages que ``position_manager`` : le suivi ne doit
        # jamais pouvoir compter autrement que ce que le courtier execute.
        risk = await settings_repo.get_risk_settings(session)
        signals = await repository.open_signals(session)
        report.checked = len(signals)

        for signal in signals:
            try:
                updates = await self._advance(session, engine, signal, config, moment, risk)
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
        risk: RiskSettings,
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
                updates.append(
                    await self._apply(session, signal, status, price, detail, config, risk)
                )

        # L'expiration ne se constate qu'en l'absence d'autre changement : un
        # signal qui vient de toucher son objectif n'est pas « expire ».
        if not updates and signal.is_open and self._expired(signal, now):
            # Une position encore ouverte se termine au dernier cours connu.
            # Sans ce prix, le message d'expiration ne dit ni ou le signal
            # s'arrete ni ce qu'il rapporte.
            en_position = not _pending(signal, signal.status)
            sortie = relevant[-1].close if relevant and en_position else None
            detail = (
                "Duree de validite ecoulee : position close au dernier cours."
                if en_position
                else "Duree de validite ecoulee sans que l'entree soit declenchee."
            )
            updates.append(
                await self._apply(
                    session, signal, WatcherStatus.EXPIRED, sortie, detail, config, risk
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
        pending = _pending(signal, status)

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
        risk: RiskSettings,
    ) -> SignalUpdate:
        """Applique le changement, l'enregistre, et le publie si demande."""
        previous = signal.status
        signal.status = status

        # Un objectif franchi n'est pas qu'une annonce : la position reelle y
        # encaisse sa tranche et voit son stop remonter. Le suivi fait de meme,
        # sinon il compte une perte pleine sur un gain deja protege.
        if status in _TARGET_STATUSES and price is not None:
            _book_partial(signal, status, price, risk)
            _arm_break_even(signal, risk)
        if status in (
            WatcherStatus.TP3_HIT,
            WatcherStatus.SL_HIT,
            WatcherStatus.INVALIDATED,
            WatcherStatus.EXPIRED,
        ):
            signal.closed_at = utcnow()
            signal.result_r = _result_in_r(signal, status, previous, price)

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


def _pending(signal: WatcherSignal, status: WatcherStatus) -> bool:
    """Vrai tant que le prix n'est pas venu chercher le declenchement."""
    return signal.entry_type in PENDING_ENTRIES and status in (
        WatcherStatus.CREATED,
        WatcherStatus.CONFIRMED,
    )


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
    offset = risk.break_even_offset_points * (10.0**-signal.digits)
    buy = signal.direction is Direction.BUY
    cible = (
        round(signal.entry + offset, signal.digits)
        if buy
        else round(signal.entry - offset, signal.digits)
    )
    deja_protecteur = (cible <= signal.stop_loss) if buy else (cible >= signal.stop_loss)
    if deja_protecteur:
        return
    signal.stop_loss = cible


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


__all__ = ["LifecycleReport", "LifecycleTracker", "SignalUpdate"]
