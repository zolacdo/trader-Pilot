"""Le simulateur de trades ne doit jamais trancher un doute en sa faveur."""

from __future__ import annotations

import numpy as np

from app.backtest.simulate import Bars, ExitPolicy, simulate_trade


def _bars(rows: list[tuple[float, float, float, float]], spread: int = 0) -> Bars:
    """Bougies M5 (open, high, low, close) a partir de t = 0, point = 0,01."""
    data = np.array(rows, dtype=float)
    n = len(rows)
    return Bars(
        time=np.arange(n, dtype=np.int64) * 300,
        open=data[:, 0],
        high=data[:, 1],
        low=data[:, 2],
        close=data[:, 3],
        spread=np.full(n, spread, dtype=float),
        point=0.01,
        seconds=300,
    )


def test_un_achat_au_marche_atteint_son_objectif():
    bars = _bars([(100, 101, 99.5, 100.5), (100.5, 102.2, 100.4, 102)])
    result = simulate_trade(bars, 0, True, 100, 99, [102], pending=False)
    assert result.exit_reason == "TARGET"
    assert result.r == 2.0


def test_stop_et_objectif_dans_la_meme_bougie_compte_le_stop():
    bars = _bars([(100, 103, 98.5, 100)])
    result = simulate_trade(bars, 0, True, 100, 99, [102], pending=False)
    assert result.exit_reason == "STOP"
    assert result.r == -1.0


def test_le_spread_penalise_l_entree_d_un_achat():
    # Spread de 50 points = 0,50 : l'achat entre a 100,50, stop a 99.
    bars = _bars([(100, 100.2, 98.9, 99)], spread=50)
    result = simulate_trade(bars, 0, True, 100, 99, [103], pending=False)
    assert result.entry_price == 100.5
    assert result.r == -1.0


def test_une_vente_sort_au_ask():
    # Vente a 100, objectif 98 : il faut que le ask (bid + 0,10) l'atteigne.
    bars = _bars([(100, 100.1, 97.95, 98), (98, 98, 97.8, 97.9)], spread=10)
    result = simulate_trade(bars, 0, False, 100, 101, [98], pending=False)
    assert result.exit_reason == "TARGET"
    assert result.exit_time == 600  # le bid a 97,95 ne suffisait pas
    assert result.r == 2.0


def test_l_escalier_remonte_le_stop_a_l_entree_apres_tp1():
    bars = _bars([
        (100, 101.2, 99.8, 101),  # TP1 a 101 franchi
        (101, 101.1, 99.9, 100),  # retour sous l'entree : sortie a 0
    ])
    result = simulate_trade(bars, 0, True, 100, 99, [101, 102, 103], pending=False)
    assert result.exit_reason == "STOP"
    assert result.r == 0.0
    assert result.targets_hit == 1


def test_l_escalier_laisse_courir_jusqu_au_dernier_objectif():
    bars = _bars([
        (100, 101.2, 99.8, 101),
        (101, 102.2, 100.5, 102),
        (102, 103.5, 101.5, 103),
    ])
    result = simulate_trade(bars, 0, True, 100, 99, [101, 102, 103], pending=False)
    assert result.exit_reason == "TARGET"
    assert result.r == 3.0


def test_sortie_au_premier_objectif():
    bars = _bars([(100, 101.2, 99.8, 101)])
    result = simulate_trade(
        bars, 0, True, 100, 99, [101, 102], pending=False, policy=ExitPolicy.FIRST_TARGET
    )
    assert result.r == 1.0


def test_un_ordre_stop_non_declenche_expire_sans_trade():
    bars = _bars([(100, 100.5, 99.5, 100)] * 60)
    result = simulate_trade(bars, 0, True, 101, 99, [104], pending=True, pending_minutes=60)
    assert not result.filled
    assert result.exit_reason == "PENDING_EXPIRED"


def test_un_saut_sous_le_stop_sort_au_prix_d_ouverture():
    bars = _bars([(100, 100.2, 99.8, 100), (98, 98.2, 97.5, 98)])
    result = simulate_trade(bars, 0, True, 100, 99, [103], pending=False)
    assert result.exit_price == 98
    assert result.r == -2.0


def test_aucune_bougie_anterieure_au_depart_n_est_lue():
    # La bougie 0 toucherait le stop ; la decision est prise apres elle.
    bars = _bars([(100, 100, 90, 95), (100, 102.5, 99.5, 102)])
    result = simulate_trade(bars, 1, True, 100, 99, [102], pending=False)
    assert result.exit_reason == "TARGET"
