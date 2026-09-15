"""Apprentissage sur les pertes (CDC3 section 41).

Trois regles dont ce module ne sort jamais :

1. aucune decision sous ``MIN_SAMPLE``. Sur une vingtaine d'operations, tout
   ajustement fin ajusterait du bruit ;
2. aucune ecriture hors des bornes declarees dans la configuration. Un
   parametre sans borne ecrite ne peut pas etre touche du tout ;
3. aucune decision silencieuse. Chaque ecriture est journalisee avec son
   chiffrage, et l'ordonnanceur la publie dans le canal ;
4. aucun bannissement sur la foi du seul suivi. Le suivi ne modelise pas le
   trailing : son resultat est un plancher du resultat reel. Quand une
   position existe dans ``trades``, c'est elle qui dit si le signal a gagne.

Une decision n'est qu'un reglage en base : elle se defait depuis
l'application, sans toucher au code. Et ce module ne connait pas le moteur
d'execution -- il ne peut pas passer d'ordre, c'est structurel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.services import journal
from app.watcher import repository
from app.watcher.config import WatcherConfig, update_config
from app.watcher.models import STRATEGY_VERSION
from app.watcher.performance import MIN_SAMPLE

logger = get_logger(__name__)


@dataclass(slots=True)
class Decision:
    """Ce que l'apprentissage a decide, et sur quels chiffres."""

    key: str
    kind: str
    losses: int
    message: str


def clamp(config: WatcherConfig, name: str, value: float) -> float | None:
    """Ramene une valeur dans ses bornes, ou refuse de l'ecrire.

    Un parametre dont la borne n'est pas declaree rend ``None`` : sans limite
    ecrite, rien ne dit jusqu'ou la boucle aurait le droit d'aller, et deviner
    serait exactement ce que les garde-fous doivent empecher.
    """
    bounds = (config.learning_bounds or {}).get(name)
    if not bounds or len(bounds) != 2:
        return None
    low, high = float(bounds[0]), float(bounds[1])
    if low > high:
        logger.warning("Bornes de %s inversees : aucun ajustement ecrit.", name)
        return None
    return min(max(value, low), high)


async def review(session: AsyncSession, config: WatcherConfig) -> list[Decision]:
    """Ecarte ce qui n'a jamais gagne. Ne decide rien sous ``MIN_SAMPLE``."""
    if not config.learning_enabled:
        return []

    since = utcnow() - timedelta(days=max(1, config.learning_window_days))
    # Uniquement la version courante : un signal mesure « sur position
    # entiere » porte un -1 R plein la ou le compte avait encaisse sa tranche
    # a TP1. Apprendre dessus reviendrait a apprendre sur du faux.
    closed = await repository.closed_signals(
        session, since=since, strategy_version=STRATEGY_VERSION
    )
    traces = await repository.post_mortems(session, since=since)
    # Le suivi ne modelise pas le trailing : son resultat est un plancher du
    # resultat reel. On demande donc au compte, quand il a quelque chose a
    # dire, avant de declarer une clef sterile.
    trades = await repository.closed_trades_since(session, since)
    gagnants = {
        signal.id for signal in closed if signal.id is not None and _a_gagne(signal, trades)
    }

    deja_ecartes = {str(item).upper() for item in config.disabled_entry_types or []}
    surveilles = {str(item).upper() for item in config.symbols or []}

    decisions = [
        decision
        for decision in _sterile(closed, traces, "entry_type", gagnants)
        if decision.key not in deja_ecartes
    ]
    # Un instrument hors de la liste surveillee n'a pas a etre « ecarte » :
    # la decision serait vide, et le canal recevrait une annonce sans objet.
    decisions += [
        decision
        for decision in _sterile(closed, traces, "symbol", gagnants)
        if decision.key in surveilles
    ]
    if not decisions:
        return []

    changes: dict[str, Any] = {}
    types = [decision.key for decision in decisions if decision.kind == "entry_type"]
    if types:
        changes["disabled_entry_types"] = sorted(deja_ecartes | set(types))
    symbols = [decision.key for decision in decisions if decision.kind == "symbol"]
    if symbols:
        changes["symbols"] = [
            item for item in config.symbols if str(item).upper() not in set(symbols)
        ]
    await update_config(session, changes)

    for decision in decisions:
        logger.info("Apprentissage : %s", decision.message)
        await journal.log(
            event="watcher_learning",
            message=decision.message,
            category="system",
        )
    return decisions


def _a_gagne(signal: Any, trades: list[Any]) -> bool:
    """Ce signal a-t-il gagne ? Le compte tranche s'il a quelque chose a dire.

    L'appariement reprend la regle de ``matching_trade`` : meme symbole, meme
    sens, position ouverte a partir du signal. Il est approximatif -- rien ne
    relie ``trades`` a ``watcher_signals`` -- mais son erreur va dans un seul
    sens : elle peut transformer une perte suivie en gain reel, jamais
    l'inverse. Elle rend donc le bannissement plus prudent, ce qui est le bon
    sens pour une action automatique.
    """
    reel = _real_pnl(signal, trades)
    if reel is not None:
        return reel > 0
    return (signal.result_r or 0.0) > 0


def _real_pnl(signal: Any, trades: list[Any]) -> float | None:
    """P&L de la position nee de ce signal, ou ``None`` si aucun ordre n'est parti."""
    created = as_utc(signal.created_at)
    for trade in trades:
        if trade.symbol != signal.broker_symbol or trade.direction is not signal.direction:
            continue
        opened = as_utc(trade.opened_at)
        if created is not None and opened is not None and opened < created:
            continue
        return float(trade.realized_pnl or 0.0)
    return None


def _sterile(
    closed: list[Any], traces: list[Any], kind: str, gagnants: set[int]
) -> list[Decision]:
    """Clefs totalisant ``MIN_SAMPLE`` operations denouees sans un seul gain."""
    total: dict[str, int] = {}
    gains: dict[str, int] = {}
    for signal in closed:
        key = _key_of(signal, kind)
        total[key] = total.get(key, 0) + 1
        if signal.id in gagnants:
            gains[key] = gains.get(key, 0) + 1

    pertes: dict[str, int] = {}
    for trace in traces:
        key = _key_of(trace, kind)
        pertes[key] = pertes.get(key, 0) + 1

    libelle = "Type d'entree" if kind == "entry_type" else "Instrument"
    decisions: list[Decision] = []
    for key, compte in sorted(total.items()):
        if compte < MIN_SAMPLE or gains.get(key, 0) > 0:
            continue
        decisions.append(
            Decision(
                key=key,
                kind=kind,
                losses=pertes.get(key, compte),
                message=(
                    f"{libelle} {key} ecarte : {compte} operation(s) denouee(s) "
                    f"sans un seul gain."
                ),
            )
        )
    return decisions


def _key_of(item: Any, kind: str) -> str:
    """Valeur de regroupement, que le champ porte un enum ou une chaine."""
    valeur = getattr(item, kind)
    return str(getattr(valeur, "value", valeur)).upper()


__all__ = ["Decision", "clamp", "review"]
