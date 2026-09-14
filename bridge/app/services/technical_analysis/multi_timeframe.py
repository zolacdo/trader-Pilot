"""Analyse multi-timeframes (CDC2 section 19).

Chaque unite de temps joue un role different : contexte, structure, declencheur
ou confirmation. Ces roles ne sont pas figes : ils sont decrits par un profil,
choisi par strategie et entierement configurable.

Exemple de sortie : D1=BULLISH, H4=BULLISH, H1=PULLBACK, M15=REVERSAL_TRIGGER,
M5=ENTRY_CONFIRMATION.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from app.models.intelligence import Timeframe, TrendState
from app.services.technical_analysis.engine import TechnicalAnalysis, TechnicalAnalysisEngine

if TYPE_CHECKING:  # pragma: no cover - uniquement pour le typage
    from app.services.market_data.engine import MarketDataEngine


class TimeframeRole(StrEnum):
    """Role joue par une unite de temps dans une strategie."""

    CONTEXT = "CONTEXT"
    STRUCTURE = "STRUCTURE"
    TRIGGER = "TRIGGER"
    CONFIRMATION = "CONFIRMATION"


# Etats produits, volontairement explicites.
STATE_BULLISH = "BULLISH"
STATE_BEARISH = "BEARISH"
STATE_NEUTRAL = "NEUTRAL"
STATE_RANGING = "RANGING"
STATE_PULLBACK = "PULLBACK"
STATE_BREAKOUT_UP = "BREAKOUT_UP"
STATE_BREAKOUT_DOWN = "BREAKOUT_DOWN"
STATE_REVERSAL_TRIGGER = "REVERSAL_TRIGGER"
STATE_BREAKOUT_TRIGGER = "BREAKOUT_TRIGGER"
STATE_CONTINUATION_TRIGGER = "CONTINUATION_TRIGGER"
STATE_NO_TRIGGER = "NO_TRIGGER"
STATE_ENTRY_CONFIRMATION = "ENTRY_CONFIRMATION"
STATE_WAIT = "WAIT"
STATE_NO_DATA = "NO_DATA"


@dataclass(slots=True)
class TimeframeProfile:
    """Repartition des roles entre unites de temps, pour une strategie."""

    name: str
    roles: dict[Timeframe, TimeframeRole] = field(default_factory=dict)

    @property
    def timeframes(self) -> list[Timeframe]:
        return list(self.roles.keys())

    def of_role(self, role: TimeframeRole) -> list[Timeframe]:
        return [frame for frame, value in self.roles.items() if value is role]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "roles": {f.value: r.value for f, r in self.roles.items()}}


def build_profile(name: str, mapping: dict[str, str]) -> TimeframeProfile:
    """Construit un profil depuis une configuration ``{"H1": "STRUCTURE"}``.

    Les entrees inconnues sont ignorees : un profil mal saisi ne doit jamais
    faire tomber l'analyse.
    """
    roles: dict[Timeframe, TimeframeRole] = {}
    for raw_frame, raw_role in mapping.items():
        try:
            frame = Timeframe(str(raw_frame).strip().upper())
            role = TimeframeRole(str(raw_role).strip().upper())
        except ValueError:
            continue
        roles[frame] = role
    return TimeframeProfile(name=name, roles=roles)


DEFAULT_PROFILE = TimeframeProfile(
    name="default",
    roles={
        Timeframe.D1: TimeframeRole.CONTEXT,
        Timeframe.H4: TimeframeRole.CONTEXT,
        Timeframe.H1: TimeframeRole.STRUCTURE,
        Timeframe.M30: TimeframeRole.STRUCTURE,
        Timeframe.M15: TimeframeRole.TRIGGER,
        Timeframe.M5: TimeframeRole.CONFIRMATION,
    },
)

SCALPING_PROFILE = TimeframeProfile(
    name="scalping",
    roles={
        Timeframe.H1: TimeframeRole.CONTEXT,
        Timeframe.M15: TimeframeRole.STRUCTURE,
        Timeframe.M5: TimeframeRole.TRIGGER,
        Timeframe.M1: TimeframeRole.CONFIRMATION,
    },
)

SWING_PROFILE = TimeframeProfile(
    name="swing",
    roles={
        Timeframe.W1: TimeframeRole.CONTEXT,
        Timeframe.D1: TimeframeRole.CONTEXT,
        Timeframe.H4: TimeframeRole.STRUCTURE,
        Timeframe.H1: TimeframeRole.STRUCTURE,
        Timeframe.M30: TimeframeRole.TRIGGER,
        Timeframe.M15: TimeframeRole.CONFIRMATION,
    },
)

PROFILES: dict[str, TimeframeProfile] = {
    DEFAULT_PROFILE.name: DEFAULT_PROFILE,
    SCALPING_PROFILE.name: SCALPING_PROFILE,
    SWING_PROFILE.name: SWING_PROFILE,
}


def profile_for(strategy: str | None) -> TimeframeProfile:
    """Profil d'une strategie. Une strategie inconnue retombe sur le defaut."""
    if not strategy:
        return DEFAULT_PROFILE
    return PROFILES.get(strategy.strip().lower(), DEFAULT_PROFILE)


@dataclass(slots=True)
class TimeframeVerdict:
    """Ce que dit une unite de temps, compte tenu de son role."""

    timeframe: Timeframe
    role: TimeframeRole
    state: str
    trend: TrendState = TrendState.NEUTRAL
    detail: str = ""
    analysis: TechnicalAnalysis | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe.value,
            "role": self.role.value,
            "state": self.state,
            "trend": self.trend.value,
            "detail": self.detail,
        }


@dataclass(slots=True)
class MultiTimeframeView:
    """Vue consolidee : un etat par unite de temps et un biais global."""

    symbol: str
    profile: str
    verdicts: list[TimeframeVerdict] = field(default_factory=list)
    bias: TrendState = TrendState.NEUTRAL
    alignment: float = 0.0
    trigger: str | None = None
    conflicts: list[str] = field(default_factory=list)

    def states(self) -> dict[str, str]:
        return {verdict.timeframe.value: verdict.state for verdict in self.verdicts}

    def analysis_for(self, timeframe: Timeframe) -> TechnicalAnalysis | None:
        for verdict in self.verdicts:
            if verdict.timeframe is timeframe:
                return verdict.analysis
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "profile": self.profile,
            "bias": self.bias.value,
            "alignment": self.alignment,
            "trigger": self.trigger,
            "states": self.states(),
            "timeframes": [verdict.to_dict() for verdict in self.verdicts],
            "conflicts": list(self.conflicts),
        }


class MultiTimeframeAnalyzer:
    """Applique le moteur technique a plusieurs unites de temps, puis recoupe."""

    def __init__(self, technical: TechnicalAnalysisEngine | None = None) -> None:
        self._technical = technical or TechnicalAnalysisEngine()

    async def analyse(
        self,
        data_engine: MarketDataEngine,
        symbol: str,
        profile: TimeframeProfile | None = None,
        bars: int = 200,
    ) -> MultiTimeframeView:
        """Recupere les bougies de chaque unite de temps puis consolide."""
        selected = profile or DEFAULT_PROFILE
        analyses: dict[Timeframe, TechnicalAnalysis] = {}
        for frame in selected.timeframes:
            candles = await data_engine.candles(symbol, frame, bars)
            analyses[frame] = self._technical.analyse(symbol, frame, candles)
        return self.combine(symbol, selected, analyses)

    def combine(
        self,
        symbol: str,
        profile: TimeframeProfile,
        analyses: dict[Timeframe, TechnicalAnalysis],
    ) -> MultiTimeframeView:
        """Consolide des analyses deja calculees : totalement deterministe."""
        view = MultiTimeframeView(symbol=symbol, profile=profile.name)
        bias = self._bias(profile, analyses)
        view.bias = bias
        for frame, role in profile.roles.items():
            analysis = analyses.get(frame)
            view.verdicts.append(self._verdict(frame, role, analysis, bias))
        view.alignment = self._alignment(view, bias)
        view.trigger = self._trigger(view)
        view.conflicts = self._conflicts(view, bias)
        return view

    # ------------------------------------------------------------------
    # Regles
    # ------------------------------------------------------------------
    def _bias(
        self, profile: TimeframeProfile, analyses: dict[Timeframe, TechnicalAnalysis]
    ) -> TrendState:
        """Biais donne par les seules unites de temps de contexte."""
        score = 0
        for frame in profile.of_role(TimeframeRole.CONTEXT):
            analysis = analyses.get(frame)
            if analysis is None or not analysis.usable:
                continue
            if analysis.trend is TrendState.BULLISH:
                score += 1
            elif analysis.trend is TrendState.BEARISH:
                score -= 1
        if score > 0:
            return TrendState.BULLISH
        if score < 0:
            return TrendState.BEARISH
        return TrendState.NEUTRAL

    def _verdict(
        self,
        frame: Timeframe,
        role: TimeframeRole,
        analysis: TechnicalAnalysis | None,
        bias: TrendState,
    ) -> TimeframeVerdict:
        if analysis is None or not analysis.usable:
            return TimeframeVerdict(
                timeframe=frame,
                role=role,
                state=STATE_NO_DATA,
                detail="Historique insuffisant sur cette unité de temps.",
                analysis=analysis,
            )
        state = {
            TimeframeRole.CONTEXT: self._context_state,
            TimeframeRole.STRUCTURE: self._structure_state,
            TimeframeRole.TRIGGER: self._trigger_state,
            TimeframeRole.CONFIRMATION: self._confirmation_state,
        }[role](analysis, bias)
        detail = analysis.reasons[0] if analysis.reasons else ""
        return TimeframeVerdict(
            timeframe=frame, role=role, state=state, trend=analysis.trend, detail=detail,
            analysis=analysis,
        )

    def _context_state(self, analysis: TechnicalAnalysis, bias: TrendState) -> str:
        if analysis.range_reading.is_range and analysis.trend is TrendState.NEUTRAL:
            return STATE_RANGING
        return analysis.trend.value

    def _structure_state(self, analysis: TechnicalAnalysis, bias: TrendState) -> str:
        if analysis.breakout == "UP":
            return STATE_BREAKOUT_UP
        if analysis.breakout == "DOWN":
            return STATE_BREAKOUT_DOWN
        if analysis.pullback is not None:
            return STATE_PULLBACK
        if analysis.range_reading.is_range and analysis.trend is TrendState.NEUTRAL:
            return STATE_RANGING
        return analysis.trend.value

    def _trigger_state(self, analysis: TechnicalAnalysis, bias: TrendState) -> str:
        wanted = "UP" if bias is TrendState.BULLISH else "DOWN"
        event = analysis.break_event
        if event is not None and event.kind == "CHOCH" and (
            bias is TrendState.NEUTRAL or event.direction == wanted
        ):
            return STATE_REVERSAL_TRIGGER
        if analysis.breakout is not None and (
            bias is TrendState.NEUTRAL or analysis.breakout == wanted
        ):
            return STATE_BREAKOUT_TRIGGER
        if event is not None and event.kind == "BOS" and (
            bias is TrendState.NEUTRAL or event.direction == wanted
        ):
            return STATE_CONTINUATION_TRIGGER
        return STATE_NO_TRIGGER

    def _confirmation_state(self, analysis: TechnicalAnalysis, bias: TrendState) -> str:
        if analysis.momentum is None or bias is TrendState.NEUTRAL:
            return STATE_WAIT
        aligned = analysis.momentum > 0 if bias is TrendState.BULLISH else analysis.momentum < 0
        if aligned and analysis.trend is not _opposite(bias):
            return STATE_ENTRY_CONFIRMATION
        return STATE_WAIT

    def _alignment(self, view: MultiTimeframeView, bias: TrendState) -> float:
        """Part des unites contexte et structure compatibles avec le biais."""
        if bias is TrendState.NEUTRAL:
            return 0.0
        considered = [
            verdict
            for verdict in view.verdicts
            if verdict.role in (TimeframeRole.CONTEXT, TimeframeRole.STRUCTURE)
            and verdict.state != STATE_NO_DATA
        ]
        if not considered:
            return 0.0
        total = 0.0
        for verdict in considered:
            if verdict.trend is bias:
                total += 1.0
            elif verdict.trend is TrendState.NEUTRAL:
                total += 0.5
        return round(total / len(considered), 3)

    def _trigger(self, view: MultiTimeframeView) -> str | None:
        for verdict in view.verdicts:
            if verdict.role is TimeframeRole.TRIGGER and verdict.state != STATE_NO_DATA:
                return verdict.state
        return None

    def _conflicts(self, view: MultiTimeframeView, bias: TrendState) -> list[str]:
        """Desaccords explicites, affiches tels quels a l'utilisateur."""
        if bias is TrendState.NEUTRAL:
            return ["Aucun biais clair : les unités de temps de contexte se contredisent."]
        conflicts: list[str] = []
        for verdict in view.verdicts:
            if verdict.state == STATE_NO_DATA:
                continue
            if verdict.trend is _opposite(bias):
                conflicts.append(
                    f"{verdict.timeframe.value} va contre le biais {bias.value}."
                )
        return conflicts


def _opposite(trend: TrendState) -> TrendState:
    if trend is TrendState.BULLISH:
        return TrendState.BEARISH
    if trend is TrendState.BEARISH:
        return TrendState.BULLISH
    return TrendState.NEUTRAL


__all__ = [
    "DEFAULT_PROFILE",
    "PROFILES",
    "SCALPING_PROFILE",
    "SWING_PROFILE",
    "MultiTimeframeAnalyzer",
    "MultiTimeframeView",
    "TimeframeProfile",
    "TimeframeRole",
    "TimeframeVerdict",
    "build_profile",
    "profile_for",
]
