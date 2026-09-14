"""Gabarits des notifications (CDC2 sections 52 a 63 et 87).

Les textes sont en francais accentue, courts et lisibles sur un ecran
verrouille : un titre qui dit tout, puis des lignes "Libelle : valeur".
Aucun gabarit ne transporte de secret ni d'ordre executable : la charge utile
sert uniquement a ouvrir le bon ecran dans l'application.

L'enveloppe (``NotificationDraft``) et les fonctions de mise en forme vivent
dans ``formatting`` : elles servent aussi aux mouvements et aux rapports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.intelligence import NotificationCategory, NotificationPriority
from app.services.notifications.formatting import (
    NotificationDraft,
    format_direction,
    format_duration,
    format_impact,
    format_moment,
    format_number,
    format_percent,
    format_ratio_percent,
    labelled_lines,
)

# ---------------------------------------------------------------------------
# Trades (CDC2 sections 52, 53, 57 a 60)
# ---------------------------------------------------------------------------

def position_opened(
    *,
    symbol: str,
    direction: Any,
    volume: float,
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profits: list[float] | None = None,
    risk_percent: float | None = None,
    source: str = "TradePilot AI",
    ai_mode: str | None = None,
    confidence: float | None = None,
    digits: int = 2,
    trade_id: int | None = None,
) -> NotificationDraft:
    """CDC2 52 et 53 : achat ouvert / vente ouverte."""
    way = format_direction(direction)
    is_buy = way == "ACHAT"
    targets = list(take_profits or [])
    body = "\n".join(
        [
            f"{symbol} · {way} · {format_number(volume, 2)} lot",
            "",
            labelled_lines(
                ("Entrée", format_number(entry, digits)),
                ("SL", format_number(stop_loss, digits)),
                ("TP1", format_number(targets[0], digits) if targets else None),
                ("Risque", format_percent(risk_percent)),
                ("Source", source),
                ("Mode IA", ai_mode),
                ("Confiance", format_ratio_percent(confidence)),
            ),
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        title=f"{'🟢 ACHAT OUVERT' if is_buy else '🔴 VENTE OUVERTE'} — {symbol}",
        body=body,
        data={"route": "trade", "tradeId": trade_id, "symbol": symbol, "direction": way},
        symbol=symbol,
    )


def take_profit_hit(
    *,
    symbol: str,
    direction: Any,
    level: int = 1,
    profit: float | None = None,
    remaining_volume: float | None = None,
    stop_loss_state: str | None = None,
    trade_id: int | None = None,
) -> NotificationDraft:
    """CDC2 57 : un objectif est atteint."""
    body = "\n".join(
        [
            f"{symbol} · {format_direction(direction)}",
            "",
            labelled_lines(
                ("Profit actuel", format_number(profit, 2)),
                ("Position restante", format_number(remaining_volume, 2) if remaining_volume else None),
                ("SL", stop_loss_state or "inchangé"),
            ),
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        title=f"✅ TP{level} ATTEINT — {symbol}",
        body=body,
        data={"route": "trade", "tradeId": trade_id, "symbol": symbol, "tpLevel": level},
        symbol=symbol,
    )


def stop_loss_hit(
    *,
    symbol: str,
    direction: Any,
    result_percent: float | None = None,
    planned_risk_percent: float | None = None,
    loss: float | None = None,
    trade_id: int | None = None,
) -> NotificationDraft:
    """CDC2 58 : stop loss touche."""
    body = "\n".join(
        [
            f"{symbol} · {format_direction(direction)}",
            "",
            labelled_lines(
                ("Résultat", format_percent(result_percent, 2)),
                ("Perte", format_number(loss, 2) if loss is not None else None),
                ("Risque prévu", format_percent(planned_risk_percent)),
            ),
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        title=f"❌ STOP LOSS — {symbol}",
        body=body,
        data={"route": "trade", "tradeId": trade_id, "symbol": symbol},
        symbol=symbol,
    )


def position_closed(
    *,
    symbol: str,
    direction: Any = None,
    r_multiple: float | None = None,
    profit: float | None = None,
    duration_seconds: float | None = None,
    source: str | None = None,
    trade_id: int | None = None,
) -> NotificationDraft:
    """CDC2 59 : position fermee."""
    header = f"{symbol} · {format_direction(direction)}" if direction else symbol
    result = f"{r_multiple:+.2f} R" if r_multiple is not None else None
    body = "\n".join(
        [
            header,
            "",
            labelled_lines(
                ("Résultat", result),
                ("Profit", format_number(profit, 2)),
                ("Durée", format_duration(duration_seconds)),
                ("Source", source),
            ),
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        title=f"🏁 POSITION FERMÉE — {symbol}",
        body=body,
        data={"route": "trade", "tradeId": trade_id, "symbol": symbol},
        symbol=symbol,
    )


def pending_order_placed(
    *,
    symbol: str,
    direction: Any,
    order_type: str,
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profits: list[float] | None = None,
    digits: int = 2,
    distance_points: float | None = None,
    trade_id: int | None = None,
) -> NotificationDraft:
    """Le prix demande n'etait pas celui du marche : l'ordre attend (CDC2 52).

    Ce n'est pas un echec. Le signal donnait un prix d'entree que le marche
    avait deja depasse ; plutot que d'entrer a un prix different de celui
    annonce, l'ordre est depose et attend que le prix revienne.
    """
    cibles = None
    if take_profits:
        cibles = " / ".join(format_number(valeur, digits) or "" for valeur in take_profits[:3])
    body = "\n".join(
        [
            f"{symbol} · {format_direction(direction)} · {order_type}",
            "",
            labelled_lines(
                ("Entrée attendue", format_number(entry, digits)),
                ("SL", format_number(stop_loss, digits)),
                ("TP", cibles),
                (
                    "Écart au marché",
                    f"{distance_points:.0f} points" if distance_points else None,
                ),
            ),
            "",
            "Aucune position n'est ouverte tant que ce prix n'est pas touché.",
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.MEDIUM,
        title=f"⏳ ORDRE EN ATTENTE — {symbol}",
        body=body,
        data={"route": "trade", "tradeId": trade_id, "symbol": symbol, "pending": True},
        symbol=symbol,
    )


def pending_order_filled(
    *,
    symbol: str,
    direction: Any,
    price: float | None = None,
    volume: float | None = None,
    digits: int = 2,
    trade_id: int | None = None,
) -> NotificationDraft:
    """Le prix est revenu chercher l'ordre : la position existe (CDC2 52)."""
    body = "\n".join(
        [
            f"{symbol} · {format_direction(direction)}",
            "",
            labelled_lines(
                ("Entrée", format_number(price, digits)),
                ("Volume", format_number(volume, 2)),
            ),
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.HIGH,
        title=f"🎯 ORDRE DÉCLENCHÉ — {symbol}",
        body=body,
        data={"route": "trade", "tradeId": trade_id, "symbol": symbol},
        symbol=symbol,
    )


def pending_order_cancelled(
    *,
    symbol: str,
    direction: Any,
    entry: float | None = None,
    digits: int = 2,
    reason: str | None = None,
    trade_id: int | None = None,
) -> NotificationDraft:
    """L'ordre a expire sans jamais etre touche (CDC2 52).

    Le dire explicitement evite de croire qu'une position dort quelque part.
    """
    body = "\n".join(
        [
            f"{symbol} · {format_direction(direction)}",
            "",
            labelled_lines(
                ("Entrée demandée", format_number(entry, digits)),
                ("Motif", reason or "annulé ou expiré chez le courtier"),
            ),
            "",
            "Le prix n'est jamais revenu : aucune position n'a été ouverte.",
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.MEDIUM,
        title=f"🚫 ORDRE NON DÉCLENCHÉ — {symbol}",
        body=body,
        data={"route": "trade", "tradeId": trade_id, "symbol": symbol},
        symbol=symbol,
    )


def break_even_applied(
    *, symbol: str, new_stop_loss: float | None = None, digits: int = 2, trade_id: int | None = None
) -> NotificationDraft:
    """CDC2 60 : le stop est remonte au point mort."""
    return NotificationDraft(
        category=NotificationCategory.TRADE,
        priority=NotificationPriority.MEDIUM,
        title=f"🛡 BREAK EVEN ACTIVÉ — {symbol}",
        body=labelled_lines(("SL déplacé", format_number(new_stop_loss, digits)), ("Risque restant", "0 %")),
        data={"route": "trade", "tradeId": trade_id, "symbol": symbol},
        symbol=symbol,
    )


# ---------------------------------------------------------------------------
# Opportunites, signaux et desaccord IA (CDC2 sections 54 a 56)
# ---------------------------------------------------------------------------

def opportunity_detected(
    *,
    symbol: str,
    direction: Any,
    confidence: float | None = None,
    technical: float | None = None,
    historical: float | None = None,
    news_risk: str | None = None,
    ai_consensus: bool | None = None,
    opportunity_id: int | None = None,
) -> NotificationDraft:
    """CDC2 54 : opportunite detectee par le systeme lui-meme."""
    consensus = None if ai_consensus is None else ("OUI" if ai_consensus else "NON")
    body = "\n".join(
        [
            f"{symbol} · {format_direction(direction)}",
            "",
            labelled_lines(
                ("Confiance", format_ratio_percent(confidence)),
                ("Technique", format_ratio_percent(technical)),
                ("Historique", format_ratio_percent(historical)),
                ("Risque news", format_impact(news_risk) if news_risk else None),
                ("Consensus IA", consensus),
            ),
            "",
            "Ouvrir l’analyse dans TradePilot.",
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.OPPORTUNITY,
        priority=NotificationPriority.HIGH,
        title=f"🤖 OPPORTUNITÉ DÉTECTÉE — {symbol}",
        body=body,
        data={"route": "opportunity", "opportunityId": opportunity_id, "symbol": symbol},
        symbol=symbol,
    )


def telegram_signal(
    *,
    symbol: str,
    direction: Any,
    channel_name: str,
    verdict: str,
    ai_consensus: bool | None = None,
    confidence: float | None = None,
    signal_id: int | None = None,
) -> NotificationDraft:
    """CDC2 55 : signal Telegram et verdict de TradePilot."""
    consensus = None if ai_consensus is None else ("OUI" if ai_consensus else "NON")
    body = "\n".join(
        [
            f"{channel_name}",
            f"{symbol} · {format_direction(direction)}",
            "",
            labelled_lines(
                ("TradePilot", verdict.upper()),
                ("Consensus IA", consensus),
                ("Confiance", format_ratio_percent(confidence)),
            ),
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.SIGNAL,
        priority=NotificationPriority.HIGH,
        title=f"📡 SIGNAL TELEGRAM — {symbol}",
        body=body,
        data={"route": "signal", "signalId": signal_id, "symbol": symbol},
        symbol=symbol,
    )


# Une alerte ne doit pas crier plus fort que ce que l'actualite pese. Sans
# cette correspondance, la priorite etait HIGH en dur et le reglage
# « priorite minimale » n'ecartait jamais rien.
_PRIORITE_PAR_IMPACT: dict[str, NotificationPriority] = {
    "CRITICAL": NotificationPriority.CRITICAL,
    "HIGH": NotificationPriority.HIGH,
    "MEDIUM": NotificationPriority.MEDIUM,
    "LOW": NotificationPriority.LOW,
}


def priority_for_impact(impact: Any) -> NotificationPriority:
    """Priorite correspondant a un impact mesure.

    Un impact inconnu vaut MEDIUM : ni assez sur pour reveiller quelqu'un, ni
    assez anodin pour etre tu.
    """
    brut = str(getattr(impact, "value", impact) or "").strip().upper()
    return _PRIORITE_PAR_IMPACT.get(brut, NotificationPriority.MEDIUM)


def ai_disagreement(
    *,
    symbol: str,
    primary_direction: Any,
    secondary_direction: Any,
    decision: str = "NO TRADE",
    detail: str | None = None,
    decision_id: int | None = None,
) -> NotificationDraft:
    """CDC2 56 : les deux modeles interroges ne disent pas la meme chose."""
    body = "\n".join(
        [
            symbol,
            "",
            labelled_lines(
                ("Modèle principal", format_direction(primary_direction)),
                ("Second modèle", format_direction(secondary_direction)),
                ("Décision", decision.upper()),
                ("Détail", detail),
            ),
            "",
            "Aucun ordre n’a été envoyé.",
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.AI_SYSTEM,
        priority=NotificationPriority.HIGH,
        title=f"⚠️ ANALYSE INCERTAINE — {symbol}",
        body=body,
        data={"route": "decision", "decisionId": decision_id, "symbol": symbol},
        symbol=symbol,
        decision_id=decision_id,
    )


# ---------------------------------------------------------------------------
# Risque, news, economie et systeme (CDC2 sections 61 a 63 et 87)
# ---------------------------------------------------------------------------

def risk_limit_reached(
    *, reason: str, detail: str | None = None, auto_trading_suspended: bool = True
) -> NotificationDraft:
    """CDC2 61 : limite de risque atteinte."""
    lines = [reason]
    if detail:
        lines.append(detail)
    if auto_trading_suspended:
        lines.append("Trading automatique suspendu.")
    return NotificationDraft(
        category=NotificationCategory.RISK,
        priority=NotificationPriority.CRITICAL,
        title="⚠️ LIMITE DE RISQUE",
        body="\n".join(lines),
        data={"route": "risk", "autoTradingSuspended": auto_trading_suspended},
    )


def high_impact_news(
    *,
    headline: str,
    affected: list[str] | None = None,
    interpretation: str | None = None,
    source: str | None = None,
    published_at: datetime | None = None,
    impact: Any = "HIGH",
    news_id: int | None = None,
) -> NotificationDraft:
    """CDC2 62 : actualite a fort impact."""
    body = "\n".join(
        [
            headline,
            "",
            labelled_lines(
                ("Instruments", ", ".join(affected or []) or None),
                ("Lecture TradePilot", interpretation),
                ("Source", source),
                ("Publié", format_moment(published_at)),
            ),
        ]
    )
    # Le titre reprend la depeche : un lot d'actualites a fort impact se
    # reduisait autrement a une seule notification, les autres etant prises
    # pour des doublons.
    return NotificationDraft(
        category=NotificationCategory.NEWS,
        priority=priority_for_impact(impact),
        title=f"🌍 {headline}"[:255],
        body=body,
        data={"route": "news", "newsId": news_id, "impact": str(getattr(impact, "value", impact))},
        symbol=(affected or [None])[0],
        news_id=news_id,
    )


def market_information(
    *, headline: str, detail: str | None = None, affected: list[str] | None = None, severity: Any = "HIGH"
) -> NotificationDraft:
    """CDC2 63 : information boursiere qui touche les indices suivis."""
    body = "\n".join(
        [
            headline,
            "",
            labelled_lines(
                ("Détail", detail),
                ("Impact potentiel", ", ".join(affected or []) or None),
                ("Sévérité", format_impact(severity)),
            ),
        ]
    )
    return NotificationDraft(
        category=NotificationCategory.NEWS,
        priority=NotificationPriority.MEDIUM,
        title="📈 INFORMATION DE MARCHÉ",
        body=body,
        data={"route": "news", "affected": list(affected or [])},
    )


def economic_event_upcoming(
    *,
    title: str,
    currency: str | None = None,
    scheduled_at: datetime | None = None,
    minutes_before: int | None = None,
    impact: Any = "HIGH",
    forecast: str | None = None,
    previous: str | None = None,
    event_id: int | None = None,
) -> NotificationDraft:
    """CDC2 34 et 62 : evenement economique imminent."""
    delay = f"dans {minutes_before} min" if minutes_before else None
    body = "\n".join(
        [
            title,
            "",
            labelled_lines(
                ("Devise", currency),
                ("Heure", format_moment(scheduled_at)),
                ("Échéance", delay),
                ("Impact", format_impact(impact)),
                ("Prévision", forecast),
                ("Précédent", previous),
            ),
        ]
    )
    # Le titre identifie l'evenement : sans cela, l'anti-doublon avalait
    # toutes les publications d'un meme creneau sauf la premiere.
    marqueur = f"{currency} · " if currency else ""
    return NotificationDraft(
        category=NotificationCategory.ECONOMIC,
        priority=NotificationPriority.HIGH,
        title=f"📅 {marqueur}{title}"[:255],
        body=body,
        data={"route": "calendar", "eventId": event_id, "currency": currency},
    )


def system_status(
    *, service: str, online: bool, detail: str | None = None, critical: bool = False
) -> NotificationDraft:
    """CDC2 87 : un service du systeme change d'etat."""
    state = "rétabli" if online else "indisponible"
    priority = NotificationPriority.MEDIUM if online else (
        NotificationPriority.CRITICAL if critical else NotificationPriority.HIGH
    )
    return NotificationDraft(
        category=NotificationCategory.SYSTEM,
        priority=priority,
        title=f"{'✅' if online else '🔌'} {service} {state}",
        body=labelled_lines(("Service", service), ("État", state.capitalize()), ("Détail", detail)),
        data={"route": "diagnostic", "service": service, "online": online},
    )


def test_notification() -> NotificationDraft:
    """Notification d'essai declenchee depuis l'application."""
    return NotificationDraft(
        category=NotificationCategory.SYSTEM,
        priority=NotificationPriority.HIGH,
        title="🔔 Test TradePilot",
        body="Si vous lisez ceci sur votre téléphone, les notifications fonctionnent.",
        data={"route": "notifications", "test": True},
    )
