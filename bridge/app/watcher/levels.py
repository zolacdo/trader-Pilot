"""Calcul de l'entree, du stop et des objectifs (CDC3 sections 26 a 29).

Ce module est le garant de la regle la plus importante du CDC3 : les niveaux
viennent des donnees de marche, jamais d'un modele de langage (section 22).
Il tourne AVANT tout appel a l'IA, et l'IA ne peut pas les corriger.

Chaque niveau est justifie par une phrase reutilisee telle quelle dans le
message Telegram : un signal doit rester explicable (section 80).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.enums import Direction
from app.services.mt5.interface import SymbolInfo
from app.watcher.analysis.context import MarketContext
from app.watcher.models import EntryType

# Distance maximale a une resistance/support, en ATR, pour proposer une entree
# sur cassure plutot qu'au marche.
BREAKOUT_REACH_ATR = 0.75
# Marge ajoutee au-dela du niveau casse, en ATR, pour ne pas etre declenche
# par une simple meche.
BREAKOUT_BUFFER_ATR = 0.05
# Stop de repli quand la structure n'offre aucun point protecteur.
DEFAULT_STOP_ATR = 1.5
# Stop minimal, en ATR : plus serre, il serait touche par le bruit.
MIN_STOP_ATR = 0.45
# Stop maximal, en ATR : au-dela, le setup n'est plus exploitable.
MAX_STOP_ATR = 4.0
# Progression minimale entre deux objectifs, en unites de risque.
MIN_TARGET_STEP_R = 0.5
# Ecart maximal, en unites de risque, entre un objectif technique et la cible
# theorique : au-dela, le niveau ne represente plus le meme objectif.
TARGET_TOLERANCE_R = 1.0


@dataclass(slots=True)
class TradeLevels:
    """Niveaux proposes pour un sens donne, et leurs justifications."""

    direction: Direction
    entry: float
    entry_type: EntryType
    stop_loss: float
    risk_distance: float
    targets: list[float] = field(default_factory=list)
    risk_rewards: list[float] = field(default_factory=list)
    entry_reason: str = ""
    stop_reason: str = ""
    target_reasons: list[str] = field(default_factory=list)
    invalidation: str = ""
    valid: bool = True
    rejection: str | None = None

    @property
    def take_profit_1(self) -> float | None:
        return self.targets[0] if len(self.targets) > 0 else None

    @property
    def take_profit_2(self) -> float | None:
        return self.targets[1] if len(self.targets) > 1 else None

    @property
    def take_profit_3(self) -> float | None:
        return self.targets[2] if len(self.targets) > 2 else None

    @property
    def first_risk_reward(self) -> float | None:
        return self.risk_rewards[0] if self.risk_rewards else None

    @property
    def best_risk_reward(self) -> float | None:
        return max(self.risk_rewards) if self.risk_rewards else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction.value,
            "entry": self.entry,
            "entryType": self.entry_type.value,
            "stopLoss": self.stop_loss,
            "riskDistance": self.risk_distance,
            "targets": list(self.targets),
            "riskRewards": list(self.risk_rewards),
            "entryReason": self.entry_reason,
            "stopReason": self.stop_reason,
            "targetReasons": list(self.target_reasons),
            "invalidation": self.invalidation,
            "valid": self.valid,
            "rejection": self.rejection,
        }


def _rejected(direction: Direction, reason: str) -> TradeLevels:
    """Niveaux inexploitables : on le dit, on n'invente rien (CDC3 section 87)."""
    return TradeLevels(
        direction=direction,
        entry=0.0,
        entry_type=EntryType.MARKET,
        stop_loss=0.0,
        risk_distance=0.0,
        valid=False,
        rejection=reason,
    )


def _round(value: float, info: SymbolInfo | None) -> float:
    """Arrondit au nombre de decimales reel de l'instrument."""
    digits = info.digits if info is not None and info.digits > 0 else 5
    return round(value, digits)


def _minimum_distance(context: MarketContext, info: SymbolInfo | None) -> float:
    """Distance minimale imposee par le broker et par le spread courant.

    Un stop plus proche que ``trade_stops_level`` est refuse par MetaTrader.
    Le spread compte double : il faut le franchir a l'ouverture puis a la
    fermeture.
    """
    floor = 0.0
    if info is not None and info.point > 0 and info.trade_stops_level > 0:
        floor = info.trade_stops_level * info.point
    spread = context.quote.spread_price if context.quote is not None else None
    if spread:
        floor = max(floor, spread * 2.0)
    return floor


def build_levels(context: MarketContext, direction: Direction, minimum_rr: float) -> TradeLevels:
    """Construit une proposition complete de niveaux pour le sens demande."""
    analysis = context.primary
    price = context.price
    if analysis is None or price is None or not analysis.usable:
        return _rejected(direction, "Analyse technique incomplete : aucun niveau calculable.")
    atr = analysis.atr
    if atr is None or atr <= 0:
        return _rejected(direction, "ATR indisponible : impossible de dimensionner le risque.")

    info = context.symbol_info
    floor = _minimum_distance(context, info)
    entry, entry_type, entry_reason = _build_entry(context, direction, atr, price, info)
    stop, stop_reason = _build_stop(context, direction, entry, atr, floor, info)

    risk = abs(entry - stop)
    if risk <= 0:
        return _rejected(direction, "Stop confondu avec l'entree : setup inexploitable.")
    if risk > atr * MAX_STOP_ATR:
        return _rejected(
            direction,
            f"Stop trop large ({round(risk / atr, 1)} ATR) : le setup ne tient pas dans le risque.",
        )

    targets, reasons = _build_targets(context, direction, entry, risk, info)
    if not targets:
        return _rejected(direction, "Aucun objectif atteignable au-dela du risque encouru.")

    levels = TradeLevels(
        direction=direction,
        entry=_round(entry, info),
        entry_type=entry_type,
        stop_loss=_round(stop, info),
        risk_distance=round(risk, 8),
        targets=[_round(target, info) for target in targets],
        risk_rewards=[round(abs(target - entry) / risk, 2) for target in targets],
        entry_reason=entry_reason,
        stop_reason=stop_reason,
        target_reasons=reasons,
    )
    levels.invalidation = _invalidation(direction, levels.stop_loss, context, info)

    best = levels.best_risk_reward or 0.0
    if best < minimum_rr:
        levels.valid = False
        levels.rejection = (
            f"Risk/Reward maximal {best} inferieur au minimum exige ({minimum_rr})."
        )
    return levels


# ---------------------------------------------------------------------------
# Entree
# ---------------------------------------------------------------------------
def _build_entry(
    context: MarketContext,
    direction: Direction,
    atr: float,
    price: float,
    info: SymbolInfo | None,
) -> tuple[float, EntryType, str]:
    """Choisit le type d'entree et son prix (CDC3 section 26)."""
    analysis = context.primary
    if analysis is None:  # deja verifie par build_levels, garde defensive
        return price, EntryType.MARKET, "Entree au marche."

    quote = context.quote
    spread = quote.spread_price if quote is not None and quote.spread_price else 0.0
    buffer_ = max(atr * BREAKOUT_BUFFER_ATR, spread)
    buy = direction is Direction.BUY

    if buy:
        market_price = quote.ask if quote is not None and quote.ask else price
        barrier = analysis.levels.resistance
    else:
        market_price = quote.bid if quote is not None and quote.bid else price
        barrier = analysis.levels.support

    # Le prix approche un niveau evident sans l'avoir franchi : on attend la
    # cassure plutot que d'acheter dans la resistance (CDC3 section 89).
    if barrier is not None:
        reachable = (
            market_price < barrier <= market_price + atr * BREAKOUT_REACH_ATR
            if buy
            else market_price > barrier >= market_price - atr * BREAKOUT_REACH_ATR
        )
        if reachable:
            entry = barrier + buffer_ if buy else barrier - buffer_
            niveau = "la resistance" if buy else "le support"
            verbe = "Achat" if buy else "Vente"
            return (
                entry,
                EntryType.STOP,
                f"{verbe} sur cassure de {niveau} {_round(barrier, info)}, "
                f"declenchement a {_round(entry, info)}.",
            )

    expected_breakout = "UP" if buy else "DOWN"
    if analysis.breakout == expected_breakout:
        sens = "haussiere" if buy else "baissiere"
        return (
            market_price,
            EntryType.BREAKOUT,
            f"Cassure {sens} deja en cours : entree au marche, sans attendre de retour.",
        )

    if analysis.pullback is not None and 0.25 <= analysis.pullback <= 0.75:
        return (
            market_price,
            EntryType.RETEST,
            f"Repli de {round(analysis.pullback * 100)} % sur la derniere impulsion : "
            "entree sur retest.",
        )

    cote = "demande" if buy else "offert"
    return (market_price, EntryType.MARKET, f"Entree au marche, au prix {cote} courant.")


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------
def _build_stop(
    context: MarketContext,
    direction: Direction,
    entry: float,
    atr: float,
    floor: float,
    info: SymbolInfo | None,
) -> tuple[float, str]:
    """Stop protecteur : structure d'abord, ATR en repli (CDC3 section 27)."""
    analysis = context.primary
    if analysis is None:
        return entry, "Stop indisponible."

    buy = direction is Direction.BUY
    swing = analysis.structure.last_low if buy else analysis.structure.last_high
    structural = analysis.stop_loss_hint(direction)
    protective = (
        swing is not None and (swing.price < entry if buy else swing.price > entry)
    )
    beyond_entry = structural is not None and (
        structural < entry if buy else structural > entry
    )

    if beyond_entry and structural is not None:
        stop = structural
        if protective and swing is not None:
            place = "sous le dernier creux" if buy else "au-dessus du dernier sommet"
            reason = f"Stop {place} protecteur {_round(swing.price, info)}."
        else:
            place = "sous" if buy else "au-dessus de"
            reason = f"Stop a {DEFAULT_STOP_ATR} ATR {place} l'entree."
    else:
        stop = entry - atr * DEFAULT_STOP_ATR if buy else entry + atr * DEFAULT_STOP_ATR
        place = "sous" if buy else "au-dessus de"
        point = "creux" if buy else "sommet"
        reason = (
            f"Stop a {DEFAULT_STOP_ATR} ATR {place} l'entree : "
            f"aucun {point} protecteur exploitable."
        )

    minimum = max(floor, atr * MIN_STOP_ATR)
    distance = entry - stop if buy else stop - entry
    if distance < minimum:
        stop = entry - minimum if buy else entry + minimum
        reason += (
            f" Ecarte a {round(minimum / atr, 2)} ATR pour absorber le bruit et le spread."
        )
    return stop, reason


# ---------------------------------------------------------------------------
# Objectifs
# ---------------------------------------------------------------------------
def _technical_targets(context: MarketContext, direction: Direction, entry: float) -> list[float]:
    """Niveaux techniques situes devant l'entree, du plus proche au plus loin."""
    analysis = context.primary
    if analysis is None:
        return []
    buy = direction is Direction.BUY
    clusters = analysis.levels.resistances if buy else analysis.levels.supports
    prices = [cluster.price for cluster in clusters]

    # Les bornes du range et les niveaux de liquidite sont de vrais objectifs :
    # c'est la que le prix va chercher les ordres en attente.
    range_reading = analysis.range_reading
    edge = range_reading.high if buy else range_reading.low
    if edge is not None:
        prices.append(edge)
    zones = context.liquidity.equal_highs if buy else context.liquidity.equal_lows
    prices.extend(zone.price for zone in zones)

    ahead = [price for price in prices if (price > entry if buy else price < entry)]
    ahead.sort(reverse=not buy)
    # Deduplication : plusieurs sources designent souvent le meme niveau.
    unique: list[float] = []
    for price in ahead:
        if all(abs(price - kept) > 1e-9 for kept in unique):
            unique.append(price)
    return unique


def _build_targets(
    context: MarketContext,
    direction: Direction,
    entry: float,
    risk: float,
    info: SymbolInfo | None,
) -> tuple[list[float], list[str]]:
    """Trois objectifs : zones techniques d'abord, multiples de R en repli.

    Le CDC3 section 28 demande de privilegier les vraies zones techniques.
    Un niveau n'est retenu que s'il reste a moins d'un R de la cible theorique :
    au-dela, il ne represente plus le meme objectif et 2R redeviendrait 4R.
    """
    buy = direction is Direction.BUY
    sign = 1.0 if buy else -1.0
    available = _technical_targets(context, direction, entry)

    targets: list[float] = []
    reasons: list[str] = []
    last = entry
    for step in (1, 2, 3):
        theoretical = entry + sign * risk * step
        minimum = last + sign * risk * MIN_TARGET_STEP_R
        pool = [
            price
            for price in available
            if sign * (price - minimum) >= 0
            and abs(price - theoretical) <= risk * TARGET_TOLERANCE_R
        ]
        if pool:
            chosen = min(pool, key=lambda price: abs(price - theoretical))
            available.remove(chosen)
            reasons.append(
                f"TP{step} sur la zone technique {_round(chosen, info)} "
                f"({round(abs(chosen - entry) / risk, 2)}R)."
            )
        else:
            chosen = theoretical
            reasons.append(f"TP{step} a {step}R, aucune zone technique a cette distance.")
        targets.append(chosen)
        last = chosen
    return targets, reasons


def _invalidation(
    direction: Direction, stop: float, context: MarketContext, info: SymbolInfo | None
) -> str:
    """Phrase d'invalidation affichee dans le message (CDC3 section 33)."""
    frame = context.primary_timeframe.value if context.primary_timeframe else "l'unite de travail"
    sens = "sous" if direction is Direction.BUY else "au-dessus de"
    return f"Cloture {frame} {sens} {_round(stop, info)}."


__all__ = ["TradeLevels", "build_levels"]
