"""Moteur de trading : orchestre analyse, risque, execution et suivi.

Flux d'un signal automatique (CDC section 52) :

    Signal -> Parser -> Validation -> RiskManager -> order_check -> order_send

Aucune etape n'est contournable, y compris en mode automatique.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.config.settings import get_settings
from app.database.session import session_scope
from app.models.core import as_utc, utcnow
from app.models.enums import (
    ChannelMode,
    EventLevel,
    ExecutionMode,
    PositionState,
    RejectionReason,
    SignalStatus,
)
from app.models.intelligence import DecisionSource
from app.models.telegram import Channel
from app.models.trading import Signal
from app.repositories import channel_repo, settings_repo, signal_repo, trade_repo
from app.services import journal
from app.services.events import EventType, event_bus
from app.services.learning import recorder
from app.services.mt5.interface import MetaTraderService
from app.services.risk.calculator import loss_for_one_lot
from app.services.risk.manager import RiskContext, RiskDecision, RiskManager
from app.services.signals import pipeline
from app.services.signals.models import FollowUp, ParsedSignal
from app.services.trading.executor import ExecutionOutcome, OrderExecutor
from app.services.trading.position_manager import PositionManager
from app.services.trading.symbol_resolver import SymbolResolver

logger = get_logger(__name__)


@dataclass(slots=True)
class ProcessOutcome:
    """Resultat complet du traitement d'un message ou d'un signal."""

    stage: str
    signal_id: int | None = None
    executed: bool = False
    rejected: bool = False
    reason: RejectionReason | None = None
    detail: str = ""
    decision: RiskDecision | None = None
    execution: ExecutionOutcome | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "signalId": self.signal_id,
            "executed": self.executed,
            "rejected": self.rejected,
            "reason": self.reason.value if self.reason else None,
            "detail": self.detail,
            "risk": self.decision.to_dict() if self.decision else None,
            "execution": self.execution.to_dict() if self.execution else None,
            **self.extra,
        }


def _learning_record(
    trade: Any, result: float, strategy: str | None = None
) -> recorder.TradeLearningRecord:
    """Contexte d'apprentissage d'un trade clos, sans rien inventer.

    Les champs que la position ne porte pas restent vides : le recorder
    distingue « absent » de « zero », et une valeur devinee vaudrait moins
    qu'un trou. La strategie vient du signal d'origine, qui seul la connait --
    le cycle autonome la nomme, un message Telegram n'en a pas, et rien n'en
    invente : elle retombe alors sur « non specifiee ».

    L'origine, elle, se deduit honnetement : un trade rattache a un signal
    vient d'un canal Telegram, sinon du cycle autonome. C'est exactement la
    comparaison que le ``by_source`` du CDC2 sert a rendre.
    """
    ouverture = as_utc(trade.opened_at)
    cloture = as_utc(trade.closed_at)
    duree: float | None = None
    if ouverture is not None and cloture is not None:
        duree = round((cloture - ouverture).total_seconds() / 60.0, 2)

    return recorder.TradeLearningRecord(
        symbol=trade.symbol,
        direction=trade.direction,
        strategy=strategy,
        source=(
            DecisionSource.TELEGRAM
            if trade.signal_id is not None
            else DecisionSource.AI_GENERATED
        ),
        entry_price=trade.open_price or None,
        stop_loss=trade.initial_stop_loss or trade.stop_loss,
        take_profit=trade.take_profit,
        take_profits=list(trade.take_profit_targets or []),
        volume=trade.initial_volume or None,
        realized_pnl=result,
        r_multiple=trade.r_multiple,
        duration_minutes=duree,
        trade_id=trade.id,
        signal_id=trade.signal_id,
        opened_at=ouverture,
        closed_at=cloture,
    )


class TradingEngine:
    """Point d'entree unique du trading. Un seul exemplaire par processus."""

    def __init__(self) -> None:
        self._market: MetaTraderService | None = None
        self._paper: MetaTraderService | None = None
        self._resolver: SymbolResolver | None = None
        self._paper_resolver: SymbolResolver | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._running = False
        self._lock = asyncio.Lock()
        self.mt5_connected = False
        self.mt5_error: str | None = None
        self.mt5_tested_on_this_machine = False

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def attach(self, market: MetaTraderService | None, paper: MetaTraderService) -> None:
        """Injecte les services de marche. Appele au demarrage de l'application."""
        self._market = market
        self._paper = paper
        self._resolver = SymbolResolver(market) if market is not None else None
        self._paper_resolver = SymbolResolver(paper)

    @property
    def market(self) -> MetaTraderService | None:
        return self._market

    @property
    def paper(self) -> MetaTraderService | None:
        return self._paper

    def service_for(self, mode: ExecutionMode) -> MetaTraderService | None:
        if mode is ExecutionMode.PAPER:
            return self._paper
        return self._market

    def resolver_for(self, mode: ExecutionMode) -> SymbolResolver | None:
        if mode is ExecutionMode.PAPER:
            return self._paper_resolver
        return self._resolver

    def invalidate_symbol_caches(self) -> None:
        """Oublie les correspondances de symboles deja calculees.

        Indispensable quand MetaTrader se connecte APRES le demarrage du
        Bridge, ce qui est le cas normal au demarrage de la machine : les
        resolveurs ont alors mis en cache la liste simulee, et le paper
        trading continuerait a travailler sur des noms et des prix inventes
        alors que le terminal est disponible.
        """
        for resolver in (self._resolver, self._paper_resolver):
            if resolver is not None:
                resolver.invalidate()
        logger.info("Correspondances de symboles reinitialisees apres connexion du terminal")

    async def start(self, poll_interval: float | None = None) -> None:
        if self._running:
            return
        self._running = True
        interval = poll_interval or get_settings().mt5_poll_interval
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))
        logger.info("Moteur de trading demarre (intervalle %.1fs)", interval)

    async def stop(self) -> None:
        self._running = False
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

    # ------------------------------------------------------------------
    # Entree principale : un message Telegram
    # ------------------------------------------------------------------
    async def handle_message(
        self,
        session: AsyncSession,
        text: str,
        channel: Channel | None = None,
        message_id: int | None = None,
        message_date: datetime | None = None,
        reply_to_message_id: int | None = None,
        internal_handoff: bool = False,
    ) -> ProcessOutcome:
        """``internal_handoff`` : le Bridge se remet un signal a lui-meme.

        Le Market Watcher publie puis transmet directement. Sans ce drapeau,
        le registre des publications propres refuserait son execution.
        """
        result = await pipeline.process_message(
            session,
            text=text,
            channel=channel,
            message_id=message_id,
            message_date=message_date,
            reply_to_message_id=reply_to_message_id,
            internal_handoff=internal_handoff,
        )

        if result.action == "duplicate":
            return ProcessOutcome(
                stage="duplicate",
                signal_id=result.signal.id if result.signal else None,
                rejected=True,
                reason=RejectionReason.DUPLICATE_SIGNAL,
                detail="Message deja traite : aucun ordre supplementaire",
            )

        if result.action == "ignored":
            return ProcessOutcome(stage="ignored", detail=result.detail)

        if result.action == "follow_up" and result.signal and result.parent_signal and result.parsed:
            return await self._handle_follow_up(
                session, result.signal, result.parent_signal, result.parsed.follow_up
            )

        if result.action == "no_action":
            return ProcessOutcome(
                stage="no_action",
                signal_id=result.signal.id if result.signal else None,
                detail=result.detail or "Aucune action",
            )

        if result.signal is None or result.parsed is None:
            return ProcessOutcome(stage="no_action", detail="Signal indisponible")

        return await self.process_signal(session, result.signal, result.parsed, channel=channel)

    async def _handle_follow_up(
        self, session: AsyncSession, follow_signal: Signal, parent: Signal, follow_up: FollowUp | None
    ) -> ProcessOutcome:
        if follow_up is None:
            return ProcessOutcome(stage="follow_up", signal_id=follow_signal.id, detail="Suivi vide")
        settings = await settings_repo.get_risk_settings(session)
        mode = parent.execution_mode or settings.execution_mode
        service = self.service_for(mode)
        if service is None:
            return ProcessOutcome(
                stage="follow_up",
                signal_id=follow_signal.id,
                rejected=True,
                reason=RejectionReason.MT5_DISCONNECTED,
                detail="Service de marche indisponible",
            )
        manager = PositionManager(service)
        result = await manager.apply_follow_up(session, follow_signal, parent, follow_up, settings)
        # Une position fermee sur ordre du canal doit compter comme toute
        # autre : la reconciliation ne la verra jamais, puisqu'elle ne repasse
        # que sur les positions encore ouvertes.
        if result.closed:
            await self._apply_closed_trades(session, result.closed)
        return ProcessOutcome(
            stage="follow_up",
            signal_id=follow_signal.id,
            executed=result.ok and bool(result.actions),
            detail=result.detail or f"{len(result.actions)} action(s)",
            extra={"management": result.to_dict()},
        )

    # ------------------------------------------------------------------
    # Traitement d'un signal structure
    # ------------------------------------------------------------------
    async def process_signal(
        self,
        session: AsyncSession,
        signal: Signal,
        parsed: ParsedSignal | None = None,
        channel: Channel | None = None,
        manual_override: bool = False,
    ) -> ProcessOutcome:
        """Evalue et execute un signal. Un seul a la fois, par construction.

        Les plafonds d'exposition — ``max_positions``,
        ``max_positions_per_symbol``, ``max_total_exposure_lots`` — comparent
        un compte de positions a une limite. Ils ne valent donc que si deux
        signaux ne peuvent pas lire l'etat du compte en meme temps.

        Le 14/09/2026, PARAMOUR a publie trois messages XAUUSD en quatre-vingt
        -dix secondes. Les trois ont ete evalues en parallele, chacun a lu
        « aucune position sur XAUUSDm », et trois positions se sont ouvertes
        alors que ``max_positions_per_symbol`` valait 1. Deux portaient meme
        le meme horodatage d'ouverture a la microseconde pres.

        Le verrou est celui de la boucle de suivi : une evaluation ne peut pas
        non plus tomber au milieu d'une reconciliation. Seule l'EXECUTION est
        serialisee ; l'analyse du message, elle, reste concurrente, ce qui
        importe car elle peut attendre une reponse d'IA.
        """
        async with self._lock:
            return await self._process_signal(
                session, signal, parsed, channel, manual_override
            )

    async def _process_signal(
        self,
        session: AsyncSession,
        signal: Signal,
        parsed: ParsedSignal | None = None,
        channel: Channel | None = None,
        manual_override: bool = False,
    ) -> ProcessOutcome:
        parsed = parsed or pipeline.parsed_from_signal(signal)
        settings = await settings_repo.get_risk_settings(session)
        state = await settings_repo.get_trading_state(session)
        channel_settings = await channel_repo.get_settings(session, signal.channel_id)

        execution_mode = settings.execution_mode
        signal.execution_mode = execution_mode

        # Mode OBSERVE : on simule sans jamais envoyer d'ordre.
        if (
            channel_settings is not None
            and channel_settings.mode is ChannelMode.OBSERVE
            and not manual_override
        ):
            await signal_repo.set_status(
                session,
                signal,
                SignalStatus.OBSERVED,
                stage="risk",
                message="Canal en mode observation : signal enregistre sans execution",
            )
            return ProcessOutcome(
                stage="observed",
                signal_id=signal.id,
                detail="Canal en mode observation",
            )

        # Mode MANUEL : on prepare tout et on attend la confirmation de l'utilisateur.
        if (
            channel_settings is not None
            and channel_settings.mode is ChannelMode.MANUAL
            and not manual_override
        ):
            expiry = settings.max_signal_age_seconds
            signal.expires_at = utcnow() + timedelta(seconds=max(60, expiry))
            await signal_repo.set_status(
                session,
                signal,
                SignalStatus.NEEDS_REVIEW,
                stage="risk",
                message="Validation manuelle requise",
            )
            event_bus.publish(
                EventType.SIGNAL_NEEDS_REVIEW,
                {"signalId": signal.id, "reason": "Validation manuelle requise"},
            )
            return ProcessOutcome(
                stage="needs_review", signal_id=signal.id, detail="Validation manuelle requise"
            )

        service = self.service_for(execution_mode)
        if service is None:
            return await self._reject(
                session,
                signal,
                RejectionReason.MT5_DISCONNECTED,
                "Aucun service de marche disponible pour ce mode",
            )

        # --- resolution du symbole broker ---
        # (l'etat du terminal est lu plus bas, une fois le symbole confirme)
        resolver = self.resolver_for(execution_mode)
        resolved = None
        if resolver is not None and signal.normalized_symbol:
            resolved = await resolver.resolve(session, signal.normalized_symbol)
        if resolved is None:
            return await self._reject(
                session,
                signal,
                RejectionReason.SYMBOL_NOT_FOUND,
                f"{signal.normalized_symbol} introuvable chez le broker",
            )
        signal.broker_symbol = resolved.broker_symbol

        tick = await service.symbol_tick(resolved.broker_symbol)
        account = await service.account_info()
        positions = await service.positions()
        algo_allowed = await self._terminal_algo_allowed(service, execution_mode)
        await settings_repo.ensure_day_rollover(session, account.balance if account else None)
        state = await settings_repo.get_trading_state(session)

        context = RiskContext(
            settings=settings,
            state=state,
            channel=channel_settings,
            account=account,
            symbol=resolved.info,
            tick=tick,
            open_positions=positions,
            mt5_connected=execution_mode is ExecutionMode.PAPER or self.mt5_connected,
            terminal_algo_allowed=algo_allowed,
            manual_override=manual_override,
        )

        decision = await RiskManager(service).evaluate(parsed, context, execution_mode)
        await trade_repo.record_risk_event(
            session,
            signal_id=signal.id,
            approved=decision.approved,
            reason=decision.reason,
            detail=decision.detail,
            checks=[check.to_dict() for check in decision.checks],
            computed_lot=decision.lot.volume if decision.lot else None,
            risk_amount=decision.lot.risk_amount if decision.lot else None,
        )
        await signal_repo.add_event(
            session,
            signal.id,
            stage="risk",
            success=decision.approved,
            message=decision.detail or "Controles de risque passes",
            data=decision.to_dict(),
        )

        if not decision.approved:
            return await self._reject(
                session, signal, decision.reason or RejectionReason.RISK_TOO_HIGH, decision.detail, decision
            )

        # --- ordres en attente deja poses sur cet instrument ---------------
        # A faire APRES l'approbation et AVANT l'execution : on n'annule rien
        # pour un signal qui va etre refuse, et on ne laisse pas un ordre du
        # sens contraire survivre a un signal qui vient de le contredire.
        annules = await self._cancel_opposite_pending(
            session, service, execution_mode, resolved.broker_symbol, parsed.direction
        )
        if annules:
            await signal_repo.add_event(
                session,
                signal.id,
                stage="risk",
                message=(
                    f"{annules} ordre(s) en attente de sens contraire annule(s) sur "
                    f"{resolved.broker_symbol}"
                ),
            )

        doublon = await self._equivalent_pending(
            session, execution_mode, resolved.broker_symbol, parsed, resolved.info
        )
        if doublon is not None:
            return await self._reject(
                session,
                signal,
                RejectionReason.DUPLICATE_SIGNAL,
                (
                    f"Ordre identique deja en attente (#{doublon.ticket}) : "
                    f"{resolved.broker_symbol} {parsed.direction.value} a {doublon.price}"
                ),
                decision,
            )

        signal.computed_lot = decision.lot.volume if decision.lot else None
        signal.risk_amount = decision.lot.risk_amount if decision.lot else None
        signal.risk_reward = decision.risk_reward
        await signal_repo.set_status(
            session, signal, SignalStatus.APPROVED, stage="risk", message="Signal approuve"
        )

        executor = OrderExecutor(service)
        execution = await executor.execute(
            session,
            signal=signal,
            parsed=parsed,
            decision=decision,
            execution_mode=execution_mode,
            broker_symbol=resolved.broker_symbol,
            symbol=resolved.info,
            tick=tick,
        )

        if not execution.ok:
            return ProcessOutcome(
                stage="execution_failed",
                signal_id=signal.id,
                rejected=True,
                reason=execution.reason,
                detail=execution.detail,
                decision=decision,
                execution=execution,
            )

        pending = all(order.pending for order in execution.orders)
        await signal_repo.set_status(
            session,
            signal,
            SignalStatus.SENT if pending else SignalStatus.OPEN,
            stage="execution",
            message=f"{len(execution.orders)} ordre(s) envoye(s)",
            data=execution.to_dict(),
        )

        # Comptabilise le risque engage sur la journee.
        if decision.lot and decision.lot.loss_at_stop and context.balance > 0:
            state.day_risked_percent += decision.lot.loss_at_stop / context.balance * 100
            await settings_repo.save_trading_state(session, state)

        await journal.record(
            session,
            event="order_sent",
            message=(
                f"{signal.normalized_symbol} {signal.direction.value if signal.direction else ''} "
                f"{decision.lot.volume if decision.lot else ''} lot(s) en {execution_mode.value}"
            ),
            category="trading",
            signal_id=signal.id,
            channel_id=signal.channel_id,
            data=execution.to_dict(),
        )
        await journal.audit(
            session,
            action="order_sent",
            target=signal.broker_symbol,
            signal_id=signal.id,
            details={
                "executionMode": execution_mode.value,
                "risk": decision.to_dict(),
                "execution": execution.to_dict(),
                "parser": parsed.source.value,
                "aiModel": parsed.ai_model,
                "confidence": parsed.confidence,
            },
        )
        return ProcessOutcome(
            stage="executed",
            signal_id=signal.id,
            executed=True,
            decision=decision,
            execution=execution,
            detail=f"{len(execution.orders)} ordre(s) envoye(s)",
        )

    @staticmethod
    async def _terminal_algo_allowed(service: Any, execution_mode: ExecutionMode) -> bool | None:
        """L'interrupteur « Trading algorithmique » du terminal MetaTrader.

        Il est independant de l'autorisation du compte : le courtier peut
        accepter les ordres alors que le terminal refuse de les envoyer. Sans
        ce controle, l'ordre partait et MetaTrader le rejetait avec un code
        technique, sans dire quoi corriger.

        Retourne ``None`` quand l'information n'est pas lisible : on ne bloque
        jamais sur une mesure absente.
        """
        if execution_mode is ExecutionMode.PAPER:
            return None
        lire = getattr(service, "terminal_info", None)
        if not callable(lire):
            return None
        try:
            terminal = await lire()
        except Exception as exc:
            logger.debug("Etat du terminal illisible : %s", exc)
            return None
        if terminal is None:
            return None
        valeur = getattr(terminal, "trade_allowed", None)
        return None if valeur is None else bool(valeur)

    async def _reject(
        self,
        session: AsyncSession,
        signal: Signal,
        reason: RejectionReason,
        detail: str,
        decision: RiskDecision | None = None,
    ) -> ProcessOutcome:
        signal.rejection_reason = reason
        signal.rejection_detail = detail[:500] if detail else None
        await signal_repo.set_status(
            session, signal, SignalStatus.REJECTED, stage="risk", message=detail, success=False
        )
        await journal.record(
            session,
            event="signal_rejected",
            message=f"{reason.value} : {detail}",
            level=EventLevel.WARNING,
            category="risk",
            signal_id=signal.id,
            channel_id=signal.channel_id,
        )
        event_bus.publish(
            EventType.SIGNAL_REJECTED,
            {"signalId": signal.id, "reason": reason.value, "detail": detail},
        )
        return ProcessOutcome(
            stage="rejected",
            signal_id=signal.id,
            rejected=True,
            reason=reason,
            detail=detail,
            decision=decision,
        )

    # ------------------------------------------------------------------
    # Ordres en attente deja poses sur l'instrument
    # ------------------------------------------------------------------
    async def _cancel_opposite_pending(
        self,
        session: AsyncSession,
        service: MetaTraderService,
        execution_mode: ExecutionMode,
        broker_symbol: str,
        direction: Any,
    ) -> int:
        """Annule les ordres en attente du sens contraire sur cet instrument.

        Un signal de vente rend caduc un achat qui attend encore son
        declenchement : le canal vient de dire l'inverse. Le 14/09/2026, des
        ordres d'achat XAUUSD attendaient toujours alors que cinq signaux de
        vente etaient passes depuis.

        Seuls les ordres EN ATTENTE sont touches. Une position deja ouverte
        n'est jamais fermee ici : ce serait un choix de gestion, pas une mise a
        jour d'ordre.
        """
        if direction is None:
            return 0
        try:
            en_attente = await trade_repo.pending_orders(session, execution_mode=execution_mode)
        except Exception as exc:
            logger.warning("Ordres en attente illisibles : %s", exc)
            return 0

        annules = 0
        for ordre in en_attente:
            if ordre.symbol != broker_symbol or ordre.direction is direction:
                continue
            try:
                resultat = await service.cancel_order(ordre.ticket)
            except Exception as exc:
                logger.warning("Annulation de l'ordre %s impossible : %s", ordre.ticket, exc)
                continue
            if not resultat.ok:
                logger.info(
                    "Ordre %s non annule : %s", ordre.ticket, resultat.message
                )
                continue
            ordre.state = PositionState.CANCELLED
            await trade_repo.save_order(session, ordre)
            event_bus.publish(EventType.ORDER_CANCELLED, {"ticket": ordre.ticket})
            logger.info(
                "Ordre %s (%s %s) annule : signal de sens contraire",
                ordre.ticket,
                ordre.symbol,
                ordre.direction.value,
            )
            annules += 1
        return annules

    async def _equivalent_pending(
        self,
        session: AsyncSession,
        execution_mode: ExecutionMode,
        broker_symbol: str,
        parsed: ParsedSignal,
        symbol: Any,
    ) -> Any:
        """Un ordre identique attend-il deja ? Rend l'ordre trouve, sinon None.

        Deux ordres sont identiques quand ils portent le meme instrument, le
        meme sens et la meme entree, a un pas de cotation pres. Le stop est
        compare quand les deux le connaissent.

        Ce filet rattrape les republications d'un canal externe : le
        14/09/2026, PARAMOUR a poste deux fois le meme signal XAUUSD a 3998, et
        deux ordres ont ete poses.
        """
        entree = parsed.entry_price if parsed.entry_price is not None else parsed.entry_min
        if entree is None or parsed.direction is None:
            return None
        # Tolerance d'un pas de cotation : deux messages du meme signal peuvent
        # arrondir differemment sans decrire deux operations distinctes.
        tolerance = max(getattr(symbol, "point", 0.0) or 0.0, 1e-9)
        try:
            en_attente = await trade_repo.pending_orders(session, execution_mode=execution_mode)
        except Exception as exc:
            logger.warning("Ordres en attente illisibles : %s", exc)
            return None

        for ordre in en_attente:
            if ordre.symbol != broker_symbol or ordre.direction is not parsed.direction:
                continue
            if ordre.price is None or abs(ordre.price - entree) > tolerance:
                continue
            if (
                ordre.stop_loss is not None
                and parsed.stop_loss is not None
                and abs(ordre.stop_loss - parsed.stop_loss) > tolerance
            ):
                continue
            return ordre
        return None

    # ------------------------------------------------------------------
    # Actions manuelles et urgence
    # ------------------------------------------------------------------
    async def approve_manually(self, session: AsyncSession, signal_id: int) -> ProcessOutcome:
        signal = await signal_repo.get(session, signal_id)
        if signal is None:
            return ProcessOutcome(stage="not_found", detail="Signal introuvable")
        if signal.expires_at is not None and as_utc(signal.expires_at) < utcnow():
            await signal_repo.set_status(
                session, signal, SignalStatus.EXPIRED, stage="manual", message="Delai de validation depasse"
            )
            return ProcessOutcome(
                stage="expired", signal_id=signal_id, rejected=True,
                reason=RejectionReason.SIGNAL_EXPIRED, detail="Delai de validation depasse",
            )
        signal.reviewed_at = utcnow()
        return await self.process_signal(session, signal, manual_override=True)

    async def reject_manually(
        self, session: AsyncSession, signal_id: int, reason: str = ""
    ) -> ProcessOutcome:
        signal = await signal_repo.get(session, signal_id)
        if signal is None:
            return ProcessOutcome(stage="not_found", detail="Signal introuvable")
        signal.reviewed_at = utcnow()
        return await self._reject(
            session, signal, RejectionReason.MANUAL_REJECTION, reason or "Refuse par l'utilisateur"
        )

    async def cancel_all_pending(self, session: AsyncSession) -> dict[str, Any]:
        """Annule tous les ordres en attente sur le mode d'execution courant."""
        settings = await settings_repo.get_risk_settings(session)
        service = self.service_for(settings.execution_mode)
        if service is None:
            return {"ok": False, "cancelled": 0, "detail": "Service de marche indisponible"}
        cancelled = 0
        errors: list[str] = []
        for order in await service.orders():
            result = await service.cancel_order(order.ticket)
            if result.ok:
                cancelled += 1
                record = await trade_repo.find_order_by_ticket(session, order.ticket)
                if record is not None:
                    record.state = PositionState.CANCELLED
                    await trade_repo.save_order(session, record)
            else:
                errors.append(f"#{order.ticket}: {result.message}")
        await journal.record(
            session,
            event="emergency_cancel_pending",
            message=f"{cancelled} ordre(s) en attente annule(s)",
            level=EventLevel.WARNING,
            category="emergency",
        )
        await journal.audit(session, action="emergency_cancel_pending", actor="user",
                            details={"cancelled": cancelled, "errors": errors})
        return {"ok": not errors, "cancelled": cancelled, "errors": errors}

    async def close_all_positions(self, session: AsyncSession, suspend: bool = False) -> dict[str, Any]:
        """Ferme toutes les positions. Action explicite et journalisee."""
        settings = await settings_repo.get_risk_settings(session)
        service = self.service_for(settings.execution_mode)
        if service is None:
            return {"ok": False, "closed": 0, "detail": "Service de marche indisponible"}
        closed = 0
        errors: list[str] = []
        fermes: list[Any] = []
        for position in await service.positions():
            result = await service.close_position(position.ticket)
            if result.ok:
                closed += 1
                trade = await trade_repo.find_by_ticket(session, position.ticket)
                if trade is not None:
                    trade.state = PositionState.CLOSED
                    trade.closed_at = utcnow()
                    trade.close_reason = "arret d'urgence"
                    trade.volume = 0.0
                    # Un arret d'urgence ferme souvent en perte. Sans resultat
                    # inscrit, la limite de perte journaliere et le compteur de
                    # pertes consecutives resteraient a zero, et le systeme
                    # repartirait comme si de rien n'etait.
                    trade.realized_pnl = trade.realized_pnl or trade.profit
                    await trade_repo.save_trade(session, trade)
                    fermes.append(trade)
            else:
                errors.append(f"#{position.ticket}: {result.message}")

        if fermes:
            await self._apply_closed_trades(session, fermes)

        if suspend:
            await self.pause(session, "Arret d'urgence declenche par l'utilisateur")

        await journal.record(
            session,
            event="emergency_close_all",
            message=f"{closed} position(s) fermee(s) par arret d'urgence",
            level=EventLevel.CRITICAL,
            category="emergency",
        )
        await journal.audit(session, action="emergency_close_all", actor="user",
                            details={"closed": closed, "errors": errors, "suspended": suspend})
        event_bus.publish(EventType.NOTIFICATION, {"title": "Arret d'urgence", "closed": closed})
        return {"ok": not errors, "closed": closed, "errors": errors, "suspended": suspend}

    async def pause(self, session: AsyncSession, reason: str, minutes: int | None = None) -> dict[str, Any]:
        """Suspend les nouveaux trades automatiques sans toucher aux positions."""
        state = await settings_repo.get_trading_state(session)
        state.paused = True
        state.pause_reason = reason[:255]
        state.paused_until = utcnow() + timedelta(minutes=minutes) if minutes else None
        await settings_repo.save_trading_state(session, state)
        await journal.record(
            session,
            event="trading_paused",
            message=f"Automatisation en pause : {reason}",
            level=EventLevel.WARNING,
            category="trading",
        )
        event_bus.publish(EventType.TRADING_STATE, {"paused": True, "reason": reason})
        return {"paused": True, "reason": reason,
                "until": state.paused_until.isoformat() if state.paused_until else None}

    async def resume(self, session: AsyncSession) -> dict[str, Any]:
        state = await settings_repo.get_trading_state(session)
        state.paused = False
        state.pause_reason = None
        state.paused_until = None
        await settings_repo.save_trading_state(session, state)
        await journal.record(
            session, event="trading_resumed", message="Automatisation reprise", category="trading"
        )
        event_bus.publish(EventType.TRADING_STATE, {"paused": False})
        return {"paused": False}

    # ------------------------------------------------------------------
    # Boucle de suivi
    # ------------------------------------------------------------------
    async def _monitor_loop(self, interval: float) -> None:
        """Rafraichit compte et positions a intervalle raisonnable (CDC section 63)."""
        consecutive_errors = 0
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self._monitor_once()
                consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                logger.warning("Cycle de suivi en echec (%s) : %s", consecutive_errors, exc)
                if consecutive_errors >= 5:
                    await asyncio.sleep(min(60.0, interval * consecutive_errors))

    async def _monitor_once(self) -> None:
        async with self._lock, session_scope() as session:
            settings = await settings_repo.get_risk_settings(session)
            mode = settings.execution_mode
            service = self.service_for(mode)
            if service is None:
                return

            # Le moteur papier avance sa simulation a chaque cycle.
            simulate = getattr(service, "simulate_step", None)
            if callable(simulate):
                events = await simulate()
                for event in events or []:
                    logger.debug("Evenement simule : %s", event)

            account = await service.account_info()
            if account is not None:
                await settings_repo.ensure_day_rollover(session, account.balance)
                event_bus.publish(EventType.ACCOUNT_UPDATED, account.to_dict())

            manager = PositionManager(service)
            closed = await manager.sync_with_broker(session, mode)
            clotures = list(closed or [])
            if clotures:
                await self._apply_closed_trades(session, clotures, service)

            open_trades = await trade_repo.open_trades(session, mode)
            if open_trades:
                automatique = await manager.apply_automatic_rules(
                    session, settings, open_trades
                )
                fermees = list(getattr(automatique, "closed", None) or [])
                if fermees:
                    clotures.extend(fermees)
                    await self._apply_closed_trades(session, fermees, service)
                total = sum(trade.profit for trade in open_trades)
                event_bus.publish(
                    EventType.PNL_UPDATED,
                    {"openPositions": len(open_trades), "floatingPnl": round(total, 2)},
                )

            # Les reperes du jour se recalent une fois les clotures inscrites au
            # compteur, et jamais pendant le cycle qui en a ferme une : le solde
            # du courtier et ``day_realized_pnl`` ne basculent pas au meme
            # instant, et l'ecart transitoire vaut exactement le resultat du
            # trade. Le confondre avec un depot effacait ``day_start_balance``
            # et ``peak_equity`` a chaque grosse perte -- voir
            # ``reconcile_external_balance_move``. Un vrai mouvement d'argent
            # est simplement detecte au cycle suivant, deux secondes plus tard.
            if account is not None:
                if not clotures:
                    await settings_repo.reconcile_external_balance_move(
                        session, account.balance
                    )
                state = await settings_repo.get_trading_state(session)
                if state.peak_equity is None or account.equity > state.peak_equity:
                    state.peak_equity = account.equity
                    await settings_repo.save_trading_state(session, state)

            await self._expire_stale_signals(session)

    @staticmethod
    async def risk_reference(service: MetaTraderService, trade: Any) -> float | None:
        """Montant reellement risque a l'ouverture, en devise du compte.

        C'est la seule definition de 1 R qui tienne : le resultat d'une
        position est en dollars, donc son denominateur doit l'etre aussi. Une
        distance de prix multipliee par un volume n'est pas un montant -- il y
        manque la taille du contrat, 100 sur l'or et 100 000 sur l'euro.

        On repasse par ``loss_for_one_lot``, la fonction qui a servi a
        dimensionner la position : le R se mesure ainsi avec la meme regle qui
        a decide du lot, ``order_calc_profit`` en tete et l'arithmetique sur
        les ticks en secours.
        """
        stop = getattr(trade, "initial_stop_loss", None)
        entree = getattr(trade, "open_price", None)
        volume = getattr(trade, "initial_volume", None)
        if stop is None or not entree or not volume:
            return None
        if abs(entree - stop) <= 0:
            return None

        symbol = await service.symbol_info(trade.symbol)
        if symbol is None:
            return None
        par_lot, _ = await loss_for_one_lot(service, symbol, trade.direction, entree, stop)
        if not par_lot or par_lot <= 0:
            return None
        return par_lot * volume

    async def _apply_closed_trades(
        self,
        session: AsyncSession,
        closed: list[Any],
        service: MetaTraderService | None = None,
    ) -> None:
        """Met a jour les compteurs journaliers et les pertes consecutives."""
        state = await settings_repo.get_trading_state(session)
        settings = await settings_repo.get_risk_settings(session)
        for trade in closed:
            result = trade.realized_pnl or trade.profit
            state.day_realized_pnl += result
            if result < 0:
                state.consecutive_losses += 1
            elif result > 0:
                state.consecutive_losses = 0
            if service is not None:
                try:
                    reference = await self.risk_reference(service, trade)
                except Exception as exc:  # le terminal peut refuser le symbole
                    logger.debug(
                        "Risque de reference indisponible pour %s : %s", trade.symbol, exc
                    )
                    reference = None
                # Sans reference fiable on laisse le champ vide : un R invente
                # pollue les statistiques par canal plus surement qu'un trou.
                if reference:
                    trade.r_multiple = round(result / reference, 3)
                    await trade_repo.save_trade(session, trade)

            # C'est ici, et nulle part ailleurs, que la memoire d'apprentissage
            # est alimentee. Elle ne l'etait par PERSONNE : le sous-systeme du
            # CDC2 existait en entier mais ``strategy_performance`` restait
            # vide, donc les statistiques d'apprentissage ne disaient rien et
            # le regleur autonome mesurait une table sans lignes.
            #
            # Non bloquant : la comptabilite du jour ne doit pas dependre
            # d'elle, sinon une panne de la memoire empecherait une perte
            # d'etre comptee et un garde-fou journalier de se declencher.
            try:
                strategie: str | None = None
                if trade.signal_id is not None:
                    origine = await signal_repo.get(session, int(trade.signal_id))
                    strategie = origine.strategy if origine is not None else None
                await recorder.record_trade_outcome(
                    session, _learning_record(trade, result, strategie)
                )
            except Exception as exc:
                logger.warning(
                    "Memoire d'apprentissage non alimentee pour le ticket %s : %s",
                    trade.ticket,
                    exc,
                )
        await settings_repo.save_trading_state(session, state)

        if (
            settings.pause_after_max_losses
            and settings.max_consecutive_losses > 0
            and state.consecutive_losses >= settings.max_consecutive_losses
            and not state.paused
        ):
            await self.pause(
                session,
                f"{state.consecutive_losses} pertes consecutives",
                minutes=settings.pause_duration_minutes,
            )

    async def _expire_stale_signals(self, session: AsyncSession) -> None:
        """Un signal en attente de validation manuelle expire silencieusement."""
        pending = await signal_repo.list_signals(
            session, limit=50, statuses=[SignalStatus.NEEDS_REVIEW]
        )
        now = utcnow()
        for signal in pending:
            expires_at = as_utc(signal.expires_at)
            if expires_at is not None and expires_at < now:
                await signal_repo.set_status(
                    session,
                    signal,
                    SignalStatus.EXPIRED,
                    stage="lifecycle",
                    message="Delai de validation manuelle depasse : signal perime",
                )
                event_bus.publish(EventType.SIGNAL_UPDATED, {"signalId": signal.id, "status": "EXPIRED"})


trading_engine = TradingEngine()
