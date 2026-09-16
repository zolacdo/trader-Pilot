"""Suivi des simulations : leur donner une issue, sinon elles ne mesurent rien.

``close_shadow_trade`` existait depuis l'origine et n'etait appele de NULLE
PART. Constate le 16/09/2026 : 72 simulations en base, aucune close, la
derniere datant du 11/09. Une simulation qui reste ouverte a vie ne dit rien,
et ``compute_stats`` la compte parmi les ``closed = 0`` -- donc toutes les
statistiques du CDC2 section 85 valaient ``None``.

Ce module fait avancer chaque simulation sur les bougies REELLES, jusqu'a son
stop, son objectif, ou son age limite. Deux choix assumes, tous deux
pessimistes, et identiques a ceux du suivi du watcher :

* quand une meme bougie contient le stop ET l'objectif, on retient le stop. On
  ne sait pas lequel a ete touche en premier, et supposer l'inverse gonflerait
  des statistiques sur lesquelles on va s'appuyer pour abaisser un seuil ;
* l'entree est supposee prise au moment de la decision. C'est le sens meme de
  « ce que le systeme aurait fait » : sans cette hypothese il n'y a pas de
  simulation, seulement une intention.

Le suivi est volontairement plus simple que celui du watcher, qui gere une
echelle d'objectifs, des fermetures partielles et un break even. Une
simulation n'a qu'un stop et qu'un objectif : reutiliser la machinerie lourde
aurait couple deux sous-systemes pour rien.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.models.enums import Direction
from app.models.intelligence import Timeframe
from app.repositories import decision_repo
from app.services.decision.shadow import close_shadow_trade

logger = get_logger(__name__)

# Au-dela, une simulation ne mesure plus le setup qui l'a fait naitre : elle
# est chiffree au dernier cours connu et fermee. La laisser ouverte la ferait
# disparaitre des statistiques, ce qui est pire qu'un resultat modeste.
MAX_AGE_HOURS = 24
# Plafond de bougies demandees par simulation, pour ne pas tirer des jours de
# M1 sur une position d'une heure.
MAX_BARS = 1500


@dataclass(slots=True)
class TrackReport:
    """Ce qu'un tour de suivi a constate."""

    checked: int = 0
    closed: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "closed": self.closed, "errors": self.errors}


def _exit_price(trade: Any, candles: list[Any]) -> float | None:
    """Prix de sortie constate, ou ``None`` si rien n'a ete touche.

    Les bougies sont parcourues dans l'ordre : la premiere issue l'emporte.
    """
    buy = trade.direction is Direction.BUY
    for candle in candles:
        touche_stop = candle.low <= trade.stop_loss if buy else candle.high >= trade.stop_loss
        if touche_stop:
            return float(trade.stop_loss)
        if trade.take_profit is not None:
            touche_cible = (
                candle.high >= trade.take_profit if buy else candle.low <= trade.take_profit
            )
            if touche_cible:
                return float(trade.take_profit)
    return None


async def advance_open_trades(
    session: AsyncSession,
    engine: Any,
    *,
    now: datetime | None = None,
) -> TrackReport:
    """Fait avancer chaque simulation ouverte sur les bougies reelles."""
    moment = now or utcnow()
    report = TrackReport()
    trades = await decision_repo.open_shadow_trades(session)
    report.checked = len(trades)

    for trade in trades:
        symbole = trade.broker_symbol or trade.symbol
        ouverture = as_utc(trade.opened_at) or moment
        minutes = max(5, int((moment - ouverture).total_seconds() // 60) + 5)
        try:
            candles = await engine.candles(symbole, Timeframe.M1, min(MAX_BARS, minutes))
        except Exception as exc:
            # Un instrument indisponible ne doit pas suspendre les autres.
            report.errors += 1
            logger.warning("Bougies indisponibles pour %s : %s", symbole, exc)
            continue

        pertinentes = [
            candle for candle in candles if (as_utc(candle.time) or moment) >= ouverture
        ]
        prix = _exit_price(trade, pertinentes)
        if prix is None and moment - ouverture >= timedelta(hours=MAX_AGE_HOURS):
            # Age limite : on chiffre au dernier cours connu plutot que de la
            # laisser ouverte, faute de quoi elle ne compterait jamais.
            prix = float(pertinentes[-1].close) if pertinentes else None
        if prix is None:
            continue

        close_shadow_trade(trade, prix)
        trade.closed_at = moment
        session.add(trade)
        report.closed += 1

    if report.closed:
        await session.flush()
        logger.info(
            "Simulations : %s cloturee(s) sur %s suivie(s)", report.closed, report.checked
        )
    return report


__all__ = ["MAX_AGE_HOURS", "TrackReport", "advance_open_trades"]
