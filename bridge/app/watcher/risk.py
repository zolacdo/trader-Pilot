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
from app.models.intelligence import TrendState
from app.services.technical_analysis.multi_timeframe import (
    STATE_ENTRY_CONFIRMATION,
    STATE_NO_DATA,
    TimeframeRole,
)
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


def _entree_ecartee(levels: TradeLevels, config: WatcherConfig) -> bool:
    """Vrai si l'apprentissage a ecarte ce type d'entree."""
    entry_type = getattr(levels, "entry_type", None)
    if entry_type is None:
        return False
    valeur = str(getattr(entry_type, "value", entry_type)).upper()
    return valeur in {str(item).upper() for item in config.disabled_entry_types or []}


def _confirmation_manquante(context: MarketContext, config: WatcherConfig) -> str | None:
    """Motif d'attente si l'unite de confirmation ne donne pas son feu vert.

    Mesure du 17/09/2026 sur les 41 premiers signaux denoues -- c'est la
    separation la plus nette de tout le jeu de donnees :

        ENTRY_CONFIRMATION  19 signaux  excursion 1,37  +10,14 R  68 % gagnants
        WAIT                22 signaux  excursion 0,76  -11,69 R  23 % gagnants

    Elle tient dans les deux populations prises separement (publies +8,93 R
    contre -4,92 R, fantomes +1,22 R contre -6,77 R), donc ce n'est pas
    l'artefact de l'une d'elles.

    Rien ne vient par-dessus, et c'est mesure aussi : exiger en plus un
    declencheur M15 ramene les 19 signaux a 12 et le total a +4,24 R -- les 7
    ecartes valaient +5,90 R. C'est coherent avec ``_confirmation_state``, qui
    exige deja un biais D1+H4 directionnel, un momentum de confirmation dans
    ce sens et une tendance qui ne s'y oppose pas : la confirmation est la
    synthese des graphes, pas la lecture isolee du plus petit.

    Une confirmation exige un feu vert, pas seulement l'absence de feu rouge :
    une unite sans donnee fait donc attendre elle aussi. Mais le motif le dit
    autrement, sinon une panne de donnees se lirait comme un marche hesitant
    et personne n'irait chercher la panne.
    """
    if not config.require_entry_confirmation or context.view is None:
        # Sans vue multi-unites, le critere n'est pas mesure : la couverture
        # s'en charge deja. On refuse une absence MESUREE, pas une absence de
        # mesure.
        return None
    verdicts = [
        verdict
        for verdict in context.view.verdicts
        if verdict.role is TimeframeRole.CONFIRMATION
    ]
    if not verdicts:
        return None
    verdict = verdicts[0]
    unite = verdict.timeframe.value
    if verdict.state == STATE_ENTRY_CONFIRMATION:
        return None
    if verdict.state == STATE_NO_DATA:
        return (
            f"Confirmation d'entree non mesurable sur {unite} : "
            "historique insuffisant sur cette unite de temps."
        )
    return (
        f"Aucune confirmation d'entree sur {unite} : le momentum ne va pas "
        "encore dans le sens du biais. Le setup reste surveille et sera "
        "reevalue a la confirmation."
    )


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

    # --- direction du marche ------------------------------------------------
    # Le biais n'etait qu'un contributeur a une moyenne ponderee : un
    # ``market_structure``, une ``volatility`` et des ``indicators`` forts
    # pouvaient l'outvoter et publier un trade directionnel dans un marche qui
    # n'allait nulle part. Une moyenne ne sait pas dire « ceci est
    # disqualifiant » -- il faut une barriere.
    #
    # Mesure du 17/09/2026 sur les six signaux reels denoues : les deux seuls
    # qui n'ont JAMAIS bouge d'un tick en notre faveur (excursion favorable
    # 0,00 R) sont exactement les deux dont le biais etait NEUTRAL. Les quatre
    # a biais directionnel ont tous avance d'au moins 0,51 R. L'un des deux --
    # USDJPY achete -- avait meme un journalier baissier.
    #
    # C'est une absence de direction MESUREE, jamais une absence de mesure :
    # sans vue multi-unites le critere correspondant est indisponible et la
    # couverture s'en charge deja. Confondre les deux ferait refuser pour
    # « pas de direction » ce qui n'a simplement pas ete mesure.
    if context.view is not None and context.bias is TrendState.NEUTRAL:
        waits.append(
            "Aucune direction de marche : les unites de temps ne s'accordent sur "
            "rien, et un declencheur sans tendance derriere lui est du bruit."
        )

    # La confirmation est redondante avec la barriere ci-dessus, qu'elle
    # contient : ``_confirmation_state`` renvoie WAIT des que le biais est
    # NEUTRAL. On garde les deux parce qu'elles ne disent pas la meme chose --
    # l'une nomme l'absence de direction, l'autre l'absence de feu vert -- et
    # parce que desarmer l'une par reglage ne doit pas desarmer l'autre.
    confirmation = _confirmation_manquante(context, config)
    if confirmation is not None:
        waits.append(confirmation)

    # --- qualite du setup ---------------------------------------------------
    if levels is None or not levels.valid:
        motif = levels.rejection if levels is not None else "Niveaux non calculables."
        rejections.append(motif or "Niveaux non calculables.")
    elif _entree_ecartee(levels, config):
        # C'est ici que la decision de l'apprentissage prend effet. Sans ce
        # refus, ``disabled_entry_types`` serait ecrit par la boucle et lu par
        # personne : le bannissement serait annonce dans le canal sans jamais
        # empecher un seul signal.
        rejections.append(
            f"Type d'entree {levels.entry_type.value} ecarte par l'apprentissage : "
            "aucun gain sur les dernieres operations denouees."
        )
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
