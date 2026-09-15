"""Mise en forme des messages Telegram (CDC3 sections 33 a 37).

Deux formats sont prevus : ``detailed``, qui explique la decision, et
``simple``, qui tient en six lignes. Le choix se fait par le reglage
``watcher.telegram_format`` (CDC3 section 34).

Le texte est produit en HTML : Telegram n'accepte qu'un jeu de balises tres
restreint, et tout ce qui vient d'une source externe (titre d'actualite, nom
d'evenement) est echappe avant d'y entrer.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from app.models.core import as_utc
from app.models.enums import Direction
from app.watcher.models import WatcherSignal, WatcherStatus

# Pastille par etat d'unite de temps.
_TREND_EMOJI: dict[str, str] = {
    "BULLISH": "\U0001f7e2",
    "BEARISH": "\U0001f534",
    "NEUTRAL": "\U0001f7e1",
    "RANGING": "\U0001f7e1",
    "NO_DATA": "⚪",
}

_STATUS_LABELS: dict[WatcherStatus, tuple[str, str]] = {
    WatcherStatus.TP1_HIT: ("✅", "TP1 atteint"),
    WatcherStatus.TP2_HIT: ("✅", "TP2 atteint"),
    WatcherStatus.TP3_HIT: ("\U0001f3af", "TP3 atteint"),
    WatcherStatus.SL_HIT: ("❌", "Stop loss touche"),
    WatcherStatus.INVALIDATED: ("⚠️", "Signal invalide"),
    WatcherStatus.EXPIRED: ("\U0001f570️", "Signal expire"),
    WatcherStatus.CANCELLED: ("\U0001f6d1", "Signal annule"),
    WatcherStatus.ACTIVE: ("▶️", "Entree atteinte"),
}

# Nombre de decimales au-dela duquel on n'espace plus les milliers : sur une
# paire a cinq decimales, un espace des milliers nuirait a la lecture.
GROUPING_MAX_DIGITS = 3


def _digits(signal: WatcherSignal) -> int:
    """Precision d'affichage : celle que le broker cote pour cet instrument."""
    return max(0, min(int(signal.digits), 8))


def price(value: float | None, digits: int = 2) -> str:
    """Prix lisible : espaces fins pour les milliers sur les gros instruments."""
    if value is None:
        return "-"
    if digits <= GROUPING_MAX_DIGITS:
        text = f"{value:,.{digits}f}".replace(",", " ")
    else:
        text = f"{value:.{digits}f}"
    return text


def _moment(value: datetime | None) -> str:
    stamp = as_utc(value)
    return stamp.strftime("%Y-%m-%d %H:%M UTC") if stamp else "-"


def _direction_word(direction: Direction) -> str:
    return "BUY" if direction is Direction.BUY else "SELL"


def simple_signal(signal: WatcherSignal) -> str:
    """Format minimal demande au CDC3 section 34."""
    digits = _digits(signal)
    lines = [
        f"{_direction_word(signal.direction)} {escape(signal.symbol)}",
        f"Entry {price(signal.entry, digits)}",
        f"SL {price(signal.stop_loss, digits)}",
    ]
    for index, target in enumerate(signal.targets, start=1):
        lines.append(f"TP{index} {price(target, digits)}")
    return "\n".join(lines)


def detailed_signal(signal: WatcherSignal, auto_trade: bool = False) -> str:
    """Format complet du CDC3 section 33, en francais."""
    digits = _digits(signal)
    direction = _direction_word(signal.direction)
    emoji = "\U0001f7e2" if signal.direction is Direction.BUY else "\U0001f534"

    lines = [
        f"\U0001f6a8 <b>{escape(signal.symbol)} — SIGNAL {escape(signal.decision.value)}</b>",
        "",
        f"{emoji} <b>{direction} {escape(signal.symbol)}</b>",
        f"Entree ({escape(signal.entry_type.value)}) : <code>{price(signal.entry, digits)}</code>",
        f"Stop loss : <code>{price(signal.stop_loss, digits)}</code>",
        "",
    ]
    for index, target in enumerate(signal.targets, start=1):
        rr = None
        rewards = [signal.risk_reward_1, signal.risk_reward_2, signal.risk_reward_3]
        if index <= len(rewards):
            rr = rewards[index - 1]
        suffix = f"  (1:{rr})" if rr else ""
        lines.append(f"TP{index} : <code>{price(target, digits)}</code>{suffix}")

    lines.extend(["", f"Confiance : <b>{signal.confidence}/100</b>"])

    states = signal.timeframe_states or {}
    if states:
        lines.append("")
        lines.append("<b>Unites de temps</b>")
        for frame, state in states.items():
            pastille = _TREND_EMOJI.get(str(state), "⚪")
            lines.append(f"{escape(str(frame)):<4} {pastille} {escape(str(state).lower())}")

    if signal.reasons:
        lines.append("")
        lines.append("<b>Pourquoi</b>")
        lines.extend(f"• {escape(reason)}" for reason in signal.reasons[:6])

    if signal.risks:
        lines.append("")
        lines.append("<b>Risques</b>")
        lines.extend(f"• {escape(risk)}" for risk in signal.risks[:5])

    if signal.ai_comment:
        lines.append("")
        lines.append(f"<b>Lecture IA</b>\n{escape(signal.ai_comment)}")

    if signal.invalidation:
        lines.append("")
        lines.append(f"<b>Invalidation</b>\n{escape(signal.invalidation)}")

    lines.extend(
        [
            "",
            f"<i>{escape(signal.strategy_version)} — {_moment(signal.created_at)}</i>",
            # Le pied de page doit dire la verite : quand l'execution
            # automatique est active, ce message n'est plus une simple analyse.
            (
                "<i>Analyse automatique. L'ordre est transmis au broker apres"
                " controle du risque. Ceci n'est pas un conseil en investissement.</i>"
                if auto_trade
                else "<i>Analyse automatique, aucun ordre n'est passe. Ceci n'est"
                " pas un conseil en investissement.</i>"
            ),
        ]
    )
    return "\n".join(lines)


def signal_message(
    signal: WatcherSignal, simple: bool = False, auto_trade: bool = False
) -> str:
    return simple_signal(signal) if simple else detailed_signal(signal, auto_trade)


def watch_message(
    symbol: str,
    current_price: float | None,
    score: float,
    buy_trigger: float | None,
    sell_trigger: float | None,
    digits: int,
    detail: str = "",
    direction: Direction | None = None,
) -> str:
    """Alerte de surveillance (CDC3 section 35).

    Le message n'affiche QUE le declencheur du sens reellement guette. Il
    montrait les deux, sans dire lequel comptait : le 13/09/2026, une
    surveillance BTCUSD a la VENTE sous 77 035 affichait aussi « confirmation
    achat au-dessus de 77 103 » alors que le prix cotait deja 77 131. Le
    lecteur voyait un seuil d'achat deja franchi et attendait un signal qui ne
    pouvait pas venir : ce n'etait pas celui-la qu'on surveillait.
    """
    guette = sell_trigger if direction is Direction.SELL else buy_trigger
    sens = "VENTE" if direction is Direction.SELL else "ACHAT"
    comparateur = "&lt;" if direction is Direction.SELL else "&gt;"

    lines = [
        f"\U0001f440 <b>{escape(symbol)} — SOUS SURVEILLANCE {escape(sens)}</b>",
        "",
        f"Prix actuel : <code>{price(current_price, digits)}</code>",
    ]
    if guette is not None:
        lines.append(
            f"Confirmation {sens.lower()} : {comparateur} "
            f"<code>{price(guette, digits)}</code>"
        )
    lines.extend(["", "Decision : <b>ATTENTE</b>", f"Score : <b>{round(score)}/100</b>"])
    if detail:
        lines.extend(["", escape(detail)])
    lines.append("")
    lines.append("<i>Aucun ordre n'est passe. Le signal sera reevalue a la confirmation.</i>")
    return "\n".join(lines)


def watch_closed_message(
    symbol: str,
    direction: Direction | None,
    trigger: float | None,
    current_price: float | None,
    digits: int,
    reason: str = "",
) -> str:
    """Fin d'une surveillance qui n'a pas abouti (CDC3 section 35).

    Une surveillance promet « le signal sera reevalue a la confirmation ». Sans
    ce message, la promesse restait sans suite : le marche s'eloignait du
    declencheur et plus rien n'etait dit. On ne sait alors pas si le systeme
    attend encore ou s'il a renonce.
    """
    sens = "VENTE" if direction is Direction.SELL else "ACHAT"
    lines = [
        f"\U0001f6ab <b>{escape(symbol)} — SURVEILLANCE LEVÉE</b>",
        "",
        f"Le declencheur {escape(sens.lower())} n'a pas ete touche.",
    ]
    if trigger is not None:
        lines.append(f"Seuil guette : <code>{price(trigger, digits)}</code>")
    if current_price is not None:
        lines.append(f"Prix actuel : <code>{price(current_price, digits)}</code>")
    if reason:
        lines.extend(["", escape(reason)])
    lines.append("")
    lines.append("<i>Aucun ordre n'a ete passe. Ce marche n'est plus surveille.</i>")
    return "\n".join(lines)


def watch_confirmed_message(
    symbol: str,
    direction: Direction | None,
    trigger: float | None,
    current_price: float | None,
    digits: int,
) -> str:
    """Le declencheur guette a ete touche : le signal arrive (CDC3 section 35).

    Une surveillance doit raconter ses deux issues. Sans ce message, la seule
    trace d'une confirmation etait le signal lui-meme, et rien ne reliait les
    deux : on ne savait pas si ce signal venait de la surveillance annoncee
    plus tot ou s'il sortait de nulle part.
    """
    sens = "VENTE" if direction is Direction.SELL else "ACHAT"
    comparateur = "sous" if direction is Direction.SELL else "au-dessus de"
    lines = [
        f"\u2705 <b>{escape(symbol)} — SURVEILLANCE CONFIRMÉE</b>",
        "",
        f"Le declencheur {escape(sens.lower())} a ete touche.",
    ]
    if trigger is not None:
        lines.append(
            f"Seuil franchi : {escape(comparateur)} "
            f"<code>{price(trigger, digits)}</code>"
        )
    if current_price is not None:
        lines.append(f"Prix actuel : <code>{price(current_price, digits)}</code>")
    lines.append("")
    lines.append("<i>Le signal correspondant suit immediatement.</i>")
    return "\n".join(lines)


def lifecycle_message(
    signal: WatcherSignal,
    status: WatcherStatus,
    hit_price: float | None,
    detail: str = "",
    lesson: str | None = None,
) -> str:
    """Mise a jour d'un signal deja publie (CDC3 section 32)."""
    emoji, label = _STATUS_LABELS.get(status, ("ℹ️", status.value))
    digits = _digits(signal)
    lines = [
        f"{emoji} <b>{escape(signal.symbol)} — {escape(label)}</b>",
        "",
        f"Signal {_direction_word(signal.direction)} du {_moment(signal.created_at)}",
        f"Entree : <code>{price(signal.entry, digits)}</code>",
    ]
    if hit_price is not None:
        lines.append(f"Prix atteint : <code>{price(hit_price, digits)}</code>")
    if signal.result_r is not None:
        lines.append(f"Resultat : <b>{signal.result_r:+.2f} R</b>")
    if detail:
        lines.extend(["", escape(detail)])
    # Une perte analysee en base et invisible n'apprend rien a personne : la
    # lecon accompagne l'annonce, la ou elle sera lue.
    if lesson:
        lines.extend(["", f"<i>{escape(lesson)}</i>"])
    return "\n".join(lines)


def news_alert_message(
    title: str,
    currency: str | None,
    impact: str,
    scheduled_at: datetime | None,
    affected: list[str],
) -> str:
    """Alerte de calendrier economique (CDC3 section 36)."""
    lines = [
        "⚠️ <b>ALERTE MARCHE</b>",
        "",
        f"Evenement : <b>{escape(title)}</b>",
        f"Devise : {escape(currency or 'inconnue')}",
        f"Importance : <b>{escape(impact)}</b>",
        f"Heure : {_moment(scheduled_at)}",
    ]
    if affected:
        lines.append(f"Instruments concernes : {escape(', '.join(affected[:8]))}")
    lines.extend(
        [
            "",
            "Decision : <b>nouvelles entrees suspendues</b> autour de l'annonce.",
        ]
    )
    return "\n".join(lines)


def breaking_news_message(
    headline: str, source: str, impact: str, sentiment: str, affected: list[str]
) -> str:
    """Actualite majeure (CDC3 section 37)."""
    lines = [
        "\U0001f6a8 <b>ACTUALITE MAJEURE</b>",
        "",
        escape(headline),
        "",
        f"Source : {escape(source)}",
        f"Impact estime : <b>{escape(impact)}</b>",
        f"Tonalite : {escape(sentiment)}",
    ]
    if affected:
        lines.append(f"Concerne : {escape(', '.join(affected[:8]))}")
    return "\n".join(lines)


def startup_message(
    symbols: list[str], dry_run: bool, version: str, auto_trade: bool = False
) -> str:
    """Message de demarrage, envoye une fois par lancement."""
    mode = "ANALYSE SEULE (aucune publication)" if dry_run else "ANALYSE ET PUBLICATION"
    lines = [
        "\U0001f6f0️ <b>AI Market Watcher demarre</b>",
        "",
        f"Version : {escape(version)}",
        f"Mode : {escape(mode)}",
        f"Instruments suivis ({len(symbols)}) : {escape(', '.join(symbols)) or 'aucun'}",
        "",
        (
            "<i>Ce service analyse, publie et transmet ses signaux au broker"
            " apres controle du risque.</i>"
            if auto_trade and not dry_run
            else "<i>Ce service analyse et publie des signaux. Il ne passe aucun ordre.</i>"
        ),
    ]
    return "\n".join(lines)


def summary_payload(signal: WatcherSignal) -> dict[str, Any]:
    """Version courte, utilisee par l'API et les journaux."""
    return {
        "symbol": signal.symbol,
        "direction": signal.direction.value,
        "decision": signal.decision.value,
        "entry": signal.entry,
        "stopLoss": signal.stop_loss,
        "targets": signal.targets,
        "confidence": signal.confidence,
    }


__all__ = [
    "breaking_news_message",
    "detailed_signal",
    "lifecycle_message",
    "news_alert_message",
    "price",
    "signal_message",
    "simple_signal",
    "startup_message",
    "summary_payload",
    "watch_message",
]
