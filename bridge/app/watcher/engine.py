"""Moteur de decision du Market Watcher (CDC3 sections 23, 25 et 64).

L'enchainement est toujours le meme, et dans cet ordre :

    donnees de marche reelles
      -> analyse deterministe
      -> niveaux calcules
      -> score sur 100
      -> Risk Manager (droit de veto)
      -> lecture IA (commentaire seulement, si le score le justifie)
      -> decision
      -> publication

L'IA arrive apres les niveaux et avant le Risk Manager dans la lecture, mais
elle n'a de pouvoir sur ni l'un ni l'autre : elle commente. Le Risk Manager,
lui, peut annuler un signal que tout le reste approuve.

Un verrou par instrument empeche deux analyses simultanees du meme symbole
(CDC3 section 78).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.models.enums import Direction
from app.services.market_data.engine import MarketDataEngine
from app.services.technical_analysis.multi_timeframe import STATE_NO_DATA
from app.watcher import ai as ai_module
from app.watcher import formatter, repository, risk
from app.watcher.analysis.context import MarketContext, build_context
from app.watcher.config import WatcherConfig
from app.watcher.execution import ExecutionReport, execute_signal
from app.watcher.levels import TradeLevels, build_levels
from app.watcher.models import (
    STRATEGY_VERSION,
    RiskVerdict,
    WatcherDecision,
    WatcherSignal,
    WatcherStatus,
)
from app.watcher.publisher import PublishResult, TelegramPublisher
from app.watcher.scoring import ScoreCard, score_direction

logger = get_logger(__name__)


@dataclass(slots=True)
class AnalysisOutcome:
    """Resultat complet d'un tour d'analyse sur un instrument."""

    symbol: str
    decision: WatcherDecision = WatcherDecision.NO_TRADE
    context: MarketContext | None = None
    card: ScoreCard | None = None
    levels: TradeLevels | None = None
    risk_decision: risk.RiskDecision = field(default_factory=risk.RiskDecision)
    ai_reading: ai_module.AIReading = field(default_factory=ai_module.AIReading)
    signal: WatcherSignal | None = None
    publication: PublishResult | None = None
    execution: ExecutionReport | None = None
    detail: str = ""

    @property
    def published(self) -> bool:
        return self.publication is not None and self.publication.sent

    @property
    def score(self) -> float:
        return self.card.score if self.card is not None else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "decision": self.decision.value,
            "score": round(self.score, 1),
            "detail": self.detail,
            "risk": self.risk_decision.to_dict(),
            "levels": self.levels.to_dict() if self.levels else None,
            "scoreBreakdown": self.card.breakdown() if self.card else None,
            "ai": self.ai_reading.to_dict(),
            "signal": self.signal.to_dict() if self.signal else None,
            "publication": self.publication.to_dict() if self.publication else None,
            "execution": self.execution.to_dict() if self.execution else None,
            "context": self.context.summary() if self.context else None,
        }


class WatcherEngine:
    """Transforme un instrument en decision, et une decision en message."""

    def __init__(self, publisher: TelegramPublisher) -> None:
        self._publisher = publisher
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, symbol: str) -> asyncio.Lock:
        """Verrou par instrument, cree a la demande.

        Il ne peut pas etre cree dans le constructeur : le moteur est
        construit avant qu'aucune boucle asyncio n'existe.
        """
        lock = self._locks.get(symbol)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[symbol] = lock
        return lock

    # ------------------------------------------------------------------
    # Un tour complet sur un instrument
    # ------------------------------------------------------------------
    async def analyse(
        self,
        session: AsyncSession,
        engine: MarketDataEngine,
        symbol: str,
        broker_symbol: str,
        config: WatcherConfig,
        now: datetime | None = None,
    ) -> AnalysisOutcome:
        """Analyse, decide, enregistre, et publie si toutes les regles passent."""
        canonical = symbol.strip().upper()
        async with self._lock(canonical):
            return await self._analyse(session, engine, canonical, broker_symbol, config, now)

    async def _analyse(
        self,
        session: AsyncSession,
        engine: MarketDataEngine,
        symbol: str,
        broker_symbol: str,
        config: WatcherConfig,
        now: datetime | None,
    ) -> AnalysisOutcome:
        moment = now or utcnow()
        outcome = AnalysisOutcome(symbol=symbol)
        context = await build_context(session, engine, symbol, broker_symbol, config, moment)
        outcome.context = context

        if not context.usable:
            # Un marche ferme explique a lui seul des bougies anciennes : le
            # dire ainsi evite de faire passer une seance fermee pour une
            # panne de donnees.
            motif = (
                f"Marche ferme sur {symbol} : {context.quality.detail}"
                if context.market_open is False
                else context.quality.detail
            )
            outcome.detail = motif
            outcome.risk_decision = risk.RiskDecision(
                verdict=RiskVerdict.REJECTED, reasons=[motif]
            )
            await self._record(session, outcome, context, moment)
            return outcome

        # Les deux sens sont evalues : le marche n'a pas a etre haussier pour
        # etre lisible, et forcer un sens produirait des signaux de complaisance.
        best_direction, card, levels = self._best_direction(context, config)
        outcome.card = card
        outcome.levels = levels

        state = await repository.portfolio_state(session, symbol, best_direction, moment)
        outcome.risk_decision = risk.evaluate(
            context, best_direction, levels, card, config, state, moment
        )

        outcome.decision = self._decide(outcome.risk_decision, card, best_direction, config)
        outcome.detail = self._explain(outcome)

        # Une surveillance annoncee a promis « le signal sera reevalue a la
        # confirmation ». Si le marche s'en eloigne, il faut le dire : sinon la
        # promesse reste sans suite et on ignore si le systeme attend encore.
        await self._close_open_watch(session, context, outcome, config)

        if outcome.decision.is_tradable and levels is not None and card is not None:
            outcome.ai_reading = await ai_module.review(
                context, best_direction, levels, card, config
            )
            outcome.signal = await self._create_signal(
                session, context, best_direction, levels, card, outcome, config, moment
            )
            outcome.publication = await self._publish_signal(session, outcome, config)
        elif outcome.decision.is_watch and config.send_watch_alerts:
            outcome.publication = await self._publish_watch(
                session, context, card, config, moment, outcome.decision
            )

        await self._record(session, outcome, context, moment)
        return outcome

    # ------------------------------------------------------------------
    # Choix du sens et de la decision
    # ------------------------------------------------------------------
    def _best_direction(
        self, context: MarketContext, config: WatcherConfig
    ) -> tuple[Direction, ScoreCard, TradeLevels | None]:
        """Evalue BUY puis SELL et garde le mieux note.

        A egalite, c'est le biais multi-timeframe qui tranche : sans lui, un
        marche parfaitement indecis basculerait au hasard d'un tour a l'autre.
        """
        results: list[tuple[Direction, ScoreCard, TradeLevels]] = []
        for direction in (Direction.BUY, Direction.SELL):
            levels = build_levels(context, direction, config.minimum_rr)
            card = score_direction(context, direction, levels, config)
            results.append((direction, card, levels))

        bias = context.bias.value
        def rank(item: tuple[Direction, ScoreCard, TradeLevels]) -> tuple[float, int]:
            direction, card, _ = item
            aligned = (
                (bias == "BULLISH" and direction is Direction.BUY)
                or (bias == "BEARISH" and direction is Direction.SELL)
            )
            return (card.score, 1 if aligned else 0)

        direction, card, levels = max(results, key=rank)
        return direction, card, levels

    def _decide(
        self,
        verdict: risk.RiskDecision,
        card: ScoreCard | None,
        direction: Direction,
        config: WatcherConfig,
    ) -> WatcherDecision:
        """Traduit score et verdict en une des huit decisions (CDC3 section 23)."""
        if card is None:
            return WatcherDecision.NO_TRADE
        buy = direction is Direction.BUY

        if verdict.verdict is RiskVerdict.REJECTED:
            return WatcherDecision.NO_TRADE
        if verdict.verdict is RiskVerdict.WAIT:
            # Le setup est presque la : on le met sous surveillance plutot que
            # de l'oublier (CDC3 section 69).
            if card.score >= config.watch_score:
                return WatcherDecision.WATCH_BUY if buy else WatcherDecision.WATCH_SELL
            return WatcherDecision.WAIT
        if card.score >= config.strong_score:
            return WatcherDecision.STRONG_BUY if buy else WatcherDecision.STRONG_SELL
        if card.score >= config.minimum_score:
            return WatcherDecision.BUY if buy else WatcherDecision.SELL
        if card.score >= config.watch_score:
            return WatcherDecision.WATCH_BUY if buy else WatcherDecision.WATCH_SELL
        return WatcherDecision.NO_TRADE

    def _explain(self, outcome: AnalysisOutcome) -> str:
        """Phrase courte resumant la decision, affichee dans l'API et les logs."""
        card = outcome.card
        score = f"score {round(card.score, 1)}/100" if card else "score indisponible"
        if outcome.risk_decision.reasons:
            return f"{outcome.decision.value} ({score}) — {outcome.risk_decision.reasons[0]}"
        grade = card.grade() if card else "-"
        return f"{outcome.decision.value} ({score}, {grade})"

    # ------------------------------------------------------------------
    # Enregistrement et publication
    # ------------------------------------------------------------------
    async def _create_signal(
        self,
        session: AsyncSession,
        context: MarketContext,
        direction: Direction,
        levels: TradeLevels,
        card: ScoreCard,
        outcome: AnalysisOutcome,
        config: WatcherConfig,
        now: datetime,
    ) -> WatcherSignal:
        """Enregistre le signal. Les niveaux sont ceux du calcul, pas ceux de l'IA."""
        reasons = [levels.entry_reason, levels.stop_reason, *levels.target_reasons]
        reasons.extend(card.reasons)
        risks = list(card.risks)
        risks.extend(outcome.ai_reading.risks)
        if outcome.ai_reading.available and outcome.ai_reading.opinion is not None:
            opinion = outcome.ai_reading.opinion
            if not opinion.agrees_with(direction):
                risks.append(
                    f"Lecture IA en desaccord : elle recommande {opinion.recommendation}."
                )

        digits = context.symbol_info.digits if context.symbol_info is not None else 5
        signal = WatcherSignal(
            symbol=context.symbol,
            broker_symbol=context.broker_symbol,
            direction=direction,
            decision=outcome.decision,
            status=WatcherStatus.CREATED,
            timeframe=context.primary_timeframe.value if context.primary_timeframe else "",
            entry_type=levels.entry_type,
            entry=levels.entry,
            stop_loss=levels.stop_loss,
            digits=digits,
            take_profit_1=levels.take_profit_1,
            take_profit_2=levels.take_profit_2,
            take_profit_3=levels.take_profit_3,
            risk_distance=levels.risk_distance,
            risk_reward_1=levels.risk_rewards[0] if len(levels.risk_rewards) > 0 else None,
            risk_reward_2=levels.risk_rewards[1] if len(levels.risk_rewards) > 1 else None,
            risk_reward_3=levels.risk_rewards[2] if len(levels.risk_rewards) > 2 else None,
            score=card.score,
            score_breakdown=card.breakdown(),
            confidence=card.confidence,
            timeframe_states=_timeframe_states(context),
            reasons=[item for item in reasons if item][:12],
            risks=[item for item in risks if item][:10],
            context=context.summary(),
            invalidation=levels.invalidation,
            ai_comment=outcome.ai_reading.comment,
            ai_provider=outcome.ai_reading.provider,
            strategy_version=STRATEGY_VERSION,
            created_at=now,
            expires_at=now + timedelta(minutes=max(1, config.signal_ttl_minutes)),
        )
        await repository.add_signal(session, signal)
        if signal.id is not None:
            await repository.add_event(
                session,
                signal.id,
                WatcherStatus.CREATED,
                price=levels.entry,
                detail=outcome.detail,
            )
        return signal

    async def _publish_signal(
        self, session: AsyncSession, outcome: AnalysisOutcome, config: WatcherConfig
    ) -> PublishResult:
        signal = outcome.signal
        if signal is None:
            return PublishResult(reason="Aucun signal a publier.")
        text = formatter.signal_message(
            signal, simple=config.simple_format, auto_trade=config.auto_trade
        )
        result = await self._publisher.publish(session, text, config)

        # L'execution ne depend pas de la publication : un canal injoignable
        # ne doit pas empecher de prendre la position. L'identifiant du message
        # n'est transmis que s'il existe vraiment, car il sert de cle
        # d'idempotence face a l'ecoute Telegram.
        target = self._publisher.target
        outcome.execution = await execute_signal(
            session,
            text,
            config,
            telegram_channel_id=target.identifier if target else None,
            message_id=result.message_id if result.sent else None,
        )

        if result.sent:
            signal.published_at = utcnow()
            signal.telegram_message_id = result.message_id
            signal.status = WatcherStatus.CONFIRMED
            session.add(signal)
            if signal.id is not None:
                await repository.add_event(
                    session,
                    signal.id,
                    WatcherStatus.CONFIRMED,
                    price=signal.entry,
                    detail="Signal publie sur Telegram.",
                    published=True,
                )
        return result

    async def _close_open_watch(
        self,
        session: AsyncSession,
        context: MarketContext,
        outcome: AnalysisOutcome,
        config: WatcherConfig,
    ) -> None:
        """Annonce la fin d'une surveillance qui n'a pas abouti.

        Appelee AVANT l'enregistrement de l'analyse en cours : le depot voit
        donc encore l'etat precedent, et la comparaison avec la decision du
        moment designe exactement le tour ou la surveillance se termine. Un
        seul message par surveillance, jamais un par cycle.

        Les DEUX issues sont annoncees. Une surveillance qui aboutit dit qu'elle
        a ete confirmee, juste avant que le signal ne parte ; une surveillance
        qui echoue dit que le declencheur n'a pas ete touche. Sans cela, rien
        ne reliait un signal a la surveillance qui l'avait annonce.
        """
        if not config.send_watch_alerts:
            return
        en_cours = await repository.watch_still_open(session, context.symbol)
        if en_cours is None or en_cours == outcome.decision.value:
            return

        sens = Direction.SELL if en_cours == WatcherDecision.WATCH_SELL.value else Direction.BUY
        analysis = context.primary
        seuil = None
        if analysis is not None:
            seuil = (
                analysis.levels.support
                if sens is Direction.SELL
                else analysis.levels.resistance
            )
        digits = context.symbol_info.digits if context.symbol_info is not None else 5

        if outcome.decision.is_tradable:
            texte = formatter.watch_confirmed_message(
                symbol=context.symbol,
                direction=sens,
                trigger=seuil,
                current_price=context.price,
                digits=digits,
            )
        else:
            texte = formatter.watch_closed_message(
                symbol=context.symbol,
                direction=sens,
                trigger=seuil,
                current_price=context.price,
                digits=digits,
                reason=outcome.detail,
            )
        await self._publisher.publish(session, texte, config)

    async def _publish_watch(
        self,
        session: AsyncSession,
        context: MarketContext,
        card: ScoreCard | None,
        config: WatcherConfig,
        now: datetime,
        decision: WatcherDecision | None = None,
    ) -> PublishResult:
        """Alerte de surveillance : une seule a la fois par instrument.

        Deux garde-fous se completent. Le premier est un etat : tant que la
        surveillance precedente n'a pas conclu, on la suit au lieu d'en ouvrir
        une autre sur le meme marche. Le second est un delai, qui evite deux
        annonces rapprochees lorsque le marche oscille autour du declencheur.
        """
        en_cours = await repository.watch_still_open(session, context.symbol)
        if en_cours is not None:
            return PublishResult(
                reason=(
                    f"Surveillance {en_cours} deja en cours sur {context.symbol} : "
                    "elle est suivie jusqu'a sa conclusion."
                )
            )

        last = await repository.last_watch_alert_at(session, context.symbol)
        if last is not None and config.watch_alert_cooldown_minutes > 0:
            elapsed = now - (as_utc(last) or last)
            if elapsed < timedelta(minutes=config.watch_alert_cooldown_minutes):
                return PublishResult(
                    reason=(
                        "Alerte de surveillance deja envoyee il y a "
                        f"{int(elapsed.total_seconds() // 60)} minute(s)."
                    )
                )

        analysis = context.primary
        digits = context.symbol_info.digits if context.symbol_info is not None else 5
        text = formatter.watch_message(
            symbol=context.symbol,
            current_price=context.price,
            score=card.score if card else 0.0,
            buy_trigger=analysis.levels.resistance if analysis is not None else None,
            sell_trigger=analysis.levels.support if analysis is not None else None,
            digits=digits,
            detail=card.reasons[0] if card and card.reasons else "",
            direction=(
                Direction.SELL if decision is WatcherDecision.WATCH_SELL else Direction.BUY
            ),
        )
        return await self._publisher.publish(session, text, config)

    async def _record(
        self,
        session: AsyncSession,
        outcome: AnalysisOutcome,
        context: MarketContext,
        now: datetime,
    ) -> None:
        """Trace l'analyse, publiee ou non (CDC3 sections 69 et 82)."""
        analysis = context.primary
        trigger: str | None = None
        if outcome.decision.is_watch and analysis is not None:
            level = (
                analysis.levels.resistance
                if outcome.decision is WatcherDecision.WATCH_BUY
                else analysis.levels.support
            )
            if level is not None:
                sens = "au-dessus de" if outcome.decision is WatcherDecision.WATCH_BUY else "sous"
                trigger = f"Confirmation {sens} {level}"

        await repository.record_analysis(
            session,
            symbol=context.symbol,
            decision=outcome.decision,
            score=outcome.score,
            bias=context.bias.value,
            price=context.price,
            volatility=context.volatility.level,
            risk_verdict=outcome.risk_decision.verdict,
            blocked_reason=outcome.risk_decision.reason,
            signal_id=outcome.signal.id if outcome.signal is not None else None,
            watch_trigger=trigger,
            alert_sent=bool(outcome.publication is not None and outcome.publication.sent),
        )


def _timeframe_states(context: MarketContext) -> dict[str, str]:
    """Etat par unite de temps, tel qu'il sera affiche dans le message."""
    if context.view is None:
        return {}
    states: dict[str, str] = {}
    for verdict in context.view.verdicts:
        if verdict.state == STATE_NO_DATA:
            states[verdict.timeframe.value] = STATE_NO_DATA
        else:
            states[verdict.timeframe.value] = verdict.trend.value
    return states


__all__ = ["AnalysisOutcome", "WatcherEngine"]
