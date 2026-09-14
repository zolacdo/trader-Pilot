"""Rattachement d'un processus enfant a un Job Object Windows.

Utilise par les deux services qui lancent un programme externe : la couche
MetaTrader 5 (processus Python isole) et le tunnel ngrok.

Pourquoi : un enfant peut cesser de repondre a toute logique Python. C'est le
cas du processus MT5 bloque dans ``mt5.initialize()``, ou l'extension C garde
le GIL et empeche tout fil de surveillance de s'executer. Un Bridge tue
brutalement (Stop-Process, plantage, fin de session Windows) laisserait alors
un orphelin derriere lui.

Un Job Object avec ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` regle cela dans le
noyau : quand le parent meurt, ses handles se ferment, le job se ferme, et
Windows termine l'enfant sans avoir besoin du moindre octet de Python.

Sur toute plateforme autre que Windows, les fonctions ne font rien.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

from app.config.logging_config import get_logger

logger = get_logger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# Le job tue ses membres des que son dernier handle est ferme.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
# JobObjectExtendedLimitInformation
_JOB_EXTENDED_LIMIT_CLASS = 9


class _BasicLimits(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    )


class _IoCounters(ctypes.Structure):
    _fields_ = tuple(
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    )


class _ExtendedLimits(ctypes.Structure):
    _fields_ = (
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


def _kernel32() -> Any:
    """Charge kernel32 avec des signatures explicites (handles 64 bits)."""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    api.CloseHandle.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.OpenProcess.restype = wintypes.HANDLE
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    return api


def _process_handle(api: Any, process: Any) -> tuple[int | None, bool]:
    """Handle natif du processus enfant, quel que soit son type.

    ``multiprocessing.Process`` expose ``sentinel``, ``subprocess.Popen``
    expose ``_handle``. Sans l'un ni l'autre, on ouvre un handle a partir du
    PID. Le booleen indique s'il faut refermer ce handle apres usage.
    """
    handle = getattr(process, "sentinel", None) or getattr(process, "_handle", None)
    if handle:
        return int(handle), False

    pid = getattr(process, "pid", None)
    if not pid:
        return None, False
    opened = api.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid))
    if not opened:
        return None, False
    return int(opened), True


def attach_child(process: Any) -> int | None:
    """Place ``process`` dans un job tue avec le parent. Retourne le handle du job.

    Retourne ``None`` si la plateforme n'est pas Windows ou si l'API refuse :
    la surveillance Python reste alors le seul filet, ce qui est acceptable
    (le cas nominal, l'arret propre, ne depend pas de ce mecanisme).
    """
    if not _IS_WINDOWS:
        return None
    try:
        api = _kernel32()
        handle, must_close = _process_handle(api, process)
        if handle is None:
            logger.warning("Processus enfant sans handle exploitable : job Windows ignore")
            return None
        job = api.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObject a echoue")
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(
            job, _JOB_EXTENDED_LIMIT_CLASS, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            api.CloseHandle(job)
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject a echoue")
        assigned = api.AssignProcessToJobObject(job, wintypes.HANDLE(handle))
        if must_close:
            api.CloseHandle(wintypes.HANDLE(handle))
        if not assigned:
            api.CloseHandle(job)
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject a echoue")
        return int(job)
    except Exception as exc:  # pragma: no cover - depend de la politique Windows
        logger.warning("Processus enfant non rattache a un job Windows : %s", exc)
        return None


def close_job(job: int | None) -> None:
    """Ferme le job : les membres encore vivants sont termines par le noyau."""
    if not _IS_WINDOWS or not job:
        return
    try:
        _kernel32().CloseHandle(wintypes.HANDLE(int(job)))
    except Exception as exc:  # pragma: no cover - handle deja invalide
        logger.debug("Fermeture du job ignoree : %s", exc)


__all__ = ["attach_child", "close_job"]
