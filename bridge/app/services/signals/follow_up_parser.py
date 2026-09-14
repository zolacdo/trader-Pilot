"""Analyse des messages de suivi rattaches a un signal deja envoye.

Exemples couverts (CDC section 18) : ``TP1 HIT``, ``CLOSE GOLD``,
``CLOSE 50%``, ``MOVE SL TO BE``, ``SL BE``, ``MOVE SL 3350``,
``CANCEL GOLD``, ``DELETE PENDING``, ``RUNNING +50 PIPS``, ``HOLD``.
"""

from __future__ import annotations

import re

from app.models.enums import FollowUpAction
from app.services.signals.models import FollowUp
from app.services.signals.normalizer import normalize_upper
from app.services.signals.symbols import extract_symbol

NUMBER = r"\d+(?:\.\d+)?"

_TP_HIT = re.compile(r"\bTP\s?(\d{1,2})?\b[^\n]{0,20}?\b(HIT|REACHED|DONE|SECURED|TOUCHED|ACHIEVED)\b")
_TP_HIT_REVERSE = re.compile(r"\b(HIT|REACHED|SECURED|SMASHED)\b[^\n]{0,12}?\bTP\s?(\d{1,2})?\b")
_TARGET_HIT = re.compile(r"\b(?:TARGET|OBJECTIF)\s?(\d{1,2})?\b[^\n]{0,20}?\b(HIT|REACHED|DONE)\b")
_SL_HIT = re.compile(r"\b(?:SL|STOP\s?LOSS)\b[^\n]{0,20}?\b(HIT|TAKEN|REACHED)\b")

_BREAK_EVEN = re.compile(
    r"\b(?:BREAK\s?EVEN|BREAKEVEN|MOVE\s+(?:SL|STOP)\s+TO\s+BE|SL\s+TO\s+BE"
    r"|SL\s+BE|BE\s+NOW|SECURE\s+ENTRY|RISK\s?FREE)\b"
)
_MOVE_SL = re.compile(
    rf"\b(?:MOVE|SHIFT|CHANGE|ADJUST|TRAIL|MODIFY)\s+(?:THE\s+)?"
    rf"(?:SL|STOP\s?LOSS)\s+(?:TO\s+)?({NUMBER})"
)
_SET_SL = re.compile(rf"\b(?:NEW\s+)?(?:SL|STOP\s?LOSS)\s+(?:NOW\s+|TO\s+)({NUMBER})")
_MOVE_TP = re.compile(rf"\b(?:MOVE|CHANGE|MODIFY|NEW)\s+(?:THE\s+)?TP\s?(\d{{1,2}})?\s+(?:TO\s+)?({NUMBER})")

_PARTIAL_VERB = r"(?:CLOSE|BOOK|TAKE|SECURE|BANK)"
_CLOSE_PARTIAL_PERCENT = re.compile(rf"\b{_PARTIAL_VERB}\b[^\n]{{0,16}}?(\d{{1,3}})\s?%")
_CLOSE_PERCENT_FIRST = re.compile(rf"(\d{{1,3}})\s?%[^\n]{{0,16}}?\b{_PARTIAL_VERB}\b")
_CLOSE_HALF = re.compile(
    r"\b(?:CLOSE|TAKE)\s+(?:HALF|50)\b|\bHALF\s+CLOSE\b"
    r"|\bCLOSE\s+PARTIAL\b|\bPARTIAL\s+CLOSE\b"
)
_CLOSE_ALL = re.compile(
    r"\b(?:CLOSE|EXIT|BOOK|SECURE)\b(?:\s+(?:ALL|THE|YOUR|EVERY))?\s*"
    r"(?:TRADE|TRADES|POSITION|POSITIONS|ORDER|ORDERS|NOW|EVERYTHING|IT)?\b"
)
_CANCEL = re.compile(
    r"\b(?:CANCEL|DELETE|REMOVE)\b[^\n]{0,24}?"
    r"\b(?:PENDING|ORDER|ORDERS|LIMIT|STOP|TRADE|SETUP)?\b"
)

_INFO_ONLY = re.compile(
    r"\b(?:RUNNING|HOLD|HOLDING|IN\s+PROFIT|PIPS?\s+IN\s+PROFIT"
    r"|LET\s+IT\s+RUN|STILL\s+VALID)\b"
)

# Un message de suivi ne doit jamais contenir une nouvelle intention d'entree.
_NEW_TRADE_HINT = re.compile(r"\b(?:BUY|SELL|LONG|SHORT)\b")


def parse_follow_up(text: str, extra_aliases: dict[str, str] | None = None) -> FollowUp | None:
    """Retourne un ``FollowUp`` ou ``None`` si le message n'en est pas un."""
    if not text or not text.strip():
        return None
    normalized = normalize_upper(text)
    if not normalized:
        return None

    _, symbol = extract_symbol(normalized, extra_aliases)

    # Un meme message combine souvent "TP1 HIT" et "MOVE SL TO BE".
    break_even_requested = bool(_BREAK_EVEN.search(normalized))

    # --- TP atteint ---
    match = _TP_HIT.search(normalized) or _TARGET_HIT.search(normalized)
    if match:
        index = match.group(1)
        return FollowUp(
            action=FollowUpAction.TP_HIT,
            symbol=symbol,
            tp_index=int(index) if index else 1,
            confidence=0.95,
            raw_hint=match.group(0).strip(),
            also_break_even=break_even_requested,
        )
    match = _TP_HIT_REVERSE.search(normalized)
    if match:
        index = match.group(2)
        return FollowUp(
            action=FollowUpAction.TP_HIT,
            symbol=symbol,
            tp_index=int(index) if index else 1,
            confidence=0.9,
            raw_hint=match.group(0).strip(),
            also_break_even=break_even_requested,
        )

    # --- SL touche ---
    match = _SL_HIT.search(normalized)
    if match:
        return FollowUp(
            action=FollowUpAction.SL_HIT, symbol=symbol, confidence=0.9, raw_hint=match.group(0).strip()
        )

    # --- deplacement de SL vers un prix explicite ---
    match = _MOVE_SL.search(normalized) or _SET_SL.search(normalized)
    if match:
        return FollowUp(
            action=FollowUpAction.MOVE_SL,
            symbol=symbol,
            price=float(match.group(1)),
            confidence=0.9,
            raw_hint=match.group(0).strip(),
        )

    # --- break even ---
    match = _BREAK_EVEN.search(normalized)
    if match:
        return FollowUp(
            action=FollowUpAction.MOVE_SL_BE,
            symbol=symbol,
            confidence=0.95,
            raw_hint=match.group(0).strip(),
        )

    # --- deplacement de TP ---
    match = _MOVE_TP.search(normalized)
    if match:
        index = match.group(1)
        return FollowUp(
            action=FollowUpAction.MOVE_TP,
            symbol=symbol,
            tp_index=int(index) if index else None,
            price=float(match.group(2)),
            confidence=0.85,
            raw_hint=match.group(0).strip(),
        )

    # --- fermeture partielle ---
    match = _CLOSE_PARTIAL_PERCENT.search(normalized) or _CLOSE_PERCENT_FIRST.search(normalized)
    if match:
        percentage = float(match.group(1))
        if 0 < percentage < 100:
            return FollowUp(
                action=FollowUpAction.CLOSE_PARTIAL,
                symbol=symbol,
                percentage=percentage,
                confidence=0.9,
                raw_hint=match.group(0).strip(),
            )
        if percentage >= 100:
            return FollowUp(
                action=FollowUpAction.CLOSE_ALL,
                symbol=symbol,
                confidence=0.9,
                raw_hint=match.group(0).strip(),
            )
    if _CLOSE_HALF.search(normalized):
        return FollowUp(
            action=FollowUpAction.CLOSE_PARTIAL, symbol=symbol, percentage=50.0, confidence=0.9,
            raw_hint="CLOSE HALF",
        )

    # --- annulation d'ordre en attente ---
    if _CANCEL.search(normalized) and not _NEW_TRADE_HINT.search(normalized):
        return FollowUp(
            action=FollowUpAction.CANCEL_PENDING, symbol=symbol, confidence=0.85, raw_hint="CANCEL"
        )

    # --- fermeture totale ---
    match = _CLOSE_ALL.search(normalized)
    if match and not _NEW_TRADE_HINT.search(normalized):
        return FollowUp(
            action=FollowUpAction.CLOSE_ALL, symbol=symbol, confidence=0.85, raw_hint=match.group(0).strip()
        )

    # --- information sans action ---
    if _INFO_ONLY.search(normalized):
        return FollowUp(action=FollowUpAction.INFO, symbol=symbol, confidence=0.6, raw_hint="INFO")

    return None
