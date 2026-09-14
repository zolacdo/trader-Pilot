"""Exposition agregee et surexposition correlee (CDC2 section 26).

BUY EURUSD + BUY GBPUSD + SELL USDCHF ne sont pas trois paris independants :
c'est un seul pari contre le dollar. Ce module decompose chaque position en
jambes elementaires, additionne l'exposition par devise ou par actif, puis
confronte les positions aux correlations REELLEMENT mesurees.

Ce module ne bloque rien : il decrit. Le RiskManager reste seul juge, via
``evaluate_correlated_exposure`` qui est volontairement synchrone et pure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import Direction
from app.services.cross_market.correlation import STRONG_CORRELATION
from app.services.signals.symbols import CURRENCIES, METALS, canonical_symbol, strip_broker_suffix

# Au-dela de ces seuils, l'exposition est signalee. Valeurs par defaut
# prudentes, surchargees par l'appelant (RiskManager).
DEFAULT_MAX_CURRENCY_EXPOSURE = 2.0
DEFAULT_MAX_CORRELATED_EXPOSURE = 2.0


@dataclass(slots=True)
class ExposureLeg:
    """Une position ouverte ou envisagee, ramenee a un poids de risque.

    ``weight`` est l'unite de mesure choisie par l'appelant : pourcentage de
    risque, volume en lots ou montant. Il doit rester homogene sur toutes les
    jambes d'un meme appel.
    """

    symbol: str
    direction: Direction
    weight: float = 1.0
    strategy: str | None = None
    reference: str | None = None


@dataclass(slots=True)
class CurrencyExposure:
    currency: str
    net: float
    gross: float
    symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "net": round(self.net, 4),
            "gross": round(self.gross, 4),
            "direction": "LONG" if self.net > 0 else ("SHORT" if self.net < 0 else "FLAT"),
            "symbols": list(self.symbols),
        }


@dataclass(slots=True)
class CorrelatedCluster:
    """Groupe de positions qui parient sur la meme chose."""

    symbols: list[str]
    exposure: float
    correlation: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": list(self.symbols),
            "exposure": round(self.exposure, 4),
            "correlation": round(self.correlation, 4),
        }


@dataclass(slots=True)
class ExposureAssessment:
    """Description chiffree de l'exposition agregee, sans decision."""

    legs: int
    currencies: list[CurrencyExposure] = field(default_factory=list)
    clusters: list[CorrelatedCluster] = field(default_factory=list)
    breaches: list[str] = field(default_factory=list)
    unparsed_symbols: list[str] = field(default_factory=list)
    max_currency_exposure: float = DEFAULT_MAX_CURRENCY_EXPOSURE
    max_correlated_exposure: float = DEFAULT_MAX_CORRELATED_EXPOSURE

    @property
    def overexposed(self) -> bool:
        return bool(self.breaches)

    @property
    def dominant(self) -> CurrencyExposure | None:
        if not self.currencies:
            return None
        return max(self.currencies, key=lambda item: abs(item.net))

    def exposure_for(self, currency: str) -> float:
        for item in self.currencies:
            if item.currency == currency.upper():
                return item.net
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        dominant = self.dominant
        return {
            "legs": self.legs,
            "overexposed": self.overexposed,
            "currencies": [item.to_dict() for item in self.currencies],
            "clusters": [item.to_dict() for item in self.clusters],
            "breaches": list(self.breaches),
            "unparsedSymbols": list(self.unparsed_symbols),
            "dominant": dominant.to_dict() if dominant else None,
            "limits": {
                "maxCurrencyExposure": self.max_currency_exposure,
                "maxCorrelatedExposure": self.max_correlated_exposure,
            },
        }


def split_symbol(symbol: str) -> tuple[str, str] | None:
    """Decompose un symbole en actif de base et actif de cotation.

    Retourne None pour un instrument non decomposable (indice, matiere
    premiere sans cotation explicite) : il sera traite comme un actif unique.
    """
    token = canonical_symbol(symbol) or strip_broker_suffix(symbol)
    if len(token) != 6:
        return None
    base, quote = token[:3], token[3:]
    known = CURRENCIES | METALS
    if quote in known:
        return base, quote
    return None


def _add(bucket: dict[str, list[float]], key: str, value: float) -> None:
    bucket.setdefault(key, []).append(value)


def aggregate_currency_exposure(legs: Sequence[ExposureLeg]) -> tuple[list[CurrencyExposure], list[str]]:
    """Exposition nette par devise ou actif, plus les symboles non decomposes."""
    amounts: dict[str, list[float]] = {}
    symbols: dict[str, list[str]] = {}
    unparsed: list[str] = []

    for leg in legs:
        sign = 1.0 if leg.direction is Direction.BUY else -1.0
        weight = abs(leg.weight) * sign
        parts = split_symbol(leg.symbol)
        if parts is None:
            asset = strip_broker_suffix(leg.symbol)
            unparsed.append(leg.symbol)
            _add(amounts, asset, weight)
            symbols.setdefault(asset, []).append(leg.symbol)
            continue
        base, quote = parts
        _add(amounts, base, weight)
        _add(amounts, quote, -weight)
        symbols.setdefault(base, []).append(leg.symbol)
        symbols.setdefault(quote, []).append(leg.symbol)

    exposures = [
        CurrencyExposure(
            currency=currency,
            net=sum(values),
            gross=sum(abs(value) for value in values),
            symbols=sorted(set(symbols.get(currency, []))),
        )
        for currency, values in amounts.items()
    ]
    exposures.sort(key=lambda item: abs(item.net), reverse=True)
    return exposures, sorted(set(unparsed))


def correlated_clusters(
    legs: Sequence[ExposureLeg],
    correlations: Mapping[str, Mapping[str, float]],
    threshold: float = STRONG_CORRELATION,
) -> list[CorrelatedCluster]:
    """Couples de positions qui revient au meme pari, correlations a l'appui."""
    clusters: list[CorrelatedCluster] = []
    for index, left in enumerate(legs):
        for right in legs[index + 1 :]:
            value = correlations.get(left.symbol, {}).get(right.symbol)
            if value is None:
                continue
            if abs(value) < threshold:
                continue
            left_sign = 1.0 if left.direction is Direction.BUY else -1.0
            right_sign = 1.0 if right.direction is Direction.BUY else -1.0
            aligned = left_sign * right_sign * value
            if aligned <= 0:
                # Positions opposees au sens de la correlation : elles se compensent.
                continue
            clusters.append(
                CorrelatedCluster(
                    symbols=sorted({left.symbol, right.symbol}),
                    exposure=abs(left.weight) + abs(right.weight),
                    correlation=value,
                )
            )
    clusters.sort(key=lambda item: item.exposure, reverse=True)
    return clusters


def evaluate_correlated_exposure(
    legs: Sequence[ExposureLeg],
    correlations: Mapping[str, Mapping[str, float]] | None = None,
    max_currency_exposure: float = DEFAULT_MAX_CURRENCY_EXPOSURE,
    max_correlated_exposure: float = DEFAULT_MAX_CORRELATED_EXPOSURE,
    correlation_threshold: float = STRONG_CORRELATION,
) -> ExposureAssessment:
    """Exposition agregee des positions, avec les depassements constates.

    Fonction destinee au RiskManager : synchrone, sans base de donnees, sans
    reseau. Elle decrit une situation et nomme les depassements ; la decision
    de refuser un ordre appartient a l'appelant.
    """
    currencies, unparsed = aggregate_currency_exposure(legs)
    clusters = (
        correlated_clusters(legs, correlations, correlation_threshold) if correlations else []
    )

    breaches: list[str] = []
    for item in currencies:
        if abs(item.net) > max_currency_exposure:
            way = "achetée" if item.net > 0 else "vendue"
            breaches.append(
                f"Exposition {way} agrégée de {abs(item.net):.2f} sur {item.currency} "
                f"(limite {max_currency_exposure:.2f}) via {', '.join(item.symbols)}."
            )
    for cluster in clusters:
        if cluster.exposure > max_correlated_exposure:
            breaches.append(
                f"Positions corrélées à {cluster.correlation:+.2f} sur "
                f"{' et '.join(cluster.symbols)} : exposition cumulée {cluster.exposure:.2f} "
                f"(limite {max_correlated_exposure:.2f})."
            )

    return ExposureAssessment(
        legs=len(legs),
        currencies=currencies,
        clusters=clusters,
        breaches=breaches,
        unparsed_symbols=unparsed,
        max_currency_exposure=max_currency_exposure,
        max_correlated_exposure=max_correlated_exposure,
    )


__all__ = [
    "DEFAULT_MAX_CORRELATED_EXPOSURE",
    "DEFAULT_MAX_CURRENCY_EXPOSURE",
    "CorrelatedCluster",
    "CurrencyExposure",
    "ExposureAssessment",
    "ExposureLeg",
    "aggregate_currency_exposure",
    "correlated_clusters",
    "evaluate_correlated_exposure",
    "split_symbol",
]
