"""Suivi des signaux observes : leur donner une issue, sinon ils ne mesurent rien.

Un canal en ``ChannelMode.OBSERVE`` enregistre ce qu'il aurait fait sans
jamais envoyer d'ordre. C'est la seule facon de juger une source Telegram sans
risquer d'argent -- a condition que quelqu'un mesure le resultat.

Verifie le 18/09/2026 : ``SignalStatus.OBSERVED`` n'apparaissait que dans sa
definition, dans la liste anti-doublon et a l'endroit qui l'ecrit. **Rien ne
denouait jamais une observation**, et aucune n'avait jamais existe en base.
L'observation etait donc un aller sans retour deguise en quarantaine : le
canal se taisait et n'accumulait aucune preuve permettant d'en sortir. La meme
famille de defaut que ``disabled_entry_types`` ecrit et lu par personne, ou
``close_shadow_trade`` appele de nulle part.

Deux choix assumes, tous deux pessimistes, et identiques a ceux du suivi du
watcher et de celui des simulations :

* quand une meme bougie contient le stop ET l'objectif, on retient le stop. On
  ne sait pas lequel a ete touche en premier, et supposer l'inverse gonflerait
  la mesure sur laquelle on va decider de rouvrir un canal ;
* l'entree est supposee prise au moment du signal. C'est le sens meme de « ce
  que cette source aurait fait » : sans cette hypothese il n'y a pas
  d'observation, seulement une intention.

Le suivi reste volontairement pauvre : un seul objectif, pas de fermeture
partielle, pas de break even. Une observation n'a pas a reproduire la gestion
reelle, elle a a dire si le setup allait dans le bon sens. Le resultat est
donc un plancher, comme partout ailleurs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.models.enums import Direction, SignalStatus
from app.models.intelligence import Timeframe
from app.models.trading import Signal
from app.repositories import signal_repo

logger = get_logger(__name__)

# Au-dela, une observation ne mesure plus le setup qui l'a fait naitre : elle
# est chiffree au dernier cours connu et close. La laisser ouverte la ferait
# disparaitre de toute statistique, ce qui est pire qu'un resultat modeste.
MAX_AGE_HOURS = 24
# Plafond de bougies demandees par observation, pour ne pas tirer des jours de
# M1 sur un signal d'une heure.
MAX_BARS = 1500
# Nombre d'observations examinees par tour. Large, mais borne : une source
# bavarde ne doit pas allonger l'entretien indefiniment.
MAX_PAR_TOUR = 200


@dataclass(slots=True)
class ObservationReport:
    """Ce qu'un tour de suivi a constate."""

    checked: int = 0
    closed: int = 0
    skipped: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "closed": self.closed,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def _entree(signal: Signal) -> float | None:
    """Prix d'entree retenu, ou ``None`` si le message n'en donnait aucun.

    Une fourchette est ramenee a son milieu : c'est la seule valeur qui ne
    favorise ni le signal ni nous.
    """
    if signal.entry_price is not None:
        return float(signal.entry_price)
    bas, haut = signal.entry_min, signal.entry_max
    if bas is not None and haut is not None:
        return (float(bas) + float(haut)) / 2.0
    return float(bas) if bas is not None else (float(haut) if haut is not None else None)


def _objectif(signal: Signal) -> float | None:
    """Premier objectif du message, seul retenu."""
    cibles = list(signal.take_profits or [])
    return float(cibles[0]) if cibles else None


def _exit_price(signal: Signal, candles: list[Any]) -> float | None:
    """Prix de sortie constate, ou ``None`` si rien n'a ete touche."""
    stop = signal.stop_loss
    if stop is None:
        return None
    buy = signal.direction is Direction.BUY
    cible = _objectif(signal)
    for candle in candles:
        touche_stop = candle.low <= stop if buy else candle.high >= stop
        if touche_stop:
            return float(stop)
        if cible is not None:
            touche_cible = candle.high >= cible if buy else candle.low <= cible
            if touche_cible:
                return float(cible)
    return None


def _result_r(signal: Signal, prix: float) -> float | None:
    """Resultat en multiples de risque, ou ``None`` s'il n'est pas calculable."""
    entree = _entree(signal)
    stop = signal.stop_loss
    if entree is None or stop is None:
        return None
    risque = abs(entree - float(stop))
    if risque <= 0:
        return None
    gagne = prix - entree if signal.direction is Direction.BUY else entree - prix
    return round(gagne / risque, 3)


async def advance_observed_signals(
    session: AsyncSession,
    engine: Any,
    *,
    now: datetime | None = None,
) -> ObservationReport:
    """Fait avancer chaque observation non denouee sur les bougies reelles."""
    moment = now or utcnow()
    report = ObservationReport()

    signals = await signal_repo.list_signals(
        session, limit=MAX_PAR_TOUR, statuses=[SignalStatus.OBSERVED]
    )
    ouvertes = [signal for signal in signals if signal.observed_result_r is None]
    report.checked = len(ouvertes)

    for signal in ouvertes:
        if signal.stop_loss is None or _entree(signal) is None:
            # Sans entree ni stop, le R n'existe pas. On ne fabrique pas un
            # resultat : l'observation reste muette et le dit.
            report.skipped += 1
            continue

        symbole = signal.broker_symbol or signal.symbol
        if not symbole:
            report.skipped += 1
            continue

        naissance = as_utc(signal.received_at) or moment
        minutes = max(5, int((moment - naissance).total_seconds() // 60) + 5)
        try:
            candles = await engine.candles(symbole, Timeframe.M1, min(MAX_BARS, minutes))
        except Exception as exc:
            # Un instrument indisponible ne doit pas suspendre les autres.
            report.errors += 1
            logger.warning("Bougies indisponibles pour %s : %s", symbole, exc)
            continue

        pertinentes = [
            candle for candle in candles if (as_utc(candle.time) or moment) >= naissance
        ]
        prix = _exit_price(signal, pertinentes)
        if prix is None and moment - naissance >= timedelta(hours=MAX_AGE_HOURS):
            prix = float(pertinentes[-1].close) if pertinentes else None
        if prix is None:
            continue

        resultat = _result_r(signal, prix)
        if resultat is None:
            report.skipped += 1
            continue

        signal.observed_result_r = resultat
        signal.observed_closed_at = moment
        signal.updated_at = moment
        session.add(signal)
        report.closed += 1

    if report.closed:
        await session.flush()
        logger.info(
            "Observations : %s denouee(s) sur %s suivie(s)", report.closed, report.checked
        )
    return report


__all__ = ["MAX_AGE_HOURS", "ObservationReport", "advance_observed_signals"]
