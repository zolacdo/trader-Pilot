"""Risk Manager du Market Watcher (CDC3 section 30).

C'est le module le plus important du sous-systeme : il peut refuser un signal
que tout le reste juge excellent. Aucun score, aucune IA, aucune insistance ne
passe au-dessus de lui.

Il est volontairement pur : il ne lit ni la base ni le reseau. L'etat du
portefeuille lui est fourni par l'appelant, ce qui le rend entierement
testable et empeche qu'un acces base en panne le rende permissif par accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.models.core import as_utc, utcnow
from app.models.enums import Direction
from app.watcher.analysis.context import MarketContext
from app.watcher.config import WatcherConfig
from app.watcher.levels import TradeLevels
from app.watcher.models import RiskVerdict, VolatilityLevel
from app.watcher.scoring import ScoreCard

# Couverture minimale des criteres. En dessous, trop de donnees manquent pour
# qu'un score ait un sens, quel que soit son niveau.
MIN_COVERAGE = 0.45


@dataclass(slots=True)
class PortfolioState:
    """Ce que le watcher a deja en cours. Fourni par l'appelant."""

    active_signals: int = 0
    signals_today: int = 0
    active_same_symbol: int = 0
    active_same_direction: bool = False
    last_signal_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "activeSignals": self.active_signals,
            "signalsToday": self.signals_today,
            "activeSameSymbol": self.active_same_symbol,
            "activeSameDirection": self.active_same_direction,
            "lastSignalAt": self.last_signal_at.isoformat() if self.last_signal_at else None,
        }


@dataclass(slots=True)
class RiskDecision:
    """Verdict motive. ``reasons`` liste tout ce qui a bloque, pas seulement le premier."""

    verdict: RiskVerdict = RiskVerdict.APPROVED
    reasons: list[str] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.verdict is RiskVerdict.APPROVED

    @property
    def reason(self) -> str | None:
        return self.reasons[0] if self.reasons else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
        }


def evaluate(
    context: MarketContext,
    direction: Direction,
    levels: TradeLevels | None,
    card: ScoreCard | None,
    config: WatcherConfig,
    state: PortfolioState,
    now: datetime | None = None,
) -> RiskDecision:
    """Passe toutes les protections. Le premier REJECTED l'emporte sur un WAIT."""
    moment = now or utcnow()
    rejections: list[str] = []
    waits: list[str] = []

    # --- disponibilite du marche et des donnees -----------------------------
    if context.market_open is False:
        rejections.append("Marche ferme sur cet instrument.")
    if not context.quality.sufficient:
        rejections.append(f"Donnees insuffisantes : {context.quality.detail}")
    elif not context.quality.fresh:
        rejections.append(f"Donnees trop anciennes : {context.quality.detail}")
    if context.primary is None or not context.primary.usable:
        rejections.append("Analyse technique inexploitable sur cet instrument.")

    # --- qualite du setup ---------------------------------------------------
    if levels is None or not levels.valid:
        motif = levels.rejection if levels is not None else "Niveaux non calculables."
        rejections.append(motif or "Niveaux non calculables.")
    if card is None:
        rejections.append("Aucun score calculable.")
    else:
        if card.coverage < MIN_COVERAGE:
            rejections.append(
                f"Couverture des criteres trop faible ({round(card.coverage * 100)} %) : "
                "trop de donnees manquantes pour decider."
            )
        if card.score < config.minimum_score:
            waits.append(
                f"Score {round(card.score, 1)} sous le minimum exige ({config.minimum_score})."
            )

    # --- conditions de marche ----------------------------------------------
    spread_reason = _check_spread(context, config)
    if spread_reason is not None:
        waits.append(spread_reason)

    if config.block_extreme_volatility and context.volatility.level is VolatilityLevel.EXTREME:
        rejections.append(f"Volatilite extreme : {context.volatility.detail}")

    if context.news_guard.blocking:
        waits.append(
            context.news_guard.reason
            or "Annonce economique majeure imminente : nouvelles entrees suspendues."
        )

    # --- anti-doublon et cadence (CDC3 section 31) --------------------------
    if state.active_same_direction:
        rejections.append(
            f"Un signal {direction.value} est deja actif sur {context.symbol} : "
            "aucun doublon ne sera publie."
        )
    if state.active_signals >= config.max_active_signals:
        waits.append(
            f"{state.active_signals} signaux deja actifs : plafond de "
            f"{config.max_active_signals} atteint."
        )
    if state.signals_today >= config.max_signals_per_day:
        waits.append(
            f"{state.signals_today} signaux publies aujourd'hui : plafond quotidien de "
            f"{config.max_signals_per_day} atteint."
        )

    cooldown = _check_cooldown(state, config, moment)
    if cooldown is not None:
        waits.append(cooldown)

    if rejections:
        return RiskDecision(verdict=RiskVerdict.REJECTED, reasons=rejections + waits)
    if waits:
        return RiskDecision(verdict=RiskVerdict.WAIT, reasons=waits)
    return RiskDecision(verdict=RiskVerdict.APPROVED, reasons=[])


def _check_spread(context: MarketContext, config: WatcherConfig) -> str | None:
    """Spread en points, puis rapporte a l'ATR.

    Les deux comptent : soixante points sont enormes sur EURUSD et negligeables
    sur US30. Seule la comparaison a l'ATR a un sens universel, mais le plafond
    en points protege des elargissements brutaux hors seance.
    """
    quote = context.quote
    if quote is None:
        return None
    if quote.spread_points is not None and quote.spread_points > config.max_spread_points:
        return (
            f"Spread de {quote.spread_points} points, au-dela du maximum tolere "
            f"({config.max_spread_points})."
        )
    analysis = context.primary
    if (
        quote.spread_price
        and analysis is not None
        and analysis.atr
        and analysis.atr > 0
        and quote.spread_price > analysis.atr * config.max_spread_atr_ratio
    ):
        part = round(quote.spread_price / analysis.atr * 100)
        return f"Spread egal a {part} % de l'ATR : le cout d'entree ampute le setup."
    return None


def _check_cooldown(
    state: PortfolioState, config: WatcherConfig, now: datetime
) -> str | None:
    """Delai minimal entre deux signaux sur le meme instrument."""
    last = as_utc(state.last_signal_at)
    if last is None or config.cooldown_minutes <= 0:
        return None
    elapsed = now - last
    minimum = timedelta(minutes=config.cooldown_minutes)
    if elapsed >= minimum:
        return None
    remaining = int((minimum - elapsed).total_seconds() // 60) + 1
    return (
        f"Dernier signal sur cet instrument il y a {int(elapsed.total_seconds() // 60)} minute(s) : "
        f"nouvelle publication possible dans {remaining} minute(s)."
    )


__all__ = ["MIN_COVERAGE", "PortfolioState", "RiskDecision", "evaluate"]
