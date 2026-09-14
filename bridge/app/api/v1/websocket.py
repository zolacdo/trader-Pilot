"""Flux WebSocket temps reel vers l'application mobile.

Le client s'authentifie avec son jeton de peripherique, recoit immediatement un
instantane des etats connus, puis chaque evenement au fil de l'eau. La
reconnexion avec backoff est geree cote Flutter (CDC section 39).
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config.logging_config import get_logger
from app.database.session import session_scope
from app.services.events import Event, EventType, event_bus
from app.services.security.auth import authenticate_websocket

logger = get_logger(__name__)

router = APIRouter()

PING_INTERVAL_SECONDS = 25.0
CLOSE_UNAUTHORIZED = 4401


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    await websocket.accept()

    # Le jeton peut arriver en query (simple) ou dans le premier message (plus sur
    # car il ne finit pas dans les journaux d'acces).
    device_token = token
    if not device_token:
        try:
            first = await asyncio.wait_for(websocket.receive_json(), timeout=10)
            device_token = (first or {}).get("token")
        except (TimeoutError, WebSocketDisconnect, ValueError):
            await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Jeton manquant")
            return

    async with session_scope() as session:
        device = await authenticate_websocket(device_token, session)
    if device is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Jeton invalide")
        return

    logger.info("Client WebSocket connecte : %s", device.name)
    async with event_bus.subscription() as queue:
        await websocket.send_json(
            Event.create(EventType.HELLO, {"device": device.name, "bridge": "TradePilot"})
        )
        for snapshot in event_bus.snapshot():
            await websocket.send_json(snapshot)

        sender = asyncio.create_task(_pump(websocket, queue))
        receiver = asyncio.create_task(_drain(websocket))
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            exception = task.exception()
            if exception and not isinstance(exception, WebSocketDisconnect):
                logger.debug("Fin de session WebSocket : %s", exception)

    if websocket.client_state is not WebSocketState.DISCONNECTED:
        with contextlib.suppress(RuntimeError):
            await websocket.close()
    logger.info("Client WebSocket deconnecte : %s", device.name)


async def _pump(websocket: WebSocket, queue: asyncio.Queue[Event]) -> None:
    """Envoie les evenements, avec un ping regulier pour garder la ligne ouverte."""
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=PING_INTERVAL_SECONDS)
        except TimeoutError:
            await websocket.send_json(Event.create(EventType.PING))
            continue
        await websocket.send_json(event)


async def _drain(websocket: WebSocket) -> None:
    """Consomme les messages entrants (ping applicatif) et detecte la fermeture."""
    while True:
        message = await websocket.receive_json()
        if isinstance(message, dict) and message.get("type") == "ping":
            await websocket.send_json(Event.create(EventType.PING))
