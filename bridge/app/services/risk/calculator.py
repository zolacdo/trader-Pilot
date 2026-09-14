"""Calcul du volume a partir du risque reel du compte.

Aucune valeur de pip codee en dur : tout provient des metadonnees renvoyees
par MT5 pour le symbole concerne, et lorsque c'est possible de la fonction
``order_calc_profit`` du terminal, plus precise que l'arithmetique sur les
ticks (CDC section 24).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.config.logging_config import get_logger
from app.models.enums import Direction
from app.services.mt5.interface import MetaTraderService, SymbolInfo

logger = get_logger(__name__)


@dataclass(slots=True)
class LotCalculation:
    """Resultat du calcul de volume, tracable pour l'audit."""

    ok: bool
    volume: float | None = None
    risk_amount: float | None = None
    loss_at_stop: float | None = None
    loss_per_lot: float | None = None
    stop_distance: float | None = None
    stop_distance_points: int | None = None
    method: str = "tick_value"
    reason: str | None = None
    # Nature de l'echec, lisible par le code. Le RiskManager en a besoin pour
    # nommer la vraie cause : lui seul sait si le risque avait ete reduit en
    # amont, et le calculateur ne peut pas le deviner.
    cause: str | None = None
    # Perte au stop si l'on prenait le lot minimum du broker. Renseignee
    # uniquement quand le volume calcule passe sous ce minimum.
    minimum_lot_loss: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "volume": self.volume,
            "riskAmount": round(self.risk_amount, 2) if self.risk_amount is not None else None,
            "lossAtStop": round(self.loss_at_stop, 2) if self.loss_at_stop is not None else None,
            "lossPerLot": round(self.loss_per_lot, 2) if self.loss_per_lot is not None else None,
            "stopDistance": self.stop_distance,
            "stopDistancePoints": self.stop_distance_points,
            "method": self.method,
            "reason": self.reason,
            "cause": self.cause,
            "minimumLotLoss": (
                round(self.minimum_lot_loss, 2) if self.minimum_lot_loss is not None else None
            ),
            **self.details,
        }


# Le volume calcule est tombe sous le lot minimum du broker. Ce n'est PAS une
# cause en soi : c'est un symptome, dont l'origine est soit un risque reduit en
# amont, soit un compte trop petit pour la distance de stop.
CAUSE_BELOW_VOLUME_MIN = "below_volume_min"


def round_to_step(volume: float, step: float) -> float:
    """Arrondit vers le bas au pas de volume du broker."""
    if step <= 0:
        return round(volume, 2)
    steps = math.floor((volume + 1e-9) / step)
    rounded = steps * step
    # Nombre de decimales du pas (0.01 -> 2, 0.001 -> 3)
    formatted = f"{step:.10f}".rstrip("0")
    decimals = len(formatted.split(".")[1]) if "." in formatted else 0
    return round(rounded, decimals)


def points_between(price_a: float, price_b: float, symbol: SymbolInfo) -> int:
    if symbol.point <= 0:
        return 0
    return round(abs(price_a - price_b) / symbol.point)


async def loss_for_one_lot(
    service: MetaTraderService,
    symbol: SymbolInfo,
    direction: Direction,
    entry: float,
    stop_loss: float,
) -> tuple[float | None, str]:
    """Perte en devise du compte pour 1.0 lot entre l'entree et le stop.

    Essaie d'abord la fonction native du terminal, qui gere les conversions de
    devises ; retombe sinon sur tick_value / tick_size.
    """
    try:
        profit = await service.calculate_profit(symbol.name, direction, 1.0, entry, stop_loss)
    except Exception as exc:  # le terminal peut refuser selon le symbole
        logger.debug("calculate_profit indisponible pour %s : %s", symbol.name, exc)
        profit = None

    if profit is not None and profit < 0:
        return abs(profit), "order_calc_profit"

    if symbol.trade_tick_size > 0 and symbol.trade_tick_value > 0:
        ticks = abs(entry - stop_loss) / symbol.trade_tick_size
        return ticks * symbol.trade_tick_value, "tick_value"

    if symbol.trade_contract_size > 0:
        # Dernier recours : valeur nominale, valable pour les paires cotees en USD.
        return abs(entry - stop_loss) * symbol.trade_contract_size, "contract_size"

    return None, "unavailable"


async def calculate_lot(
    service: MetaTraderService,
    symbol: SymbolInfo,
    direction: Direction,
    entry: float,
    stop_loss: float,
    balance: float,
    risk_percent: float,
    max_lot: float | None = None,
) -> LotCalculation:
    """Volume tel que la perte au stop ne depasse pas le capital risque."""
    if entry <= 0 or stop_loss <= 0:
        return LotCalculation(ok=False, reason="Prix d'entree ou stop loss invalide")
    if entry == stop_loss:
        return LotCalculation(ok=False, reason="Stop loss confondu avec l'entree")
    if balance <= 0:
        return LotCalculation(ok=False, reason="Solde du compte indisponible ou nul")
    if risk_percent <= 0:
        return LotCalculation(ok=False, reason="Pourcentage de risque nul")

    risk_amount = balance * risk_percent / 100.0
    stop_distance = abs(entry - stop_loss)
    stop_points = points_between(entry, stop_loss, symbol)

    loss_per_lot, method = await loss_for_one_lot(service, symbol, direction, entry, stop_loss)
    if not loss_per_lot or loss_per_lot <= 0:
        return LotCalculation(
            ok=False,
            reason=f"Impossible de valoriser le risque sur {symbol.name}",
            risk_amount=risk_amount,
            stop_distance=stop_distance,
            stop_distance_points=stop_points,
            method=method,
        )

    raw_volume = risk_amount / loss_per_lot
    volume = round_to_step(raw_volume, symbol.volume_step)

    limits: list[float] = [symbol.volume_max]
    if max_lot is not None and max_lot > 0:
        limits.append(max_lot)
    ceiling = min(limits)
    capped = False
    if volume > ceiling:
        volume = round_to_step(ceiling, symbol.volume_step)
        capped = True

    if volume < symbol.volume_min - 1e-9:
        # Le motif reste factuel et ne designe aucun coupable : le calculateur
        # ignore pourquoi ``risk_percent`` vaut ce qu'il vaut. C'est le
        # RiskManager, qui connait le risque configure et l'eventuelle
        # reduction appliquee, qui enrichit ce texte.
        minimum_loss = symbol.volume_min * loss_per_lot
        return LotCalculation(
            ok=False,
            reason=(
                f"Volume calcule {raw_volume:.4f} sous le minimum broker "
                f"{symbol.volume_min} (risque vise {risk_amount:.2f}, "
                f"lot minimum {minimum_loss:.2f})"
            ),
            cause=CAUSE_BELOW_VOLUME_MIN,
            minimum_lot_loss=minimum_loss,
            risk_amount=risk_amount,
            loss_per_lot=loss_per_lot,
            stop_distance=stop_distance,
            stop_distance_points=stop_points,
            method=method,
            details={"requestedVolume": round(raw_volume, 4), "volumeMin": symbol.volume_min},
        )

    loss_at_stop = volume * loss_per_lot
    return LotCalculation(
        ok=True,
        volume=volume,
        risk_amount=risk_amount,
        loss_at_stop=loss_at_stop,
        loss_per_lot=loss_per_lot,
        stop_distance=stop_distance,
        stop_distance_points=stop_points,
        method=method,
        details={
            "requestedVolume": round(raw_volume, 4),
            "cappedByLimit": capped,
            "volumeStep": symbol.volume_step,
            "effectiveRiskPercent": round(loss_at_stop / balance * 100, 3) if balance else None,
        },
    )


def split_volume(total: float, ratios: list[float], symbol: SymbolInfo) -> list[float]:
    """Repartit un volume en plusieurs positions (strategie TP multiples).

    Retourne une liste vide si le fractionnement produit un volume invalide :
    dans ce cas l'appelant doit revenir a une position unique.
    """
    if total <= 0 or not ratios:
        return []
    weights = [ratio for ratio in ratios if ratio > 0]
    if not weights:
        return []
    total_weight = sum(weights)

    volumes: list[float] = []
    for weight in weights:
        part = round_to_step(total * weight / total_weight, symbol.volume_step)
        volumes.append(part)

    if any(volume < symbol.volume_min - 1e-9 for volume in volumes):
        return []

    # Reaffecte l'arrondi residuel a la premiere position.
    allocated = sum(volumes)
    residual = round_to_step(total - allocated, symbol.volume_step)
    if residual > 0:
        volumes[0] = round_to_step(volumes[0] + residual, symbol.volume_step)
    return volumes


def normalize_price(price: float | None, symbol: SymbolInfo) -> float | None:
    if price is None:
        return None
    return round(price, symbol.digits)


def respects_stops_level(
    price: float, stop_price: float, symbol: SymbolInfo, tolerance_points: int = 0
) -> bool:
    """Verifie la distance minimale imposee par le broker entre prix et SL/TP."""
    required = symbol.trade_stops_level + tolerance_points
    if required <= 0:
        return True
    return points_between(price, stop_price, symbol) >= required


def clamp_to_stops_level(
    price: float, stop_price: float, symbol: SymbolInfo, is_above: bool
) -> float:
    """Repousse un SL/TP juste au-dela de la distance minimale exigee."""
    required = symbol.trade_stops_level
    if required <= 0:
        return round(stop_price, symbol.digits)
    minimal_distance = required * symbol.point
    if is_above:
        return round(max(stop_price, price + minimal_distance), symbol.digits)
    return round(min(stop_price, price - minimal_distance), symbol.digits)
