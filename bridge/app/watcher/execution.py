"""Passage a l'acte : un signal du Market Watcher devient une position.

Jusqu'ici le watcher analysait, decidait, publiait -- et s'arretait la. Le
message partait dans le canal Telegram en esperant que l'ecoute le renvoie au
moteur de trading. Elle ne le renvoyait jamais : Telegram ne rejoue pas dans
le flux d'updates les messages que la session a elle-meme envoyes. Le signal
faisait donc un aller sans retour, et aucune position ne s'ouvrait.

Ce module supprime le detour. La decision est remise directement au moteur de
trading, avec le texte exact qui a ete publie : le parser, la verification IA,
le RiskManager et MetaTrader voient rigoureusement ce que voit le lecteur du
canal. Aucun chemin d'execution parallele n'est cree -- c'est le meme que pour
un signal recu d'un canal tiers.

Trois garde-fous, dans cet ordre :

* ``auto_trade`` a ``False`` laisse le watcher en simple publicateur ;
* ``dry_run`` interdit l'execution comme il interdit deja la publication ;
* l'identifiant du message publie sert de cle d'idempotence. Si l'ecoute
  finissait un jour par rendre ces messages, le moteur les reconnaitrait comme
  deja traites au lieu d'ouvrir une seconde position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.enums import EventLevel
from app.repositories import channel_repo
from app.services import journal
from app.services.trading import trading_engine
from app.watcher.config import WatcherConfig

logger = get_logger(__name__)


@dataclass(slots=True)
class ExecutionReport:
    """Ce que l'execution a reellement produit. ``skipped`` n'est pas une erreur."""

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


def _skip(detail: str) -> ExecutionReport:
    return ExecutionReport(stage="skipped", detail=detail)


async def execute_signal(
    session: AsyncSession,
    text: str,
    config: WatcherConfig,
    telegram_channel_id: int | None = None,
    message_id: int | None = None,
) -> ExecutionReport:
    """Remet un signal publie au moteur de trading. Ne leve jamais.

    Une exception ici ferait tomber le tour d'analyse en cours et, avec lui,
    l'enregistrement du signal : l'echec d'execution doit rester un echec
    d'execution.
    """
    if not config.auto_trade:
        return _skip("Execution automatique desactivee (watcher.auto_trade).")
    if config.dry_run:
        return _skip("Mode analyse seule : aucun ordre n'est transmis.")
    if not text.strip():
        return _skip("Aucun texte de signal a transmettre.")

    # Le canal d'origine porte ses propres reglages de risque et ses alias de
    # symboles. L'ignorer ferait travailler le moteur sur les valeurs par
    # defaut alors que l'utilisateur a peut-etre regle ce canal.
    channel = None
    if telegram_channel_id is not None:
        channel = await channel_repo.get_by_telegram_id(session, int(telegram_channel_id))

    try:
        outcome = await trading_engine.handle_message(
            session,
            text=text,
            channel=channel,
            message_id=message_id,
        )
    except Exception as exc:
        logger.exception("Echec de l'execution automatique d'un signal du watcher")
        await journal.record(
            session,
            event="watcher_execution_failed",
            message=f"Signal du watcher non execute : {exc}",
            level=EventLevel.ERROR,
            category="trading",
            channel_id=channel.id if channel else None,
        )
        return ExecutionReport(attempted=True, stage="error", detail=str(exc))

    report = ExecutionReport(
        attempted=True,
        executed=outcome.executed,
        stage=outcome.stage,
        detail=outcome.detail,
        signal_id=outcome.signal_id,
    )
    await journal.record(
        session,
        event="watcher_executed" if outcome.executed else "watcher_not_executed",
        message=(
            f"Signal du watcher execute ({outcome.stage})"
            if outcome.executed
            else f"Signal du watcher non execute : {outcome.detail or outcome.stage}"
        ),
        level=EventLevel.INFO if outcome.executed else EventLevel.WARNING,
        category="trading",
        channel_id=channel.id if channel else None,
    )
    logger.info(
        "Execution automatique du watcher : etape=%s execute=%s",
        outcome.stage,
        outcome.executed,
    )
    return report
