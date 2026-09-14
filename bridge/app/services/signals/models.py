"""Structures produites par le pipeline d'analyse des messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.enums import Direction, FollowUpAction, OrderType, ParserSource


@dataclass(slots=True)
class FollowUp:
    """Message rattache a un signal existant (TP HIT, CLOSE, MOVE SL, ...)."""

    action: FollowUpAction
    symbol: str | None = None
    tp_index: int | None = None
    percentage: float | None = None
    price: float | None = None
    confidence: float = 0.0
    raw_hint: str | None = None
    also_break_even: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "symbol": self.symbol,
            "tpIndex": self.tp_index,
            "percentage": self.percentage,
            "price": self.price,
            "confidence": round(self.confidence, 3),
            "hint": self.raw_hint,
            "alsoBreakEven": self.also_break_even,
        }


@dataclass(slots=True)
class ParsedSignal:
    """Resultat d'analyse d'un message.

    Une valeur absente du message reste ``None`` : le parser n'invente jamais
    de prix, de direction ni de symbole (CDC sections 17 et 49).
    """

    is_signal: bool = False
    symbol_raw: str | None = None
    symbol: str | None = None
    direction: Direction | None = None
    order_type: OrderType | None = None

    entry_min: float | None = None
    entry_max: float | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)

    confidence: float = 0.0
    source: ParserSource = ParserSource.DETERMINISTIC
    format_signature: str | None = None
    ai_model: str | None = None

    follow_up: FollowUp | None = None
    warnings: list[str] = field(default_factory=list)

    # Date du message Telegram d'origine, renseignee par le pipeline.
    # Sert au controle de fraicheur du signal (un vieux signal ne part jamais).
    message_date: datetime | None = None

    @property
    def has_entry(self) -> bool:
        return self.entry_price is not None or (self.entry_min is not None and self.entry_max is not None)

    @property
    def is_follow_up(self) -> bool:
        return self.follow_up is not None

    @property
    def reference_entry(self) -> float | None:
        """Prix de reference pour les controles (milieu de zone si necessaire)."""
        if self.entry_price is not None:
            return self.entry_price
        if self.entry_min is not None and self.entry_max is not None:
            return (self.entry_min + self.entry_max) / 2
        return self.entry_min if self.entry_min is not None else self.entry_max

    def add_warning(self, warning: str) -> None:
        if warning not in self.warnings:
            self.warnings.append(warning)

    def to_dict(self) -> dict[str, Any]:
        return {
            "isSignal": self.is_signal,
            "symbolRaw": self.symbol_raw,
            "symbol": self.symbol,
            "direction": self.direction.value if self.direction else None,
            "orderType": self.order_type.value if self.order_type else None,
            "entryMin": self.entry_min,
            "entryMax": self.entry_max,
            "entryPrice": self.entry_price,
            "stopLoss": self.stop_loss,
            "takeProfits": list(self.take_profits),
            "confidence": round(self.confidence, 3),
            "source": self.source.value,
            "formatSignature": self.format_signature,
            "aiModel": self.ai_model,
            "followUp": self.follow_up.to_dict() if self.follow_up else None,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    blocking: bool = True


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def blocking_issues(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.blocking]

    @property
    def first_blocking(self) -> ValidationIssue | None:
        blocking = self.blocking_issues
        return blocking[0] if blocking else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [
                {"code": issue.code, "message": issue.message, "blocking": issue.blocking}
                for issue in self.issues
            ],
        }
