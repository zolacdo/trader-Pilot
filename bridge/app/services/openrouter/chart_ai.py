"""Analyse IA d'une capture d'ecran de graphique (CDC section 22).

Strictement informatif : aucun ordre n'est jamais declenche depuis cette page.
Seul un modele vision GRATUIT est utilise.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.config.logging_config import get_logger
from app.services.openrouter.client import OpenRouterClient, OpenRouterError, extract_text

logger = get_logger(__name__)

MAX_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

SYSTEM_PROMPT = (
    "You are a technical chart reader. Describe only what is visible on the chart image. "
    "Never guarantee an outcome, never give financial advice, never claim certainty. "
    "If the image is unreadable or is not a price chart, say so clearly and return empty lists. "
    "Prices you report must be readable on the chart axis; otherwise use null."
)

JSON_INSTRUCTION = (
    "Return one JSON object with these keys: "
    '{"readable": bool, "instrument": string|null, "timeframe": string|null, '
    '"trend": "UP"|"DOWN"|"RANGE"|"UNCLEAR", "supports": [number], "resistances": [number], '
    '"structure": string, "scenarios": [string], "invalidation": string|null, "summary": string}. '
    "No markdown, no commentary outside the JSON."
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

DISCLAIMER = (
    "Analyse indicative produite par un modele de langage a partir d'une image. "
    "Elle ne constitue pas un conseil et ne declenche aucun ordre."
)


class ChartAnalysisError(OpenRouterError):
    """L'image ou la reponse du modele est inexploitable."""


@dataclass(slots=True)
class ChartAnalysis:
    readable: bool = False
    instrument: str | None = None
    timeframe: str | None = None
    trend: str = "UNCLEAR"
    supports: list[float] = field(default_factory=list)
    resistances: list[float] = field(default_factory=list)
    structure: str = ""
    scenarios: list[str] = field(default_factory=list)
    invalidation: str | None = None
    summary: str = ""
    model: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "readable": self.readable,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "trend": self.trend,
            "supports": self.supports,
            "resistances": self.resistances,
            "structure": self.structure,
            "scenarios": self.scenarios,
            "invalidation": self.invalidation,
            "summary": self.summary,
            "model": self.model,
            "disclaimer": DISCLAIMER,
        }


def build_data_url(image_bytes: bytes, mime_type: str) -> str:
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ChartAnalysisError("Image trop volumineuse (maximum 4 Mo)")
    normalized = mime_type.lower().strip()
    if normalized not in ALLOWED_MIME:
        raise ChartAnalysisError(f"Format d'image non supporte : {mime_type}")
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    encoded = base64.b64encode(image_bytes).decode()
    return f"data:{normalized};base64,{encoded}"


def _floats(values: Any) -> list[float]:
    result: list[float] = []
    if isinstance(values, list):
        for item in values:
            if isinstance(item, bool):
                continue
            if isinstance(item, (int, float)):
                result.append(float(item))
            elif isinstance(item, str):
                try:
                    result.append(float(item.replace(",", ".")))
                except ValueError:
                    continue
    return result


def _strings(values: Any, limit: int = 5) -> list[str]:
    result: list[str] = []
    if isinstance(values, list):
        for item in values:
            if isinstance(item, str) and item.strip():
                result.append(item.strip()[:400])
    return result[:limit]


def payload_to_analysis(payload: dict[str, Any], model: str, raw_text: str) -> ChartAnalysis:
    trend = str(payload.get("trend", "UNCLEAR")).upper()
    if trend not in {"UP", "DOWN", "RANGE", "UNCLEAR"}:
        trend = "UNCLEAR"
    return ChartAnalysis(
        readable=bool(payload.get("readable")),
        instrument=(str(payload["instrument"])[:32] if payload.get("instrument") else None),
        timeframe=(str(payload["timeframe"])[:16] if payload.get("timeframe") else None),
        trend=trend,
        supports=_floats(payload.get("supports")),
        resistances=_floats(payload.get("resistances")),
        structure=str(payload.get("structure") or "")[:1200],
        scenarios=_strings(payload.get("scenarios")),
        invalidation=(str(payload["invalidation"])[:400] if payload.get("invalidation") else None),
        summary=str(payload.get("summary") or "")[:1200],
        model=model,
        raw_text=raw_text[:4000],
    )


async def analyze_chart(
    client: OpenRouterClient,
    model: str,
    image_bytes: bytes,
    mime_type: str,
    instrument: str | None = None,
    question: str | None = None,
) -> ChartAnalysis:
    """Envoie l'image au modele vision gratuit selectionne."""
    data_url = build_data_url(image_bytes, mime_type)

    prompt_parts = ["Analyse this trading chart screenshot."]
    if instrument:
        prompt_parts.append(f"The user says the instrument is {instrument[:32]}.")
    if question:
        prompt_parts.append(f"User question: {question.strip()[:400]}")
    prompt_parts.append(JSON_INSTRUCTION)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": " ".join(prompt_parts)},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    response = await client.chat(
        model=model, messages=messages, max_tokens=900, temperature=0.1, timeout=90.0
    )
    text = extract_text(response)
    match = _JSON_BLOCK.search(text or "")
    if not match:
        if not text:
            raise ChartAnalysisError("Le modele n'a retourne aucune analyse")
        # Le modele a repondu en texte libre : on conserve le texte tel quel.
        return ChartAnalysis(readable=True, summary=text[:1200], model=model, raw_text=text[:4000])
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ChartAnalysisError("Reponse du modele illisible") from exc
    if not isinstance(payload, dict):
        raise ChartAnalysisError("Reponse du modele inattendue")
    return payload_to_analysis(payload, str(response.get("model", model)), text)
