"""La requete d'ordre part en arguments NOMMES, jamais en dictionnaire positionnel.

Constate le 12/09/2026 sur le compte demo, meme dictionnaire, meme processus,
meme instant :

    mt5.order_check(payload)      -> None,  (-2, 'Unnamed arguments not allowed')
    mt5.order_check(**payload)    -> retcode 0

C'est ce qui empechait TOUT ordre de partir depuis le debut du projet. Un
signal traversait le parser, le validateur, le RiskManager et le
dimensionnement -- puis mourait a la derniere ligne sur une convention
d'appel. L'ecran affichait « Controle broker refuse », ce qui laissait croire
a un refus du courtier alors que la requete ne l'avait jamais atteint.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.models.enums import Direction, OrderType
from app.services.mt5.interface import OrderRequest, SymbolInfo
from app.services.mt5.real_service import RealMetaTraderService


class _AppelEspion:
    """Note comment chaque commande MT5 est appelee."""

    def __init__(self) -> None:
        self.appels: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(self, command: str, *args: Any, **kwargs: Any) -> Any:
        self.appels.append((command, args, kwargs))
        if command in {"order_check", "order_send"}:
            return {"retcode": 0, "comment": "Done", "order": 111, "volume": 0.02}
        return None

    def pour(self, command: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
        for nom, args, kwargs in self.appels:
            if nom == command:
                return args, kwargs
        raise AssertionError(f"{command} n'a jamais ete appele : {self.appels}")


def _symbole() -> SymbolInfo:
    return SymbolInfo(
        name="BTCUSDm",
        digits=2,
        point=0.01,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        trade_contract_size=1.0,
        trade_tick_value=0.01,
        trade_tick_size=0.01,
        trade_stops_level=0,
    )


def _requete() -> OrderRequest:
    return OrderRequest(
        symbol="BTCUSDm",
        direction=Direction.BUY,
        order_type=OrderType.MARKET,
        volume=0.02,
        price=77200.0,
        stop_loss=76814.0,
        take_profit=77586.0,
    )


def _preparer(service: RealMetaTraderService, espion: _AppelEspion) -> None:
    """Court-circuite la construction, qui exige un vrai terminal."""
    service._call = espion  # type: ignore[method-assign]
    service._require_package = lambda: None  # type: ignore[method-assign]

    async def build(_request: OrderRequest) -> tuple[dict[str, Any], str]:
        return (
            {
                "action": 1,
                "symbol": "BTCUSDm",
                "volume": 0.02,
                "type": 0,
                "price": 77200.0,
                "sl": 76814.0,
                "tp": 77586.0,
            },
            "",
        )

    service._build_request = build  # type: ignore[method-assign]


@pytest.mark.parametrize("commande", ["order_check", "order_send"])
async def test_la_requete_part_en_arguments_nommes(commande: str) -> None:
    """Un dictionnaire positionnel fait rendre None au paquet MetaTrader5."""
    service = RealMetaTraderService()
    espion = _AppelEspion()
    _preparer(service, espion)

    if commande == "order_check":
        await service.order_check(_requete())
    else:
        await service._send(
            {
                "action": 1,
                "symbol": "BTCUSDm",
                "volume": 0.02,
                "type": 0,
                "price": 77200.0,
                "sl": 76814.0,
                "tp": 77586.0,
            }
        )

    args, kwargs = espion.pour(commande)

    assert args == (), (
        f"{commande} a recu un argument positionnel : le paquet MetaTrader5 "
        f"repondrait « Unnamed arguments not allowed » et rendrait None"
    )
    assert kwargs["symbol"] == "BTCUSDm"
    assert kwargs["volume"] == 0.02
    assert kwargs["action"] == 1


async def test_le_controle_broker_aboutit() -> None:
    """Bout en bout du cote service : la verification doit rendre un verdict."""
    service = RealMetaTraderService()
    espion = _AppelEspion()
    _preparer(service, espion)

    resultat = await service.order_check(_requete())

    assert resultat.ok is True
    assert resultat.retcode == 0


def test_le_symbole_de_reference_reste_coherent() -> None:
    """Garde-fou : le test suppose un pas de volume de 0,01."""
    assert _symbole().volume_step == 0.01
