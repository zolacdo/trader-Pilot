"""Bus d'evenements interne, relaye vers les clients WebSocket.

Chaque abonne possede sa propre file bornee : un client lent ne bloque jamais
le moteur de trading, il perd simplement les evenements les plus anciens.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from app.config.logging_config import get_logger

logger = get_logger(__name__)

QUEUE_MAX_SIZE = 500


class EventType:
    """Noms d'evenements pousses vers l'application mobile (CDC section 39)."""

    HELLO = "hello"
    PING = "ping"
    SIGNAL_NEW = "signal.new"
    SIGNAL_UPDATED = "signal.updated"
    SIGNAL_REJECTED = "signal.rejected"
    SIGNAL_NEEDS_REVIEW = "signal.needs_review"
    POSITION_OPENED = "position.opened"
    POSITION_UPDATED = "position.updated"
    POSITION_CLOSED = "position.closed"
    ORDER_PLACED = "order.placed"
    ORDER_CANCELLED = "order.cancelled"
    ACCOUNT_UPDATED = "account.updated"
    PNL_UPDATED = "pnl.updated"
    MT5_STATUS = "mt5.status"
    TELEGRAM_STATUS = "telegram.status"
    OPENROUTER_STATUS = "openrouter.status"
    TUNNEL_STATUS = "tunnel.status"
    TRADING_STATE = "trading.state"
    CHANNEL_UPDATED = "channel.updated"
    CHANNEL_ANALYSIS = "channel.analysis"
    # --- intelligence de marche (CDC2 section 99) ---
    LOCAL_AI_STATUS = "local_ai.status"
    OPENROUTER_AI_STATUS = "openrouter.status"
    AI_ROUTING_EVENT = "ai.routing"
    AI_CONSENSUS_EVENT = "ai.consensus"
    AI_DISAGREEMENT = "ai.disagreement"
    MARKET_UPDATE = "market.update"
    OPPORTUNITY_CREATED = "opportunity.created"
    DECISION_CREATED = "decision.created"
    NEWS_HIGH_IMPACT = "news.high_impact"
    ECONOMIC_EVENT = "economic.event"
    TRADE_EXECUTED = "trade.executed"
    TRADE_CLOSED = "trade.closed"
    RISK_BREAKER = "risk.breaker"
    NOTIFICATION_CREATED = "notification.created"
    JOURNAL = "journal"
    ERROR = "error"
    NOTIFICATION = "notification"


class Event(dict):
    """Enveloppe JSON simple : {type, ts, data}."""

    @classmethod
    def create(cls, event_type: str, data: dict[str, Any] | None = None) -> Event:
        return cls(
            type=event_type,
            ts=datetime.now(UTC).isoformat(),
            data=data or {},
        )


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._lock = asyncio.Lock()
        self._last_events: dict[str, Event] = {}

    async def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    @asynccontextmanager
    async def subscription(self) -> AsyncIterator[asyncio.Queue[Event]]:
        queue = await self.subscribe()
        try:
            yield queue
        finally:
            await self.unsubscribe(queue)

    def publish(self, event_type: str, data: dict[str, Any] | None = None) -> Event:
        """Publication non bloquante, appelable depuis n'importe quel service async."""
        event = Event.create(event_type, data)
        self._last_events[event_type] = event
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()  # abandonne le plus ancien
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover
                    logger.debug("File d'evenements saturee, evenement ignore")
        return event

    def snapshot(self) -> list[Event]:
        """Derniers evenements d'etat, envoyes a la connexion d'un client."""
        keys = (
            EventType.MT5_STATUS,
            EventType.TELEGRAM_STATUS,
            EventType.OPENROUTER_STATUS,
            EventType.TRADING_STATE,
            EventType.ACCOUNT_UPDATED,
            EventType.TUNNEL_STATUS,
        )
        return [self._last_events[key] for key in keys if key in self._last_events]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


event_bus = EventBus()
