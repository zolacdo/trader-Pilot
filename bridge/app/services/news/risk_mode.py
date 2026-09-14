"""NewsRiskMode : fenetre de silence autour des evenements majeurs (CDC2 35).

Ce module ne bloque rien lui-meme. Il repond a une seule question, que le
RiskManager posera au moment voulu :

    is_in_news_blackout(symbol, now) -> (bloque, raison)

X minutes avant et Y minutes apres un evenement HIGH ou CRITICAL touchant une
devise du symbole, la reponse est ``(True, raison)``. Le RiskManager reste
libre d'en faire ce qu'il veut : ce fichier ne le modifie pas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.database.session import session_scope
from app.models.core import as_utc, utcnow
from app.models.intelligence import EconomicEvent, NewsImpact
from app.repositories import news_repo, settings_repo
from app.services.news.relevance import rank
from app.services.news.taxonomy import currencies_for_symbol

logger = get_logger(__name__)

BLACKOUT_KEY = "news.blackout"

DEFAULT_MINUTES_BEFORE = 30
DEFAULT_MINUTES_AFTER = 15


@dataclass(slots=True)
class BlackoutConfig:
    """Reglage de la fenetre de silence, modifiable par l'utilisateur."""

    enabled: bool = True
    minutes_before: int = DEFAULT_MINUTES_BEFORE
    minutes_after: int = DEFAULT_MINUTES_AFTER
    minimum_impact: NewsImpact = NewsImpact.HIGH

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["minimum_impact"] = self.minimum_impact.value
        return data

    @classmethod
    def from_dict(cls, raw: Any) -> BlackoutConfig:
        base = cls()
        if not isinstance(raw, dict):
            return base
        try:
            before = int(raw.get("minutes_before", raw.get("minutesBefore", base.minutes_before)))
        except (TypeError, ValueError):
            before = base.minutes_before
        try:
            after = int(raw.get("minutes_after", raw.get("minutesAfter", base.minutes_after)))
        except (TypeError, ValueError):
            after = base.minutes_after
        impact = base.minimum_impact
        raw_impact = raw.get("minimum_impact", raw.get("minimumImpact"))
        if isinstance(raw_impact, str):
            try:
                impact = NewsImpact(raw_impact.strip().upper())
            except ValueError:
                impact = base.minimum_impact
        return cls(
            enabled=bool(raw.get("enabled", True)),
            minutes_before=max(0, min(before, 720)),
            minutes_after=max(0, min(after, 720)),
            minimum_impact=impact,
        )


async def load_config(session: AsyncSession) -> BlackoutConfig:
    stored = await settings_repo.get_setting(session, BLACKOUT_KEY, None)
    return BlackoutConfig.from_dict(stored)


async def save_config(session: AsyncSession, config: BlackoutConfig) -> BlackoutConfig:
    await settings_repo.set_setting(session, BLACKOUT_KEY, config.to_dict())
    return config


def evaluate_blackout(
    symbol: str,
    events: list[EconomicEvent],
    now: datetime,
    config: BlackoutConfig,
) -> tuple[bool, str | None]:
    """Coeur deterministe, sans base de donnees : entierement testable.

    Un evenement concerne le symbole si sa devise est l'une de celles que le
    symbole porte. Un evenement sans devise renseignee ne bloque rien : on ne
    devine pas a quel marche il se rattache.
    """
    if not config.enabled:
        return False, None
    symbol_currencies = currencies_for_symbol(symbol)
    if not symbol_currencies:
        return False, None

    minimum = rank(config.minimum_impact)
    for event in events:
        if rank(event.impact) < minimum:
            continue
        currency = (event.currency or "").strip().upper()
        if not currency or currency not in symbol_currencies:
            continue
        scheduled = as_utc(event.scheduled_at)
        if scheduled is None:
            continue
        start = scheduled - timedelta(minutes=config.minutes_before)
        end = scheduled + timedelta(minutes=config.minutes_after)
        if start <= now <= end:
            delta = int((scheduled - now).total_seconds() // 60)
            when = (
                f"dans {delta} minute(s)"
                if delta > 0
                else ("maintenant" if delta == 0 else f"il y a {abs(delta)} minute(s)")
            )
            return True, (
                f"Événement {event.impact.value} {currency} « {event.title} » {when} : "
                f"fenêtre de silence de {config.minutes_before} min avant et "
                f"{config.minutes_after} min après."
            )
    return False, None


async def is_in_news_blackout(
    symbol: str, now: datetime | None = None
) -> tuple[bool, str | None]:
    """Le symbole est-il dans une fenetre de silence news ?

    Signature destinee au RiskManager (CDC2 section 35). Retourne
    ``(False, None)`` quand rien ne bloque, ``(True, raison)`` sinon. La raison
    est un texte affichable a l'utilisateur.

    En cas d'erreur de lecture de la base, la reponse est ``(False, None)`` :
    ce module ne doit jamais bloquer le moteur sur une panne technique, les
    autres barrieres du RiskManager restent en place.
    """
    moment = as_utc(now) or utcnow()
    try:
        async with session_scope() as session:
            return await evaluate_for_session(session, symbol, moment)
    except Exception as exc:
        logger.warning("Fenetre de silence news non evaluable : %s", exc)
        return False, None


async def evaluate_for_session(
    session: AsyncSession, symbol: str, now: datetime | None = None
) -> tuple[bool, str | None]:
    """Meme reponse, dans une session deja ouverte."""
    moment = as_utc(now) or utcnow()
    config = await load_config(session)
    if not config.enabled:
        return False, None
    events = await news_repo.list_economic_events(
        session,
        start=moment - timedelta(minutes=config.minutes_after + 1),
        end=moment + timedelta(minutes=config.minutes_before + 1),
    )
    return evaluate_blackout(symbol, events, moment, config)


__all__ = [
    "BLACKOUT_KEY",
    "DEFAULT_MINUTES_AFTER",
    "DEFAULT_MINUTES_BEFORE",
    "BlackoutConfig",
    "evaluate_blackout",
    "evaluate_for_session",
    "is_in_news_blackout",
    "load_config",
    "save_config",
]
