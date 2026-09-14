"""Budget de risque journalier illimite : la valeur 0 desactive le plafond.

Le moteur traitait deja 0 comme « illimite » a ses trois points de controle,
mais le schema de l'API refusait cette valeur (``ge=0.1``) : le reglage etait
donc inatteignable depuis l'application. Ces tests verrouillent la coherence
entre les deux, et surtout le fait que desactiver CE plafond ne desactive rien
d'autre.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import ExecutionMode, RejectionReason
from app.schemas.requests import RiskSettingsRequest
from app.services.risk.manager import RiskManager
from app.services.risk.quality import quality_multiplier
from app.services.trading.paper import PaperTradingService
from tests.test_risk_manager import (
    BALANCE,
    make_context,
    make_settings,
    make_signal,
    make_state,
)


# ---------------------------------------------------------------------------
# Le schema de l'API
# ---------------------------------------------------------------------------
class TestSchemaApi:
    def test_zero_est_accepte(self) -> None:
        """Sans cela, « illimite » reste inatteignable depuis l'application."""
        requete = RiskSettingsRequest.model_validate({"maxDailyRiskPercent": 0})
        assert requete.max_daily_risk_percent == 0

    def test_une_valeur_negative_reste_refusee(self) -> None:
        with pytest.raises(ValidationError):
            RiskSettingsRequest.model_validate({"maxDailyRiskPercent": -1})

    def test_le_plafond_de_perte_reste_borne_a_zero_exclu(self) -> None:
        """Desactiver le budget de RISQUE ne doit pas ouvrir celui des PERTES."""
        with pytest.raises(ValidationError):
            RiskSettingsRequest.model_validate({"maxDailyLossPercent": 0})

    def test_une_valeur_normale_passe_toujours(self) -> None:
        requete = RiskSettingsRequest.model_validate({"maxDailyRiskPercent": 12})
        assert requete.max_daily_risk_percent == 12


# ---------------------------------------------------------------------------
# Le dimensionnement
# ---------------------------------------------------------------------------
class TestDimensionnement:
    def test_le_budget_ne_bride_plus_la_taille(self) -> None:
        """C'est ce facteur qui ecrasait 4 % a 0,737 % le 14/09/2026."""
        bride = quality_multiplier(
            risk_percent=4.0,
            risk_reward=2.0,
            spread_cost=0.1,
            stop_distance=10.0,
            age_seconds=10.0,
            max_signal_age_seconds=300,
            consecutive_losses=0,
            warnings=[],
            source=None,
            day_risked_percent=11.26,
            max_daily_risk_percent=12.0,
        )
        illimite = quality_multiplier(
            risk_percent=4.0,
            risk_reward=2.0,
            spread_cost=0.1,
            stop_distance=10.0,
            age_seconds=10.0,
            max_signal_age_seconds=300,
            consecutive_losses=0,
            warnings=[],
            source=None,
            day_risked_percent=11.26,
            max_daily_risk_percent=0.0,
        )
        assert bride.budget_factor == pytest.approx(0.185, abs=0.01)
        assert illimite.budget_factor == pytest.approx(1.0)
        assert illimite.sized_risk_percent > bride.sized_risk_percent

    def test_le_multiplicateur_ne_depasse_toujours_jamais_un(self) -> None:
        """L'invariant du module tient meme sans plafond journalier."""
        resultat = quality_multiplier(
            risk_percent=4.0,
            risk_reward=9.0,
            spread_cost=0.0,
            stop_distance=100.0,
            age_seconds=0.0,
            max_signal_age_seconds=300,
            consecutive_losses=0,
            warnings=[],
            source=None,
            day_risked_percent=0.0,
            max_daily_risk_percent=0.0,
        )
        assert resultat.multiplier <= 1.0
        assert resultat.sized_risk_percent <= 4.0 + 1e-9


# ---------------------------------------------------------------------------
# Le RiskManager
# ---------------------------------------------------------------------------
class TestRiskManager:
    async def test_un_cumul_enorme_ne_bloque_plus(self, paper: PaperTradingService) -> None:
        """Avec 0, le cumul du jour ne peut plus refuser un trade."""
        context = await make_context(
            paper,
            settings=make_settings(max_daily_risk_percent=0.0),
            state=make_state(day_risked_percent=95.0),
        )
        decision = await RiskManager(paper).evaluate(
            make_signal(), context, ExecutionMode.PAPER
        )
        assert decision.reason is not RejectionReason.DAILY_RISK_LIMIT

    async def test_le_plafond_reste_actif_quand_il_est_renseigne(
        self, paper: PaperTradingService
    ) -> None:
        """La desactivation doit etre explicite, jamais un effet de bord."""
        context = await make_context(
            paper,
            settings=make_settings(max_daily_risk_percent=12.0),
            state=make_state(day_risked_percent=95.0),
        )
        decision = await RiskManager(paper).evaluate(
            make_signal(), context, ExecutionMode.PAPER
        )
        assert decision.approved is False
        assert decision.reason is RejectionReason.DAILY_RISK_LIMIT

    async def test_la_perte_du_jour_protege_encore(
        self, paper: PaperTradingService
    ) -> None:
        """Le garde-fou qui compte les pertes REELLES n'est pas touche."""
        context = await make_context(
            paper,
            settings=make_settings(max_daily_risk_percent=0.0, max_daily_loss_percent=8.0),
            state=make_state(day_realized_pnl=-0.20 * BALANCE),
        )
        decision = await RiskManager(paper).evaluate(
            make_signal(), context, ExecutionMode.PAPER
        )
        assert decision.approved is False
        assert decision.reason is RejectionReason.DAILY_LOSS_LIMIT
