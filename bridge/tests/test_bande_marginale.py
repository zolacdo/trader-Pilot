"""Bande marginale du moteur de decision : mesurer ce que le seuil ecarte.

Sans ce capteur, abaisser ``min_opportunity_confidence`` serait un pari : les
opportunites sous le seuil sont ecartees avant d'exister, et le shadow mode du
CDC2 ne les enregistre que lorsqu'il est actif -- c'est-a-dire quand plus rien
ne part au broker, donc sans rien a quoi les comparer.

Une opportunite ecartee pour la SEULE raison du seuil est donc enregistree
avec ses niveaux, pendant que le trading continue normalement. Puis elle est
suivie sur les bougies reelles jusqu'a son stop, son objectif, ou son age
limite. C'est ce qui rend la descente du seuil defendable.

Etat constate le 16/09/2026 : 72 trades fantomes en base, tous WOULD_SKIP,
aucun clos, le dernier datant du 11/09 -- et ``close_shadow_trade`` n'etait
appele de nulle part.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.core import utcnow
from app.models.enums import Direction
from app.models.intelligence import ShadowOutcome, ShadowTrade
from app.repositories import decision_repo
from app.services.decision import shadow_tracker
from app.services.mt5.interface import Candle


class FauxMoteur:
    """Moteur de bougies minimal : rend la serie qu'on lui donne."""

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self.service = None
        self.demandes: list[str] = []

    async def candles(self, symbol: str, timeframe, bars: int) -> list[Candle]:
        self.demandes.append(symbol)
        return list(self._candles)


def _bougie(high: float, low: float, close: float, minute: int = 1) -> Candle:
    return Candle(
        time=utcnow() - timedelta(minutes=60 - minute),
        open=100.0,
        high=high,
        low=low,
        close=close,
        tick_volume=10,
    )


async def _marginal(session, **overrides) -> ShadowTrade:
    """Un achat marginal : entree 100, stop 98, objectif 104."""
    valeurs: dict[str, object] = {
        "symbol": "TESTUSD",
        "broker_symbol": "TESTUSDm",
        "outcome": ShadowOutcome.WOULD_BUY,
        "direction": Direction.BUY,
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "marginal": True,
        "opened_at": utcnow() - timedelta(hours=1),
    }
    valeurs.update(overrides)
    return await decision_repo.save_shadow_trade(session, ShadowTrade(**valeurs))


async def test_un_stop_touche_cloture_la_simulation(session) -> None:
    trade = await _marginal(session)
    moteur = FauxMoteur([_bougie(high=101.0, low=97.0, close=97.5)])

    rapport = await shadow_tracker.advance_open_trades(session, moteur)

    assert rapport.closed == 1
    assert trade.closed_at is not None
    assert trade.close_price == pytest.approx(98.0)
    assert trade.r_multiple == pytest.approx(-1.0)
    assert trade.result == "LOSS"


async def test_un_objectif_atteint_cloture_la_simulation(session) -> None:
    trade = await _marginal(session)
    moteur = FauxMoteur([_bougie(high=104.5, low=99.5, close=104.2)])

    await shadow_tracker.advance_open_trades(session, moteur)

    assert trade.close_price == pytest.approx(104.0)
    assert trade.r_multiple == pytest.approx(2.0)
    assert trade.result == "WIN"


async def test_le_stop_prime_sur_l_objectif_dans_la_meme_bougie(session) -> None:
    """On ignore l'ordre reel : l'hypothese retenue est la plus prudente.

    Meme convention que le suivi du watcher. Supposer l'inverse gonflerait les
    statistiques de la bande, et c'est precisement sur elles qu'on s'appuiera
    pour abaisser le seuil.
    """
    trade = await _marginal(session)
    moteur = FauxMoteur([_bougie(high=105.0, low=97.0, close=104.0)])

    await shadow_tracker.advance_open_trades(session, moteur)

    assert trade.close_price == pytest.approx(98.0)
    assert trade.result == "LOSS"


async def test_une_simulation_sans_issue_reste_ouverte(session) -> None:
    trade = await _marginal(session)
    moteur = FauxMoteur([_bougie(high=101.0, low=99.0, close=100.5)])

    rapport = await shadow_tracker.advance_open_trades(session, moteur)

    assert rapport.closed == 0
    assert trade.closed_at is None


async def test_une_simulation_trop_vieille_est_chiffree_au_dernier_cours(session) -> None:
    """Elle ne peut pas rester ouverte a vie : sinon elle ne mesure rien."""
    trade = await _marginal(
        session, opened_at=utcnow() - timedelta(hours=shadow_tracker.MAX_AGE_HOURS + 1)
    )
    moteur = FauxMoteur([_bougie(high=101.0, low=99.0, close=100.6)])

    await shadow_tracker.advance_open_trades(session, moteur)

    assert trade.closed_at is not None
    assert trade.close_price == pytest.approx(100.6)
    assert trade.r_multiple == pytest.approx(0.3)


async def test_les_bougies_sont_demandees_au_symbole_du_courtier(session) -> None:
    """Le symbole canonique ne dit rien au terminal : « TESTUSD » n'existe pas."""
    await _marginal(session)
    moteur = FauxMoteur([_bougie(high=101.0, low=99.0, close=100.5)])

    await shadow_tracker.advance_open_trades(session, moteur)

    assert moteur.demandes == ["TESTUSDm"]


async def test_une_decision_de_ne_rien_faire_n_est_pas_suivie(session) -> None:
    """Un WOULD_SKIP ne porte aucun niveau : il n'y a rien a mesurer.

    Les 72 lignes presentes en base le 16/09/2026 etaient toutes de ce type,
    ce qui explique qu'aucune n'ait jamais pu etre clos.
    """
    trade = await _marginal(
        session,
        outcome=ShadowOutcome.WOULD_SKIP,
        direction=None,
        entry_price=None,
        stop_loss=None,
        take_profit=None,
        marginal=False,
    )
    moteur = FauxMoteur([_bougie(high=105.0, low=97.0, close=104.0)])

    rapport = await shadow_tracker.advance_open_trades(session, moteur)

    assert rapport.closed == 0
    assert trade.closed_at is None
    assert moteur.demandes == [], "aucune bougie n'est meme demandee"
