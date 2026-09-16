"""Passage a l'acte du cycle autonome : une decision devient une position.

Jusqu'au 16/09/2026 le cycle analysait, decidait, notifiait -- et s'arretait
la. Il produisait des opportunites que personne n'executait, ce qui laissait
la moitie des mesures du CDC2 sans matiere : ``strategy_performance`` restait
vide de ce cote, et ``by_source`` ne pouvait comparer que Telegram a
lui-meme.

La decision est desormais remise au moteur de trading avec le MEME chemin
qu'un signal recu d'un canal : parser, validation, RiskManager,
``order_check``, ``order_send``. Aucun chemin d'execution parallele n'est
cree, et c'est la tout l'interet -- les plafonds d'exposition, les limites
journalieres, la pause apres pertes consecutives et le coupe-circuit valent
donc pour lui sans qu'une seule ligne n'ait a les redire.

Trois garde-fous, dans cet ordre, et le premier ne se discute pas :

* le **mode observation** signifie que RIEN ne part au broker. Un reglage qui
  passerait devant lui le viderait de son sens ;
* ``intelligence.auto_trade``, coupe par defaut. Un defaut qui trade ferait
  trader quiconque demarre ce depot sans le savoir : le reglage s'allume
  explicitement, en base, jamais par supposition du code ;
* sans plan de trade complet, rien ne part. Le moteur doit lire une entree, un
  stop et au moins un objectif, pas une intention.

L'idempotence ne demande pas d'identifiant invente. La cle du pipeline combine
canal, identifiant de message ET empreinte du texte : avec un canal nul,
l'empreinte suffit, et deux tours qui produiraient la meme decision ne peuvent
pas ouvrir deux positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.enums import Direction, EventLevel
from app.repositories import settings_repo, signal_repo
from app.services import journal
from app.services.decision.inputs import TradeLevels
from app.services.trading import trading_engine

logger = get_logger(__name__)

SETTING_AUTO_TRADE = "intelligence.auto_trade"


@dataclass(slots=True)
class HandoffReport:
    """Ce que la remise au moteur a produit. ``skipped`` n'est pas une erreur."""

    attempted: bool = False
    executed: bool = False
    stage: str = ""
    detail: str = ""
    signal_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "executed": self.executed,
            "stage": self.stage,
            "detail": self.detail,
            "signalId": self.signal_id,
        }


def _skip(detail: str) -> HandoffReport:
    return HandoffReport(stage="skipped", detail=detail)


async def auto_trade_enabled(session: AsyncSession) -> bool:
    """Le cycle autonome a-t-il le droit de passer des ordres ?

    Coupe par defaut, volontairement. Ce reglage ouvre une SECONDE source
    d'ordres sur le compte, a cote des canaux Telegram : il doit etre allume
    par un acte explicite, pas herite d'une valeur ecrite dans le code.
    """
    brut = await settings_repo.get_setting(session, SETTING_AUTO_TRADE)
    if brut is None:
        return False
    if isinstance(brut, bool):
        return brut
    return str(brut).strip().lower() not in {"0", "false", "non", "off", ""}


def _number(value: float) -> str:
    """Nombre ecrit sans precision inventee ni precision perdue.

    Cinq decimales couvrent le forex, puis les zeros de fin tombent : 3350
    reste « 3350 » et 1,15396 reste « 1.15396 ». Deduire un nombre de
    decimales du symbole demanderait de connaitre le courtier, et se tromper
    la-dessus se paierait en pips.
    """
    texte = f"{float(value):.5f}".rstrip("0").rstrip(".")
    return texte or "0"


def signal_text(symbol: str, levels: TradeLevels) -> str:
    """Plan de trade au format que le parser lit le plus surement.

    C'est le format minimal du CDC3 section 34, celui que le Market Watcher
    remet deja au moteur. Le format detaille annote chaque objectif de son
    rapport de risque -- « TP1 : 1.34474  (1:1.0) » -- et le parser y lisait
    les deux nombres ; ce format-ci ne porte que des niveaux.
    """
    mot = "BUY" if levels.direction is Direction.BUY else "SELL"
    lignes = [
        f"{mot} {symbol.strip().upper()}",
        f"Entry {_number(levels.entry_price)}",
        f"SL {_number(levels.stop_loss)}",
    ]
    for index, cible in enumerate(levels.take_profits, start=1):
        lignes.append(f"TP{index} {_number(cible)}")
    return "\n".join(lignes)


async def execute_decision(
    session: AsyncSession,
    symbol: str,
    levels: TradeLevels | None,
    *,
    shadow_mode: bool,
    strategy: str | None = None,
) -> HandoffReport:
    """Remet une decision tradable au moteur. Ne leve jamais.

    Une exception ici ferait tomber le tour d'analyse en cours et, avec lui,
    la trace de la decision : l'echec d'execution doit rester un echec
    d'execution.
    """
    if shadow_mode:
        return _skip("Mode observation : aucun ordre ne part au broker.")
    if not await auto_trade_enabled(session):
        return _skip("Execution autonome desactivee (intelligence.auto_trade).")
    if levels is None or not levels.take_profits:
        return _skip("Plan de trade incomplet : aucun ordre transmis.")

    texte = signal_text(symbol, levels)
    try:
        outcome = await trading_engine.handle_message(
            session,
            text=texte,
            channel=None,
            message_id=None,
            # Remise directe, pas un message lu : le registre des publications
            # propres ne doit pas refuser ce que le cycle vient de decider.
            internal_handoff=True,
        )
    except Exception as exc:
        logger.exception("Echec de l'execution autonome sur %s", symbol)
        await journal.record(
            session,
            event="autonomous_execution_failed",
            message=f"Decision autonome sur {symbol} non executee : {exc}",
            level=EventLevel.ERROR,
            category="trading",
        )
        return HandoffReport(attempted=True, stage="error", detail=str(exc))

    # La strategie est estampillee sur le signal, dont heriteront la position
    # et l'ordre en attente. Une etiquette ne se rattrape pas apres coup : sans
    # cette ligne, les premieres positions autonomes resteraient anonymes pour
    # toujours et le ``by_strategy`` du CDC2 section 49 continuerait de tout
    # regrouper sous « non specifiee ».
    if strategy and outcome.signal_id is not None:
        signal = await signal_repo.get(session, outcome.signal_id)
        if signal is not None:
            signal.strategy = strategy.strip()[:64] or None
            await signal_repo.save(session, signal)

    report = HandoffReport(
        attempted=True,
        executed=outcome.executed,
        stage=outcome.stage,
        detail=outcome.detail,
        signal_id=outcome.signal_id,
    )
    await journal.record(
        session,
        event="autonomous_executed" if outcome.executed else "autonomous_not_executed",
        message=(
            f"Decision autonome sur {symbol} executee ({outcome.stage})"
            if outcome.executed
            else f"Decision autonome sur {symbol} non executee : "
            f"{outcome.detail or outcome.stage}"
        ),
        level=EventLevel.INFO if outcome.executed else EventLevel.WARNING,
        category="trading",
    )
    logger.info(
        "Execution autonome %s : etape=%s execute=%s",
        symbol,
        outcome.stage,
        outcome.executed,
    )
    return report


__all__ = [
    "SETTING_AUTO_TRADE",
    "HandoffReport",
    "auto_trade_enabled",
    "execute_decision",
    "signal_text",
]
