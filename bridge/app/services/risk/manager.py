"""RiskManager : derniere barriere avant tout envoi d'ordre.

Entierement independant de l'IA et sans acces base de donnees : l'appelant
assemble un ``RiskContext``, le manager applique les regles. Cela le rend
testable exhaustivement et impossible a contourner (CDC sections 23 et 25).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any

from app.config.logging_config import get_logger
from app.models.core import RiskSettings, TradingState, as_utc
from app.models.enums import (
    AccountKind,
    ChannelMode,
    Direction,
    ExecutionMode,
    MultiTpStrategy,
    RejectionReason,
)
from app.models.telegram import ChannelSettings
from app.services.mt5.interface import AccountInfo, MetaTraderService, PositionInfo, SymbolInfo, Tick
from app.services.risk.calculator import (
    CAUSE_BELOW_VOLUME_MIN,
    LotCalculation,
    calculate_lot,
    points_between,
)
from app.services.risk.quality import (
    QualityMultiplier,
    quality_multiplier,
    weighted_risk_reward,
)
from app.services.signals.models import ParsedSignal

logger = get_logger(__name__)


@dataclass(slots=True)
class EffectiveSettings:
    """Reglages globaux fusionnes avec les overrides du canal."""

    risk_percent: float
    max_lot: float
    max_positions: int
    max_positions_per_symbol: int
    max_total_exposure_lots: float
    max_spread_points: int
    max_signal_age_seconds: int
    require_stop_loss: bool
    require_take_profit: bool
    min_confidence: float
    min_risk_reward: float | None
    allowed_symbols: list[str]
    multi_tp_strategy: MultiTpStrategy
    split_ratios: list[float]
    max_slippage_points: int
    copy_buy: bool
    copy_sell: bool
    mode: ChannelMode


def resolve_settings(settings: RiskSettings, channel: ChannelSettings | None) -> EffectiveSettings:
    """Un champ NULL du canal signifie : utiliser le reglage global."""

    def pick(channel_value: Any, global_value: Any) -> Any:
        return global_value if channel_value is None else channel_value

    allowed = list(settings.allowed_symbols or [])
    if channel is not None and channel.allowed_symbols:
        allowed = list(channel.allowed_symbols)

    return EffectiveSettings(
        risk_percent=pick(channel.risk_percent if channel else None, settings.risk_percent),
        max_lot=pick(channel.max_lot if channel else None, settings.max_lot),
        max_positions=pick(channel.max_positions if channel else None, settings.max_positions),
        max_positions_per_symbol=settings.max_positions_per_symbol,
        max_total_exposure_lots=settings.max_total_exposure_lots,
        max_spread_points=pick(channel.max_spread_points if channel else None, settings.max_spread_points),
        max_signal_age_seconds=pick(
            channel.max_signal_age_seconds if channel else None, settings.max_signal_age_seconds
        ),
        require_stop_loss=pick(channel.require_stop_loss if channel else None, settings.require_stop_loss),
        require_take_profit=pick(
            channel.require_take_profit if channel else None, settings.require_take_profit
        ),
        min_confidence=pick(channel.min_confidence if channel else None, settings.min_confidence),
        min_risk_reward=settings.min_risk_reward,
        allowed_symbols=allowed,
        multi_tp_strategy=pick(channel.multi_tp_strategy if channel else None, settings.multi_tp_strategy),
        split_ratios=list(settings.split_ratios or [40.0, 30.0, 30.0]),
        max_slippage_points=settings.max_slippage_points,
        copy_buy=channel.copy_buy if channel else True,
        copy_sell=channel.copy_sell if channel else True,
        mode=channel.mode if channel else ChannelMode.OBSERVE,
    )


@dataclass(slots=True)
class RiskContext:
    settings: RiskSettings
    state: TradingState
    channel: ChannelSettings | None = None
    account: AccountInfo | None = None
    symbol: SymbolInfo | None = None
    tick: Tick | None = None
    open_positions: list[PositionInfo] = field(default_factory=list)
    mt5_connected: bool = True
    # Interrupteur « Trading algorithmique » du terminal MetaTrader. Il est
    # distinct de l'autorisation portee par le compte : le serveur peut
    # accepter les ordres alors que le terminal refuse de les envoyer.
    # ``None`` signifie « information indisponible » : on ne bloque pas sur
    # une absence de mesure.
    terminal_algo_allowed: bool | None = None
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    manual_override: bool = False

    @property
    def balance(self) -> float:
        if self.account is not None:
            return self.account.balance
        return self.settings.paper_balance

    @property
    def equity(self) -> float:
        if self.account is not None:
            return self.account.equity
        return self.settings.paper_balance


@dataclass(slots=True)
class RiskCheck:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reason: RejectionReason | None = None
    detail: str = ""
    checks: list[RiskCheck] = field(default_factory=list)
    lot: LotCalculation | None = None
    effective: EffectiveSettings | None = None
    entry_price: float | None = None
    risk_reward: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason.value if self.reason else None,
            "detail": self.detail,
            "checks": [check.to_dict() for check in self.checks],
            "lot": self.lot.to_dict() if self.lot else None,
            "entryPrice": self.entry_price,
            "riskReward": round(self.risk_reward, 2) if self.risk_reward is not None else None,
        }


def _parse_hhmm(value: str, fallback: time) -> time:
    try:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return fallback


def _explain_volume_failure(
    *,
    lot: LotCalculation,
    quality: QualityMultiplier | None,
    configured_risk_percent: float,
    sized_risk_percent: float,
    balance: float,
) -> str:
    """Nomme la cause reelle d'un volume refuse, pas son symptome.

    Le message accusait le lot minimum du courtier. Le 14/09/2026, un signal
    XAUUSD a ete refuse ainsi alors que le courtier n'y etait pour rien : le
    budget de risque du jour etait a 11,26 % sur 12, le multiplicateur avait
    donc ecrase le risque de 4 % a 0,737 %, et c'est CE risque minuscule qui
    faisait tomber le volume sous 0,01. Au risque configure, le lot minimum
    n'aurait coute que 2,25 % du solde — il passait largement.

    Le partage se fait sur une question verifiable : au risque que
    l'utilisateur a configure, le lot minimum serait-il acceptable ?

    * oui -> la reduction est la cause, et on dit laquelle ;
    * non -> le compte est reellement trop petit pour cette distance de stop.
    """
    base = lot.reason or "Volume invalide"
    if lot.cause != CAUSE_BELOW_VOLUME_MIN or lot.minimum_lot_loss is None or balance <= 0:
        # Autre cause (prix invalide, risque non valorisable) : le motif du
        # calculateur est deja le bon, on n'y ajoute rien.
        return base

    part = lot.minimum_lot_loss / balance * 100.0
    reduit = quality is not None and quality.applied
    abordable = part <= configured_risk_percent + 1e-9

    if reduit and abordable:
        facteur = min(quality.factors, key=lambda cle: quality.factors[cle]) if quality.factors else None
        origine = (
            f" Facteur le plus penalisant : {facteur} ({quality.factors[facteur]:.2f})."
            if facteur
            else ""
        )
        return (
            f"Taille reduite en amont : le risque est passe de {configured_risk_percent:.2f}% "
            f"a {sized_risk_percent:.3f}%, ce qui fait tomber le volume sous le minimum "
            f"du courtier. Au risque configure, le lot minimum couterait "
            f"{lot.minimum_lot_loss:.2f} ({part:.2f}% du solde) et serait accepte.{origine}"
        )

    if reduit:
        return (
            f"Compte trop petit pour ce stop : le lot minimum couterait "
            f"{lot.minimum_lot_loss:.2f} ({part:.2f}% du solde), au-dela du risque "
            f"configure de {configured_risk_percent:.2f}%. La taille avait en outre ete "
            f"reduite a {sized_risk_percent:.3f}%."
        )

    return (
        f"Compte trop petit pour ce stop : le lot minimum couterait "
        f"{lot.minimum_lot_loss:.2f} ({part:.2f}% du solde), au-dela du risque "
        f"configure de {configured_risk_percent:.2f}%."
    )


class RiskManager:
    """Applique toutes les regles de risque. Aucune ne peut etre desactivee a chaud."""

    def __init__(self, service: MetaTraderService | None = None) -> None:
        self._service = service

    async def evaluate(
        self, signal: ParsedSignal, context: RiskContext, execution_mode: ExecutionMode
    ) -> RiskDecision:
        checks: list[RiskCheck] = []
        effective = resolve_settings(context.settings, context.channel)

        def fail(reason: RejectionReason, detail: str, name: str) -> RiskDecision:
            checks.append(RiskCheck(name, False, detail))
            logger.info("Signal refuse (%s) : %s", reason.value, detail)
            return RiskDecision(
                approved=False, reason=reason, detail=detail, checks=checks, effective=effective
            )

        def ok(name: str, detail: str = "") -> None:
            checks.append(RiskCheck(name, True, detail))

        # ------------------------------------------------------------------
        # 1. Interrupteurs generaux
        # ------------------------------------------------------------------
        if not context.manual_override and not context.settings.auto_trading_enabled:
            return fail(
                RejectionReason.AUTO_TRADING_OFF,
                "Le trading automatique est desactive",
                "auto_trading",
            )
        ok("auto_trading")

        if context.state.paused:
            until = as_utc(context.state.paused_until)
            if until is None or until > context.now:
                detail = context.state.pause_reason or "Automatisation en pause"
                return fail(RejectionReason.TRADING_PAUSED, detail, "pause")
        ok("pause")

        # ------------------------------------------------------------------
        # 2. Canal
        # ------------------------------------------------------------------
        if context.channel is not None:
            if not context.channel.enabled:
                return fail(RejectionReason.CHANNEL_DISABLED, "Canal desactive", "channel_enabled")
            if effective.mode is ChannelMode.OBSERVE and not context.manual_override:
                return fail(
                    RejectionReason.CHANNEL_OBSERVE_MODE,
                    "Canal en mode observation : aucun ordre n'est envoye",
                    "channel_mode",
                )
        ok("channel")

        # ------------------------------------------------------------------
        # 3. Compte et mode d'execution
        # ------------------------------------------------------------------
        if execution_mode in (ExecutionMode.MT5_DEMO, ExecutionMode.MT5_LIVE):
            if not context.mt5_connected:
                return fail(RejectionReason.MT5_DISCONNECTED, "MetaTrader 5 n'est pas connecte", "mt5")
            if context.account is None:
                return fail(
                    RejectionReason.MT5_DISCONNECTED, "Informations de compte MT5 indisponibles", "account"
                )
            account_kind = context.account.kind
            if execution_mode is ExecutionMode.MT5_LIVE:
                if not context.settings.live_unlocked:
                    return fail(
                        RejectionReason.LIVE_NOT_UNLOCKED,
                        "Le mode reel n'a pas ete deverrouille explicitement",
                        "live_unlock",
                    )
            elif account_kind is AccountKind.REAL:
                return fail(
                    RejectionReason.ACCOUNT_MISMATCH,
                    "Le compte MT5 connecte est un compte REEL alors que le mode demande est DEMO",
                    "account_kind",
                )
            elif account_kind is AccountKind.UNKNOWN:
                return fail(
                    RejectionReason.ACCOUNT_MISMATCH,
                    "Impossible de determiner si le compte est demo ou reel : execution refusee",
                    "account_kind",
                )
            if not context.account.trade_allowed:
                return fail(
                    RejectionReason.MT5_DISCONNECTED,
                    "Le trading n'est pas autorise sur ce compte chez le courtier",
                    "trade_allowed",
                )
            if context.terminal_algo_allowed is False:
                # Sans ce controle, l'ordre partait et MetaTrader le refusait
                # avec un code technique illisible. Mieux vaut expliquer ce
                # qu'il y a a faire, et ou.
                return fail(
                    RejectionReason.MT5_DISCONNECTED,
                    "Le trading algorithmique est desactive dans MetaTrader 5. "
                    "Ouvrez le terminal, menu Outils > Options > Expert Advisors, "
                    "et cochez « Autoriser le trading algorithmique ».",
                    "terminal_algo_allowed",
                )
        ok("execution_mode", execution_mode.value)

        # ------------------------------------------------------------------
        # 4. Contenu du signal
        # ------------------------------------------------------------------
        if not signal.is_signal or signal.symbol is None or signal.direction is None:
            return fail(RejectionReason.NO_ACTION, "Message sans intention de trade exploitable", "signal")
        ok("signal")

        if signal.confidence < effective.min_confidence and not context.manual_override:
            return fail(
                RejectionReason.LOW_CONFIDENCE,
                f"Confiance {signal.confidence:.2f} inferieure au minimum {effective.min_confidence:.2f}",
                "confidence",
            )
        ok("confidence", f"{signal.confidence:.2f}")

        if signal.direction is Direction.BUY and not effective.copy_buy:
            return fail(RejectionReason.DIRECTION_NOT_ALLOWED, "Les achats ne sont pas copies", "direction")
        if signal.direction is Direction.SELL and not effective.copy_sell:
            return fail(RejectionReason.DIRECTION_NOT_ALLOWED, "Les ventes ne sont pas copiees", "direction")
        ok("direction", signal.direction.value)

        if effective.allowed_symbols and signal.symbol not in effective.allowed_symbols:
            return fail(
                RejectionReason.SYMBOL_NOT_ALLOWED,
                f"{signal.symbol} n'est pas dans la liste des instruments autorises",
                "symbol_allowed",
            )
        ok("symbol_allowed", signal.symbol)

        if effective.require_stop_loss and signal.stop_loss is None:
            return fail(
                RejectionReason.MISSING_STOP_LOSS, "Stop loss obligatoire et absent du signal", "stop_loss"
            )
        if effective.require_take_profit and not signal.take_profits:
            return fail(
                RejectionReason.MISSING_TAKE_PROFIT,
                "Take profit obligatoire et absent du signal",
                "take_profit",
            )
        ok("stop_take")

        # ------------------------------------------------------------------
        # 5. Fraicheur du signal : un vieux signal ne doit jamais partir
        # ------------------------------------------------------------------
        age_seconds = self._signal_age_seconds(signal, context)
        if age_seconds is not None and age_seconds > effective.max_signal_age_seconds:
            return fail(
                RejectionReason.SIGNAL_EXPIRED,
                f"Signal age de {int(age_seconds)}s (maximum {effective.max_signal_age_seconds}s)",
                "signal_age",
            )
        ok("signal_age", f"{int(age_seconds)}s" if age_seconds is not None else "inconnu")

        # ------------------------------------------------------------------
        # 6. Fenetres horaires
        # ------------------------------------------------------------------
        weekday = context.now.weekday()
        allowed_days = context.settings.trading_days or []
        if allowed_days and weekday not in allowed_days:
            return fail(
                RejectionReason.OUTSIDE_TRADING_DAYS, "Jour non autorise par les reglages", "trading_days"
            )
        start = _parse_hhmm(context.settings.trading_hours_start, time(0, 0))
        end = _parse_hhmm(context.settings.trading_hours_end, time(23, 59))
        current = context.now.timetz().replace(tzinfo=None)
        within = start <= current <= end if start <= end else (current >= start or current <= end)
        if not within:
            return fail(
                RejectionReason.OUTSIDE_TRADING_HOURS,
                f"Hors plage horaire autorisee ({context.settings.trading_hours_start}"
                f"-{context.settings.trading_hours_end} UTC)",
                "trading_hours",
            )
        ok("trading_window")

        # ------------------------------------------------------------------
        # 7. Instrument cote broker
        # ------------------------------------------------------------------
        symbol_info = context.symbol
        if symbol_info is None:
            return fail(
                RejectionReason.SYMBOL_NOT_FOUND,
                f"{signal.symbol} introuvable chez le broker",
                "symbol_available",
            )
        if not symbol_info.tradable:
            return fail(
                RejectionReason.MARKET_CLOSED,
                f"{symbol_info.name} n'est pas ouvert au trading en ce moment",
                "symbol_tradable",
            )
        ok("symbol_available", symbol_info.name)

        tick = context.tick
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            return fail(
                RejectionReason.MARKET_CLOSED, f"Aucune cotation disponible pour {symbol_info.name}", "quote"
            )
        spread_points = tick.spread_points(symbol_info.point)
        if spread_points > effective.max_spread_points:
            return fail(
                RejectionReason.SPREAD_TOO_HIGH,
                f"Spread {spread_points} points superieur au maximum {effective.max_spread_points}",
                "spread",
            )
        ok("spread", f"{spread_points} points")

        # ------------------------------------------------------------------
        # 8. Prix de reference et coherence
        # ------------------------------------------------------------------
        entry_price = self._resolve_entry_price(signal, tick)
        if entry_price is None or entry_price <= 0:
            return fail(RejectionReason.INVALID_ENTRY, "Prix d'entree indeterminable", "entry_price")

        stop_loss = signal.stop_loss
        if stop_loss is not None:
            wrong_side = (
                signal.direction is Direction.BUY and stop_loss >= entry_price
            ) or (signal.direction is Direction.SELL and stop_loss <= entry_price)
            if wrong_side:
                return fail(
                    RejectionReason.INVALID_STOP_LOSS,
                    "Stop loss du mauvais cote par rapport au prix d'execution",
                    "stop_side",
                )
            if not self._respects_broker_distance(entry_price, stop_loss, symbol_info):
                return fail(
                    RejectionReason.INVALID_STOP_LOSS,
                    f"Stop loss trop proche du prix : le broker exige {symbol_info.trade_stops_level} points",
                    "stop_distance",
                )
        ok("stop_side")

        risk_reward = self._risk_reward(signal, entry_price)
        if (
            effective.min_risk_reward is not None
            and risk_reward is not None
            and risk_reward < effective.min_risk_reward
        ):
                return fail(
                    RejectionReason.RR_TOO_LOW,
                    f"Ratio rendement/risque {risk_reward:.2f} inferieur au minimum "
                    f"{effective.min_risk_reward:.2f}",
                    "risk_reward",
                )
        ok("risk_reward", f"{risk_reward:.2f}" if risk_reward is not None else "non calculable")

        # ------------------------------------------------------------------
        # 9. Limites journalieres et drawdown
        #
        # Evaluees AVANT les limites d'exposition : lorsqu'une limite de perte
        # est atteinte, c'est le motif que l'utilisateur doit voir, meme si une
        # position est deja ouverte sur le meme instrument.
        # ------------------------------------------------------------------
        daily = self._check_daily_limits(context)
        if daily is not None:
            reason, detail = daily
            return fail(reason, detail, "daily_limits")
        ok("daily_limits")

        if (
            context.settings.max_consecutive_losses > 0
            and context.state.consecutive_losses >= context.settings.max_consecutive_losses
        ):
            return fail(
                RejectionReason.CONSECUTIVE_LOSSES,
                f"{context.state.consecutive_losses} pertes consecutives : seuil atteint",
                "consecutive_losses",
            )
        ok("consecutive_losses", str(context.state.consecutive_losses))

        # ------------------------------------------------------------------
        # 10. Limites d'exposition
        # ------------------------------------------------------------------
        positions = context.open_positions
        if len(positions) >= effective.max_positions:
            return fail(
                RejectionReason.MAX_POSITIONS,
                f"{len(positions)} positions ouvertes : maximum {effective.max_positions}",
                "max_positions",
            )
        same_symbol = [p for p in positions if p.symbol == symbol_info.name]
        if len(same_symbol) >= effective.max_positions_per_symbol:
            return fail(
                RejectionReason.MAX_POSITIONS_SYMBOL,
                f"{len(same_symbol)} position(s) deja ouverte(s) sur {symbol_info.name}",
                "max_positions_symbol",
            )
        exposure = sum(position.volume for position in positions)
        if exposure >= effective.max_total_exposure_lots:
            return fail(
                RejectionReason.MAX_EXPOSURE,
                f"Exposition totale {exposure:.2f} lots au plafond {effective.max_total_exposure_lots:.2f}",
                "exposure",
            )
        ok("exposure", f"{exposure:.2f} lots")

        # ------------------------------------------------------------------
        # 11. Volume
        # ------------------------------------------------------------------
        if stop_loss is None:
            return fail(
                RejectionReason.MISSING_STOP_LOSS,
                "Impossible de dimensionner la position sans stop loss",
                "lot",
            )
        service = self._service
        if service is None:
            return fail(RejectionReason.MT5_DISCONNECTED, "Aucun service de marche disponible", "lot")

        # Le risque cesse d'etre une constante : chaque signal est dimensionne
        # selon sa propre qualite. Le multiplicateur est borne a 1,0, donc il
        # ne peut que reduire le pourcentage configure.
        quality: QualityMultiplier | None = None
        risk_percent = effective.risk_percent
        if context.settings.dynamic_risk_enabled:
            quality = quality_multiplier(
                risk_percent=effective.risk_percent,
                risk_reward=weighted_risk_reward(
                    entry=entry_price,
                    stop_loss=stop_loss,
                    take_profits=signal.take_profits,
                    split_ratios=effective.split_ratios,
                ),
                spread_cost=spread_points * symbol_info.point,
                stop_distance=abs(entry_price - stop_loss),
                age_seconds=age_seconds,
                max_signal_age_seconds=effective.max_signal_age_seconds,
                consecutive_losses=context.state.consecutive_losses,
                warnings=signal.warnings,
                source=signal.source,
                day_risked_percent=context.state.day_risked_percent,
                max_daily_risk_percent=context.settings.max_daily_risk_percent,
                floor=context.settings.dynamic_risk_floor,
            )
            risk_percent = quality.sized_risk_percent
            checks.append(RiskCheck("risk_multiplier", True, quality.detail))

        lot = await calculate_lot(
            service=service,
            symbol=symbol_info,
            direction=signal.direction,
            entry=entry_price,
            stop_loss=stop_loss,
            balance=context.balance,
            risk_percent=risk_percent,
            max_lot=effective.max_lot,
        )
        if not lot.ok or lot.volume is None:
            motif = _explain_volume_failure(
                lot=lot,
                quality=quality,
                configured_risk_percent=effective.risk_percent,
                sized_risk_percent=risk_percent,
                balance=context.balance,
            )
            return fail(RejectionReason.INVALID_VOLUME, motif, "lot")
        checks.append(RiskCheck("lot", True, f"{lot.volume} lots"))

        if lot.loss_at_stop is not None and context.balance > 0:
            effective_risk = lot.loss_at_stop / context.balance * 100
            if effective_risk > effective.risk_percent * 1.5:
                return fail(
                    RejectionReason.RISK_TOO_HIGH,
                    f"Risque effectif {effective_risk:.2f}% trop eloigne de la cible "
                    f"{effective.risk_percent:.2f}%",
                    "effective_risk",
                )
        ok("effective_risk")

        # Le plafond journalier ne comparait que le cumul ANTERIEUR : un seul
        # trade pouvait donc terminer la journee tres au-dessus de la limite.
        # On verifie desormais le cumul PROJETE, sur la perte reelle au stop.
        risk_limit = context.settings.max_daily_risk_percent
        if risk_limit > 0 and lot.loss_at_stop is not None and context.balance > 0:
            projected = context.state.day_risked_percent + lot.loss_at_stop / context.balance * 100
            if projected > risk_limit:
                return fail(
                    RejectionReason.DAILY_RISK_LIMIT,
                    f"Risque cumule projete {projected:.2f}% : limite {risk_limit:.2f}%",
                    "daily_risk_projected",
                )
        ok("daily_risk_projected")

        # Meme trou sur l'exposition : le lot a venir n'etait pas compte.
        projected_exposure = exposure + lot.volume
        if projected_exposure > effective.max_total_exposure_lots + 1e-9:
            return fail(
                RejectionReason.MAX_EXPOSURE,
                f"Exposition projetee {projected_exposure:.2f} lots au-dela du plafond "
                f"{effective.max_total_exposure_lots:.2f}",
                "exposure_projected",
            )
        ok("exposure_projected")

        # ------------------------------------------------------------------
        # 12. Marge
        # ------------------------------------------------------------------
        try:
            margin = await service.calculate_margin(
                symbol_info.name, signal.direction, lot.volume, entry_price
            )
        except Exception as exc:  # pragma: no cover - depend du terminal
            logger.debug("calculate_margin indisponible : %s", exc)
            margin = None
        if (
            margin is not None
            and context.account is not None
            and margin > context.account.margin_free
        ):
                return fail(
                    RejectionReason.INSUFFICIENT_MARGIN,
                    f"Marge requise {margin:.2f} superieure a la marge libre "
                    f"{context.account.margin_free:.2f}",
                    "margin",
                )
        ok("margin", f"{margin:.2f}" if margin is not None else "non evaluee")

        return RiskDecision(
            approved=True,
            checks=checks,
            lot=lot,
            effective=effective,
            entry_price=entry_price,
            risk_reward=risk_reward,
        )

    # ------------------------------------------------------------------
    # Aides internes
    # ------------------------------------------------------------------
    @staticmethod
    def _signal_age_seconds(signal: ParsedSignal, context: RiskContext) -> float | None:
        message_date = getattr(signal, "message_date", None)
        if message_date is None:
            return None
        if message_date.tzinfo is None:
            message_date = message_date.replace(tzinfo=UTC)
        return (context.now - message_date).total_seconds()

    @staticmethod
    def _resolve_entry_price(signal: ParsedSignal, tick: Tick) -> float | None:
        """Prix retenu pour les controles et le calcul du volume."""
        market_price = tick.ask if signal.direction is Direction.BUY else tick.bid
        if signal.entry_price is not None:
            return signal.entry_price
        if signal.entry_min is not None and signal.entry_max is not None:
            # Dans la zone : on utilise le cours courant, sinon la borne la plus favorable.
            if signal.entry_min <= market_price <= signal.entry_max:
                return market_price
            return signal.entry_max if signal.direction is Direction.SELL else signal.entry_min
        return market_price

    @staticmethod
    def _respects_broker_distance(entry: float, stop: float, symbol: SymbolInfo) -> bool:
        if symbol.trade_stops_level <= 0:
            return abs(entry - stop) > 0
        return points_between(entry, stop, symbol) >= symbol.trade_stops_level

    @staticmethod
    def _risk_reward(signal: ParsedSignal, entry_price: float) -> float | None:
        if signal.stop_loss is None or not signal.take_profits:
            return None
        risk = abs(entry_price - signal.stop_loss)
        if risk <= 0:
            return None
        reward = abs(signal.take_profits[0] - entry_price)
        return reward / risk

    @staticmethod
    def _check_daily_limits(context: RiskContext) -> tuple[RejectionReason, str] | None:
        settings = context.settings
        state = context.state
        start_balance = state.day_start_balance or context.balance
        if start_balance <= 0:
            return None

        realized = state.day_realized_pnl
        if settings.max_daily_loss_percent > 0:
            loss_percent = -realized / start_balance * 100 if realized < 0 else 0.0
            if loss_percent >= settings.max_daily_loss_percent:
                return (
                    RejectionReason.DAILY_LOSS_LIMIT,
                    f"Perte du jour {loss_percent:.2f}% : limite {settings.max_daily_loss_percent:.2f}%",
                )

        risk_limit = settings.max_daily_risk_percent
        if risk_limit > 0 and state.day_risked_percent >= risk_limit:
            return (
                RejectionReason.DAILY_RISK_LIMIT,
                f"Risque cumule du jour {state.day_risked_percent:.2f}% : limite "
                f"{settings.max_daily_risk_percent:.2f}%",
            )

        if settings.daily_profit_target_percent is not None and realized > 0:
            profit_percent = realized / start_balance * 100
            if profit_percent >= settings.daily_profit_target_percent:
                return (
                    RejectionReason.DAILY_PROFIT_TARGET,
                    f"Objectif de gain journalier atteint ({profit_percent:.2f}%)",
                )

        if settings.max_drawdown_percent > 0 and state.peak_equity:
            drawdown = (state.peak_equity - context.equity) / state.peak_equity * 100
            if drawdown >= settings.max_drawdown_percent:
                return (
                    RejectionReason.MAX_DRAWDOWN,
                    f"Drawdown {drawdown:.2f}% : limite {settings.max_drawdown_percent:.2f}%",
                )
        return None
