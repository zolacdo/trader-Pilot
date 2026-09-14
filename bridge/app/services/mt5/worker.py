"""Worker mono-thread generique (PLUS UTILISE PAR LA COUCHE MT5).

AVERTISSEMENT : ce worker ne pilote plus MetaTrader 5. Une mesure faite sur
cette machine a montre que l'extension C ``MetaTrader5`` conserve le GIL
pendant toute son attente IPC : ``mt5.initialize(path=..., timeout=5000)`` a
bloque 101,9 secondes et le thread principal n'a execute aucune instruction
pendant ce temps (0 battement observe sur ~509 attendus, le parametre
``timeout`` etant ignore par l'extension). Un thread ne peut donc pas isoler
un terminal muet : tout le Bridge se figeait, API, WebSocket et Telegram
compris.

La couche MT5 passe desormais par ``app.services.mt5.process_worker``, qui
isole MetaTrader5 dans un processus enfant tuable. Ce module est conserve
comme utilitaire generique pour d'eventuelles bibliotheques bloquantes qui,
elles, relachent le GIL ; il ne doit plus servir a MetaTrader 5.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.config.logging_config import get_logger
from app.services.mt5.interface import MetaTraderError

logger = get_logger(__name__)

T = TypeVar("T")

DEFAULT_TASK_TIMEOUT = 30.0
# Duree d'attente sur la file : permet au thread de reagir vite a l'arret.
_POLL_TIMEOUT = 0.25


@dataclass(slots=True)
class _Task:
    """Une unite de travail poussee dans la file du worker."""

    func: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[Any]
    timeout: float
    label: str
    queued_at: float = field(default_factory=time.monotonic)
    abandoned: threading.Event = field(default_factory=threading.Event)


class _StopSignal:
    """Sentinelle poussee dans la file pour terminer proprement le thread."""


_STOP = _StopSignal()


def _resolve(task: _Task, result: Any, error: BaseException | None) -> None:
    """Renvoie le resultat vers la boucle asyncio d'origine, sans jamais lever."""

    def _apply() -> None:
        if task.future.done():
            return
        if error is not None:
            task.future.set_exception(error)
        else:
            task.future.set_result(result)

    try:
        task.loop.call_soon_threadsafe(_apply)
    except RuntimeError:
        # La boucle est fermee (arret de l'application) : plus personne n'attend.
        logger.debug("Resultat MT5 ignore, boucle fermee (%s)", task.label)


class Mt5Worker:
    """Serialise tous les appels au terminal MT5 dans un thread unique."""

    def __init__(self, name: str = "mt5-worker", default_timeout: float = DEFAULT_TASK_TIMEOUT) -> None:
        self._name = name
        self._default_timeout = max(0.5, float(default_timeout))
        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._busy = threading.Event()
        self._lock = threading.Lock()
        self._completed = 0
        self._failed = 0
        self._current_label: str | None = None

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Demarre le thread s'il ne tourne pas deja (idempotent)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._running.set()
            self._thread = threading.Thread(target=self._loop, name=self._name, daemon=True)
            self._thread.start()
            logger.info("Worker MT5 demarre (thread %s)", self._name)

    def stop(self, timeout: float = 5.0) -> None:
        """Arrete le thread apres avoir vide la file (best effort)."""
        with self._lock:
            thread = self._thread
            if thread is None:
                self._running.clear()
                return
            self._running.clear()
            self._thread = None
        self._queue.put(_STOP)
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.warning("Worker MT5 toujours actif apres %.1f s d'attente", timeout)
        else:
            logger.info("Worker MT5 arrete (%d taches executees)", self._completed)
        self._drain()

    def _drain(self) -> None:
        """Reveille les appelants encore en attente apres un arret."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, _Task):
                _resolve(item, None, MetaTraderError("Worker MT5 arrete avant execution de la tache"))
            self._queue.task_done()

    # ------------------------------------------------------------------
    # Etat
    # ------------------------------------------------------------------
    @property
    def alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def busy(self) -> bool:
        """Vrai lorsqu'une tache est en cours d'execution dans le thread."""
        return self._busy.is_set()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def completed(self) -> int:
        """Nombre total de taches terminees (succes ou echec)."""
        return self._completed

    @property
    def failed(self) -> int:
        return self._failed

    @property
    def current_label(self) -> str | None:
        return self._current_label

    def stats(self) -> dict[str, Any]:
        return {
            "alive": self.alive,
            "busy": self.busy,
            "pending": self.pending,
            "completed": self._completed,
            "failed": self._failed,
            "current": self._current_label,
        }

    # ------------------------------------------------------------------
    # Soumission de taches
    # ------------------------------------------------------------------
    async def run(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute ``func`` dans le thread MT5 et attend le resultat.

        Le timeout par defaut du worker s'applique. Utiliser :meth:`run_timeout`
        pour un appel dont la duree attendue est differente.
        """
        return await self.run_timeout(self._default_timeout, func, *args, **kwargs)

    async def run_timeout(
        self, timeout: float | None, func: Callable[..., T], *args: Any, **kwargs: Any
    ) -> T:
        """Variante de :meth:`run` avec un timeout explicite (``None`` = illimite)."""
        if not self.alive:
            self.start()
        if not self.alive:
            raise MetaTraderError("Worker MT5 indisponible : le thread n'a pas pu demarrer")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        effective = self._default_timeout if timeout is None else float(timeout)
        label = getattr(func, "__name__", repr(func))
        task = _Task(
            func=func,
            args=args,
            kwargs=kwargs,
            loop=loop,
            future=future,
            timeout=effective,
            label=label,
        )
        self._queue.put(task)

        try:
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout=effective)
        except TimeoutError as exc:
            task.abandoned.set()
            logger.warning("Appel MT5 '%s' expire apres %.1f s", label, effective)
            raise MetaTraderError(f"Appel MT5 '{label}' expire apres {effective:.1f} s") from exc
        except asyncio.CancelledError:
            task.abandoned.set()
            raise

    # ------------------------------------------------------------------
    # Boucle du thread
    # ------------------------------------------------------------------
    def _loop(self) -> None:
        logger.debug("Boucle worker MT5 active")
        while self._running.is_set():
            try:
                item = self._queue.get(timeout=_POLL_TIMEOUT)
            except queue.Empty:
                continue
            try:
                if isinstance(item, _StopSignal):
                    break
                if isinstance(item, _Task):
                    self._execute(item)
            finally:
                self._queue.task_done()
        logger.debug("Boucle worker MT5 terminee")

    def _execute(self, task: _Task) -> None:
        """Execute une tache. Aucune exception ne doit tuer le thread."""
        if task.abandoned.is_set() or task.future.cancelled():
            # L'appelant a abandonne (timeout ou annulation) : on ne touche pas au terminal.
            logger.debug("Tache MT5 '%s' abandonnee avant execution", task.label)
            return

        self._busy.set()
        self._current_label = task.label
        started = time.monotonic()
        result: Any = None
        error: BaseException | None = None
        try:
            result = task.func(*task.args, **task.kwargs)
        except BaseException as exc:
            error = exc if isinstance(exc, Exception) else MetaTraderError(f"Erreur fatale MT5 : {exc}")
            self._failed += 1
            logger.error("Tache MT5 '%s' en erreur : %s", task.label, exc)
        finally:
            self._completed += 1
            self._busy.clear()
            self._current_label = None

        elapsed = time.monotonic() - started
        if elapsed > 5.0:
            logger.warning("Tache MT5 '%s' lente : %.2f s", task.label, elapsed)

        if task.abandoned.is_set():
            logger.debug("Resultat de '%s' ignore : appelant parti", task.label)
            return
        _resolve(task, result, error)


__all__ = ["DEFAULT_TASK_TIMEOUT", "Mt5Worker"]
