"""Le moteur de decision regle seul son exigence de confiance.

Demande du 16/09/2026 : « il doit le changer, pas besoin de la presence d'un
humain ». La regle CDC2 qui reservait toute evolution de configuration a une
decision humaine ne vaut donc plus ici.

Une asymetrie assumee, faute de capteur. Une perte mesuree justifie de
**lever** l'exigence : la preuve est la, dans les trades reellement clos. Rien
ne mesure en revanche ce qui se passe SOUS le seuil -- ces opportunites sont
ecartees avant d'exister. Le regleur peut donc toujours defaire ses propres
hausses quand la performance se redresse, mais il ne descend pas sous la
reference posee par l'humain tant qu'aucune mesure ne couvre cette zone.
"""

from __future__ import annotations

import pytest

from app.models.core import utcnow
from app.models.intelligence import DecisionSource, StrategyPerformance
from app.repositories import ai_repo
from app.services.learning import tuner


async def _performance(session, trades: int, net_r: float, jour: str = "2026-09-16") -> None:
    """Une ligne de performance agregee, telle que le recorder en produit."""
    gagnants = trades if net_r > 0 else 0
    session.add(
        StrategyPerformance(
            day=jour,
            strategy="BREAKOUT",
            source=DecisionSource.AI_GENERATED,
            trades=trades,
            wins=gagnants,
            losses=trades - gagnants,
            net_r=net_r,
            net_pnl=net_r * 10.0,
        )
    )
    await session.flush()


async def test_le_seuil_monte_quand_les_trades_perdent(session) -> None:
    """Dix trades a -1 R : l'exigence se releve d'un pas."""
    await _performance(session, trades=10, net_r=-10.0)

    decisions = await tuner.tune(session)

    assert [item.key for item in decisions] == ["min_opportunity_confidence"]
    reglages = await ai_repo.get_settings(session)
    assert reglages.min_opportunity_confidence == pytest.approx(0.77)


async def test_rien_ne_bouge_sous_le_minimum_d_echantillon(session) -> None:
    await _performance(session, trades=9, net_r=-9.0)

    assert await tuner.tune(session) == []
    reglages = await ai_repo.get_settings(session)
    assert reglages.min_opportunity_confidence == pytest.approx(0.75)


async def test_une_perte_marginale_ne_fait_rien_bouger(session) -> None:
    """-0,05 R de moyenne est du bruit centre, pas une preuve."""
    await _performance(session, trades=20, net_r=-1.0)

    assert await tuner.tune(session) == []


async def test_un_pas_exige_une_preuve_neuve(session) -> None:
    await _performance(session, trades=10, net_r=-10.0)
    assert len(await tuner.tune(session)) == 1

    # Meme mesure, tour suivant : rien de neuf a apprendre.
    assert await tuner.tune(session) == []
    reglages = await ai_repo.get_settings(session)
    assert reglages.min_opportunity_confidence == pytest.approx(0.77)


async def test_le_seuil_revient_vers_sa_reference_quand_ca_se_redresse(session) -> None:
    """Le regleur defait ses propres hausses : c'est le sens « baisser »."""
    await _performance(session, trades=10, net_r=-10.0)
    await tuner.tune(session)

    await _performance(session, trades=12, net_r=24.0, jour="2026-09-17")
    decisions = await tuner.tune(session)

    assert [item.key for item in decisions] == ["min_opportunity_confidence"]
    reglages = await ai_repo.get_settings(session)
    assert reglages.min_opportunity_confidence == pytest.approx(0.75)


async def test_le_seuil_ne_descend_jamais_sous_la_reference_humaine(session) -> None:
    """Sous le seuil, rien n'est mesure : descendre y serait un pari aveugle."""
    await _performance(session, trades=15, net_r=30.0)

    assert await tuner.tune(session) == []
    reglages = await ai_repo.get_settings(session)
    assert reglages.min_opportunity_confidence == pytest.approx(0.75)


async def _marginale(session, r_multiple: float, index: int = 0) -> None:
    """Une simulation de la bande marginale, deja close."""
    from app.models.enums import Direction
    from app.models.intelligence import ShadowOutcome, ShadowTrade
    from app.repositories import decision_repo

    await decision_repo.save_shadow_trade(
        session,
        ShadowTrade(
            symbol=f"SYM{index:02d}USD",
            broker_symbol=f"SYM{index:02d}USDm",
            outcome=ShadowOutcome.WOULD_BUY,
            direction=Direction.BUY,
            entry_price=100.0,
            stop_loss=98.0,
            take_profit=104.0,
            marginal=True,
            r_multiple=r_multiple,
            result="WIN" if r_multiple > 0 else "LOSS",
            closed_at=utcnow(),
            close_price=104.0 if r_multiple > 0 else 98.0,
        ),
    )


async def test_le_seuil_descend_sous_la_reference_quand_la_bande_gagne(session) -> None:
    """Le capteur debloque ce que la reference interdisait faute de mesure."""
    for index in range(10):
        await _marginale(session, r_multiple=1.5, index=index)

    decisions = await tuner.tune(session)

    assert [item.key for item in decisions] == ["min_opportunity_confidence"]
    reglages = await ai_repo.get_settings(session)
    assert reglages.min_opportunity_confidence == pytest.approx(0.73)


async def test_une_bande_insuffisante_ne_franchit_pas_la_reference(session) -> None:
    """Neuf simulations ne prouvent rien : la reference tient."""
    for index in range(9):
        await _marginale(session, r_multiple=1.5, index=index)

    assert await tuner.tune(session) == []
    reglages = await ai_repo.get_settings(session)
    assert reglages.min_opportunity_confidence == pytest.approx(0.75)


async def test_une_bande_perdante_ne_fait_rien_descendre(session) -> None:
    for index in range(12):
        await _marginale(session, r_multiple=-1.0, index=index)

    assert await tuner.tune(session) == []


async def test_le_seuil_ne_descend_pas_sous_le_plancher_absolu(session) -> None:
    """Meme prouvee, la bande ne fait pas tomber l'exigence a rien."""
    await ai_repo.update_settings(
        session, {"min_opportunity_confidence": tuner.MARGINAL_FLOOR}
    )
    for index in range(10):
        await _marginale(session, r_multiple=1.5, index=index)

    assert await tuner.tune(session) == []


async def test_le_seuil_ne_depasse_pas_son_plafond(session) -> None:
    """Une exigence a 0,95 n'accepterait plus rien : ce n'est plus un reglage."""
    await ai_repo.update_settings(session, {"min_opportunity_confidence": tuner.CEILING})
    await _performance(session, trades=10, net_r=-10.0)

    assert await tuner.tune(session) == []
