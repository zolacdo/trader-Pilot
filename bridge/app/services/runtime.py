"""Etat global du Bridge et assemblage des statuts affiches par l'application."""

from __future__ import annotations

import platform
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.config.settings import API_VERSION, APP_VERSION, get_settings
from app.models.enums import AccountKind, ConnectionState, ExecutionMode
from app.repositories import settings_repo
from app.services.openrouter.service import openrouter_service
from app.services.trading.engine import trading_engine
from app.services.tunnel.ngrok_service import ngrok_service

logger = get_logger(__name__)


class RuntimeState:
    """Informations de fonctionnement du processus."""

    def __init__(self) -> None:
        self.started_at = time.time()
        self.mt5_available = False
        self.mt5_state = ConnectionState.NOT_CONFIGURED
        self.mt5_error: str | None = None
        self.mt5_terminal_path: str | None = None
        self.mt5_real_tested = False
        self.telegram_started = False
        self.last_signal_at: str | None = None
        self.last_trade_at: str | None = None

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": APP_VERSION,
            "apiVersion": API_VERSION,
            "uptimeSeconds": self.uptime_seconds,
            "python": platform.python_version(),
            "platform": platform.platform(),
        }


runtime_state = RuntimeState()


async def telegram_status() -> dict[str, Any]:
    """Statut Telegram, tolerant a l'absence totale de configuration."""
    try:
        from app.services.telegram import telegram_service

        return await telegram_service.status()
    except Exception as exc:  # le Bridge doit demarrer meme sans Telegram
        logger.debug("Statut Telegram indisponible : %s", exc)
        return {"state": ConnectionState.NOT_CONFIGURED.value, "authorized": False, "lastError": str(exc)}


async def mt5_status() -> dict[str, Any]:
    """Statut du terminal MetaTrader 5."""
    market = trading_engine.market
    payload: dict[str, Any] = {
        "state": runtime_state.mt5_state.value,
        "available": runtime_state.mt5_available,
        "error": runtime_state.mt5_error,
        "terminalPath": runtime_state.mt5_terminal_path,
        "realTestedOnThisMachine": runtime_state.mt5_real_tested,
        "account": None,
        "terminal": None,
    }
    if market is None:
        return payload
    try:
        connected = await market.is_connected()
    except Exception as exc:
        payload["error"] = str(exc)
        return payload

    payload["state"] = (
        ConnectionState.CONNECTED.value if connected else ConnectionState.DISCONNECTED.value
    )
    if not connected:
        return payload
    try:
        account = await market.account_info()
        terminal = await market.terminal_info()
        payload["account"] = account.to_dict() if account else None
        payload["terminal"] = terminal.to_dict() if terminal else None
    except Exception as exc:
        payload["error"] = str(exc)
    return payload


async def account_snapshot(session: AsyncSession) -> dict[str, Any]:
    """Compte reellement utilise par le mode d'execution actif."""
    settings = await settings_repo.get_risk_settings(session)
    service = trading_engine.service_for(settings.execution_mode)
    if service is None:
        return {
            "executionMode": settings.execution_mode.value,
            "account": None,
            "kind": AccountKind.UNKNOWN.value,
        }
    try:
        account = await service.account_info()
    except Exception as exc:
        logger.debug("Compte indisponible : %s", exc)
        account = None
    paper_live_prices = getattr(service, "uses_live_prices", None)
    return {
        "executionMode": settings.execution_mode.value,
        "account": account.to_dict() if account else None,
        "kind": account.kind.value if account else AccountKind.UNKNOWN.value,
        "paperUsesLivePrices": paper_live_prices,
    }


async def connection_summary(session: AsyncSession) -> dict[str, Any]:
    """Bandeau d'etat de l'ecran d'accueil et de l'onboarding."""
    settings = await settings_repo.get_risk_settings(session)
    state = await settings_repo.get_trading_state(session)
    telegram = await telegram_status()
    mt5 = await mt5_status()
    openrouter = await openrouter_service.status(session)
    account = await account_snapshot(session)

    return {
        "bridge": {
            "state": ConnectionState.CONNECTED.value,
            **runtime_state.to_dict(),
            "publicUrl": ngrok_service.status.public_url,
        },
        "telegram": telegram,
        "mt5": mt5,
        "openrouter": openrouter,
        "tunnel": ngrok_service.status.to_dict(),
        "account": account,
        "trading": {
            "autoTradingEnabled": settings.auto_trading_enabled,
            "executionMode": settings.execution_mode.value,
            "liveUnlocked": settings.live_unlocked,
            "paused": state.paused,
            "pauseReason": state.pause_reason,
            "pausedUntil": state.paused_until.isoformat() if state.paused_until else None,
            "consecutiveLosses": state.consecutive_losses,
            "onboardingCompleted": state.onboarding_completed,
        },
    }


def execution_mode_label(mode: ExecutionMode) -> str:
    return {
        ExecutionMode.PAPER: "Paper Trading (aucun ordre reel)",
        ExecutionMode.MT5_DEMO: "MetaTrader 5 - compte demo",
        ExecutionMode.MT5_LIVE: "MetaTrader 5 - compte reel",
    }[mode]


def describe_environment() -> dict[str, Any]:
    settings = get_settings()
    return {
        "host": settings.bridge_host,
        "port": settings.bridge_port,
        "dataDir": str(settings.data_dir),
        "logLevel": settings.log_level,
        "ngrokEnabled": settings.ngrok_enabled,
        "ngrokDomain": settings.ngrok_domain or None,
    }
