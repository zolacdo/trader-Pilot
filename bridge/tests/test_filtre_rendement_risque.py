"""Le filtre de rendement/risque doit juger la sortie que le systeme execute.

``min_risk_reward`` etait mesure sur TP1 seul, quelle que soit la strategie de
sortie configuree. Or TP1 n'est le point de sortie que pour ``FIRST_TP_ONLY`` :

* ``LAST_TP_ONLY``  -> toute la position va au dernier objectif ;
* ``PARTIAL_CLOSE`` -> la position est portee au dernier objectif, avec des
  fermetures partielles aux objectifs intermediaires ;
* ``SPLIT_POSITIONS`` -> une position par objectif, ponderee par les ratios.

Le meme RiskManager dimensionnait deja sur la sortie reelle
(``weighted_risk_reward``) et refusait sur TP1 : il mesurait donc deux choses
differentes selon qu'il s'agissait de choisir la taille ou d'accepter le trade.

Mesure du 14/09/2026 sur les 65 signaux du jour du canal PARAMOUR, en
``PARTIAL_CLOSE`` 40/30/30 : **zero** passait un seuil de 1,0 juge sur TP1,
contre une mediane de 0,63 et un maximum de 1,23 sur la sortie reelle. Un
seuil pose a 1,0 fermait donc le robot entier, au lieu d'ecarter les mauvais
signaux.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction, ExecutionMode, MultiTpStrategy, RejectionReason
from app.services.risk.manager import RiskManager
from app.services.trading.paper import PaperTradingService
from tests.test_risk_manager import (
    make_context,
    make_settings,
    make_signal,
    make_state,
)

# Signal de reference : stop a 10 points, objectifs a +4, +8, +12.
# TP1 seul  -> 4 / 10               = 0,40
# Pondere   -> (0,4x4 + 0,3x8 + 0,3x12) / 10 = 0,76
ENTREE = 3320.0
STOP = 3310.0
CIBLES = [3324.0, 3328.0, 3332.0]
RR_TP1 = 0.40
RR_PONDERE = 0.76


async def _evaluer(
    paper: PaperTradingService,
    *,
    strategie: MultiTpStrategy,
    minimum: float | None,
    cibles: list[float] | None = None,
):
    context = await make_context(
        paper,
        settings=make_settings(
            min_risk_reward=minimum,
            multi_tp_strategy=strategie,
            split_ratios=[40.0, 30.0, 30.0],
            execution_mode=ExecutionMode.PAPER,
        ),
        state=make_state(),
    )
    signal = make_signal(
        direction=Direction.BUY,
        entry_price=ENTREE,
        stop_loss=STOP,
        take_profits=list(cibles if cibles is not None else CIBLES),
    )
    return await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)


def _detail_rr(decision) -> float:
    for check in decision.checks:
        if check.name == "risk_reward":
            return float(check.detail)
    raise AssertionError("aucun controle risk_reward dans la decision")


class TestLaMesureSuitLaStrategieDeSortie:
    async def test_partial_close_juge_la_sortie_ponderee(
        self, paper: PaperTradingService
    ) -> None:
        """La strategie configuree chez l'utilisateur le 14/09."""
        decision = await _evaluer(
            paper, strategie=MultiTpStrategy.PARTIAL_CLOSE, minimum=None
        )
        assert _detail_rr(decision) == pytest.approx(RR_PONDERE, abs=0.01)

    async def test_split_positions_juge_la_sortie_ponderee(
        self, paper: PaperTradingService
    ) -> None:
        decision = await _evaluer(
            paper, strategie=MultiTpStrategy.SPLIT_POSITIONS, minimum=None
        )
        assert _detail_rr(decision) == pytest.approx(RR_PONDERE, abs=0.01)

    async def test_first_tp_only_juge_toujours_tp1(
        self, paper: PaperTradingService
    ) -> None:
        """La seule strategie ou TP1 est reellement le point de sortie."""
        decision = await _evaluer(
            paper, strategie=MultiTpStrategy.FIRST_TP_ONLY, minimum=None
        )
        assert _detail_rr(decision) == pytest.approx(RR_TP1, abs=0.01)

    async def test_last_tp_only_juge_le_dernier_objectif(
        self, paper: PaperTradingService
    ) -> None:
        decision = await _evaluer(
            paper, strategie=MultiTpStrategy.LAST_TP_ONLY, minimum=None
        )
        assert _detail_rr(decision) == pytest.approx(1.20, abs=0.01)


class TestLeSeuilPorteSurLaBonneGrandeur:
    async def test_un_signal_refuse_a_tort_passe_desormais(
        self, paper: PaperTradingService
    ) -> None:
        """0,76 en sortie reelle : au-dessus du seuil de 0,60, donc accepte.

        Juge sur TP1 (0,40) il etait refuse -- c'est ce qui a ferme le robot.
        """
        decision = await _evaluer(
            paper, strategie=MultiTpStrategy.PARTIAL_CLOSE, minimum=0.60
        )
        assert decision.approved, decision.detail

    async def test_un_signal_reellement_mauvais_reste_refuse(
        self, paper: PaperTradingService
    ) -> None:
        """Objectifs a +1, +2, +3 sur un stop de 10 : 0,19 en sortie reelle."""
        decision = await _evaluer(
            paper,
            strategie=MultiTpStrategy.PARTIAL_CLOSE,
            minimum=0.60,
            cibles=[3321.0, 3322.0, 3323.0],
        )
        assert not decision.approved
        assert decision.reason is RejectionReason.RR_TOO_LOW

    async def test_first_tp_only_reste_juge_severement(
        self, paper: PaperTradingService
    ) -> None:
        """On ne relache rien : qui sort a TP1 est juge sur TP1."""
        decision = await _evaluer(
            paper, strategie=MultiTpStrategy.FIRST_TP_ONLY, minimum=0.60
        )
        assert not decision.approved
        assert decision.reason is RejectionReason.RR_TOO_LOW

    async def test_un_objectif_unique_ne_change_pas_de_mesure(
        self, paper: PaperTradingService
    ) -> None:
        """Sans paliers, la sortie ponderee retombe exactement sur TP1."""
        decision = await _evaluer(
            paper,
            strategie=MultiTpStrategy.PARTIAL_CLOSE,
            minimum=None,
            cibles=[3324.0],
        )
        assert _detail_rr(decision) == pytest.approx(RR_TP1, abs=0.01)
