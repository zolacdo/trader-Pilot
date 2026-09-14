"""Code execute DANS le processus enfant dedie a MetaTrader 5.

Ce module est volontairement autonome : il n'importe MetaTrader5 qu'a
l'interieur du processus enfant et ne connait rien du reste du Bridge. Le
parent (``app.services.mt5.process_worker``) ne fait qu'y puiser la fonction
d'entree :func:`child_main` et les constantes du protocole.

Regle absolue : aucune valeur renvoyee ne doit dependre de l'extension C.
Les namedtuples MetaTrader5 sont convertis en ``dict`` via ``._asdict()`` et
les tableaux numpy en listes de ``dict`` avant de traverser la frontiere de
processus. Aucun secret (mot de passe) n'est journalise ni renvoye.
"""

from __future__ import annotations

import contextlib
import multiprocessing as mp
import os
import pickle
import threading
from collections.abc import Mapping, Sequence
from typing import Any

# Commande interne demandant a l'enfant de s'arreter proprement.
STOP_COMMAND = "__stop__"

# Code d'erreur utilise quand l'appel echoue dans l'enfant (hors codes MT5).
ERROR_PACKAGE = -20003


def to_plain(value: Any) -> Any:
    """Rend une valeur MT5 picklable et independante de l'extension C."""
    if value is None or isinstance(value, bool | int | float | str | bytes):
        return value
    # Namedtuples MetaTrader5 (account_info, symbol_info, order_send, ...).
    as_dict = getattr(value, "_asdict", None)
    if callable(as_dict):
        return {str(key): to_plain(item) for key, item in as_dict().items()}
    # Tableaux numpy renvoyes par copy_rates_range / copy_ticks_range.
    dtype = getattr(value, "dtype", None)
    if dtype is not None and hasattr(value, "tolist"):
        names = getattr(dtype, "names", None)
        if names:
            return [{str(name): to_plain(row[name]) for name in names} for row in value]
        item = getattr(value, "item", None)
        if callable(item) and getattr(value, "shape", None) == ():
            return item()
        return value.tolist()
    if isinstance(value, Mapping):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [to_plain(item) for item in value]
    return value


def _last_error(api: Any) -> tuple[int, str]:
    """Dernier code d'erreur du terminal, sans jamais lever."""
    try:
        code, description = api.last_error()
        return int(code), str(description)
    except Exception:
        return (-1, "Erreur MT5 inconnue")


def _connect(
    api: Any,
    path: str | None = None,
    login: str = "",
    password: str = "",
    server: str = "",
    timeout_ms: int = 10000,
) -> dict[str, Any]:
    """Sequence initialize + login optionnel.

    Le mot de passe n'est ni journalise ni renvoye : seuls un code et une
    description remontent vers le parent.
    """
    ok = api.initialize(path=path, timeout=timeout_ms) if path else api.initialize(timeout=timeout_ms)
    if not ok:
        code, description = _last_error(api)
        return {"ok": False, "code": code, "description": description, "logged_in": False}
    if not (login and password and server):
        return {"ok": True, "code": 0, "description": "Session MT5 existante", "logged_in": False}
    try:
        account = int(login)
    except ValueError:
        return {
            "ok": False,
            "code": ERROR_PACKAGE,
            "description": "Identifiant MT5 invalide : un nombre est attendu",
            "logged_in": False,
        }
    if not api.login(login=account, password=password, server=server):
        code, description = _last_error(api)
        return {"ok": False, "code": code, "description": description, "logged_in": False}
    return {"ok": True, "code": 0, "description": "Connexion explicite reussie", "logged_in": True}


def _symbol_names(api: Any) -> list[str]:
    """Noms des symboles seuls : evite de transferer des milliers de structures."""
    raw = api.symbols_get()
    if not raw:
        return []
    return sorted({str(getattr(item, "name", "")) for item in raw if getattr(item, "name", "")})


def execute(api: Any, command: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
    """Repartit une commande vers la fonction MetaTrader5 correspondante."""
    if command == "connect":
        return _connect(api, *args, **kwargs)
    if command == "symbol_names":
        return _symbol_names(api)
    if command == "ping":
        return True
    func = getattr(api, command, None)
    if func is None or not callable(func):
        raise AttributeError(f"Commande MetaTrader5 inconnue : {command}")
    return to_plain(func(*args, **kwargs))


def _import_api() -> tuple[Any, str]:
    """Importe MetaTrader5. Retourne (module, message d'echec en francais)."""
    try:
        import MetaTrader5 as api
    except Exception as exc:  # pragma: no cover - depend de la machine
        return None, (
            "Le paquet MetaTrader5 n'est pas utilisable dans le processus dedie "
            f"({type(exc).__name__}). Installez-le avec 'pip install MetaTrader5' (Windows)."
        )
    return api, ""


def _watch_parent() -> None:
    """Sort des que le parent disparait : aucun processus MT5 orphelin.

    Indispensable sous Windows : si le Bridge est tue brutalement, son atexit
    n'est pas execute et l'enfant, bloque sur la file, survivrait. Les deux
    extremites du tube etant detenues par l'enfant, aucun EOF ne l'avertirait.
    """
    parent = mp.parent_process()
    if parent is None:  # pragma: no cover - enfant lance hors multiprocessing
        return
    parent.join()
    os._exit(0)


def _guard() -> None:
    """Ignore les signaux console et surveille la mort du parent."""
    with contextlib.suppress(Exception):
        import signal

        # L'arret est pilote par le parent (sentinelle puis terminate) : un
        # Ctrl+C ou Ctrl+Pause de la console ne doit pas couper l'enfant au
        # milieu d'un appel au terminal.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        sigbreak = getattr(signal, "SIGBREAK", None)
        if sigbreak is not None:
            signal.signal(sigbreak, signal.SIG_IGN)
    with contextlib.suppress(Exception):
        threading.Thread(target=_watch_parent, name="mt5-parent-watch", daemon=True).start()


def _answer(message: dict[str, Any], api: Any, unavailable: str) -> dict[str, Any]:
    """Construit la reponse a une requete, sans jamais lever."""
    response: dict[str, Any] = {
        "id": int(message.get("id", 0)),
        "ok": False,
        "result": None,
        "error": None,
        "code": None,
    }
    if api is None:
        response["error"] = unavailable
        response["code"] = ERROR_PACKAGE
        return response
    try:
        response["result"] = execute(
            api,
            str(message.get("command", "")),
            list(message.get("args") or []),
            dict(message.get("kwargs") or {}),
        )
        response["ok"] = True
    except Exception as exc:
        # Le message ne contient que le type d'exception et son texte : jamais
        # les arguments recus (le mot de passe ne doit pas fuir).
        response["error"] = f"{type(exc).__name__} : {exc}"
        response["code"] = ERROR_PACKAGE
    try:
        # Verification explicite : un resultat non picklable ferait echouer
        # silencieusement le thread d'alimentation de la file.
        pickle.dumps(response)
    except Exception as exc:
        return {
            "id": response["id"],
            "ok": False,
            "result": None,
            "error": f"Resultat MT5 non transferable : {type(exc).__name__}",
            "code": ERROR_PACKAGE,
        }
    return response


def child_main(requests: Any, responses: Any) -> None:
    """Boucle du processus enfant : lit une requete, repond, recommence."""
    _guard()
    api, unavailable = _import_api()
    while True:
        try:
            message = requests.get()
        except (EOFError, OSError, KeyboardInterrupt):
            break
        if not isinstance(message, dict) or message.get("command") == STOP_COMMAND:
            break
        try:
            responses.put(_answer(message, api, unavailable))
        except Exception:  # pragma: no cover - file fermee par le parent
            break
    if api is not None:
        with contextlib.suppress(Exception):
            api.shutdown()


__all__ = ["ERROR_PACKAGE", "STOP_COMMAND", "child_main", "execute", "to_plain"]
