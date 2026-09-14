"""Calcul deterministe des niveaux (CDC2 section 41).

INTERDICTION ABSOLUE : aucune intelligence artificielle ne fixe un prix. Entry,
Stop Loss et Take Profit sortent d'ici, et d'ici seulement, a partir de :

 - la structure relevee sur le graphique (swings, supports, resistances) ;
 - la volatilite mesuree (ATR) ;
 - des multiples de risque fixes a l'avance.

Les modeles interviennent apres, pour interpreter et expliquer. Si la
structure ne permet pas de calculer un plan coherent, ce module rend ``None``
et le systeme ne trade pas : il ne comble jamais un trou par une estimation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config.logging_config import get_logger
from app.models.enums import Direction
from app.services.decision.inputs import PriceStructure, TradeLevels

logger = get_logger(__name__)


@dataclass(slots=True)
class PlannerConfig:
    """Regles de calcul, toutes exprimees en multiples d'ATR ou de risque."""

    # Demi-largeur de la zone d'entree, en ATR.
    entry_band_atr: float = 0.25
    # Marge ajoutee au-dela du niveau structurel pour placer le stop.
    stop_buffer_atr: float = 0.30
    # Stop de repli quand aucune structure exploitable n'est disponible.
    fallback_stop_atr: float = 1.50
    # Distance minimale entre entree et stop, en ATR : un stop colle saute.
    min_stop_atr: float = 0.40
    # Distance maximale acceptee : au-dela, le setup n'est plus finançable.
    max_stop_atr: float = 4.0
    # Multiples de risque des cibles successives.
    target_multiples: tuple[float, ...] = (1.0, 2.0, 3.0)
    # RR minimal pour qu'un obstacle structurel serve de premiere cible.
    min_structural_rr: float = 1.0

    def __post_init__(self) -> None:
        if not self.target_multiples:
            raise ValueError("Au moins une cible doit être configurée.")
        if self.min_stop_atr >= self.max_stop_atr:
            raise ValueError("min_stop_atr doit rester inférieur à max_stop_atr.")


@dataclass(slots=True)
class PlanRejection:
    """Pourquoi aucun plan n'a pu etre calcule."""

    code: str
    message: str


@dataclass(slots=True)
class PlanResult:
    """Plan calcule, ou refus motive. Jamais les deux."""

    levels: TradeLevels | None = None
    rejections: list[PlanRejection] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.levels is not None


class LevelPlanner:
    """Traduit une direction et une structure en un plan de trade chiffre."""

    def __init__(self, config: PlannerConfig | None = None) -> None:
        self._config = config or PlannerConfig()

    @property
    def config(self) -> PlannerConfig:
        return self._config

    # ------------------------------------------------------------------
    def plan(self, direction: Direction, structure: PriceStructure) -> PlanResult:
        """Calcule entree, stop et cibles. Rend un refus motive sinon."""
        config = self._config

        if structure.last_price <= 0:
            return PlanResult(rejections=[PlanRejection("NO_PRICE", "Prix de référence inconnu.")])
        atr = structure.atr
        if atr is None or atr <= 0:
            return PlanResult(
                rejections=[
                    PlanRejection(
                        "NO_VOLATILITY",
                        "Volatilité (ATR) indisponible : aucun niveau ne peut être calculé.",
                    )
                ]
            )

        entry = structure.last_price
        band = config.entry_band_atr * atr
        entry_min = self._round(entry - band, structure.digits)
        entry_max = self._round(entry + band, structure.digits)

        stop, method = self._stop_for(direction, entry, atr, structure)
        if stop is None:
            return PlanResult(
                rejections=[
                    PlanRejection("NO_STOP", "Aucun stop loss cohérent ne peut être placé.")
                ]
            )

        risk = abs(entry - stop)
        if risk < config.min_stop_atr * atr:
            return PlanResult(
                rejections=[
                    PlanRejection(
                        "STOP_TOO_CLOSE",
                        f"Stop trop proche de l'entrée : {risk / atr:.2f} ATR pour un minimum "
                        f"de {config.min_stop_atr:.2f}.",
                    )
                ]
            )
        if risk > config.max_stop_atr * atr:
            return PlanResult(
                rejections=[
                    PlanRejection(
                        "STOP_TOO_FAR",
                        f"Stop trop éloigné : {risk / atr:.2f} ATR pour un maximum "
                        f"de {config.max_stop_atr:.2f}.",
                    )
                ]
            )

        targets = self._targets(direction, entry, risk, structure)
        if not targets:
            return PlanResult(
                rejections=[
                    PlanRejection("NO_TARGET", "Aucune cible exploitable au-delà de l'entrée.")
                ]
            )

        first_rr = abs(targets[0] - entry) / risk
        last_rr = abs(targets[-1] - entry) / risk
        levels = TradeLevels(
            direction=direction,
            entry_price=self._round(entry, structure.digits),
            entry_min=min(entry_min, entry_max),
            entry_max=max(entry_min, entry_max),
            stop_loss=self._round(stop, structure.digits),
            take_profits=targets,
            expected_rr=round(last_rr, 2),
            first_target_rr=round(first_rr, 2),
            risk_distance=round(risk, structure.digits + 2),
            method=method,
        )
        if not levels.valid:
            return PlanResult(
                rejections=[
                    PlanRejection("INVALID_PLAN", "Le plan calculé est incohérent après arrondi.")
                ]
            )
        return PlanResult(levels=levels)

    # ------------------------------------------------------------------
    def _stop_for(
        self,
        direction: Direction,
        entry: float,
        atr: float,
        structure: PriceStructure,
    ) -> tuple[float | None, str]:
        """Stop derriere le niveau structurel le plus proche, sinon a l'ATR.

        On retient le niveau le plus proche de l'entree : c'est lui qui
        invalide le scenario. La marge d'ATR evite un stop pose exactement sur
        le niveau, la ou le bruit va le chercher.
        """
        config = self._config
        buffer_ = config.stop_buffer_atr * atr

        if direction is Direction.BUY:
            candidates = (structure.swing_low, structure.nearest_support(entry))
            anchors = [level for level in candidates if level is not None and level < entry]
            if anchors:
                return max(anchors) - buffer_, "structure+atr"
            return entry - config.fallback_stop_atr * atr, "atr"

        candidates = (structure.swing_high, structure.nearest_resistance(entry))
        anchors = [level for level in candidates if level is not None and level > entry]
        if anchors:
            return min(anchors) + buffer_, "structure+atr"
        return entry + config.fallback_stop_atr * atr, "atr"

    def _targets(
        self,
        direction: Direction,
        entry: float,
        risk: float,
        structure: PriceStructure,
    ) -> list[float]:
        """Cibles a multiples de risque, la premiere calee sur la structure."""
        config = self._config
        sign = 1.0 if direction is Direction.BUY else -1.0
        obstacle = (
            structure.nearest_resistance(entry)
            if direction is Direction.BUY
            else structure.nearest_support(entry)
        )

        targets: list[float] = []
        first = entry + sign * config.target_multiples[0] * risk
        if obstacle is not None:
            structural_rr = abs(obstacle - entry) / risk
            # L'obstacle sert de premiere cible seulement s'il est a la fois
            # assez loin pour valoir le risque, et pas plus loin que la cible
            # la plus ambitieuse du plan : au-dela, il n'a plus rien d'un
            # objectif atteignable.
            if config.min_structural_rr <= structural_rr <= max(config.target_multiples):
                first = obstacle
        targets.append(first)

        for multiple in config.target_multiples[1:]:
            targets.append(entry + sign * multiple * risk)

        cleaned: list[float] = []
        for value in targets:
            rounded = self._round(value, structure.digits)
            if direction is Direction.BUY and rounded <= entry:
                continue
            if direction is Direction.SELL and rounded >= entry:
                continue
            if rounded not in cleaned:
                cleaned.append(rounded)
        cleaned.sort(reverse=direction is Direction.SELL)
        return cleaned

    @staticmethod
    def _round(value: float, digits: int) -> float:
        return round(value, max(0, min(8, digits)))


level_planner = LevelPlanner()

__all__ = [
    "LevelPlanner",
    "PlanRejection",
    "PlanResult",
    "PlannerConfig",
    "level_planner",
]
