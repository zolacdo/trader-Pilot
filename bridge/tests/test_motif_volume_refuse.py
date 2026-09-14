"""Un volume refuse doit nommer sa cause reelle, pas son symptome.

Le message accusait le lot minimum du courtier. Le 14/09/2026, un signal
XAUUSD a ete refuse ainsi alors que le courtier n'y etait pour rien : le
budget de risque du jour etait a 11,26 % sur 12, le multiplicateur avait donc
ecrase le risque de 4 % a 0,737 %, et c'est CE risque minuscule qui faisait
tomber le volume sous 0,01 lot. Au risque configure, le lot minimum n'aurait
coute que 2,25 % du solde : il passait largement.

Ces tests verrouillent le partage entre les deux causes possibles.
"""

from __future__ import annotations

import pytest

from app.services.risk.calculator import CAUSE_BELOW_VOLUME_MIN, LotCalculation, calculate_lot
from app.services.risk.manager import _explain_volume_failure
from app.services.risk.quality import quality_multiplier
from app.services.trading.paper import PaperTradingService

BALANCE = 488.32


def refus_sous_minimum(minimum_lot_loss: float = 11.00) -> LotCalculation:
    """Echec type : volume calcule sous le lot minimum du courtier."""
    return LotCalculation(
        ok=False,
        reason="Volume calcule 0.0033 sous le minimum broker 0.01",
        cause=CAUSE_BELOW_VOLUME_MIN,
        minimum_lot_loss=minimum_lot_loss,
        risk_amount=3.60,
        loss_per_lot=1100.0,
    )


def multiplicateur_budget_epuise():
    """Le multiplicateur reellement observe le 14/09/2026."""
    return quality_multiplier(
        risk_percent=4.0,
        risk_reward=1.0,
        spread_cost=0.3,
        stop_distance=11.0,
        age_seconds=30.0,
        max_signal_age_seconds=300,
        consecutive_losses=0,
        warnings=[],
        source=None,
        day_risked_percent=11.26,
        max_daily_risk_percent=12.0,
        floor=1.0,
    )


# ---------------------------------------------------------------------------
# Cas reel : la taille avait ete reduite en amont
# ---------------------------------------------------------------------------
class TestReductionEnAmont:
    def test_le_courtier_n_est_plus_accuse(self) -> None:
        """Le cas exact du 14/09/2026, reproduit avec ses vrais chiffres."""
        quality = multiplicateur_budget_epuise()
        motif = _explain_volume_failure(
            lot=refus_sous_minimum(),
            quality=quality,
            configured_risk_percent=4.0,
            sized_risk_percent=quality.sized_risk_percent,
            balance=BALANCE,
        )
        assert "Taille reduite en amont" in motif
        assert "4.00%" in motif
        assert "minimum broker" not in motif

    def test_il_dit_que_le_lot_minimum_serait_acceptable(self) -> None:
        """C'est l'information qui manquait : le lot minimum passait."""
        quality = multiplicateur_budget_epuise()
        motif = _explain_volume_failure(
            lot=refus_sous_minimum(),
            quality=quality,
            configured_risk_percent=4.0,
            sized_risk_percent=quality.sized_risk_percent,
            balance=BALANCE,
        )
        assert "serait accepte" in motif
        assert "2.25% du solde" in motif

    def test_il_nomme_le_facteur_le_plus_penalisant(self) -> None:
        quality = multiplicateur_budget_epuise()
        motif = _explain_volume_failure(
            lot=refus_sous_minimum(),
            quality=quality,
            configured_risk_percent=4.0,
            sized_risk_percent=quality.sized_risk_percent,
            balance=BALANCE,
        )
        assert "penalisant" in motif


# ---------------------------------------------------------------------------
# Cas ou le compte est reellement trop petit
# ---------------------------------------------------------------------------
class TestCompteTropPetit:
    def test_sans_reduction_la_cause_est_le_compte(self) -> None:
        motif = _explain_volume_failure(
            lot=refus_sous_minimum(minimum_lot_loss=43.70),
            quality=None,
            configured_risk_percent=4.0,
            sized_risk_percent=4.0,
            balance=BALANCE,
        )
        assert "Compte trop petit pour ce stop" in motif
        assert "8.95% du solde" in motif
        assert "Taille reduite" not in motif

    def test_avec_reduction_les_deux_sont_dits(self) -> None:
        """Une reduction ne doit pas masquer un compte reellement trop petit."""
        quality = multiplicateur_budget_epuise()
        motif = _explain_volume_failure(
            lot=refus_sous_minimum(minimum_lot_loss=43.70),
            quality=quality,
            configured_risk_percent=4.0,
            sized_risk_percent=quality.sized_risk_percent,
            balance=BALANCE,
        )
        assert "Compte trop petit pour ce stop" in motif
        assert "reduite" in motif


# ---------------------------------------------------------------------------
# Les autres causes ne sont pas reecrites
# ---------------------------------------------------------------------------
class TestAutresCauses:
    @pytest.mark.parametrize(
        "motif_calculateur",
        [
            "Stop loss confondu avec l'entree",
            "Impossible de valoriser le risque sur XAUUSD",
            "Pourcentage de risque nul",
        ],
    )
    def test_un_autre_echec_garde_son_motif(self, motif_calculateur: str) -> None:
        lot = LotCalculation(ok=False, reason=motif_calculateur)
        motif = _explain_volume_failure(
            lot=lot,
            quality=None,
            configured_risk_percent=4.0,
            sized_risk_percent=4.0,
            balance=BALANCE,
        )
        assert motif == motif_calculateur

    def test_un_solde_nul_ne_fait_pas_diviser_par_zero(self) -> None:
        motif = _explain_volume_failure(
            lot=refus_sous_minimum(),
            quality=None,
            configured_risk_percent=4.0,
            sized_risk_percent=4.0,
            balance=0.0,
        )
        assert motif


# ---------------------------------------------------------------------------
# Le calculateur renseigne bien ce dont le manager a besoin
# ---------------------------------------------------------------------------
class TestCalculateur:
    async def test_le_refus_porte_sa_cause_et_le_cout_du_lot_minimum(
        self, paper: PaperTradingService
    ) -> None:
        symbol = await paper.symbol_info("XAUUSD")
        assert symbol is not None
        from app.models.enums import Direction

        lot = await calculate_lot(
            service=paper,
            symbol=symbol,
            direction=Direction.BUY,
            entry=3350.0,
            stop_loss=3340.0,
            balance=BALANCE,
            # Risque volontairement minuscule : le volume tombera sous 0.01.
            risk_percent=0.01,
        )
        assert lot.ok is False
        assert lot.cause == CAUSE_BELOW_VOLUME_MIN
        assert lot.minimum_lot_loss is not None and lot.minimum_lot_loss > 0
        assert "minimum broker" in (lot.reason or "")
        assert lot.to_dict()["minimumLotLoss"] == pytest.approx(lot.minimum_lot_loss, abs=0.01)

    async def test_un_volume_suffisant_n_a_ni_cause_ni_cout_minimum(
        self, paper: PaperTradingService
    ) -> None:
        symbol = await paper.symbol_info("XAUUSD")
        assert symbol is not None
        from app.models.enums import Direction

        lot = await calculate_lot(
            service=paper,
            symbol=symbol,
            direction=Direction.BUY,
            entry=3350.0,
            stop_loss=3340.0,
            balance=BALANCE,
            risk_percent=4.0,
        )
        assert lot.ok is True
        assert lot.cause is None
        assert lot.minimum_lot_loss is None
