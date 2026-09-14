"""Validateur strict d'un signal analyse.

Derniere barriere avant le RiskManager, et surtout garde-fou contre une sortie
d'IA incoherente : aucune donnee produite par le modele n'atteint MT5 sans
passer par ces controles purement locaux (CDC sections 21 et 49).
"""

from __future__ import annotations

from app.models.enums import Direction, OrderType
from app.services.signals.models import ParsedSignal, ValidationIssue, ValidationResult

# Ecart maximal tolere entre l'entree et le SL, en pourcentage du prix.
# Au-dela, la valeur est presque surement une erreur de lecture.
MAX_STOP_DISTANCE_RATIO = 0.25
MIN_STOP_DISTANCE_RATIO = 0.00002


def _positive(value: float | None) -> bool:
    return value is not None and value > 0


def validate(signal: ParsedSignal) -> ValidationResult:
    """Verifie la coherence interne du signal. Ne consulte ni MT5 ni le risque."""
    issues: list[ValidationIssue] = []

    if not signal.is_signal:
        issues.append(ValidationIssue("NO_ACTION", "Le message ne contient pas d'intention de trade"))
        return ValidationResult(ok=False, issues=issues)

    if signal.symbol is None:
        issues.append(ValidationIssue("SYMBOL_MISSING", "Instrument absent ou non reconnu"))
    if signal.direction is None:
        issues.append(ValidationIssue("DIRECTION_MISSING", "Direction BUY/SELL absente"))
    if issues:
        return ValidationResult(ok=False, issues=issues)

    # --- valeurs numeriques positives ---
    for label, value in (
        ("entryPrice", signal.entry_price),
        ("entryMin", signal.entry_min),
        ("entryMax", signal.entry_max),
        ("stopLoss", signal.stop_loss),
    ):
        if value is not None and value <= 0:
            issues.append(ValidationIssue("NEGATIVE_VALUE", f"{label} doit etre strictement positif"))
    for index, target in enumerate(signal.take_profits, start=1):
        if target <= 0:
            issues.append(ValidationIssue("NEGATIVE_VALUE", f"TP{index} doit etre strictement positif"))

    has_zone = signal.entry_min is not None and signal.entry_max is not None
    if has_zone and signal.entry_min > signal.entry_max:
        issues.append(ValidationIssue("ENTRY_RANGE_INVERTED", "Zone d'entree inversee"))

    reference = signal.reference_entry

    # --- coherence directionnelle du stop loss ---
    if _positive(signal.stop_loss) and _positive(reference):
        stop_loss = float(signal.stop_loss)
        entry = float(reference)
        if signal.direction is Direction.BUY and stop_loss >= entry:
            issues.append(
                ValidationIssue("SL_WRONG_SIDE", "Sur un achat, le stop loss doit etre sous l'entree")
            )
        if signal.direction is Direction.SELL and stop_loss <= entry:
            issues.append(
                ValidationIssue(
                    "SL_WRONG_SIDE",
                    "Sur une vente, le stop loss doit etre au-dessus de l'entree",
                )
            )
        distance_ratio = abs(entry - stop_loss) / entry
        if distance_ratio > MAX_STOP_DISTANCE_RATIO:
            issues.append(
                ValidationIssue(
                    "SL_TOO_FAR",
                    f"Stop loss a {distance_ratio:.1%} de l'entree : valeur probablement mal lue",
                )
            )
        elif distance_ratio < MIN_STOP_DISTANCE_RATIO:
            issues.append(ValidationIssue("SL_TOO_CLOSE", "Stop loss confondu avec le prix d'entree"))

    # --- coherence directionnelle des take profits ---
    if signal.take_profits and _positive(reference):
        entry = float(reference)
        for index, target in enumerate(signal.take_profits, start=1):
            if signal.direction is Direction.BUY and target <= entry:
                issues.append(
                    ValidationIssue(
                        "TP_WRONG_SIDE",
                        f"Sur un achat, TP{index} doit etre au-dessus de l'entree",
                    )
                )
            if signal.direction is Direction.SELL and target >= entry:
                issues.append(
                    ValidationIssue("TP_WRONG_SIDE", f"Sur une vente, TP{index} doit etre sous l'entree")
                )

        ordered = sorted(signal.take_profits, reverse=signal.direction is Direction.SELL)
        if ordered != signal.take_profits:
            issues.append(
                ValidationIssue(
                    "TP_ORDER", "Les take profits ne sont pas ordonnes dans le sens du trade", blocking=False
                )
            )

    # --- coherence du type d'ordre ---
    pending_types = {
        OrderType.BUY_LIMIT,
        OrderType.SELL_LIMIT,
        OrderType.BUY_STOP,
        OrderType.SELL_STOP,
    }
    if signal.order_type in pending_types:
        if not signal.has_entry:
            issues.append(ValidationIssue("PENDING_WITHOUT_PRICE", "Un ordre en attente exige un prix"))
        expected_direction = (
            Direction.BUY
            if signal.order_type in {OrderType.BUY_LIMIT, OrderType.BUY_STOP}
            else Direction.SELL
        )
        if signal.direction is not expected_direction:
            issues.append(ValidationIssue("ORDER_TYPE_MISMATCH", "Type d'ordre incoherent avec la direction"))

    # --- doublons de take profit ---
    if len(set(signal.take_profits)) != len(signal.take_profits):
        issues.append(ValidationIssue("TP_DUPLICATE", "Take profits en doublon", blocking=False))

    blocking = [issue for issue in issues if issue.blocking]
    return ValidationResult(ok=not blocking, issues=issues)


def sanitize(signal: ParsedSignal) -> ParsedSignal:
    """Nettoyages non destructifs : doublons de TP et ordre de la zone d'entree.

    Aucune valeur n'est inventee ni corrigee : seules les redondances evidentes
    sont retirees et les bornes remises dans l'ordre.
    """
    if signal.entry_min is not None and signal.entry_max is not None and signal.entry_min > signal.entry_max:
        signal.entry_min, signal.entry_max = signal.entry_max, signal.entry_min
        signal.add_warning("zone_entree_reordonnee")

    if signal.take_profits:
        unique: list[float] = []
        for target in signal.take_profits:
            if target not in unique:
                unique.append(target)
        if len(unique) != len(signal.take_profits):
            signal.add_warning("take_profits_dedupliques")
        if signal.direction is Direction.BUY:
            unique.sort()
        elif signal.direction is Direction.SELL:
            unique.sort(reverse=True)
        signal.take_profits = unique

    return signal
