"""Point d'entree du Bridge TradePilot.

Demarrage tolerant : le Bridge doit se lancer meme si MetaTrader 5, Telegram
ou OpenRouter sont absents ou mal configures. Chaque composant indisponible est
signale dans le diagnostic plutot que de bloquer le service (CDC section 44).
"""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing
import sys
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.router import api_router
from app.config.logging_config import get_logger, redact, register_secret, setup_logging
from app.config.settings import API_VERSION, APP_VERSION, get_settings
from app.database.session import dispose_engine, init_database, session_scope
from app.models.enums import ConnectionState, ExecutionMode
from app.repositories import settings_repo
from app.services import journal, runtime, telegram_runtime
from app.services.ai.service import ai_service
from app.services.events import EventType, event_bus
from app.services.intelligence.scheduler import intelligence_scheduler
from app.services.mt5 import RealMetaTraderService, detect_terminals
from app.services.mt5.interface import MetaTraderNotAvailable
from app.services.openrouter.service import openrouter_service
from app.services.security.auth import pairing_manager
from app.services.telegram import telegram_service
from app.services.trading.engine import trading_engine
from app.services.trading.paper import PaperTradingService
from app.services.tunnel.ngrok_service import ngrok_service
from app.watcher.scheduler import watcher_scheduler

logger = get_logger("tradepilot")


# ---------------------------------------------------------------------------
# Demarrage des composants
# ---------------------------------------------------------------------------

MT5_RETRY_DELAYS = (30, 60, 120, 300)


def _create_market_service() -> RealMetaTraderService | None:
    """Prepare le service MT5 sans encore ouvrir de session."""
    terminals = detect_terminals()
    runtime.runtime_state.mt5_terminal_path = terminals[0] if terminals else None
    try:
        service = RealMetaTraderService()
    except MetaTraderNotAvailable as exc:
        runtime.runtime_state.mt5_available = False
        runtime.runtime_state.mt5_state = ConnectionState.NOT_CONFIGURED
        runtime.runtime_state.mt5_error = str(exc)
        logger.warning("MetaTrader 5 indisponible : %s", exc)
        return None
    runtime.runtime_state.mt5_available = True
    runtime.runtime_state.mt5_state = ConnectionState.CONNECTING
    return service


async def _connect_market_service(service: RealMetaTraderService) -> bool:
    """Une tentative de connexion au terminal, sans jamais lever."""
    try:
        connected = await service.initialize()
    except MetaTraderNotAvailable as exc:
        runtime.runtime_state.mt5_available = False
        runtime.runtime_state.mt5_state = ConnectionState.NOT_CONFIGURED
        runtime.runtime_state.mt5_error = str(exc)
        return False
    except Exception as exc:
        runtime.runtime_state.mt5_state = ConnectionState.ERROR
        runtime.runtime_state.mt5_error = (
            f"{exc}. Verifiez que MetaTrader 5 est ouvert, connecte a votre compte, "
            "et que le trading algorithmique est autorise dans Outils > Options > Expert Advisors."
        )
        logger.warning("Connexion MetaTrader 5 impossible : %s", exc)
        trading_engine.mt5_connected = False
        return False

    if connected:
        runtime.runtime_state.mt5_state = ConnectionState.CONNECTED
        runtime.runtime_state.mt5_real_tested = True
        runtime.runtime_state.mt5_error = None
        trading_engine.mt5_connected = True
        account = await service.account_info()
        if account is not None:
            logger.info(
                "MetaTrader 5 connecte : serveur %s, compte %s, %s %s",
                account.server,
                account.kind.value,
                round(account.balance, 2),
                account.currency,
            )
        event_bus.publish(EventType.MT5_STATUS, {"state": ConnectionState.CONNECTED.value})
        return True

    runtime.runtime_state.mt5_state = ConnectionState.DISCONNECTED
    runtime.runtime_state.mt5_error = (
        "Terminal MetaTrader 5 detecte mais non connecte. Ouvrez MT5 Desktop "
        "et connectez-vous a votre compte Exness."
    )
    trading_engine.mt5_connected = False
    logger.warning(runtime.runtime_state.mt5_error)
    return False


async def _market_connection_loop(service: RealMetaTraderService, paper: PaperTradingService) -> None:
    """Connecte MT5 en tache de fond et retente avec un delai croissant.

    Le Bridge doit repondre immediatement : l'API, Telegram et le paper trading
    ne dependent pas du terminal. Une connexion MT5 qui met une minute a echouer
    ne doit jamais retarder le demarrage (CDC section 44).
    """
    for index, delay in enumerate((0, *MT5_RETRY_DELAYS)):
        if delay:
            await asyncio.sleep(delay)
        if await _connect_market_service(service):
            # Le paper trading bascule alors sur les prix reels du broker.
            paper.attach_price_source(service)
            # Les resolveurs ont pu mettre en cache la liste simulee avant que
            # le terminal ne reponde : sans cela, XAUUSD ne deviendrait jamais
            # XAUUSDm et les prix resteraient simules.
            trading_engine.invalidate_symbol_caches()
            return
        if index == 0:
            logger.info("Nouvelle tentative de connexion MetaTrader dans %ss", MT5_RETRY_DELAYS[0])
    logger.warning(
        "MetaTrader 5 reste injoignable pour l'instant. La surveillance continue "
        "en arriere-plan."
    )


# Periode de surveillance du terminal une fois le demarrage passe.
MARKET_CHECK_INTERVAL = 60.0


async def _market_supervisor(service: RealMetaTraderService, paper: PaperTradingService) -> None:
    """Maintient la session MetaTrader ouverte pendant toute la vie du Bridge.

    La sequence de demarrage abandonne au bout de quelques essais, ce qui est
    juste : elle ne doit pas retarder le lancement. Mais le processus MT5 est
    tue et recycle des qu'un appel depasse son delai, et la session est alors
    perdue. Sans cette surveillance, plus rien ne la rouvrait : le Bridge
    restait aveugle sur le marche jusqu'a une action manuelle.
    """
    while True:
        await asyncio.sleep(MARKET_CHECK_INTERVAL)
        try:
            if await service.is_connected():
                continue
            if runtime.runtime_state.mt5_state is ConnectionState.NOT_CONFIGURED:
                # MetaTrader n'est pas installe sur cette machine : insister
                # n'apporterait rien.
                continue
            logger.info("Session MetaTrader absente : nouvelle tentative de connexion")
            if await _connect_market_service(service):
                paper.attach_price_source(service)
                trading_engine.invalidate_symbol_caches()
                await journal.log(
                    event="mt5_reconnected",
                    message="Session MetaTrader 5 retablie automatiquement",
                    category="system",
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # la surveillance ne doit jamais tuer le Bridge
            logger.debug("Surveillance MetaTrader : %s", exc)


TUNNEL_CHECK_INTERVAL = 60.0


async def _tunnel_supervisor() -> None:
    """Maintient le tunnel ouvert pendant toute la vie du Bridge.

    Sans surveillance, un tunnel qui n'a pas demarre a temps — machine chargee
    au demarrage — ou qui tombe en cours de route laisse le telephone coupe
    jusqu'au prochain redemarrage. Le Bridge, lui, continue de tourner : rien
    ne signalerait le probleme.
    """
    settings = get_settings()
    if not settings.ngrok_enabled:
        return

    while True:
        await asyncio.sleep(TUNNEL_CHECK_INTERVAL)
        try:
            status = await ngrok_service.refresh()
            if status.running:
                continue
            logger.warning("Tunnel ngrok interrompu : nouvelle tentative d'ouverture")
            restarted = await ngrok_service.start()
            if restarted.running:
                logger.info("Tunnel ngrok retabli : %s", restarted.public_url)
                await journal.log(
                    event="tunnel_restored",
                    message=f"Tunnel distant retabli : {restarted.public_url}",
                    category="system",
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # la surveillance ne doit jamais tuer le Bridge
            logger.debug("Surveillance du tunnel : %s", exc)


async def _start_telegram() -> None:
    try:
        connected = await telegram_service.connect_existing()
    except Exception as exc:
        logger.warning("Reconnexion Telegram impossible : %s", exc)
        return
    if connected:
        await telegram_runtime.start_listener()
    else:
        logger.info("Aucune session Telegram enregistree : connectez le compte depuis l'application")


async def _print_startup_banner(public_url: str | None) -> None:
    settings = get_settings()
    code = pairing_manager.issue()
    local_url = f"http://{settings.bridge_host}:{settings.bridge_port}"
    lines = [
        "",
        "=" * 66,
        f"  TradePilot Bridge {APP_VERSION} (API {API_VERSION})",
        "=" * 66,
        f"  Adresse locale   : {local_url}",
        f"  Adresse publique : {public_url or 'aucune (tunnel desactive)'}",
        f"  Code d'appairage : {code.code}   (valable {code.seconds_remaining // 60} minutes)",
        "",
        "  Saisissez ce code dans l'application Android pour appairer le telephone.",
        "=" * 66,
        "",
    ]
    # Le code d'appairage est volontairement affiche seulement ici : il est
    # enregistre comme secret, donc masque dans les fichiers de journal.
    for line in lines:
        print(line, flush=True)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_dir)
    for secret in (settings.openrouter_api_key, settings.telegram_api_hash, settings.ngrok_authtoken):
        register_secret(secret)

    logger.info("Demarrage du Bridge TradePilot %s", APP_VERSION)
    await init_database()

    # --- services de marche ---
    # La connexion au terminal se fait en tache de fond : elle peut prendre une
    # minute ou echouer, sans jamais retarder la disponibilite de l'API.
    market = _create_market_service()
    paper = PaperTradingService(price_source=None)
    await paper.initialize()
    async with session_scope() as session:
        risk_settings = await settings_repo.get_risk_settings(session)
        paper.balance = risk_settings.paper_balance
        await openrouter_service.configure(session)
        # Les moteurs compatibles OpenAI (Groq, Google AI Studio) ne sont
        # configures que par cet appel. Sans lui, ils restent invisibles du
        # routeur tant que personne n'a touche une route /ai ou fait passer un
        # signal Telegram : le Bridge n'avait alors qu'OpenRouter, sans repli,
        # et toute analyse IA echouait des que son quota etait a sec.
        # L'appel ne fait que des lectures en base, aucun acces reseau.
        await ai_service.configure(session)
        # Une bascule automatique vers le reel est impossible : au demarrage,
        # un mode reel non deverrouille retombe systematiquement en demo.
        if risk_settings.execution_mode is ExecutionMode.MT5_LIVE and not risk_settings.live_unlocked:
            risk_settings.execution_mode = ExecutionMode.MT5_DEMO
            session.add(risk_settings)
            # Le compte change : le pic d'equity du compte reel fausserait le
            # drawdown mesure sur le compte de demonstration.
            await settings_repo.reset_account_baselines(session)
            logger.warning("Mode reel non deverrouille : retour au mode demo")

    trading_engine.attach(market, paper)
    await trading_engine.start()

    # --- services optionnels, en tache de fond pour ne pas retarder l'ecoute ---
    background: list[asyncio.Task[Any]] = [
        asyncio.create_task(_start_telegram()),
        asyncio.create_task(_refresh_models_safely()),
    ]
    if market is not None:
        background.append(asyncio.create_task(_market_connection_loop(market, paper)))
        background.append(asyncio.create_task(_market_supervisor(market, paper)))

    tunnel = await ngrok_service.start()
    if tunnel.enabled and not tunnel.running:
        logger.warning("Tunnel indisponible au demarrage : nouvelle tentative dans une minute")
    background.append(asyncio.create_task(_tunnel_supervisor()))

    # Intelligence de marche autonome : scan, actualites, calendrier (CDC2).
    # Ses boucles se lancent decalees et survivent a leurs propres pannes ;
    # elles n'envoient aucun ordre, elles observent et expliquent.
    intelligence_scheduler.start()

    # AI Market Watcher (CDC3) : sous-systeme autonome, etanche du reste du
    # Bridge. Il analyse les marches et publie ses signaux dans son canal
    # Telegram. Il ne passe aucun ordre : il n'importe pas le moteur
    # d'execution. Ses boucles demarrent decalees et survivent a leurs pannes.
    watcher_scheduler.start()

    await _print_startup_banner(tunnel.public_url)
    await journal.log(
        event="bridge_started",
        message=f"Bridge demarre (version {APP_VERSION})",
        category="system",
    )
    event_bus.publish(EventType.TRADING_STATE, {"bridge": "started"})

    try:
        yield
    finally:
        logger.info("Arret du Bridge")
        await watcher_scheduler.stop()
        await intelligence_scheduler.stop()
        for task in background:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await telegram_runtime.stop_listener()
        with contextlib.suppress(Exception):
            await telegram_service.disconnect()
        await trading_engine.stop()
        await ngrok_service.stop()
        if market is not None:
            with contextlib.suppress(Exception):
                await market.shutdown()
        await journal.log(event="bridge_stopped", message="Bridge arrete", category="system")
        await dispose_engine()


async def _refresh_models_safely() -> None:
    """Selection des modeles gratuits, sans jamais bloquer le demarrage.

    Les modeles sont reellement testes (CDC section 19) : un modele gratuit
    peut disparaitre ou saturer du jour au lendemain. Sans ce test, un modele
    mort resterait selectionne indefiniment et chaque signal ambigu partirait
    en NEEDS_REVIEW sans explication.

    La tache tourne en arriere-plan : ce controle prend jusqu'a une minute et
    ne doit pas retarder le demarrage du Bridge. En mode manuel, la selection
    de l'utilisateur n'est jamais remplacee.
    """
    try:
        async with session_scope() as session:
            if openrouter_service.configured:
                state = await openrouter_service.refresh_models(session, force=True, run_tests=True)
                if state.text_model and not state.text_model_ok:
                    logger.warning(
                        "Aucun modele texte gratuit n'a repondu au test : %s",
                        state.last_error or "cause inconnue",
                    )
                elif state.text_model != state.preferred_text_model:
                    logger.info(
                        "Modele texte de repli retenu : %s (le modele prefere ne repond pas)",
                        state.text_model,
                    )
    except Exception as exc:
        logger.info("Modeles OpenRouter non rafraichis au demarrage : %s", exc)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """En-tetes de securite minimaux, utiles derriere un tunnel public."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TradePilot Bridge",
        version=APP_VERSION,
        description=(
            "Passerelle personnelle entre Telegram, l'analyse de signaux et MetaTrader 5. "
            "Toutes les routes sensibles exigent un jeton de peripherique."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Message lisible plutot qu'une trace technique (CDC section 62)."""
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "requete"
        return JSONResponse(
            status_code=422,
            content={
                "detail": f"Champ invalide : {field}",
                "technical": redact(str(first.get("msg", ""))),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Erreur non geree sur %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Une erreur interne est survenue cote Bridge.",
                "technical": redact(str(exc))[:300],
            },
        )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": "TradePilot Bridge", "version": APP_VERSION, "api": f"/api/{API_VERSION}"}

    return app


app = create_app()


def run() -> None:
    """Lancement direct : python -m app.main, ou executable PyInstaller."""
    # Le worker MetaTrader utilise multiprocessing en mode "spawn". Dans un
    # executable gele, l'enfant relance le meme .exe : sans freeze_support, il
    # redemarrerait le Bridge en boucle au lieu d'executer le worker.
    multiprocessing.freeze_support()

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_dir)
    uvicorn.run(
        # En mode gele, l'import par chaine n'est pas resolvable : on passe
        # directement l'objet application.
        app if getattr(sys, "frozen", False) else "app.main:app",
        host=settings.bridge_host,
        port=settings.bridge_port,
        log_level=settings.log_level.lower(),
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    run()
