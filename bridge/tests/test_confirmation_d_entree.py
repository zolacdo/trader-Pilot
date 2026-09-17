"""La confirmation d'entree devient une barriere, plus un contributeur.

Mesure du 17/09/2026 sur les 41 signaux denoues : l'etat de l'unite de
confirmation separe le jeu en deux moities presque symetriques.

    ENTRY_CONFIRMATION  19 signaux  excursion 1,37  +10,14 R  68 % gagnants
    WAIT                22 signaux  excursion 0,76  -11,69 R  23 % gagnants

L'effet tient dans les deux populations prises separement -- publies +8,93 R
contre -4,92 R, fantomes +1,22 R contre -6,77 R -- donc ce n'est pas
l'artefact de l'une d'elles.

Elle n'etait pourtant qu'un contributeur a une moyenne ponderee : un
``market_structure`` fort pouvait l'outvoter. Le meme defaut de structure que
le biais, et la meme reponse : une moyenne ne sait pas dire « ceci est
disqualifiant », il faut une barriere.

Aucune autre barriere ne vient par-dessus, et c'est mesure aussi : exiger en
plus un declencheur M15 ramene les 19 signaux a 12 et le total de +10,14 a
+4,24 R -- les 7 ecartes valaient +5,90 R a eux seuls. La confirmation
contient deja la chaine complete des graphes, puisque ``_confirmation_state``
exige un biais D1+H4 directionnel, un momentum M5 dans ce sens et une
tendance M5 qui ne s'y oppose pas.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction
from app.models.intelligence import Timeframe, TrendState
from app.services.technical_analysis.multi_timeframe import (
    MultiTimeframeView,
    TimeframeRole,
    TimeframeVerdict,
)
from app.watcher import risk
from app.watcher.analysis.context import MarketContext
from app.watcher.config import WatcherConfig
from app.watcher.levels import build_levels
from app.watcher.models import RiskVerdict
from app.watcher.scoring import score_direction
from tests.test_watcher_decision import make_context


@pytest.fixture
def config() -> WatcherConfig:
    return WatcherConfig()


def avec_confirmation(context: MarketContext, state: str) -> MarketContext:
    """Attache une vue dont l'unite de confirmation est dans l'etat voulu."""
    context.view = MultiTimeframeView(
        symbol=context.symbol, profile="default", bias=TrendState.BULLISH
    )
    context.view.verdicts = [
        TimeframeVerdict(
            timeframe=Timeframe.D1,
            role=TimeframeRole.CONTEXT,
            state="BULLISH",
            trend=TrendState.BULLISH,
        ),
        TimeframeVerdict(
            timeframe=Timeframe.H1,
            role=TimeframeRole.STRUCTURE,
            state="PULLBACK",
            trend=TrendState.BEARISH,
        ),
        TimeframeVerdict(
            timeframe=Timeframe.M5,
            role=TimeframeRole.CONFIRMATION,
            state=state,
            trend=TrendState.BULLISH,
        ),
    ]
    return context


def evaluer(context: MarketContext, config: WatcherConfig) -> risk.RiskDecision:
    direction = Direction.BUY
    levels = build_levels(context, direction, config.minimum_rr)
    card = score_direction(context, direction, levels, config)
    return risk.evaluate(context, direction, levels, card, config, risk.PortfolioState())


def test_sans_confirmation_le_signal_attend(config: WatcherConfig) -> None:
    """Le cas -11,69 R : entrer sans feu vert de l'unite de confirmation."""
    context = avec_confirmation(make_context(), "WAIT")

    decision = evaluer(context, config)

    assert decision.verdict is not RiskVerdict.APPROVED
    assert any("confirmation" in reason.lower() for reason in decision.reasons)


def test_avec_la_confirmation_la_barriere_ne_retient_pas(config: WatcherConfig) -> None:
    """Le cas +10,14 R doit passer : elle ne refuse que l'absence de feu vert."""
    config.minimum_score = 0.0
    context = avec_confirmation(make_context(), "ENTRY_CONFIRMATION")

    decision = evaluer(context, config)

    assert not any("confirmation" in reason.lower() for reason in decision.reasons)


def test_une_confirmation_non_mesurable_est_dite_comme_telle(config: WatcherConfig) -> None:
    """Une donnee manquante n'est pas un refus mesure, et se lit autrement.

    La barriere attend dans les deux cas -- une confirmation exige un feu
    vert, pas seulement l'absence de feu rouge -- mais le motif doit
    distinguer « le marche ne confirme pas » de « je n'ai pas pu le mesurer ».
    Sans cela une panne de donnees M5 se lirait comme un marche hesitant, et
    personne n'irait chercher la panne.
    """
    context = avec_confirmation(make_context(), "NO_DATA")

    decision = evaluer(context, config)

    assert decision.verdict is not RiskVerdict.APPROVED
    assert any("non mesurable" in reason.lower() for reason in decision.reasons)


def test_sans_vue_la_barriere_ne_se_declenche_pas(config: WatcherConfig) -> None:
    """Sans vue multi-unites, la couverture s'en charge deja.

    Le meme principe que la barriere de direction : on refuse une absence
    MESUREE, jamais une absence de mesure.
    """
    context = make_context()
    assert context.view is None

    decision = evaluer(context, config)

    assert not any("confirmation" in reason.lower() for reason in decision.reasons)


def test_la_barriere_se_desarme_par_reglage(config: WatcherConfig) -> None:
    """Une decision reste un reglage, jamais du code (CDC3 section 41)."""
    config.minimum_score = 0.0
    config.require_entry_confirmation = False
    context = avec_confirmation(make_context(), "WAIT")

    decision = evaluer(context, config)

    assert not any("confirmation" in reason.lower() for reason in decision.reasons)


def test_les_tendances_par_unite_sont_enregistrees(config: WatcherConfig) -> None:
    """Ce que la base ne gardait pas, et qui a manque pour mesurer.

    Le contexte du signal stockait ``timeframes``, c'est-a-dire l'etat
    dependant du role : une H1 baissiere en repli s'y lit ``PULLBACK`` et sa
    tendance disparait. Sur les 41 signaux denoues, 15 avaient ainsi leur
    tendance H1 masquee, et aucune requete ne pouvait la retrouver. On
    enregistre donc les deux : l'etat pour lire le role, la tendance pour
    mesurer la direction.
    """
    context = avec_confirmation(make_context(), "ENTRY_CONFIRMATION")

    resume = context.summary()

    assert resume["timeframes"]["H1"] == "PULLBACK"
    assert resume["trends"]["H1"] == "BEARISH"
    assert resume["trends"]["M5"] == "BULLISH"
