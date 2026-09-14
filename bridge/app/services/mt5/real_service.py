"""Implementation reelle du service MetaTrader 5.

Chaque appel au terminal traverse ``Mt5ProcessWorker`` : le paquet
``MetaTrader5`` est charge et appele dans un PROCESSUS enfant dedie, jamais
dans le processus du Bridge. L'extension C garde le GIL pendant son attente
IPC (mesure : 101,9 s de gel complet sur un terminal muet), donc un simple
thread ne protege de rien. Avec un processus, un terminal qui ne repond pas
est tue et relance sans que l'API, le WebSocket ou Telegram ne bronchent.

Le mode recommande est la session deja ouverte manuellement dans MT5 Desktop
(aucun identifiant stocke). Un login explicite reste possible via le .env ;
le mot de passe ne transite que dans la file de commandes et n'est jamais
journalise, ni ici ni dans le processus enfant.
"""

from __future__ import annotations

import asyncio
import glob
import os
from datetime import UTC, datetime
from typing import Any

from app.config.logging_config import get_logger
from app.config.settings import get_settings
from app.models.enums import Direction
from app.services.mt5._mapping import (
    TIMEFRAME_CONSTANTS,
    build_order_payload,
    filling_mode,
    map_account_info,
    map_candle,
    map_deal,
    map_order,
    map_position,
    map_symbol_info,
    map_terminal_info,
    map_tick,
    read_field,
    result_from_raw,
    round_price,
    round_volume,
)
from app.services.mt5.interface import (
    RETCODE_DONE,
    RETCODE_DONE_PARTIAL,
    RETCODE_PLACED,
    AccountInfo,
    Candle,
    DealInfo,
    MetaTraderError,
    MetaTraderNotAvailable,
    MetaTraderService,
    OrderInfo,
    OrderRequest,
    PositionInfo,
    SymbolInfo,
    TerminalInfo,
    Tick,
    TradeResult,
    describe_retcode,
)
from app.services.mt5.process_worker import CONNECT_TIMEOUT, Mt5ProcessWorker

try:  # Le paquet n'existe que sur Windows avec le terminal installe.
    import MetaTrader5 as mt5

    MT5_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - depend de la machine
    # Volontairement large : dans un executable PyInstaller, l'echec peut etre
    # une ImportError comme une erreur de chargement de la DLL native. Sans la
    # cause exacte, le diagnostic serait trompeur (CDC section 62).
    mt5 = None  # type: ignore[assignment]
    MT5_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

logger = get_logger(__name__)

# Delai (millisecondes) transmis a mt5.initialize() dans le processus enfant.
# Il est en pratique ignore par l'extension : la vraie protection est le delai
# de CONNECT_TIMEOUT secondes applique cote parent, qui tue l'enfant fige.
CONNECT_TIMEOUT_MS = 10000

# Delai court pour recuperer le dernier code d'erreur du terminal.
LAST_ERROR_TIMEOUT = 5.0

_OK_RETCODES = {RETCODE_DONE, RETCODE_PLACED, RETCODE_DONE_PARTIAL}

# Emplacements habituels du terminal sous Windows.
_SEARCH_PATTERNS: tuple[str, ...] = (
    r"C:\Program Files\MetaTrader 5*\terminal64.exe",
    r"C:\Program Files\*MetaTrader*\terminal64.exe",
    r"C:\Program Files (x86)\*MetaTrader*\terminal64.exe",
)


def detect_terminals() -> list[str]:
    """Retourne les chemins de terminal64.exe trouves sur la machine."""
    found: list[str] = []
    patterns = list(_SEARCH_PATTERNS)
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = os.path.join(appdata, "MetaQuotes", "Terminal")
        patterns.append(os.path.join(base, "*", "terminal64.exe"))
        patterns.append(os.path.join(base, "*", "*", "terminal64.exe"))
    for pattern in patterns:
        for path in glob.glob(pattern):
            normalised = os.path.normpath(path)
            if os.path.isfile(normalised) and normalised not in found:
                found.append(normalised)
    return found


class RealMetaTraderService(MetaTraderService):
    """Pilote le terminal MT5 installe sur la machine, via un processus dedie."""

    name = "mt5"

    def __init__(self, worker: Mt5ProcessWorker | None = None) -> None:
        self._settings = get_settings()
        self._worker = worker or Mt5ProcessWorker(name="mt5-process")
        self._worker.set_on_restart(self._on_worker_restart)
        self._initialised = False
        self._terminal_path: str | None = None
        self._lock = asyncio.Lock()

    # --- utilitaires internes -----------------------------------------
    @staticmethod
    def _require_package() -> Any:
        """Le parent a besoin du paquet pour ses constantes (types d'ordre...)."""
        if mt5 is None:
            detail = f" Cause exacte : {MT5_IMPORT_ERROR}." if MT5_IMPORT_ERROR else ""
            raise MetaTraderNotAvailable(
                "Le paquet MetaTrader5 n'a pas pu etre charge. "
                "Installez-le avec 'pip install MetaTrader5' (Windows uniquement) "
                f"puis relancez le Bridge.{detail}"
            )
        return mt5

    def _on_worker_restart(self) -> None:
        """Un enfant relance a perdu sa session : il faudra refaire initialize()."""
        if self._initialised:
            logger.warning("Session MT5 perdue (processus relance) : reconnexion necessaire")
        self._initialised = False

    async def _last_error(self) -> tuple[int, str]:
        """Dernier code d'erreur, lu dans le processus enfant."""
        try:
            raw = await self._call("last_error", timeout=LAST_ERROR_TIMEOUT)
        except Exception:  # la lecture d'erreur ne doit jamais casser un appel
            return (-1, "Erreur MT5 inconnue")
        if isinstance(raw, list | tuple) and len(raw) >= 2:
            try:
                return int(raw[0]), str(raw[1])
            except (TypeError, ValueError):
                return (-1, "Erreur MT5 inconnue")
        return (-1, "Erreur MT5 inconnue")

    def _resolve_path(self) -> str | None:
        configured = (self._settings.mt5_terminal_path or "").strip()
        if configured:
            return configured
        candidates = detect_terminals()
        if candidates:
            logger.info("Terminal MT5 detecte automatiquement : %s", candidates[0])
            return candidates[0]
        return None

    async def _call(self, command: str, *args: Any, timeout: float | None = None, **kwargs: Any) -> Any:
        """Envoie une commande au processus MT5. Les arguments ne sont pas journalises."""
        return await self._worker.call(command, *args, timeout=timeout, **kwargs)

    # --- cycle de vie --------------------------------------------------
    async def initialize(self) -> bool:
        """Ouvre la session MT5. Rend la main en CONNECT_TIMEOUT secondes au pire."""
        self._require_package()
        async with self._lock:
            path = self._resolve_path()
            self._terminal_path = path
            login = (self._settings.mt5_login or "").strip()
            password = (self._settings.mt5_password or "").strip()
            server = (self._settings.mt5_server or "").strip()
            if login and password and server:
                # Jamais de mot de passe ni de login complet dans les journaux.
                logger.info("Connexion MT5 explicite (compte ...%s, serveur %s)", login[-3:], server)
            else:
                logger.info("Session MT5 existante utilisee (aucun identifiant stocke)")

            outcome = await self._call(
                "connect",
                timeout=CONNECT_TIMEOUT,
                path=path,
                login=login,
                password=password,
                server=server,
                timeout_ms=CONNECT_TIMEOUT_MS,
            )
            ok = bool(read_field(outcome, "ok", False))
            self._initialised = ok
            if ok:
                logger.info("Terminal MT5 initialise")
            else:
                logger.error(
                    "Echec de connexion MT5 (%s) : %s",
                    read_field(outcome, "code", -1),
                    read_field(outcome, "description", "raison inconnue"),
                )
            return ok

    async def shutdown(self) -> None:
        """Arrete le processus MT5. Ne leve jamais et ne laisse aucun orphelin."""
        self._initialised = False
        try:
            await asyncio.to_thread(self._worker.stop)
        except Exception as exc:  # l'arret ne doit jamais lever
            logger.warning("Erreur pendant l'arret MT5 : %s", exc)
        logger.info("Service MT5 arrete")

    async def reconnect(self, attempts: int = 3, base_delay: float = 1.0) -> bool:
        """Relance le processus MT5 puis rouvre la session, avec un backoff."""
        self._require_package()
        for attempt in range(1, max(1, attempts) + 1):
            # Un processus neuf garantit une session MT5 propre, meme si le
            # precedent etait fige dans un appel IPC sans fin.
            await asyncio.to_thread(self._worker.restart)
            delay = base_delay * (2 ** (attempt - 1))
            logger.info("Tentative de reconnexion MT5 %d/%d dans %.1f s", attempt, attempts, delay)
            await asyncio.sleep(delay)
            try:
                if await self.initialize():
                    logger.info("Reconnexion MT5 reussie")
                    return True
            except Exception as exc:
                logger.warning("Reconnexion MT5 en echec : %s", exc)
        logger.error("Reconnexion MT5 impossible apres %d tentatives", attempts)
        return False

    async def is_connected(self) -> bool:
        if mt5 is None or not self._initialised:
            return False
        try:
            raw = await self._call("terminal_info")
        except Exception:
            return False
        return bool(raw is not None and read_field(raw, "connected", False))

    def stats(self) -> dict[str, Any]:
        """Etat du processus MT5 (diagnostic)."""
        return self._worker.stats()

    # --- lecture -------------------------------------------------------
    async def terminal_info(self) -> TerminalInfo | None:
        self._require_package()
        raw = await self._call("terminal_info")
        if raw is None:
            return None
        info = map_terminal_info(raw)
        if info.path is None:
            info.path = self._terminal_path
        return info

    async def account_info(self) -> AccountInfo | None:
        self._require_package()
        raw = await self._call("account_info")
        return map_account_info(raw) if raw is not None else None

    async def symbols(self) -> list[str]:
        self._require_package()
        # Commande dediee : l'enfant ne renvoie que les noms, pas des milliers
        # de structures completes a serialiser.
        raw = await self._call("symbol_names")
        return list(raw) if raw else []

    async def symbol_info(self, symbol: str) -> SymbolInfo | None:
        self._require_package()
        raw = await self._call("symbol_info", symbol)
        return map_symbol_info(raw) if raw is not None else None

    async def symbol_tick(self, symbol: str) -> Tick | None:
        self._require_package()
        raw = await self._call("symbol_info_tick", symbol)
        return map_tick(symbol, raw) if raw is not None else None

    async def ensure_symbol(self, symbol: str) -> bool:
        """Rend le symbole visible dans le Market Watch (prealable a tout ordre)."""
        self._require_package()
        info = await self._call("symbol_info", symbol)
        if info is None:
            logger.warning("Symbole inconnu du broker : %s", symbol)
            return False
        if read_field(info, "visible", False):
            return True
        return bool(await self._call("symbol_select", symbol, True))

    async def positions(self, symbol: str | None = None) -> list[PositionInfo]:
        """Positions ouvertes. Leve si le terminal n'a pas pu les lire.

        MetaTrader rend ``None`` quand l'appel echoue et un tuple vide quand
        le compte n'a aucune position. Confondre les deux est dangereux : la
        reconciliation prend une liste vide pour la preuve que tout a ete
        ferme, et marque en base des positions encore ouvertes chez le
        courtier.
        """
        self._require_package()
        if symbol:
            raw = await self._call("positions_get", symbol=symbol)
        else:
            raw = await self._call("positions_get")
        if raw is None:
            raise MetaTraderError(
                "MetaTrader n'a pas pu lire les positions ouvertes. "
                "Aucune conclusion n'est tiree tant que la lecture echoue."
            )
        return [map_position(item) for item in raw]

    async def orders(self, symbol: str | None = None) -> list[OrderInfo]:
        """Ordres en attente. Leve aussi lorsque la lecture echoue."""
        self._require_package()
        if symbol:
            raw = await self._call("orders_get", symbol=symbol)
        else:
            raw = await self._call("orders_get")
        if raw is None:
            raise MetaTraderError(
                "MetaTrader n'a pas pu lire les ordres en attente."
            )
        return [map_order(item) for item in raw]

    async def history_deals(self, since: datetime, until: datetime | None = None) -> list[DealInfo]:
        self._require_package()
        end = until or datetime.now(tz=UTC)
        raw = await self._call("history_deals_get", since, end)
        return [map_deal(item) for item in raw] if raw else []

    async def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        self._require_package()
        constant = TIMEFRAME_CONSTANTS.get(timeframe.upper())
        if constant is None:
            logger.warning("Timeframe non supporte : %s", timeframe)
            return []
        tf_value = getattr(mt5, constant, None)
        if tf_value is None:  # pragma: no cover - build MT5 exotique
            return []
        raw = await self._call("copy_rates_range", symbol, int(tf_value), start, end)
        return self._map_candles(raw)

    async def recent_candles(self, symbol: str, timeframe: str, bars: int) -> list[Candle]:
        """Les ``bars`` dernieres bougies connues du terminal.

        ``copy_rates_from_pos`` lit ce que le terminal a deja ; il ne declenche
        pas le telechargement d'un historique complet, contrairement a
        ``copy_rates_range``. C'est ce qui evite qu'une unite de temps large
        fasse expirer le delai et tuer le processus MetaTrader.
        """
        self._require_package()
        constant = TIMEFRAME_CONSTANTS.get(timeframe.upper())
        if constant is None:
            logger.warning("Timeframe non supporte : %s", timeframe)
            return []
        tf_value = getattr(mt5, constant, None)
        if tf_value is None:  # pragma: no cover - build MT5 exotique
            return []
        # Le symbole doit etre dans le Market Watch, sinon le terminal ne
        # tient aucune serie pour lui et rend une liste vide sans erreur.
        await self.ensure_symbol(symbol)
        raw = await self._call(
            "copy_rates_from_pos", symbol, int(tf_value), 0, max(1, int(bars))
        )
        return self._map_candles(raw)

    @staticmethod
    def _map_candles(raw: Any) -> list[Candle]:
        if not raw:
            return []
        return [candle for candle in (map_candle(row) for row in raw) if candle is not None]

    # --- construction des requetes -------------------------------------
    async def _symbol_context(self, symbol: str) -> tuple[Any, SymbolInfo | None]:
        raw_info = await self._call("symbol_info", symbol)
        return raw_info, map_symbol_info(raw_info) if raw_info is not None else None

    async def _build_request(self, request: OrderRequest) -> tuple[dict[str, Any] | None, str]:
        """Prepare la requete MT5 : cotation, arrondis et mode de remplissage."""
        raw_info, info = await self._symbol_context(request.symbol)
        if info is None:
            return None, f"Symbole introuvable chez le broker : {request.symbol}"
        if not await self.ensure_symbol(request.symbol):
            return None, f"Symbole non selectionnable dans le Market Watch : {request.symbol}"

        if request.is_pending:
            if request.price is None:
                return None, "Un ordre en attente exige un prix d'entree"
            price = float(request.price)
        else:
            raw_tick = await self._call("symbol_info_tick", request.symbol)
            if raw_tick is None:
                return None, f"Aucune cotation disponible pour {request.symbol}"
            tick = map_tick(request.symbol, raw_tick)
            price = tick.ask if request.direction is Direction.BUY else tick.bid
        return build_order_payload(mt5, request, raw_info, info, price)

    async def _send(self, payload: dict[str, Any]) -> TradeResult:
        # Arguments NOMMES obligatoires : passee positionnellement, la requete
        # fait rendre None au paquet avec « Unnamed arguments not allowed ».
        raw = await self._call("order_send", **payload)
        if raw is None:
            code, description = await self._last_error()
            message = f"Aucune reponse du terminal MT5 : {description}"
            logger.warning("Ordre MT5 sans reponse (%s) : %s", code, description)
            return TradeResult(ok=False, retcode=code, message=message, request=payload)
        result = result_from_raw(raw, payload, _OK_RETCODES)
        if not result.ok:
            logger.warning("Ordre MT5 refuse (%s) : %s", result.retcode, result.message)
        return result

    # --- ecriture ------------------------------------------------------
    async def order_check(self, request: OrderRequest) -> TradeResult:
        self._require_package()
        payload, error = await self._build_request(request)
        if payload is None:
            return TradeResult.failure(error)
        # Arguments nommes, pour la meme raison que dans _send.
        raw = await self._call("order_check", **payload)
        if raw is None:
            code, description = await self._last_error()
            return TradeResult(ok=False, retcode=code, message=f"order_check indisponible : {description}")
        retcode = int(read_field(raw, "retcode", 0) or 0)
        ok = retcode == 0 or retcode in _OK_RETCODES
        message = "Requete valide" if ok else describe_retcode(retcode)
        return TradeResult(ok=ok, retcode=retcode, message=message, request=payload)

    async def order_send(self, request: OrderRequest) -> TradeResult:
        self._require_package()
        payload, error = await self._build_request(request)
        if payload is None:
            return TradeResult.failure(error)
        return await self._send(payload)

    async def modify_position(
        self, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult:
        self._require_package()
        raw_positions = await self._call("positions_get", ticket=ticket)
        if not raw_positions:
            return TradeResult.failure(f"Position {ticket} introuvable")
        position = map_position(raw_positions[0])
        _, info = await self._symbol_context(position.symbol)
        digits = info.digits if info else 5
        payload = {
            "action": int(mt5.TRADE_ACTION_SLTP),
            "position": int(ticket),
            "symbol": position.symbol,
            "sl": round_price(stop_loss, digits) or 0.0,
            "tp": round_price(take_profit, digits) or 0.0,
        }
        return await self._send(payload)

    async def close_position(
        self, ticket: int, volume: float | None = None, deviation: int = 20
    ) -> TradeResult:
        """Ferme tout ou partie d'une position par un ordre inverse cible."""
        self._require_package()
        raw_positions = await self._call("positions_get", ticket=ticket)
        if not raw_positions:
            return TradeResult.failure(f"Position {ticket} introuvable")
        position = map_position(raw_positions[0])
        raw_info, info = await self._symbol_context(position.symbol)
        if info is None:
            return TradeResult.failure(f"Symbole introuvable : {position.symbol}")

        target = position.volume if volume is None else min(float(volume), position.volume)
        target = round_volume(target, info.volume_step, info.volume_min, position.volume)
        if target <= 0:
            return TradeResult.failure("Volume de fermeture invalide")

        raw_tick = await self._call("symbol_info_tick", position.symbol)
        if raw_tick is None:
            return TradeResult.failure(f"Aucune cotation disponible pour {position.symbol}")
        tick = map_tick(position.symbol, raw_tick)
        is_buy = position.direction is Direction.BUY
        close_type = getattr(mt5, "ORDER_TYPE_SELL" if is_buy else "ORDER_TYPE_BUY")
        payload = {
            "action": int(mt5.TRADE_ACTION_DEAL),
            "symbol": position.symbol,
            "volume": target,
            "type": int(close_type),
            "position": int(ticket),
            "price": round_price(tick.bid if is_buy else tick.ask, info.digits),
            "deviation": int(deviation),
            "magic": position.magic,
            "comment": "TradePilot close",
            "type_time": int(getattr(mt5, "ORDER_TIME_GTC", 0)),
            "type_filling": filling_mode(mt5, raw_info, False),
        }
        return await self._send(payload)

    async def cancel_order(self, ticket: int) -> TradeResult:
        self._require_package()
        payload = {"action": int(mt5.TRADE_ACTION_REMOVE), "order": int(ticket)}
        return await self._send(payload)

    async def modify_order(
        self, ticket: int, price: float | None, stop_loss: float | None, take_profit: float | None
    ) -> TradeResult:
        self._require_package()
        raw_orders = await self._call("orders_get", ticket=ticket)
        if not raw_orders:
            return TradeResult.failure(f"Ordre en attente {ticket} introuvable")
        order = map_order(raw_orders[0])
        _, info = await self._symbol_context(order.symbol)
        digits = info.digits if info else 5
        new_price = price if price is not None else order.price_open
        new_sl = stop_loss if stop_loss is not None else order.stop_loss
        new_tp = take_profit if take_profit is not None else order.take_profit
        payload = {
            "action": int(mt5.TRADE_ACTION_MODIFY),
            "order": int(ticket),
            "price": round_price(new_price, digits),
            "sl": round_price(new_sl, digits) or 0.0,
            "tp": round_price(new_tp, digits) or 0.0,
            "type_time": int(getattr(mt5, "ORDER_TIME_GTC", 0)),
        }
        return await self._send(payload)

    # --- calculs broker -------------------------------------------------
    async def calculate_margin(
        self, symbol: str, direction: Direction, volume: float, price: float
    ) -> float | None:
        self._require_package()
        order_type = getattr(mt5, "ORDER_TYPE_BUY" if direction is Direction.BUY else "ORDER_TYPE_SELL")
        raw = await self._call("order_calc_margin", int(order_type), symbol, float(volume), float(price))
        return float(raw) if raw is not None else None

    async def calculate_profit(
        self, symbol: str, direction: Direction, volume: float, price_open: float, price_close: float
    ) -> float | None:
        self._require_package()
        order_type = getattr(mt5, "ORDER_TYPE_BUY" if direction is Direction.BUY else "ORDER_TYPE_SELL")
        raw = await self._call(
            "order_calc_profit",
            int(order_type),
            symbol,
            float(volume),
            float(price_open),
            float(price_close),
        )
        return float(raw) if raw is not None else None


__all__ = ["RealMetaTraderService", "detect_terminals"]
