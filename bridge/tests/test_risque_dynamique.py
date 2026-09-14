"""Le risque par trade est recalcule pour CHAQUE signal, selon sa qualite.

Avant, ``risk_percent`` etait une constante : deux signaux du meme canal
prenaient la meme taille, qu'ils soient excellents ou mediocres. Ces tests
verrouillent le nouveau comportement et, surtout, l'invariant qui le rend sur :
le multiplicateur ne peut JAMAIS augmenter la taille.
"""

from __future__ import annotations

import pytest

from app.models.enums import ExecutionMode, ParserSource, RejectionReason
from app.services.risk.manager import RiskManager
from app.services.risk.quality import (
    QualityMultiplier,
    quality_multiplier,
    weighted_risk_reward,
)
from app.services.trading.paper import PaperTradingService
from tests.test_risk_manager import (
    BALANCE,
    make_context,
    make_settings,
    make_signal,
    make_state,
    open_position,
)


def calculer(**kwargs: object) -> QualityMultiplier:
    """Signal de reference : parfait sur tous les axes, multiplicateur = 1."""
    base: dict[str, object] = {
        "risk_percent": 1.0,
        "risk_reward": 2.0,
        "spread_cost": 0.1,
        "stop_distance": 10.0,
        "age_seconds": 10.0,
        "max_signal_age_seconds": 300,
        "consecutive_losses": 0,
        "warnings": [],
        "source": ParserSource.DETERMINISTIC,
        "day_risked_percent": 0.0,
        "max_daily_risk_percent": 3.0,
    }
    base.update(kwargs)
    return quality_multiplier(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# L'invariant fondamental
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("risk_reward", [None, 0.1, 0.5, 1.0, 2.0, 5.0, 50.0])
@pytest.mark.parametrize("spread_cost", [0.0, 0.1, 0.26, 2.0, 50.0])
@pytest.mark.parametrize("consecutive_losses", [0, 1, 2, 10])
def test_le_multiplicateur_ne_depasse_jamais_un(
    risk_reward: float | None, spread_cost: float, consecutive_losses: int
) -> None:
    """Aucune combinaison d'entrees ne doit pouvoir amplifier la taille.

    C'est ce qui rend la regle des 1,5x du RiskManager inatteignable et permet
    de n'avoir a toucher aucun garde-fou existant.
    """
    resultat = calculer(
        risk_reward=risk_reward,
        spread_cost=spread_cost,
        consecutive_losses=consecutive_losses,
    )
    assert 0.0 <= resultat.multiplier <= 1.0
    assert resultat.sized_risk_percent <= 1.0 + 1e-9


def test_un_signal_parfait_garde_le_risque_configure() -> None:
    resultat = calculer()
    assert resultat.multiplier == pytest.approx(1.0)
    assert resultat.sized_risk_percent == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Chaque facteur pris isolement
# ---------------------------------------------------------------------------

def test_un_mauvais_ratio_rendement_risque_reduit_la_taille() -> None:
    """Le R:R est la seule mesure vraiment continue de la qualite du trade."""
    bon = calculer(risk_reward=2.0)
    mediocre = calculer(risk_reward=1.0)
    absent = calculer(risk_reward=None)

    assert mediocre.multiplier < bon.multiplier
    assert absent.multiplier < bon.multiplier
    assert mediocre.factors["rendement_risque"] == pytest.approx(0.50)


def test_le_spread_de_l_or_reel_n_est_pas_penalise() -> None:
    """Cas mesure en production, et la raison d'etre de cette mesure.

    Les signaux or reels ont 260 points de spread, soit 0,26 dollar, face a un
    stop de 10 dollars : le spread absorbe 2,6 % du risque, ce qui est normal.
    Une echelle en points le penalisait au maximum et refusait tous ces
    signaux ; ancree sur le cout reel, la penalite disparait.
    """
    reel = calculer(spread_cost=0.26, stop_distance=10.0)
    assert reel.factors["spread"] == pytest.approx(1.0)


def test_un_spread_qui_mange_le_risque_est_penalise() -> None:
    """Un scalp a stop tres serre paie le spread trois fois plutot qu'une."""
    devorant = calculer(spread_cost=0.26, stop_distance=0.8)
    assert devorant.factors["spread"] < 0.7


def test_la_mesure_du_spread_est_comparable_entre_instruments() -> None:
    """Le meme poids economique doit donner le meme facteur.

    Or : 0,26 dollar de spread sur 2 dollars de stop. Bitcoin : 10 dollars de
    spread sur 77 dollars de stop. Les deux absorbent environ 13 % du risque,
    donc les deux doivent etre juges pareil -- alors qu'en points l'un affiche
    260 et l'autre 1000.
    """
    de_l_or = calculer(spread_cost=0.26, stop_distance=2.0)
    du_bitcoin = calculer(spread_cost=10.0, stop_distance=77.0)
    assert de_l_or.factors["spread"] == pytest.approx(du_bitcoin.factors["spread"], abs=0.02)


def test_la_tolerance_reglee_par_l_utilisateur_n_influence_plus_le_facteur() -> None:
    """Relacher son propre seuil ne doit pas faire grossir les positions.

    C'est le piege de l'ancienne mesure relative : plus le canal tolerait de
    spread, moins le spread comptait dans le dimensionnement.
    """
    assert "max_spread_points" not in quality_multiplier.__code__.co_varnames


def test_les_pertes_consecutives_reduisent_la_taille() -> None:
    assert calculer(consecutive_losses=1).factors["series_perdantes"] == pytest.approx(0.75)
    assert calculer(consecutive_losses=2).factors["series_perdantes"] == pytest.approx(0.50)
    # Plancher : on ne descend pas sous 0,50, le blocage a 3 pertes prend le relais.
    assert calculer(consecutive_losses=9).factors["series_perdantes"] == pytest.approx(0.50)


def test_un_signal_sans_horodatage_n_est_pas_penalise() -> None:
    """L'absence de date n'est pas une preuve de retard.

    Penaliser ``age_seconds is None`` taxerait le chemin manuel et le chemin
    API, qui ne sont pas en retard pour autant.
    """
    assert calculer(age_seconds=None).factors["fraicheur"] == pytest.approx(1.0)


def test_les_anomalies_de_parsing_reduisent_la_taille() -> None:
    propre = calculer(warnings=[])
    sale = calculer(warnings=["a", "b", "c"])
    assert sale.multiplier < propre.multiplier


# ---------------------------------------------------------------------------
# Le budget journalier est une contrainte dure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("deja_risque", [0.0, 1.0, 2.5, 2.99, 3.0, 4.0])
def test_le_risque_dimensionne_ne_deborde_jamais_du_budget_du_jour(deja_risque: float) -> None:
    """Invariant : le risque dimensionne ne depasse jamais le budget RESTANT.

    C'est ici que prendre le MINIMUM au lieu du PRODUIT laissait passer un
    depassement : le facteur budgetaire est calcule par rapport au risque
    prevu, il doit donc le multiplier, pas le concurrencer.

    Quand le budget est deja consomme, le reste est nul et le dimensionnement
    tombe a zero ; c'est ``calculate_lot`` qui refusera proprement, et la
    barriere DAILY_RISK_LIMIT en amont a de toute facon deja bloque.
    """
    resultat = calculer(
        risk_percent=4.0, day_risked_percent=deja_risque, max_daily_risk_percent=3.0
    )
    reste = max(0.0, 3.0 - deja_risque)
    assert resultat.sized_risk_percent <= reste + 1e-9


def test_un_budget_journalier_desactive_ne_bride_rien() -> None:
    resultat = calculer(max_daily_risk_percent=0.0)
    assert resultat.budget_factor == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# La demande : deux signaux differents, deux risques differents
# ---------------------------------------------------------------------------

def test_deux_signaux_differents_donnent_deux_risques_differents() -> None:
    """Le coeur de la demande : le pourcentage cesse d'etre une constante."""
    excellent = calculer(risk_reward=3.0, spread_cost=0.05, consecutive_losses=0)
    moyen = calculer(risk_reward=1.2, spread_cost=1.5, consecutive_losses=0)
    mauvais = calculer(
        risk_reward=None, spread_cost=4.0, consecutive_losses=2, warnings=["x"]
    )

    risques = [
        excellent.sized_risk_percent,
        moyen.sized_risk_percent,
        mauvais.sized_risk_percent,
    ]
    assert len(set(risques)) == 3, f"les trois signaux prennent le meme risque : {risques}"
    assert excellent.sized_risk_percent > moyen.sized_risk_percent > mauvais.sized_risk_percent


def test_le_plancher_empeche_une_reduction_sans_fin() -> None:
    ecrase = calculer(
        risk_reward=None,
        spread_cost=500.0,
        consecutive_losses=2,
        warnings=["a"] * 20,
        floor=0.35,
    )
    assert ecrase.quality == pytest.approx(0.35)


# ---------------------------------------------------------------------------
# Integration dans le RiskManager
# ---------------------------------------------------------------------------

async def test_eteint_le_risque_reste_exactement_celui_configure(
    paper: PaperTradingService,
) -> None:
    """Par defaut rien ne bouge : 0,5 % de 10 000 avec 10 $ de stop -> 0,05 lot."""
    context = await make_context(paper)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)

    assert decision.approved is True, decision.detail
    assert decision.lot is not None
    assert decision.lot.volume == pytest.approx(0.05)


async def test_allume_un_signal_mediocre_prend_un_lot_plus_petit(
    paper: PaperTradingService,
) -> None:
    context = await make_context(paper, settings=make_settings(dynamic_risk_enabled=True))
    manager = RiskManager(paper)

    bon = await manager.evaluate(make_signal(), context, ExecutionMode.PAPER)
    # Take profit rapproche : le ratio rendement/risque tombe de 2,0 a 0,5.
    mediocre = await manager.evaluate(
        make_signal(take_profits=[3325.0]), context, ExecutionMode.PAPER
    )

    assert bon.approved is True and mediocre.approved is True
    assert bon.lot is not None and mediocre.lot is not None
    assert mediocre.lot.volume < bon.lot.volume, (
        f"le signal mediocre prend le meme lot : {mediocre.lot.volume}"
    )


async def test_allume_la_regle_des_1_5x_ne_se_declenche_jamais(
    paper: PaperTradingService,
) -> None:
    """Detecteur de regression : si ce test tombe, le multiplicateur amplifie."""
    context = await make_context(paper, settings=make_settings(dynamic_risk_enabled=True))
    manager = RiskManager(paper)

    for take_profits in ([3340.0], [3325.0], [3321.0], [3500.0]):
        decision = await manager.evaluate(
            make_signal(take_profits=take_profits), context, ExecutionMode.PAPER
        )
        assert decision.reason is not RejectionReason.RISK_TOO_HIGH, decision.detail


async def test_le_motif_de_refus_dit_que_le_risque_a_ete_reduit(
    paper: PaperTradingService,
) -> None:
    """Sans cette mention, le message accuserait le courtier a tort."""
    context = await make_context(
        paper,
        settings=make_settings(dynamic_risk_enabled=True, risk_percent=0.01),
    )
    decision = await RiskManager(paper).evaluate(
        make_signal(take_profits=[3325.0]), context, ExecutionMode.PAPER
    )

    assert decision.approved is False
    assert decision.reason is RejectionReason.INVALID_VOLUME
    detail = decision.detail or ""
    # On verrouille le SENS, pas la formulation : la reduction doit etre dite,
    # et le risque configure nomme pour que la comparaison soit verifiable.
    assert "reduite" in detail
    assert "risque configure" in detail


# ---------------------------------------------------------------------------
# Les deux trous confirmes : plafond et exposition ignoraient le trade en cours
# ---------------------------------------------------------------------------

async def test_le_plafond_journalier_compte_le_trade_en_cours(
    paper: PaperTradingService,
) -> None:
    """Le controle ne comparait que le cumul ANTERIEUR.

    Un seul trade pouvait donc terminer la journee tres au-dessus du plafond.
    """
    context = await make_context(
        paper,
        settings=make_settings(max_daily_risk_percent=0.3),
        state=make_state(day_risked_percent=0.2),
    )
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)

    assert decision.approved is False
    assert decision.reason is RejectionReason.DAILY_RISK_LIMIT
    assert "projete" in (decision.detail or "")


async def test_l_exposition_compte_le_lot_a_venir(paper: PaperTradingService) -> None:
    """Meme trou sur l'exposition totale : le lot a ouvrir n'etait pas compte."""
    context = await make_context(
        paper,
        settings=make_settings(max_total_exposure_lots=0.98),
        open_positions=[open_position(symbol="EURUSD", volume=0.95)],
    )
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)

    assert decision.approved is False
    assert decision.reason is RejectionReason.MAX_EXPOSURE
    assert "projetee" in (decision.detail or "")


def test_le_solde_reste_celui_des_fixtures() -> None:
    """Garde-fou : les calculs ci-dessus supposent un compte de 10 000."""
    assert BALANCE == 10000.0


# ---------------------------------------------------------------------------
# Le rendement se juge sur la sortie reelle, pas sur TP1 seul
# ---------------------------------------------------------------------------

def test_avec_un_seul_take_profit_le_rendement_est_celui_de_tp1() -> None:
    """Aucune surprise sur les signaux simples : la valeur ne change pas."""
    valeur = weighted_risk_reward(
        entry=3320.0, stop_loss=3310.0, take_profits=[3340.0], split_ratios=[40.0, 30.0, 30.0]
    )
    assert valeur == pytest.approx(2.0)


def test_les_paliers_de_sortie_sont_ponderes() -> None:
    """Signal or reel : 10 points de stop, TP a +3 / +6 / +9, sortie 40/30/30.

    Sur TP1 seul le ratio vaut 0,30 et ecraserait le signal au plancher ;
    la sortie reelle rapporte (0,4x3 + 0,3x6 + 0,3x9) / 10 = 0,57.
    """
    valeur = weighted_risk_reward(
        entry=4372.0,
        stop_loss=4362.0,
        take_profits=[4375.0, 4378.0, 4381.0, 4384.0, 4387.0],
        split_ratios=[40.0, 30.0, 30.0],
    )
    assert valeur == pytest.approx(0.57)


def test_un_signal_sans_take_profit_ou_sans_stop_ne_donne_rien() -> None:
    assert weighted_risk_reward(
        entry=3320.0, stop_loss=None, take_profits=[3340.0], split_ratios=[100.0]
    ) is None
    assert weighted_risk_reward(
        entry=3320.0, stop_loss=3310.0, take_profits=[], split_ratios=[100.0]
    ) is None
    # Stop confondu avec l'entree : aucun risque mesurable.
    assert weighted_risk_reward(
        entry=3320.0, stop_loss=3320.0, take_profits=[3340.0], split_ratios=[100.0]
    ) is None


def test_des_ratios_absents_retombent_sur_le_premier_palier() -> None:
    valeur = weighted_risk_reward(
        entry=3320.0, stop_loss=3310.0, take_profits=[3340.0, 3360.0], split_ratios=[]
    )
    assert valeur == pytest.approx(2.0)
