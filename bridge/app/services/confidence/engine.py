"""Moteur de confiance : d'ou vient chaque point du score (CDC2 section 43).

Deux regles gouvernent ce fichier :

 - une composante absente reste absente. Elle n'est jamais remplacee par une
   valeur moyenne inventee : son poids est retire du calcul et la couverture
   du score baisse, ce qui rend le doute visible ;
 - le score explique toujours sa propre composition. La somme des
   contributions est exactement egale au score global.

Le score produit ici ne module JAMAIS la taille d'une position
(CDC2 section 44) : il sert a decider d'agir ou non, pas de combien risquer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import Direction
from app.models.intelligence import DecisionFactor
from app.services.confidence.weights import (
    COMPONENT_LABELS,
    ConfidenceComponent,
    ConfidenceWeights,
)


@dataclass(slots=True)
class ComponentScore:
    """Note brute d'une composante, telle que produite par son module.

    ``score`` vaut 0.0 a 1.0. ``None`` signifie explicitement : donnee
    indisponible. Aucune valeur de remplacement n'est fabriquee.
    """

    component: ConfidenceComponent
    score: float | None = None
    detail: str | None = None
    direction: Direction | None = None
    # Faux quand la composante n'a aucun sens pour ce dossier : pas de signal
    # Telegram sur une opportunite generee, pas de consensus sans moteur d'IA
    # actif. Une composante hors sujet sort du calcul de couverture au lieu de
    # la faire baisser ; une composante applicable mais absente la fait
    # baisser, et c'est voulu.
    applicable: bool = True

    @property
    def available(self) -> bool:
        return self.score is not None

    @property
    def counts_toward_coverage(self) -> bool:
        return self.applicable

    def clamped(self) -> float | None:
        if self.score is None:
            return None
        return max(0.0, min(1.0, float(self.score)))


@dataclass(slots=True)
class FactorBreakdown:
    """Contribution chiffree d'une composante au score final."""

    component: ConfidenceComponent
    label: str
    score: float | None
    weight: float
    contribution: float
    detail: str | None = None

    @property
    def available(self) -> bool:
        return self.score is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component.value,
            "label": self.label,
            "score": round(self.score, 2) if self.score is not None else None,
            "weight": round(self.weight, 4),
            "contribution": round(self.contribution, 2),
            "detail": self.detail,
        }

    def to_model(self, decision_id: int) -> DecisionFactor:
        return DecisionFactor(
            decision_id=decision_id,
            name=self.component.value,
            score=round(self.score, 2) if self.score is not None else 0.0,
            weight=round(self.weight, 4),
            contribution=round(self.contribution, 2),
            detail=(self.detail or "")[:500] or None,
        )


@dataclass(slots=True)
class ConfidenceResult:
    """Score global 0-100 et sa decomposition complete."""

    score: float = 0.0
    factors: list[FactorBreakdown] = field(default_factory=list)
    missing: list[ConfidenceComponent] = field(default_factory=list)
    coverage: float = 0.0
    weights: ConfidenceWeights = field(default_factory=ConfidenceWeights)

    @property
    def ratio(self) -> float:
        """Score ramene sur 0-1."""
        return self.score / 100.0

    @property
    def complete(self) -> bool:
        return not self.missing

    def factor(self, component: ConfidenceComponent) -> FactorBreakdown | None:
        return next((item for item in self.factors if item.component is component), None)

    def available_factors(self) -> list[FactorBreakdown]:
        return [item for item in self.factors if item.available]

    def strongest(self, limit: int = 3) -> list[FactorBreakdown]:
        """Composantes qui portent le plus le score."""
        ranked = sorted(self.available_factors(), key=lambda item: item.contribution, reverse=True)
        return [item for item in ranked[:limit] if item.contribution > 0]

    def weakest(self, limit: int = 3, threshold: float = 45.0) -> list[FactorBreakdown]:
        """Composantes qui tirent le score vers le bas."""
        weak = [item for item in self.available_factors() if (item.score or 0.0) < threshold]
        return sorted(weak, key=lambda item: item.score or 0.0)[:limit]

    def to_decision_factors(self, decision_id: int) -> list[DecisionFactor]:
        """Lignes ``decision_factors`` pretes a etre enregistrees."""
        return [item.to_model(decision_id) for item in self.factors]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "coverage": round(self.coverage, 3),
            "complete": self.complete,
            "missing": [component.value for component in self.missing],
            "weights": self.weights.to_dict(),
            "factors": [item.to_dict() for item in self.factors],
        }


class ConfidenceEngine:
    """Assemble les notes des modules en un score explicable.

    Le moteur ne connait aucun module : il recoit des ``ComponentScore``. Cela
    le rend entierement testable sans marche, sans IA et sans reseau.
    """

    def __init__(self, weights: ConfidenceWeights | None = None) -> None:
        self._weights = weights or ConfidenceWeights()

    @property
    def weights(self) -> ConfidenceWeights:
        return self._weights

    def with_weights(self, weights: ConfidenceWeights) -> ConfidenceEngine:
        """Nouveau moteur, meme logique, ponderation differente."""
        return ConfidenceEngine(weights)

    def evaluate(self, components: Iterable[ComponentScore]) -> ConfidenceResult:
        """Calcule le score global et la contribution de chaque composante."""
        provided = self._index(components)
        weights = self._weights

        usable: list[tuple[ConfidenceComponent, float, ComponentScore]] = []
        for component in ConfidenceComponent:
            weight = weights.weight_of(component)
            entry = provided.get(component)
            value = entry.clamped() if entry is not None else None
            if value is None or weight <= 0:
                continue
            usable.append((component, weight, entry))

        active_weight = sum(weight for _, weight, _ in usable)
        # Denominateur : tout ce qui s'applique a ce dossier. Une composante
        # declaree hors sujet en est retiree, sinon la couverture serait
        # plafonnee par construction et aucune decision ne passerait jamais.
        total_weight = sum(
            weights.weight_of(component)
            for component in ConfidenceComponent
            if _applicable(provided.get(component))
        )

        factors: list[FactorBreakdown] = []
        missing: list[ConfidenceComponent] = []
        score = 0.0

        for component in ConfidenceComponent:
            configured = weights.weight_of(component)
            entry = provided.get(component)
            value = entry.clamped() if entry is not None else None

            if value is None or configured <= 0 or active_weight <= 0:
                if configured > 0 and _applicable(entry):
                    missing.append(component)
                factors.append(
                    FactorBreakdown(
                        component=component,
                        label=COMPONENT_LABELS[component],
                        score=None,
                        weight=0.0,
                        contribution=0.0,
                        detail=self._missing_detail(entry, configured),
                    )
                )
                continue

            effective = configured / active_weight
            contribution = value * effective * 100.0
            score += contribution
            factors.append(
                FactorBreakdown(
                    component=component,
                    label=COMPONENT_LABELS[component],
                    score=value * 100.0,
                    weight=effective,
                    contribution=contribution,
                    detail=entry.detail if entry is not None else None,
                )
            )

        coverage = (active_weight / total_weight) if total_weight > 0 else 0.0
        return ConfidenceResult(
            score=round(min(100.0, max(0.0, score)), 4),
            factors=factors,
            missing=missing,
            coverage=round(coverage, 6),
            weights=weights,
        )

    # ------------------------------------------------------------------
    # Outils internes
    # ------------------------------------------------------------------
    @staticmethod
    def _index(components: Iterable[ComponentScore]) -> dict[ConfidenceComponent, ComponentScore]:
        """Derniere note fournie pour une composante donnee."""
        indexed: dict[ConfidenceComponent, ComponentScore] = {}
        for item in components:
            if item is None:
                continue
            indexed[item.component] = item
        return indexed

    @staticmethod
    def _missing_detail(entry: ComponentScore | None, configured: float) -> str:
        if configured <= 0:
            return "Composante désactivée : poids nul."
        if entry is not None and entry.detail:
            return entry.detail
        return "Donnée indisponible : cette composante ne compte pas dans le score."


def _applicable(entry: ComponentScore | None) -> bool:
    """Une composante non fournie est consideree comme applicable.

    Ne pas fournir d'entree veut dire « je n'ai pas la donnee », pas « cette
    composante ne me concerne pas ». Seul un appelant qui le declare
    explicitement, en passant ``applicable=False``, sort du denominateur.
    """
    return True if entry is None else entry.applicable


def aligned_score(
    score: float | None,
    view_direction: Direction | None,
    proposed: Direction | None,
) -> float | None:
    """Ramene une note a l'appui qu'elle apporte a la direction envisagee.

    Une composante qui pointe dans l'autre sens ne vaut pas zero par principe :
    sa force devient une force contraire. Regle unique, deterministe, pour que
    le score reste comparable d'un instrument a l'autre.

    L'appui d'une composante contraire est plafonne au point neutre (0,5) et
    decroit avec sa force. La formule precedente, ``1 - note``, transformait
    une conviction NULLE pointant a l'oppose en appui MAXIMAL : une lecture
    technique sans conviction annoncant la vente faisait monter le score d'un
    achat comme si elle l'avait recommande.
    """
    if score is None:
        return None
    value = max(0.0, min(1.0, float(score)))
    if view_direction is None or proposed is None or view_direction is proposed:
        return value
    return (1.0 - value) / 2.0


def build_components(raw: Sequence[ComponentScore | None]) -> list[ComponentScore]:
    """Filtre les entrees nulles sans jamais en fabriquer."""
    return [item for item in raw if item is not None]


confidence_engine = ConfidenceEngine()

__all__ = [
    "ComponentScore",
    "ConfidenceEngine",
    "ConfidenceResult",
    "FactorBreakdown",
    "aligned_score",
    "build_components",
    "confidence_engine",
]
