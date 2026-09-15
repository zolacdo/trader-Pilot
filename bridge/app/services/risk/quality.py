"""Dimensionnement dynamique : le risque configure devient un PLAFOND.

Jusqu'ici `risk_percent` etait une constante : deux signaux du meme canal
prenaient le meme pourcentage, quelle que soit leur qualite. Ce module calcule
un multiplicateur M, structurellement borne a 1,0, qui ne peut que REDUIRE ce
pourcentage.

Le choix de ne jamais amplifier n'est pas de la timidite : comme M <= 1 et que
`round_to_step` arrondit toujours vers le bas (calculator.py), le risque
effectif reste mecaniquement inferieur ou egal au risque configure. La regle
des 1,5x du RiskManager devient inatteignable par construction, et aucun
garde-fou existant n'a besoin d'etre touche.

Les cinq facteurs n'utilisent que des grandeurs reellement disponibles et
reellement variables au moment du dimensionnement. `signal.confidence` est
volontairement EXCLU : il mesure la completude du message (entree presente,
stop present, TP present) et non la qualite du trade, et le filtre
`min_confidence` ne laisse de toute facon passer qu'une bande etroite. On
penalise directement `warnings`, la grandeur brute que la confiance agrege.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.signals.models import ParserSource

# Part du risque que le spread peut absorber avant d'etre penalise, puis part
# a laquelle la penalite est maximale. Ancrer sur le cout reel plutot que sur
# un nombre de points rend la mesure comparable d'un instrument a l'autre, et
# la rend independante de la tolerance reglee par l'utilisateur.
SPREAD_FREE_RATIO = 0.05
SPREAD_FULL_RATIO = 0.25

# Plancher des facteurs de qualite. En dessous, on ne descend pas davantage :
# c'est `calculate_lot` qui tranchera via volume_min, sans nouveau motif de
# rejet a inventer.
DEFAULT_QUALITY_FLOOR = 0.35

# Borne haute du plancher. A 1,0, la borne basse devient aussi la borne haute :
# les cinq facteurs sont calcules, ecrits dans le journal d'audit, puis jetes.
# Le reglage eteignait donc la modulation en la laissant affichee active, et le
# detail d'audit se contredisait -- « qualite 1.00 [...] (plus penalisant :
# rendement_risque 0.50) ». Pour eteindre la modulation il y a
# `dynamic_risk_enabled` ; un second chemin silencieux n'a pas lieu d'etre.
MAX_QUALITY_FLOOR = 0.90


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


@dataclass(frozen=True, slots=True)
class QualityMultiplier:
    """Resultat du calcul, entierement inspectable pour l'audit."""

    multiplier: float
    quality: float
    budget_factor: float
    sized_risk_percent: float
    factors: dict[str, float] = field(default_factory=dict)
    detail: str = ""

    @property
    def applied(self) -> bool:
        """Vrai des que le multiplicateur a reellement reduit la taille."""
        return self.multiplier < 1.0 - 1e-9


def weighted_risk_reward(
    *,
    entry: float,
    stop_loss: float | None,
    take_profits: list[float] | None,
    split_ratios: list[float] | None,
) -> float | None:
    """Rendement attendu en tenant compte de la sortie par paliers.

    Le RiskManager juge le ratio sur TP1 seul, ce qui convient a son filtre
    `min_risk_reward` mais pas au dimensionnement : les canaux or envoient
    cinq TP et le systeme sort par tranches (40/30/30 par defaut). Sur un
    signal a 10 points de stop, TP1 a +3 donne 0,30 alors que la sortie reelle
    rapporte 0,57. Juger sur TP1 ecraserait tous ces signaux au plancher.

    Avec un seul take profit, la valeur retombe exactement sur celle de TP1.
    """
    if stop_loss is None or not take_profits:
        return None
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return None

    ratios = [ratio for ratio in (split_ratios or []) if ratio > 0][: len(take_profits)]
    if not ratios:
        ratios = [1.0]

    total = sum(ratios)
    if total <= 0:
        return None

    reward = sum(
        ratio * abs(target - entry) for ratio, target in zip(ratios, take_profits, strict=False)
    )
    return reward / total / risk


def _reward_factor(risk_reward: float | None) -> float:
    """Seule mesure reellement continue de la qualite du trade.

    Un signal sans take profit ne permet aucun jugement : on le penalise sans
    l'ecraser.
    """
    if risk_reward is None:
        return 0.60
    return 0.50 + 0.50 * _clamp(risk_reward - 1.0, 0.0, 1.0)


def _spread_factor(spread_cost: float | None, stop_distance: float | None) -> float:
    """Ce qui compte est la part du risque que le spread absorbe d'entree.

    Compter en points n'a aucun sens d'un instrument a l'autre : 260 points
    valent 0,26 dollar sur l'or, 10 dollars sur le Bitcoin, et moins d'un
    centieme sur l'euro. Mesuree ainsi, la tolerance reglee par l'utilisateur
    n'influence plus le facteur -- elle reste le seuil de refus, pas l'echelle.
    """
    if not spread_cost or not stop_distance or stop_distance <= 0:
        return 1.0
    part = spread_cost / stop_distance
    severity = _clamp(
        (part - SPREAD_FREE_RATIO) / (SPREAD_FULL_RATIO - SPREAD_FREE_RATIO), 0.0, 1.0
    )
    return 1.0 - 0.40 * severity


def _age_factor(age_seconds: float | None, max_age_seconds: int) -> float:
    """Un signal absent d'horodatage n'est pas un signal perime.

    On reste neutre : penaliser l'absence de `message_date` reviendrait a
    taxer le chemin manuel et le chemin API, qui ne sont pas en retard.
    """
    if age_seconds is None:
        return 1.0
    relative = age_seconds / max(max_age_seconds, 1)
    severity = _clamp((relative - 0.30) / 0.70, 0.0, 1.0)
    return 1.0 - 0.30 * severity


def _streak_factor(consecutive_losses: int) -> float:
    return _clamp(1.0 - 0.25 * max(consecutive_losses, 0), 0.50, 1.0)


def _parsing_factor(warnings: list[str] | None, source: ParserSource | None) -> float:
    penalty = _clamp(1.0 - 0.05 * len(warnings or []), 0.80, 1.0)
    if source is ParserSource.AI:
        penalty *= 0.85
    return penalty


def quality_multiplier(
    *,
    risk_percent: float,
    risk_reward: float | None,
    spread_cost: float | None,
    stop_distance: float | None,
    age_seconds: float | None,
    max_signal_age_seconds: int,
    consecutive_losses: int,
    warnings: list[str] | None,
    source: ParserSource | None,
    day_risked_percent: float,
    max_daily_risk_percent: float,
    floor: float = DEFAULT_QUALITY_FLOOR,
) -> QualityMultiplier:
    """Calcule le pourcentage de risque a appliquer a CE signal.

    Fonction pure : aucune entree/sortie, aucun acces base, aucun appel MT5.
    """
    factors = {
        "rendement_risque": _reward_factor(risk_reward),
        "spread": _spread_factor(spread_cost, stop_distance),
        "fraicheur": _age_factor(age_seconds, max_signal_age_seconds),
        "series_perdantes": _streak_factor(consecutive_losses),
        "parsing": _parsing_factor(warnings, source),
    }

    produit = 1.0
    for valeur in factors.values():
        produit *= valeur
    quality = _clamp(produit, _clamp(floor, 0.0, MAX_QUALITY_FLOOR), 1.0)

    # Le budget journalier restant est une contrainte DURE : il n'est jamais
    # plancheee. Le facteur est multiplicatif et non pris en minimum, sinon
    # `sized` pourrait depasser le reste disponible des que f_budget < 1.
    prevu = risk_percent * quality
    if max_daily_risk_percent <= 0 or prevu <= 0:
        budget_factor = 1.0
    else:
        reste = max_daily_risk_percent - day_risked_percent
        budget_factor = _clamp(reste / prevu, 0.0, 1.0)

    multiplier = _clamp(quality * budget_factor, 0.0, 1.0)
    sized = risk_percent * multiplier

    faible = min(factors, key=lambda cle: factors[cle])
    detail = (
        f"qualite {quality:.2f} x budget {budget_factor:.2f} = {multiplier:.2f} "
        f"-> risque {sized:.3f}% (plus penalisant : {faible} {factors[faible]:.2f})"
    )

    return QualityMultiplier(
        multiplier=multiplier,
        quality=quality,
        budget_factor=budget_factor,
        sized_risk_percent=sized,
        factors=factors,
        detail=detail,
    )
