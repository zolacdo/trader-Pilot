"""Annonces du cycle de vie d'une position, sur Telegram et sur le telephone.

Les gabarits de notification existaient depuis longtemps -- ``take_profit_hit``,
``stop_loss_hit``, ``position_closed`` -- mais personne ne les appelait. Une
position pouvait s'ouvrir, toucher ses objectifs et se fermer sans qu'aucun
message ne parte. Ce module est le chainon manquant.

Deux canaux, une seule verite. Le telephone recoit la notification poussee ; le
canal Telegram recoit le meme evenement en clair, pour ceux qui suivent de la
et pour garder une trace lisible. Un canal indisponible n'empeche jamais
l'autre : l'annonce est un effet de bord du trading, jamais une condition.

Ce module n'execute rien et ne decide rien. Il raconte. Aucune notification ne
transporte d'ordre executable (CDC2 section 94).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.enums import Direction
from app.services.notifications import templates
from app.services.notifications.formatting import NotificationDraft
from app.services.notifications.service import notification_service

logger = get_logger(__name__)


def _echappe(valeur: Any) -> str:
    """Telegram lit du HTML : trois caracteres doivent etre neutralises."""
    return (
        str(valeur).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _sens(direction: Any) -> str:
    if direction is Direction.BUY:
        return "ACHAT"
    if direction is Direction.SELL:
        return "VENTE"
    return str(getattr(direction, "value", direction) or "")


def _prix(valeur: float | None, digits: int = 2) -> str:
    return f"{valeur:.{digits}f}" if valeur is not None else "—"


async def _telegram(session: AsyncSession, texte: str) -> bool:
    """Publie sur le canal du watcher. Ne leve jamais, ne bloque jamais."""
    try:
        from app.watcher.config import load_config
        from app.watcher.publisher import telegram_publisher

        config = await load_config(session)
        resultat = await telegram_publisher.publish(session, texte, config)
        return bool(resultat.sent)
    except Exception:
        logger.exception("Annonce Telegram impossible")
        return False


async def _pousse(session: AsyncSession, draft: NotificationDraft) -> bool:
    try:
        evenement = await notification_service.send(draft, session=session)
        return evenement is not None
    except Exception:
        logger.exception("Notification poussee impossible")
        return False


async def annoncer(
    session: AsyncSession, draft: NotificationDraft, texte_telegram: str
) -> None:
    """Envoie le meme evenement sur les deux canaux, independamment.

    L'echec de l'un ne doit pas priver l'utilisateur de l'autre : les deux
    envois sont tentes quoi qu'il arrive, et aucun ne peut faire remonter une
    exception jusqu'au moteur de trading.
    """
    pousse = await _pousse(session, draft)
    telegram = await _telegram(session, texte_telegram)
    logger.info(
        "Annonce « %s » : telephone=%s telegram=%s", draft.title, pousse, telegram
    )


# ---------------------------------------------------------------------------
# Ordres en attente
# ---------------------------------------------------------------------------
async def ordre_en_attente(
    session: AsyncSession,
    *,
    symbol: str,
    direction: Any,
    order_type: Any,
    entry: float | None,
    stop_loss: float | None,
    take_profits: list[float] | None = None,
    digits: int = 2,
    trade_id: int | None = None,
) -> None:
    """Le prix demande n'etait pas celui du marche : l'ordre attend.

    Ce cas passait totalement inapercu. L'utilisateur voyait un signal accepte
    et supposait une position ouverte, alors que l'ordre dormait chez le
    courtier en attendant un prix qui ne reviendrait peut-etre jamais.
    """
    type_lisible = str(getattr(order_type, "value", order_type) or "").replace("_", " ")
    draft = templates.pending_order_placed(
        symbol=symbol,
        direction=direction,
        order_type=type_lisible,
        entry=entry,
        stop_loss=stop_loss,
        take_profits=take_profits,
        digits=digits,
        trade_id=trade_id,
    )
    cibles = (
        " / ".join(_prix(valeur, digits) for valeur in (take_profits or [])[:3]) or "—"
    )
    texte = "\n".join(
        [
            f"⏳ <b>ORDRE EN ATTENTE — {_echappe(symbol)}</b>",
            "",
            f"{_echappe(_sens(direction))} · {_echappe(type_lisible)}",
            f"Entrée attendue : {_prix(entry, digits)}",
            f"SL : {_prix(stop_loss, digits)}",
            f"TP : {cibles}",
            "",
            "<i>Aucune position n'est ouverte tant que ce prix n'est pas touché.</i>",
        ]
    )
    await annoncer(session, draft, texte)


async def ordre_declenche(
    session: AsyncSession,
    *,
    symbol: str,
    direction: Any,
    price: float | None,
    volume: float | None,
    digits: int = 2,
    trade_id: int | None = None,
) -> None:
    """Le prix est revenu chercher l'ordre : la position existe maintenant."""
    draft = templates.pending_order_filled(
        symbol=symbol,
        direction=direction,
        price=price,
        volume=volume,
        digits=digits,
        trade_id=trade_id,
    )
    texte = "\n".join(
        [
            f"🎯 <b>ORDRE DÉCLENCHÉ — {_echappe(symbol)}</b>",
            "",
            f"{_echappe(_sens(direction))}",
            f"Entrée : {_prix(price, digits)}",
            f"Volume : {_prix(volume, 2)}",
        ]
    )
    await annoncer(session, draft, texte)


async def ordre_non_declenche(
    session: AsyncSession,
    *,
    symbol: str,
    direction: Any,
    entry: float | None,
    digits: int = 2,
    reason: str | None = None,
    trade_id: int | None = None,
) -> None:
    """L'ordre a disparu du terminal sans jamais avoir ete touche."""
    draft = templates.pending_order_cancelled(
        symbol=symbol,
        direction=direction,
        entry=entry,
        digits=digits,
        reason=reason,
        trade_id=trade_id,
    )
    texte = "\n".join(
        [
            f"🚫 <b>ORDRE NON DÉCLENCHÉ — {_echappe(symbol)}</b>",
            "",
            f"{_echappe(_sens(direction))}",
            f"Entrée demandée : {_prix(entry, digits)}",
            f"Motif : {_echappe(reason or 'annulé ou expiré chez le courtier')}",
            "",
            "<i>Le prix n'est jamais revenu : aucune position n'a été ouverte.</i>",
        ]
    )
    await annoncer(session, draft, texte)


# ---------------------------------------------------------------------------
# Objectifs
# ---------------------------------------------------------------------------
async def objectif_atteint(
    session: AsyncSession,
    *,
    symbol: str,
    direction: Any,
    level: int,
    total: int,
    price: float | None = None,
    profit: float | None = None,
    remaining_volume: float | None = None,
    digits: int = 2,
    trade_id: int | None = None,
) -> None:
    """Un objectif vient d'etre franchi. Annonce a chaque palier, pas au dernier.

    Le compte « TP2 sur 3 » est ce qui permet de suivre une position sans
    ouvrir l'application : on sait combien il reste a valider.
    """
    draft = templates.take_profit_hit(
        symbol=symbol,
        direction=direction,
        level=level,
        profit=profit,
        remaining_volume=remaining_volume,
        trade_id=trade_id,
    )
    draft.title = f"✅ TP{level}/{total} ATTEINT — {symbol}"
    restants = total - level
    suite = (
        f"Reste {restants} objectif(s) à valider."
        if restants > 0
        else "Tous les objectifs sont validés."
    )
    texte = "\n".join(
        [
            f"✅ <b>TP{level}/{total} ATTEINT — {_echappe(symbol)}</b>",
            "",
            f"{_echappe(_sens(direction))}",
            f"Prix : {_prix(price, digits)}",
            f"Profit courant : {_prix(profit, 2)}",
            "",
            f"<i>{suite}</i>",
        ]
    )
    await annoncer(session, draft, texte)


async def position_fermee(
    session: AsyncSession,
    *,
    symbol: str,
    direction: Any,
    atteints: int,
    total: int,
    profit: float | None = None,
    reason: str | None = None,
    trade_id: int | None = None,
) -> None:
    """Fin de l'histoire : combien d'objectifs ont ete valides, et pour quel resultat.

    C'est le message qui clot le suivi commence au premier objectif. Sans lui,
    une position partie a 2 TP sur 3 laisserait croire qu'elle court encore.
    """
    perte = profit is not None and profit < 0
    if perte:
        draft = templates.stop_loss_hit(
            symbol=symbol, direction=direction, loss=profit, trade_id=trade_id
        )
    else:
        draft = templates.position_closed(
            symbol=symbol,
            direction=direction,
            profit=profit,
            source=reason,
            trade_id=trade_id,
        )

    if total > 0:
        bilan = f"{atteints}/{total} objectif(s) validé(s)"
    else:
        bilan = "aucun objectif déclaré"
    draft.body = f"{draft.body}\n\nObjectifs : {bilan}"

    titre = "❌ <b>STOP LOSS" if perte else "🏁 <b>POSITION FERMÉE"
    texte = "\n".join(
        [
            f"{titre} — {_echappe(symbol)}</b>",
            "",
            f"{_echappe(_sens(direction))}",
            f"Résultat : {_prix(profit, 2)}",
            f"Objectifs : {_echappe(bilan)}",
            f"Motif : {_echappe(reason or 'fermée côté courtier')}",
        ]
    )
    await annoncer(session, draft, texte)


__all__ = [
    "annoncer",
    "objectif_atteint",
    "ordre_declenche",
    "ordre_en_attente",
    "ordre_non_declenche",
    "position_fermee",
]
