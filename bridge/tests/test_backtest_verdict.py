"""Le verdict du backtest n'autorise que ce qui gagne sur les deux periodes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.backtest.cli import canonical, validated_instruments


def _rows(symbol: str, results: list[float]) -> list[dict]:
    debut = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {
            "symbol": symbol,
            "time": (debut + timedelta(hours=i)).isoformat(),
            "direction": "BUY",
            "entry_type": "MARKET",
            "raw_score": 75.0,
            "first_rr": 1.0,
            "ladder_filled": True,
            "ladder_r": r,
        }
        for i, r in enumerate(results)
    ]


def test_un_instrument_qui_gagne_partout_est_valide():
    rows = _rows("EURUSDm", [1.5, -1.0, 2.0, -1.0] * 40)
    valides = validated_instruments(rows)
    assert list(valides) == ["EURUSD"]
    assert valides["EURUSD"]["budget_r"] >= 3.0


def test_un_instrument_qui_ne_gagne_qu_en_apprentissage_est_refuse():
    rows = _rows("XAUUSDm", [2.0, -1.0] * 60 + [-1.0, 0.5] * 30)
    assert validated_instruments(rows) == {}


def test_trop_peu_de_trades_en_validation_ne_valide_rien():
    rows = _rows("GBPUSDm", [2.0, -1.0] * 10)
    assert validated_instruments(rows) == {}


def test_les_noms_exness_redeviennent_ceux_du_watcher():
    assert canonical("USTECm") == "NAS100"
    assert canonical("EURUSDm") == "EURUSD"
    assert canonical("US30m") == "US30"
