"""Tests du generateur d'opportunites et des strategies (CDC2 sections 40, 41, 45).

Le test central de ce fichier est celui de l'interdiction absolue : l'IA ne
fixe aucun prix. Les niveaux sortent des regles deterministes, et le
commentaire des modeles ne peut pas les modifier — y compris quand le modele
renvoie des prix inventes.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction
from app.models.intelligence import AiOpportunity, MarketRegime, NewsImpact, TrendState
from app.repositories import decision_repo
from app.services.decision.inputs import (
    AnalysisBundle,
    ConsensusView,
    CrossMarketView,
    HistoricalView,
    MacroView,
    NewsView,
    PriceStructure,
    QuoteView,
    RegimeView,
    TechnicalView,
    TelegramView,
)
from app.services.opportunities.generator import GeneratorConfig, OpportunityGenerator
from app.services.opportunities.narrative import annotate, build_prompt
from app.services.opportunities.planner import LevelPlanner, PlannerConfig
from app.services.strategies.base import StrategyFamily, StrategyProposal
from app.services.strategies.families import (
    BreakoutStrategy,
    MeanReversionStrategy,
    PullbackStrategy,
    TrendFollowingStrategy,
)
from app.services.strategies.registry import StrategyRegistry, select_best

PREFIX = "/api/v1"


def _structure(**remplacements: Any) -> PriceStructure:
    base: dict[str, Any] = {
        "symbol": "XAUUSD",
        "last_price": 3500.0,
        "atr": 10.0,
        "digits": 2,
        "supports": [3480.0, 3450.0],
        "resistances": [3530.0, 3560.0],
        "swing_low": 3470.0,
        "swing_high": 3560.0,
        "computed_at": utcnow(),
    }
    base.update(remplacements)
    return PriceStructure(**base)


def _lectures(
    regime: MarketRegime = MarketRegime.TRENDING_UP,
    note: float = 0.85,
    tendance: TrendState = TrendState.BULLISH,
    tendance_courte: TrendState | None = None,
) -> AnalysisBundle:
    return AnalysisBundle(
        symbol="XAUUSD",
        quote=QuoteView(symbol="XAUUSD", bid=3500.0, ask=3500.3, captured_at=utcnow()),
        technical=TechnicalView(
            score=note,
            direction=Direction.BUY if tendance is TrendState.BULLISH else Direction.SELL,
            trend_d1=tendance,
            trend_h4=tendance,
            trend_h1=tendance_courte or tendance,
            detail="Structure lisible.",
        ),
        regime=RegimeView(regime=regime, score=note),
        historical=HistoricalView(score=note, direction=Direction.BUY, matches=12),
        macro=MacroView(score=note, direction=Direction.BUY),
        news=NewsView(score=note, impact=NewsImpact.LOW),
        cross_market=CrossMarketView(score=note, direction=Direction.BUY),
        telegram=TelegramView(score=note, direction=Direction.BUY),
        consensus=ConsensusView(score=note, direction=Direction.BUY, available=True),
    )


# ---------------------------------------------------------------------------
# Calcul deterministe des niveaux (CDC2 section 41)
# ---------------------------------------------------------------------------

def test_le_stop_est_calcule_depuis_la_structure_et_l_atr() -> None:
    resultat = LevelPlanner().plan(Direction.BUY, _structure())

    assert resultat.ok
    niveaux = resultat.levels
    assert niveaux is not None
    # Support le plus proche a 3480, moins 0,30 ATR de marge.
    assert niveaux.stop_loss == 3477.0
    assert niveaux.method == "structure+atr"
    assert niveaux.entry_price == 3500.0
    assert niveaux.entry_min == 3497.5
    assert niveaux.entry_max == 3502.5
    assert niveaux.risk_distance == 23.0


def test_la_premiere_cible_se_cale_sur_la_resistance() -> None:
    niveaux = LevelPlanner().plan(Direction.BUY, _structure()).levels

    assert niveaux is not None
    assert niveaux.take_profits[0] == 3530.0
    assert niveaux.first_target_rr == 1.30
    assert niveaux.expected_rr == 3.0


def test_une_resistance_trop_proche_est_ignoree_comme_cible() -> None:
    """Sous 1 R, l'obstacle ne devient pas une cible : on garde le multiple."""
    niveaux = LevelPlanner().plan(Direction.SELL, _structure()).levels

    assert niveaux is not None
    assert niveaux.stop_loss == 3533.0
    assert niveaux.take_profits[0] == 3467.0
    assert niveaux.take_profits == [3467.0, 3434.0, 3401.0]


def test_sans_volatilite_aucun_niveau_n_est_calcule() -> None:
    resultat = LevelPlanner().plan(Direction.BUY, _structure(atr=None))

    assert resultat.ok is False
    assert resultat.levels is None
    assert resultat.rejections[0].code == "NO_VOLATILITY"


def test_sans_structure_le_stop_retombe_sur_l_atr() -> None:
    resultat = LevelPlanner().plan(
        Direction.BUY, _structure(supports=[], resistances=[], swing_low=None, swing_high=None)
    )

    niveaux = resultat.levels
    assert niveaux is not None
    assert niveaux.method == "atr"
    assert niveaux.stop_loss == 3485.0  # 1,5 ATR sous l'entree


def test_un_stop_trop_proche_est_refuse() -> None:
    resultat = LevelPlanner().plan(
        Direction.BUY, _structure(supports=[3499.5], swing_low=None)
    )

    assert resultat.ok is False
    assert resultat.rejections[0].code == "STOP_TOO_CLOSE"


def test_un_stop_trop_eloigne_est_refuse() -> None:
    resultat = LevelPlanner().plan(
        Direction.BUY, _structure(supports=[3440.0], swing_low=None)
    )

    assert resultat.ok is False
    assert resultat.rejections[0].code == "STOP_TOO_FAR"


def test_le_planificateur_est_reproductible() -> None:
    """Memes entrees, memes prix : aucun alea, aucune interpretation."""
    premier = LevelPlanner().plan(Direction.BUY, _structure()).levels
    second = LevelPlanner().plan(Direction.BUY, _structure()).levels

    assert premier is not None and second is not None
    assert premier.to_dict() == second.to_dict()


def test_les_multiples_de_cible_sont_configurables() -> None:
    planificateur = LevelPlanner(PlannerConfig(target_multiples=(1.0, 4.0)))
    niveaux = planificateur.plan(
        Direction.BUY, _structure(resistances=[9999.0])
    ).levels

    assert niveaux is not None
    assert len(niveaux.take_profits) == 2
    assert niveaux.expected_rr == 4.0


# ---------------------------------------------------------------------------
# L'IA n'invente jamais les prix (CDC2 section 41)
# ---------------------------------------------------------------------------

@dataclass
class _ConsensusMenteur:
    """Reponse de modele truffee de prix inventes."""

    outcome: str = "CONSENSUS"
    direction: Direction | None = Direction.BUY
    confidence: float = 0.99
    detail: str = "Entrée conseillée 1.2345, stop 0.9999, TP 9999.99 — chiffres inventés."
    entry_price: float = 1.2345
    stop_loss: float = 0.9999
    take_profits: tuple[float, ...] = (9999.99,)

    @property
    def blocks_auto_trade(self) -> bool:
        return False


class _ServiceIaMenteur:
    """Service IA de test : il repond toujours, toujours avec des prix faux."""

    def __init__(self) -> None:
        self.appels = 0

    async def consensus(self, prompt: str, **kwargs: Any) -> _ConsensusMenteur:
        self.appels += 1
        self.dernier_prompt = prompt
        return _ConsensusMenteur()

    def requires_manual_review(self, result: Any) -> bool:
        return False


async def test_l_ia_ne_peut_pas_modifier_les_prix_calcules() -> None:
    """Preuve du CDC2 section 41 : les niveaux resistent a un modele menteur."""
    generateur = OpportunityGenerator()
    brouillon = generateur.generate(_lectures(), _structure())
    assert brouillon is not None

    avant = copy.deepcopy(brouillon.levels)
    service = _ServiceIaMenteur()

    apres = await annotate(brouillon, service)

    assert service.appels == 1
    assert apres.levels.to_dict() == avant.to_dict()
    assert apres.levels.entry_price == 3500.0
    assert apres.levels.stop_loss == 3477.0
    assert 1.2345 not in (apres.levels.entry_price, apres.levels.stop_loss)
    assert 9999.99 not in apres.levels.take_profits
    # Le modele n'a servi qu'a commenter.
    assert apres.ai_comment is not None


async def test_une_ia_en_panne_ne_casse_pas_l_opportunite() -> None:
    class _ServiceEnPanne:
        async def consensus(self, prompt: str, **kwargs: Any) -> Any:
            raise RuntimeError("moteur indisponible")

        def requires_manual_review(self, result: Any) -> bool:
            return True

    brouillon = OpportunityGenerator().generate(_lectures(), _structure())
    assert brouillon is not None
    avant = copy.deepcopy(brouillon.levels)

    apres = await annotate(brouillon, _ServiceEnPanne())

    assert apres.ai_comment is None
    assert apres.levels.to_dict() == avant.to_dict()


def test_le_prompt_interdit_explicitement_de_proposer_des_prix() -> None:
    brouillon = OpportunityGenerator().generate(_lectures(), _structure())
    assert brouillon is not None

    prompt = build_prompt(brouillon)

    assert "NE PAS MODIFIER" in prompt
    assert "N'indique aucun prix." in prompt
    assert "3477" in prompt  # le stop deja calcule est donne, pas demande


# ---------------------------------------------------------------------------
# Generation d'opportunites (CDC2 section 40)
# ---------------------------------------------------------------------------

def test_une_opportunite_complete_est_produite() -> None:
    brouillon = OpportunityGenerator().generate(_lectures(), _structure())

    assert brouillon is not None
    assert brouillon.direction is Direction.BUY
    assert brouillon.strategy == "trend_following"
    assert brouillon.levels.stop_loss < brouillon.levels.entry_price
    assert brouillon.levels.take_profits
    assert brouillon.levels.expected_rr is not None
    assert brouillon.confidence.score > 0
    assert brouillon.reasons
    assert brouillon.expires_at is not None


def test_une_opportunite_expose_ses_facteurs_negatifs() -> None:
    lectures = _lectures(note=0.85)
    lectures.macro = None

    brouillon = OpportunityGenerator().generate(lectures, _structure())

    assert brouillon is not None
    assert any("MACRO" in facteur for facteur in brouillon.negative_factors)


def test_une_confiance_insuffisante_marque_l_opportunite_comme_surveillee() -> None:
    brouillon = OpportunityGenerator(
        config=GeneratorConfig(min_confidence=0.95)
    ).generate(_lectures(note=0.80), _structure())

    assert brouillon is not None
    assert brouillon.qualified is False
    assert brouillon.to_model().status == "WATCHED"


def test_aucun_regime_exploitable_ne_produit_aucune_opportunite() -> None:
    """Ne rien proposer est un resultat normal (CDC2 section 2)."""
    brouillon = OpportunityGenerator().generate(
        _lectures(regime=MarketRegime.UNCERTAIN), _structure()
    )

    assert brouillon is None


def test_sans_volatilite_aucune_opportunite_n_est_produite() -> None:
    brouillon = OpportunityGenerator().generate(_lectures(), _structure(atr=None))

    assert brouillon is None


def test_un_plan_non_calculable_annule_l_opportunite() -> None:
    brouillon = OpportunityGenerator().generate(
        _lectures(), _structure(supports=[3440.0], swing_low=None)
    )

    assert brouillon is None


def test_l_opportunite_se_convertit_en_ligne_de_base() -> None:
    brouillon = OpportunityGenerator().generate(_lectures(), _structure())
    assert brouillon is not None

    ligne = brouillon.to_model(broker_symbol="XAUUSDm")

    assert isinstance(ligne, AiOpportunity)
    assert ligne.broker_symbol == "XAUUSDm"
    assert ligne.entry_price == brouillon.levels.entry_price
    assert ligne.stop_loss == brouillon.levels.stop_loss
    assert ligne.take_profits == brouillon.levels.take_profits


# ---------------------------------------------------------------------------
# Strategies (CDC2 section 45)
# ---------------------------------------------------------------------------

def test_le_suivi_de_tendance_s_active_en_tendance() -> None:
    proposition = TrendFollowingStrategy().propose(_lectures(), _structure())

    assert proposition is not None
    assert proposition.family is StrategyFamily.TREND_FOLLOWING
    assert proposition.direction is Direction.BUY


def test_le_suivi_de_tendance_se_tait_en_range() -> None:
    proposition = TrendFollowingStrategy().propose(
        _lectures(regime=MarketRegime.RANGING), _structure()
    )

    assert proposition is None


def test_la_cassure_s_active_au_dela_du_niveau() -> None:
    lectures = _lectures(regime=MarketRegime.BREAKOUT)
    structure = _structure(resistances=[3490.0], supports=[3400.0], swing_high=None)

    proposition = BreakoutStrategy().propose(lectures, structure)

    assert proposition is not None
    assert proposition.direction is Direction.BUY
    assert proposition.family is StrategyFamily.BREAKOUT


def test_une_cassure_des_deux_cotes_est_ambigue() -> None:
    lectures = _lectures(regime=MarketRegime.BREAKOUT)
    structure = _structure(resistances=[3490.0], supports=[3510.0])

    assert BreakoutStrategy().propose(lectures, structure) is None


def test_le_repli_exige_une_unite_de_temps_courte_contraire() -> None:
    lectures = _lectures(tendance_courte=TrendState.BEARISH)
    structure = _structure(supports=[3495.0], swing_low=None)

    proposition = PullbackStrategy().propose(lectures, structure)

    assert proposition is not None
    assert proposition.family is StrategyFamily.PULLBACK
    assert proposition.direction is Direction.BUY


def test_le_repli_se_tait_quand_tout_est_deja_aligne() -> None:
    assert PullbackStrategy().propose(_lectures(), _structure()) is None


def test_le_retour_a_la_moyenne_joue_les_extremes_du_range() -> None:
    lectures = _lectures(regime=MarketRegime.RANGING)
    structure = _structure(
        last_price=3482.0, supports=[3480.0], resistances=[3520.0], swing_low=None
    )

    proposition = MeanReversionStrategy().propose(lectures, structure)

    assert proposition is not None
    assert proposition.direction is Direction.BUY
    assert proposition.family is StrategyFamily.MEAN_REVERSION


def test_le_retour_a_la_moyenne_se_tait_au_milieu_du_range() -> None:
    lectures = _lectures(regime=MarketRegime.RANGING)
    structure = _structure(last_price=3500.0, supports=[3480.0], resistances=[3520.0])

    assert MeanReversionStrategy().propose(lectures, structure) is None


def test_le_registre_n_active_que_les_strategies_implementees() -> None:
    class _Brouillon(TrendFollowingStrategy):
        name = "jamais_testee"
        enabled = False

    registre = StrategyRegistry([_Brouillon()])

    assert registre.strategies == []


def test_le_registre_refuse_un_doublon() -> None:
    registre = StrategyRegistry([TrendFollowingStrategy()])

    try:
        registre.register(TrendFollowingStrategy())
    except ValueError as exc:
        assert "déjà" in str(exc)
    else:  # pragma: no cover - le doublon doit lever
        raise AssertionError("Un doublon aurait dû être refusé.")


def test_les_quatre_familles_sont_actives() -> None:
    familles = {strategie.family for strategie in StrategyRegistry().strategies}

    assert familles == set(StrategyFamily)


def test_deux_strategies_contradictoires_ne_tranchent_pas() -> None:
    """Le doute ne se tranche pas : aucune proposition retenue."""
    propositions = [
        StrategyProposal("a", StrategyFamily.BREAKOUT, Direction.BUY, 0.70),
        StrategyProposal("b", StrategyFamily.MEAN_REVERSION, Direction.SELL, 0.68),
    ]

    assert select_best(propositions) is None


def test_une_contradiction_nette_laisse_gagner_la_meilleure() -> None:
    propositions = [
        StrategyProposal("a", StrategyFamily.BREAKOUT, Direction.BUY, 0.90),
        StrategyProposal("b", StrategyFamily.MEAN_REVERSION, Direction.SELL, 0.40),
    ]

    meilleure = select_best(propositions)

    assert meilleure is not None and meilleure.strategy == "a"


def test_un_score_de_strategie_reste_entre_zero_et_un() -> None:
    proposition = StrategyProposal("a", StrategyFamily.BREAKOUT, Direction.BUY, 4.2)

    assert proposition.score == 1.0


# ---------------------------------------------------------------------------
# Routes (CDC2 section 72)
# ---------------------------------------------------------------------------

async def test_les_opportunites_sont_listees(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    brouillon = OpportunityGenerator().generate(_lectures(), _structure())
    assert brouillon is not None
    ligne = await decision_repo.save_opportunity(session, brouillon.to_model())
    await session.commit()

    reponse = await auth_client.get(f"{PREFIX}/opportunities")
    assert reponse.status_code == 200
    charge = reponse.json()

    assert charge["total"] == 1
    premiere = charge["items"][0]
    assert premiere["symbol"] == "XAUUSD"
    assert premiere["stopLoss"] == 3477.0
    assert premiere["reasons"]

    detail = await auth_client.get(f"{PREFIX}/opportunities/{ligne.id}")
    assert detail.status_code == 200
    assert detail.json()["takeProfits"]


async def test_une_opportunite_inconnue_renvoie_404(auth_client: AsyncClient) -> None:
    reponse = await auth_client.get(f"{PREFIX}/opportunities/123456")

    assert reponse.status_code == 404


async def test_les_opportunites_exigent_un_appairage(client: AsyncClient) -> None:
    reponse = await client.get(f"{PREFIX}/opportunities")

    assert reponse.status_code == 401
