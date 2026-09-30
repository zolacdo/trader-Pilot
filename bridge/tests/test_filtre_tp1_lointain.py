"""Un TP1 trop loin de l'entree, compare au risque, est refuse.

Rejeu M1 du 30/09/2026 sur les 46 trades clotures du compte demo : quand
TP1 etait a plus de 1,2 R de l'entree, 8 trades sur 10 allaient au stop
sans jamais toucher TP1, contre 2 sur 11 sous 0,7 R. Le stop est alors trop
serre pour ce que le signal vise, et le bruit l'atteint avant le mouvement.
Sans ces 10 trades, les 36 restants passaient de -4,74 R a +2,77 R.
"""

from __future__ import annotations

from app.models.enums import Direction, ExecutionMode, MultiTpStrategy, RejectionReason
from app.services.risk.manager import RiskManager
from app.services.trading.paper import PaperTradingService
from tests.test_risk_manager import make_context, make_settings, make_signal, make_state

ENTREE = 3320.0
STOP = 3310.0  # risque de 10


async def _evaluer(paper: PaperTradingService, *, maximum: float | None, tp1: float):
    context = await make_context(
        paper,
        settings=make_settings(
            max_tp1_risk_ratio=maximum,
            multi_tp_strategy=MultiTpStrategy.LAST_TP_ONLY,
            execution_mode=ExecutionMode.PAPER,
        ),
        state=make_state(),
    )
    signal = make_signal(
        direction=Direction.BUY,
        entry_price=ENTREE,
        stop_loss=STOP,
        take_profits=[tp1, tp1 + 10.0, tp1 + 20.0],
    )
    return await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)


async def test_tp1_au_dela_du_maximum_est_refuse(paper: PaperTradingService) -> None:
    """TP1 a +15 sur un risque de 10 : 1,5 R, au-dela de 1,2 R."""
    decision = await _evaluer(paper, maximum=1.2, tp1=3335.0)

    assert not decision.approved
    assert decision.reason is RejectionReason.RR_TOO_LOW
    assert "TP1" in decision.detail


async def test_tp1_sous_le_maximum_passe(paper: PaperTradingService) -> None:
    """TP1 a +10 : 1,0 R, le cas des signaux du watcher."""
    decision = await _evaluer(paper, maximum=1.2, tp1=3330.0)

    assert decision.approved, decision.detail


async def test_sans_maximum_le_filtre_est_eteint(paper: PaperTradingService) -> None:
    """NULL, le defaut d'une installation neuve : rien ne change."""
    decision = await _evaluer(paper, maximum=None, tp1=3340.0)

    assert decision.approved, decision.detail
