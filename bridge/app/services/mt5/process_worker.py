"""Isolation du paquet MetaTrader5 dans un processus dedie (cote parent).

Pourquoi un processus et non un thread : l'extension C ``MetaTrader5``
conserve le GIL pendant toute son attente IPC avec le terminal. La mesure
faite sur cette machine est sans appel : ``mt5.initialize(path=..., timeout=5000)``
a bloque 101,9 secondes (le parametre ``timeout`` est ignore) et le thread
principal n'a execute aucune instruction pendant ce temps (0 battement observe
sur ~509 attendus). Un worker thread ne protege donc de rien : un terminal
muet gelait tout le Bridge, API, WebSocket et Telegram compris.

Ici, MetaTrader5 n'est importe et appele que dans un processus enfant
``spawn`` (voir :mod:`app.services.mt5._child_process`). Le parent dialogue
par deux files ``multiprocessing.Queue`` et n'attend jamais dans la boucle
asyncio : l'attente se fait dans un thread via ``asyncio.to_thread``. Si
l'enfant ne repond pas dans le delai imparti, il est tue et l'appel leve une
erreur claire ; un enfant neuf est cree au prochain appel. Le Bridge reste
vivant en toutes circonstances.

Protocole (tout doit etre picklable) :

* requete : ``{"id": int, "command": str, "args": list, "kwargs": dict}``
* reponse : ``{"id": int, "ok": bool, "result": Any, "error": str | None,
  "code": int | None}``
"""

from __future__ import annotations

import asyncio
import contextlib
import multiprocessing as mp
import queue
import sys
import time
import types
from collections.abc import Callable, Iterator
from typing import Any

from app.config.logging_config import get_logger
from app.services.mt5._child_process import STOP_COMMAND, child_main
from app.services.mt5.interface import MetaTraderError
from app.services.win_job import attach_child, close_job

logger = get_logger(__name__)

# Delai par defaut d'un appel courant (lecture de compte, cotation, ordre).
DEFAULT_CALL_TIMEOUT = 30.0
# Delai de la sequence de connexion : volontairement court, l'appelant doit
# reprendre la main vite quand le terminal ne repond pas.
CONNECT_TIMEOUT = 15.0

# Codes d'erreur propres a la couche processus (hors plage des codes MT5).
ERROR_NO_RESPONSE = -20001
ERROR_NO_PROCESS = -20002

# Granularite d'attente sur la file de reponses : permet de reagir vite a la
# mort de l'enfant ou a l'arret du parent sans consommer de CPU.
_POLL = 0.25
# Temps laisse a l'enfant pour mourir a chaque etape de l'arret.
_JOIN_TIMEOUT = 2.0


@contextlib.contextmanager
def _neutral_main() -> Iterator[None]:
    """Neutralise le module ``__main__`` le temps du demarrage de l'enfant.

    ``spawn`` reimporte le module principal du parent dans l'enfant. Selon le
    point d'entree (``python -m app.main``, uvicorn, pytest, un script de
    mesure), cela rejouerait tout le demarrage du Bridge, voire la suite de
    tests, dans le processus MT5. Un module principal sans ``__spec__`` ni
    ``__file__`` fait que ``multiprocessing`` laisse ``__main__`` tranquille :
    l'enfant n'importe alors que le module du worker et MetaTrader5.
    """
    real = sys.modules.get("__main__")
    shim = types.ModuleType("__main__")
    shim.__spec__ = None
    sys.modules["__main__"] = shim
    try:
        yield
    finally:
        if real is not None:
            sys.modules["__main__"] = real
        else:  # pragma: no cover - situation theorique
            sys.modules.pop("__main__", None)


class Mt5ProcessWorker:
    """Pilote un processus enfant dedie aux appels MetaTrader 5."""

    def __init__(self, name: str = "mt5-process", default_timeout: float = DEFAULT_CALL_TIMEOUT) -> None:
        self._name = name
        self._default_timeout = max(1.0, float(default_timeout))
        self._ctx = mp.get_context("spawn")
        self._process: Any = None
        self._job: int | None = None
        self._requests: Any = None
        self._responses: Any = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self._generation = 0
        self._restarts = 0
        self._completed = 0
        self._failed = 0
        self._stopping = False
        self._on_restart: Callable[[], None] | None = None

    # --- etat -----------------------------------------------------------
    @property
    def alive(self) -> bool:
        process = self._process
        return bool(process is not None and process.is_alive())

    @property
    def generation(self) -> int:
        """Numero de session : change a chaque demarrage d'un enfant."""
        return self._generation

    @property
    def pid(self) -> int | None:
        process = self._process
        return int(process.pid) if process is not None and process.pid else None

    def stats(self) -> dict[str, Any]:
        return {
            "alive": self.alive,
            "pid": self.pid,
            "generation": self._generation,
            "restarts": self._restarts,
            "completed": self._completed,
            "failed": self._failed,
        }

    def set_on_restart(self, callback: Callable[[], None] | None) -> None:
        """Callback appele apres un recyclage force (la session MT5 est perdue)."""
        self._on_restart = callback

    # --- cycle de vie ---------------------------------------------------
    def start(self) -> None:
        """Demarre le processus enfant s'il ne tourne pas deja (idempotent)."""
        if self.alive:
            return
        self._halt(graceful=False)
        self._stopping = False
        self._requests = self._ctx.Queue()
        self._responses = self._ctx.Queue()
        with _neutral_main():
            process = self._ctx.Process(
                target=child_main,
                args=(self._requests, self._responses),
                name=self._name,
                daemon=True,
            )
            process.start()
        self._process = process
        # Filet de securite noyau : si le Bridge est tue brutalement, Windows
        # termine l'enfant meme s'il est fige dans un appel MetaTrader5.
        self._job = attach_child(process)
        self._generation += 1
        logger.info("Processus MT5 demarre (pid %s, session %d)", process.pid, self._generation)

    def stop(self) -> None:
        """Arrete l'enfant et laisse la table des processus propre."""
        self._stopping = True
        had_process = self._process is not None
        self._halt(graceful=True)
        if had_process:
            logger.info("Processus MT5 arrete (%d appels traites)", self._completed)

    def restart(self) -> None:
        """Tue l'enfant puis en relance un neuf (session MT5 remise a zero)."""
        self.recycle()
        self.start()

    def recycle(self) -> None:
        """Tue l'enfant sans en relancer un : le prochain appel en creera un.

        Rendre la main tout de suite compte : l'appelant vient d'attendre son
        delai complet. L'arret est donc brutal (l'enfant est fige, il ne lirait
        jamais la sentinelle) et le nouvel enfant est cree paresseusement, ce
        qui evite de garder un processus MT5 inutile quand le terminal est muet.
        """
        self._halt(graceful=False)
        self._restarts += 1
        callback = self._on_restart
        if callback is not None:
            with contextlib.suppress(Exception):
                callback()

    def _halt(self, graceful: bool) -> None:
        """Termine l'enfant courant et libere les files. Ne leve jamais."""
        process, requests, responses = self._process, self._requests, self._responses
        job = self._job
        self._process = None
        self._job = None
        self._requests = None
        self._responses = None
        if process is None:
            close_job(job)
            self._close_queues(requests, responses)
            return
        if graceful and requests is not None and process.is_alive():
            with contextlib.suppress(Exception):
                requests.put({"id": 0, "command": STOP_COMMAND, "args": [], "kwargs": {}})
            process.join(timeout=_JOIN_TIMEOUT)
        for finish in (process.terminate, process.kill):
            if not process.is_alive():
                break
            with contextlib.suppress(Exception):
                finish()
            process.join(timeout=_JOIN_TIMEOUT)
        if process.is_alive():  # pragma: no cover - impossible sous Windows
            logger.error("Processus MT5 %s toujours vivant apres kill()", process.pid)
        self._close_queues(requests, responses)
        with contextlib.suppress(Exception):
            process.close()
        close_job(job)

    @staticmethod
    def _close_queues(*queues: Any) -> None:
        for item in queues:
            if item is None:
                continue
            # cancel_join_thread : l'enfant est mort, personne ne lira le reste.
            with contextlib.suppress(Exception):
                item.cancel_join_thread()
            with contextlib.suppress(Exception):
                item.close()

    # --- appels ---------------------------------------------------------
    async def call(self, command: str, *args: Any, timeout: float | None = None, **kwargs: Any) -> Any:
        """Execute une commande dans l'enfant et attend sa reponse.

        L'attente n'occupe jamais la boucle asyncio. En cas de depassement du
        delai, l'enfant est tue puis une ``MetaTraderError`` est levee. Les
        arguments ne sont jamais journalises (mot de passe).
        """
        budget = self._default_timeout if timeout is None else max(0.5, float(timeout))
        async with self._lock:
            message = await self._exchange(command, list(args), kwargs, budget)
        self._completed += 1
        if not message.get("ok"):
            raise MetaTraderError(
                str(message.get("error") or "Erreur MetaTrader 5 inconnue"),
                code=message.get("code"),
            )
        return message.get("result")

    async def _exchange(
        self, command: str, args: list[Any], kwargs: dict[str, Any], budget: float
    ) -> dict[str, Any]:
        """Envoie une requete et attend sa reponse. Le verrou est deja tenu."""
        if not self.alive:
            if self._stopping:
                raise MetaTraderError("Processus MT5 arrete", code=ERROR_NO_PROCESS)
            await asyncio.to_thread(self.start)
        requests, responses, process = self._requests, self._responses, self._process
        if requests is None or responses is None or process is None:
            raise MetaTraderError("Processus MT5 indisponible", code=ERROR_NO_PROCESS)

        self._next_id += 1
        request_id = self._next_id
        try:
            requests.put({"id": request_id, "command": command, "args": args, "kwargs": kwargs})
        except Exception as exc:
            self._failed += 1
            raise MetaTraderError(
                f"Impossible d'envoyer la commande MT5 '{command}' : {type(exc).__name__}",
                code=ERROR_NO_PROCESS,
            ) from exc

        started = time.monotonic()
        message = await asyncio.to_thread(self._wait_response, responses, process, request_id, budget)
        if message is not None:
            return message

        self._failed += 1
        elapsed = time.monotonic() - started
        died = not process.is_alive()
        logger.warning(
            "Commande MT5 '%s' sans reponse apres %.1f s (%s)",
            command,
            elapsed,
            "processus arrete" if died else "delai depasse, processus tue",
        )
        await asyncio.to_thread(self.recycle)
        if died:
            raise MetaTraderError(
                f"Le processus MT5 s'est arrete pendant '{command}' (apres {elapsed:.1f} s). "
                "Un processus neuf sera cree au prochain appel ; le Bridge reste operationnel.",
                code=ERROR_NO_RESPONSE,
            )
        raise MetaTraderError(
            f"Le terminal MT5 n'a pas repondu a '{command}' en {budget:.0f} s. "
            "Le processus MT5 a ete tue ; le Bridge reste operationnel.",
            code=ERROR_NO_RESPONSE,
        )

    def _wait_response(
        self, responses: Any, process: Any, request_id: int, budget: float
    ) -> dict[str, Any] | None:
        """Attend la reponse dans un thread. ``None`` = delai depasse ou enfant mort."""
        deadline = time.monotonic() + budget
        while not self._stopping and time.monotonic() < deadline:
            try:
                message = responses.get(timeout=_POLL)
            except queue.Empty:
                if not process.is_alive():
                    logger.warning("Processus MT5 termine avant d'avoir repondu")
                    return None
                continue
            except (OSError, EOFError, ValueError):  # pragma: no cover - file fermee
                return None
            if isinstance(message, dict) and int(message.get("id", -1)) == request_id:
                return message
            # Reponse d'un appel abandonne (annulation) : on la jette.
            logger.debug("Reponse MT5 obsolete ignoree (id %s)", message.get("id") if message else None)
        return None


__all__ = [
    "CONNECT_TIMEOUT",
    "DEFAULT_CALL_TIMEOUT",
    "Mt5ProcessWorker",
]
