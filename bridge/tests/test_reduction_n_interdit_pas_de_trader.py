"""Reduire une taille ne doit jamais revenir a interdire la position.

Le multiplicateur de qualite existe pour diminuer l'exposition quand le
contexte est mauvais -- serie perdante, budget de risque du jour entame,
parsing douteux. Sur un petit compte il produisait l'effet inverse : le lot
reduit tombait sous le minimum du courtier, et le signal etait refuse
entierement. Moins d'exposition devenait zero exposition.

Mesure du 18/09/2026, trois refus `INVALID_VOLUME` dont un de huit minutes :

    623 USDJPY  risque 2,00% -> 1,200%   facteur : series_perdantes (0.50)
    574 US30    risque 2,00% -> 1,370%   facteur : series_perdantes (0.75)
    229 XAUUSD  risque 4,00% -> 3,008%   facteur : rendement_risque (0.79)

Le message de refus disait deja tout : « Au risque configure, le lot minimum
couterait 7.26 (1.85% du solde) **et serait accepte** ». Le calcul etait donc
juste, la conclusion fausse.

``_streak_factor`` vaut ``clamp(1 - 0,25 x pertes, 0,50, 1,0)`` : deux pertes
consecutives suffisent a atteindre le plancher de 0,50. Autrement dit, apres
deux pertes, un petit compte cessait purement et simplement de trader -- au
moment precis ou le systeme croyait seulement lever le pied.

Quand la reduction est la seule cause du refus ET que le lot minimum tient
dans le risque **configure**, on prend donc le lot minimum. C'est la plus
petite exposition qui existe, et elle coute par construction moins que ce que
l'utilisateur a autorise. Le garde-fou ``effective_risk`` reste derriere :
depasser 1,5 fois le risque configure refuse toujours.
"""

from __future__ import annotations

import pytest

from app.models.enums import ExecutionMode
from app.services.risk.manager import RiskManager
from app.services.trading.paper import PaperTradingService
from tests.test_risk_manager import make_context, make_settings, make_signal, make_state

# 0,12 % de 10 000 = 12 USD, soit 0,012 lot pour 1000 USD de perte au lot.
# Reduit de moitie par la serie perdante : 6 USD, soit 0,006 lot -- sous le
# minimum de 0,01. Le lot minimum, lui, coute 10 USD, donc 0,10 % du solde :
# il tient dans les 0,12 % configures.
RISQUE = 0.12


def reglages(**overrides: object):
    """Reglages avec le risque dynamique actif, comme sur le compte reel.

    Sans ``dynamic_risk_enabled``, le multiplicateur n'est jamais calcule et
    ces tests passeraient sans rien eprouver. Le plancher est fixe a 0,50 pour
    que la serie perdante puisse l'atteindre : en production il vaut 0,60, et
    le signal 623 y est tombe exactement (2,00 % -> 1,200 %).
    """
    return make_settings(dynamic_risk_enabled=True, dynamic_risk_floor=0.5, **overrides)


async def test_deux_pertes_consecutives_n_empechent_pas_de_trader(
    paper: PaperTradingService,
) -> None:
    """Le cas du signal 623 : la reduction ne doit pas fermer la porte."""
    context = await make_context(
        paper,
        settings=reglages(risk_percent=RISQUE),
        state=make_state(consecutive_losses=2),
    )

    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)

    assert decision.approved is True, decision.detail
    assert decision.lot is not None
    assert decision.lot.volume == pytest.approx(0.01)


async def test_le_lot_minimum_reste_sous_le_risque_configure(
    paper: PaperTradingService,
) -> None:
    """On ne depasse pas ce que l'utilisateur a autorise : c'est la condition."""
    context = await make_context(
        paper,
        settings=reglages(risk_percent=RISQUE),
        state=make_state(consecutive_losses=2),
    )

    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)

    assert decision.lot is not None
    assert decision.lot.loss_at_stop is not None
    plafond = context.balance * RISQUE / 100.0
    assert decision.lot.loss_at_stop <= plafond + 1e-9


async def test_un_compte_vraiment_trop_petit_est_toujours_refuse(
    paper: PaperTradingService,
) -> None:
    """La porte ne s'ouvre que si le lot minimum tient dans le risque configure.

    Sans ce test, il suffirait de retomber toujours sur le lot minimum pour
    faire passer le precedent -- et le systeme depasserait alors le risque
    voulu sur les comptes que le courtier ne peut pas servir.
    """
    context = await make_context(
        paper,
        # 0,05 % de 10 000 = 5 USD, alors que le lot minimum en coute 10.
        settings=reglages(risk_percent=0.05),
        state=make_state(consecutive_losses=2),
    )

    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)

    assert decision.approved is False
    assert "trop petit" in (decision.detail or "").lower()


async def test_sans_serie_perdante_le_lot_normal_est_conserve(
    paper: PaperTradingService,
) -> None:
    """Le repli ne s'applique qu'au refus : il ne rabote pas un lot valide."""
    context = await make_context(
        paper,
        settings=reglages(risk_percent=0.5),
        state=make_state(consecutive_losses=0),
    )

    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)

    assert decision.approved is True, decision.detail
    assert decision.lot is not None
    assert decision.lot.volume == pytest.approx(0.05)
