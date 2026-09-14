"""Extraction de signal assistee par IA.

L'IA sert uniquement a LIRE un texte ambigu. Elle ne juge jamais la rentabilite
d'un trade et n'a jamais le dernier mot : sa sortie est retypee puis revalidee
localement avant toute suite (CDC sections 21 et 49).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.config.logging_config import get_logger
from app.models.enums import Direction, OrderType, ParserSource
from app.services.ai.base import MIN_JSON_MAX_TOKENS
from app.services.openrouter.client import (
    OpenRouterClient,
    OpenRouterError,
    extract_message,
    extract_text,
)
from app.services.signals.models import ParsedSignal
from app.services.signals.symbols import canonical_symbol

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "You extract trading signal fields from a Telegram message. "
    "Extract only information explicitly present or strongly unambiguous in the message. "
    "Never invent prices, stop losses, targets, symbols or directions. "
    "Unknown values must be null. "
    "If the message is commentary, greetings, results, promotion or market opinion without an explicit "
    "order instruction, set is_signal to false. "
    "Answer only with the structured data, no explanation."
)

TOOL_NAME = "parse_trading_signal"

TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Return the trading instruction contained in the message, or is_signal=false.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "is_signal": {
                    "type": "boolean",
                    "description": "True only if the message explicitly instructs to open a trade.",
                },
                "symbol": {
                    "type": ["string", "null"],
                    "description": (
                        "Instrument exactly as written in the message, e.g. GOLD, XAUUSD, EURUSD."
                    ),
                },
                "direction": {"type": ["string", "null"], "enum": ["BUY", "SELL", None]},
                "order_type": {
                    "type": ["string", "null"],
                    "enum": ["MARKET", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", None],
                },
                "entry_price": {"type": ["number", "null"]},
                "entry_min": {"type": ["number", "null"], "description": "Lower bound of an entry zone."},
                "entry_max": {"type": ["number", "null"], "description": "Upper bound of an entry zone."},
                "stop_loss": {"type": ["number", "null"]},
                "take_profits": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["is_signal"],
        },
    },
}

# Reponse JSON attendue lorsque le modele ne supporte pas le tool calling.
JSON_INSTRUCTION = (
    "Return a single JSON object with exactly these keys: "
    '{"is_signal": bool, "symbol": string|null, "direction": "BUY"|"SELL"|null, '
    '"order_type": "MARKET"|"BUY_LIMIT"|"SELL_LIMIT"|"BUY_STOP"|"SELL_STOP"|null, '
    '"entry_price": number|null, "entry_min": number|null, "entry_max": number|null, '
    '"stop_loss": number|null, "take_profits": [number]}. '
    "No markdown, no commentary."
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class AiParseError(OpenRouterError):
    """La reponse du modele est inexploitable."""


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _coerce_direction(value: Any) -> Direction | None:
    if not isinstance(value, str):
        return None
    upper = value.strip().upper()
    if upper in {"BUY", "LONG"}:
        return Direction.BUY
    if upper in {"SELL", "SHORT"}:
        return Direction.SELL
    return None


def _coerce_order_type(value: Any, direction: Direction | None) -> OrderType | None:
    if not isinstance(value, str):
        return None
    upper = value.strip().upper().replace(" ", "_")
    try:
        order_type = OrderType(upper)
    except ValueError:
        return None
    if order_type is OrderType.MARKET:
        return order_type
    expected = Direction.BUY if order_type.value.startswith("BUY") else Direction.SELL
    if direction is not None and expected is not direction:
        return None  # incoherence : on refuse plutot que de corriger
    return order_type


def payload_to_signal(payload: dict[str, Any], model: str) -> ParsedSignal:
    """Retype la sortie du modele. Toute valeur douteuse devient None."""
    signal = ParsedSignal(source=ParserSource.AI, ai_model=model)

    if not bool(payload.get("is_signal")):
        signal.add_warning("ia_aucune_intention_de_trade")
        return signal

    raw_symbol = payload.get("symbol")
    signal.symbol_raw = str(raw_symbol) if raw_symbol else None
    signal.symbol = canonical_symbol(signal.symbol_raw) if signal.symbol_raw else None

    signal.direction = _coerce_direction(payload.get("direction"))
    signal.order_type = _coerce_order_type(payload.get("order_type"), signal.direction)

    signal.entry_price = _coerce_float(payload.get("entry_price"))
    signal.entry_min = _coerce_float(payload.get("entry_min"))
    signal.entry_max = _coerce_float(payload.get("entry_max"))
    signal.stop_loss = _coerce_float(payload.get("stop_loss"))

    raw_targets = payload.get("take_profits") or []
    targets: list[float] = []
    if isinstance(raw_targets, list):
        for item in raw_targets:
            value = _coerce_float(item)
            if value is not None and value > 0:
                targets.append(value)
    signal.take_profits = targets

    if signal.symbol is None:
        signal.add_warning("ia_symbole_non_reconnu")
        return signal
    if signal.direction is None:
        signal.add_warning("ia_direction_absente")
        return signal

    signal.is_signal = True
    # Une lecture par IA plafonne a 0.80 : elle reste moins sure qu'une
    # structure reconnue localement (CDC section 50).
    confidence = 0.60
    if signal.has_entry:
        confidence += 0.05
    if signal.stop_loss is not None:
        confidence += 0.10
    if signal.take_profits:
        confidence += 0.05
    signal.confidence = round(min(0.80, confidence), 3)
    return signal


def _extract_tool_payload(response: dict[str, Any]) -> dict[str, Any] | None:
    message = extract_message(response)
    tool_calls = message.get("tool_calls") or []
    for call in tool_calls:
        function = call.get("function") or {}
        if function.get("name") != TOOL_NAME:
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                logger.debug("Arguments d'outil illisibles")
    return None


def _extract_json_payload(response: dict[str, Any]) -> dict[str, Any] | None:
    text = extract_text(response)
    if not text:
        return None
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def parse_with_ai(
    client: OpenRouterClient,
    model: str,
    message_text: str,
    use_tools: bool = True,
    max_chars: int = 4000,
) -> tuple[ParsedSignal, dict[str, Any]]:
    """Demande au modele d'extraire le signal. Retourne (signal, metadonnees).

    Seul le texte du message est transmis : aucune donnee de compte, aucun
    identifiant, aucun solde (CDC section 74).
    """
    trimmed = message_text.strip()[:max_chars]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT if use_tools else f"{SYSTEM_PROMPT} {JSON_INSTRUCTION}"},
        {"role": "user", "content": trimmed},
    ]

    kwargs: dict[str, Any] = {"max_tokens": MIN_JSON_MAX_TOKENS, "temperature": 0.0}
    if use_tools:
        kwargs["tools"] = [TOOL_SCHEMA]
        kwargs["tool_choice"] = {"type": "function", "function": {"name": TOOL_NAME}}

    response = await client.chat(model=model, messages=messages, **kwargs)

    payload = _extract_tool_payload(response) if use_tools else None
    if payload is None:
        payload = _extract_json_payload(response)
    if payload is None:
        raise AiParseError("Reponse du modele inexploitable")

    signal = payload_to_signal(payload, model)
    usage = response.get("usage") or {}
    metadata = {
        "model": response.get("model", model),
        "promptTokens": usage.get("prompt_tokens"),
        "completionTokens": usage.get("completion_tokens"),
        "usedTools": use_tools and _extract_tool_payload(response) is not None,
    }
    return signal, metadata
