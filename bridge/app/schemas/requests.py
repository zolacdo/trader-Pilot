"""Corps de requetes acceptes par l'API. Validation stricte cote Pydantic."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    BreakEvenTrigger,
    ChannelMode,
    ExecutionMode,
    MultiTpStrategy,
    TrailingMode,
)
from app.models.intelligence import AIMode
from app.services.risk.quality import MAX_QUALITY_FLOOR


class PairingRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    device_id: str = Field(min_length=4, max_length=64, alias="deviceId")
    name: str = Field(default="Android", max_length=128)
    platform: str = Field(default="android", max_length=32)

    model_config = {"populate_by_name": True}


class DeviceActionRequest(BaseModel):
    device_id: str = Field(alias="deviceId", max_length=64)

    model_config = {"populate_by_name": True}


class PushTokenRequest(BaseModel):
    token: str = Field(max_length=512)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

class TelegramLoginStartRequest(BaseModel):
    """Identifiants Telegram pour la premiere connexion.

    Les trois champs sont facultatifs : lorsqu'ils sont absents, le Bridge
    reprend les valeurs de son fichier .env (TELEGRAM_API_ID, TELEGRAM_API_HASH,
    TELEGRAM_PHONE). Cela evite de ressaisir sur le telephone ce qui est deja
    configure sur l'ordinateur.
    """

    api_id: int | None = Field(default=None, alias="apiId", gt=0)
    api_hash: str | None = Field(default=None, alias="apiHash", min_length=8, max_length=64)
    phone: str | None = Field(default=None, min_length=6, max_length=32)

    model_config = {"populate_by_name": True}


class TelegramCodeRequest(BaseModel):
    request_id: str = Field(alias="requestId", max_length=64)
    code: str = Field(min_length=3, max_length=16)

    model_config = {"populate_by_name": True}


class TelegramPasswordRequest(BaseModel):
    request_id: str = Field(alias="requestId", max_length=64)
    password: str = Field(min_length=1, max_length=256)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Canaux
# ---------------------------------------------------------------------------

class ChannelSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=64)
    limit: int = Field(default=30, ge=1, le=50)


class ChannelAddRequest(BaseModel):
    """Ajout a la surveillance. Le canal demarre toujours en mode OBSERVE."""

    telegram_id: int | None = Field(default=None, alias="telegramId")
    username: str | None = Field(default=None, max_length=128)
    join: bool = Field(default=False, description="Rejoindre le canal (action explicite)")

    model_config = {"populate_by_name": True}


class ChannelAnalyzeRequest(BaseModel):
    messages: int = Field(default=250, ge=50, le=1000)
    backtest: bool = Field(default=False)


class ChannelSettingsRequest(BaseModel):
    enabled: bool | None = None
    mode: ChannelMode | None = None
    copy_buy: bool | None = Field(default=None, alias="copyBuy")
    copy_sell: bool | None = Field(default=None, alias="copySell")
    risk_percent: float | None = Field(default=None, alias="riskPercent", ge=0.01, le=10)
    max_positions: int | None = Field(default=None, alias="maxPositions", ge=1, le=50)
    max_lot: float | None = Field(default=None, alias="maxLot", gt=0, le=100)
    max_spread_points: int | None = Field(default=None, alias="maxSpreadPoints", ge=0, le=1000)
    max_signal_age_seconds: int | None = Field(default=None, alias="maxSignalAgeSeconds", ge=10, le=86400)
    min_confidence: float | None = Field(default=None, alias="minConfidence", ge=0, le=1)
    require_stop_loss: bool | None = Field(default=None, alias="requireStopLoss")
    require_take_profit: bool | None = Field(default=None, alias="requireTakeProfit")
    multi_tp_strategy: MultiTpStrategy | None = Field(default=None, alias="multiTpStrategy")
    allowed_symbols: list[str] | None = Field(default=None, alias="allowedSymbols")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Risque et trading
# ---------------------------------------------------------------------------

class RiskSettingsRequest(BaseModel):
    auto_trading_enabled: bool | None = Field(default=None, alias="autoTradingEnabled")
    risk_percent: float | None = Field(default=None, alias="riskPercent", ge=0.01, le=10)
    # 0 = plafond desactive. Le moteur traite deja cette valeur comme
    # « illimite » a ses trois points de controle (manager.py, quality.py),
    # mais le schema la refusait a l'entree : le reglage etait donc
    # inatteignable depuis l'API. La borne basse laisse maintenant passer 0,
    # et seul 0 desactive -- 0.05 resterait un plafond, tres bas.
    max_daily_risk_percent: float | None = Field(default=None, alias="maxDailyRiskPercent", ge=0, le=50)
    max_daily_loss_percent: float | None = Field(default=None, alias="maxDailyLossPercent", ge=0.1, le=50)
    max_drawdown_percent: float | None = Field(default=None, alias="maxDrawdownPercent", ge=1, le=90)
    daily_profit_target_percent: float | None = Field(
        default=None, alias="dailyProfitTargetPercent", ge=0.1, le=100
    )
    dynamic_risk_enabled: bool | None = Field(default=None, alias="dynamicRiskEnabled")
    # Borne haute a MAX_QUALITY_FLOOR et non a 1,0 : un plancher a 1,0
    # neutralise la modulation en la laissant affichee active. Pour l'eteindre,
    # `dynamicRiskEnabled`.
    dynamic_risk_floor: float | None = Field(
        default=None, alias="dynamicRiskFloor", ge=0.05, le=MAX_QUALITY_FLOOR
    )
    max_lot: float | None = Field(default=None, alias="maxLot", gt=0, le=100)
    max_positions: int | None = Field(default=None, alias="maxPositions", ge=1, le=50)
    max_positions_per_symbol: int | None = Field(default=None, alias="maxPositionsPerSymbol", ge=1, le=20)
    max_total_exposure_lots: float | None = Field(default=None, alias="maxTotalExposureLots", gt=0, le=500)
    max_spread_points: int | None = Field(default=None, alias="maxSpreadPoints", ge=0, le=2000)
    max_slippage_points: int | None = Field(default=None, alias="maxSlippagePoints", ge=0, le=500)
    max_signal_age_seconds: int | None = Field(default=None, alias="maxSignalAgeSeconds", ge=10, le=86400)
    require_stop_loss: bool | None = Field(default=None, alias="requireStopLoss")
    require_take_profit: bool | None = Field(default=None, alias="requireTakeProfit")
    min_risk_reward: float | None = Field(default=None, alias="minRiskReward", ge=0, le=100)
    min_confidence: float | None = Field(default=None, alias="minConfidence", ge=0, le=1)
    max_consecutive_losses: int | None = Field(default=None, alias="maxConsecutiveLosses", ge=0, le=50)
    pause_after_max_losses: bool | None = Field(default=None, alias="pauseAfterMaxLosses")
    pause_duration_minutes: int | None = Field(default=None, alias="pauseDurationMinutes", ge=1, le=10080)
    trading_hours_start: str | None = Field(default=None, alias="tradingHoursStart", max_length=5)
    trading_hours_end: str | None = Field(default=None, alias="tradingHoursEnd", max_length=5)
    trading_days: list[int] | None = Field(default=None, alias="tradingDays")
    allowed_symbols: list[str] | None = Field(default=None, alias="allowedSymbols")
    multi_tp_strategy: MultiTpStrategy | None = Field(default=None, alias="multiTpStrategy")
    split_ratios: list[float] | None = Field(default=None, alias="splitRatios")
    break_even_enabled: bool | None = Field(default=None, alias="breakEvenEnabled")
    break_even_trigger: BreakEvenTrigger | None = Field(default=None, alias="breakEvenTrigger")
    break_even_r_multiple: float | None = Field(default=None, alias="breakEvenRMultiple", ge=0.1, le=10)
    break_even_points: int | None = Field(default=None, alias="breakEvenPoints", ge=1, le=100000)
    break_even_offset_points: int | None = Field(default=None, alias="breakEvenOffsetPoints", ge=0, le=1000)
    trailing_mode: TrailingMode | None = Field(default=None, alias="trailingMode")
    trailing_distance_points: int | None = Field(
        default=None, alias="trailingDistancePoints", ge=1, le=100000
    )
    trailing_step_points: int | None = Field(default=None, alias="trailingStepPoints", ge=1, le=100000)
    # Trailing adosse a la volatilite : une seule valeur qui garde le meme sens
    # sur EURUSD et sur BTCUSD, ce qu'aucun nombre de points ne peut faire.
    trailing_atr_multiple: float | None = Field(
        default=None, alias="trailingAtrMultiple", gt=0, le=20
    )
    trailing_atr_tight_multiple: float | None = Field(
        default=None, alias="trailingAtrTightMultiple", gt=0, le=20
    )
    trailing_tighten_after_r: float | None = Field(
        default=None, alias="trailingTightenAfterR", ge=0, le=50
    )
    trailing_atr_period: int | None = Field(
        default=None, alias="trailingAtrPeriod", ge=2, le=200
    )
    trailing_atr_timeframe: str | None = Field(default=None, alias="trailingAtrTimeframe")
    paper_balance: float | None = Field(default=None, alias="paperBalance", gt=0, le=10_000_000)

    model_config = {"populate_by_name": True}

    @field_validator("trading_days")
    @classmethod
    def _valid_days(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("Les jours doivent etre compris entre 0 (lundi) et 6 (dimanche)")
        return sorted(set(value))

    @field_validator("trading_hours_start", "trading_hours_end")
    @classmethod
    def _valid_hour(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("Format attendu HH:MM")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Heure invalide")
        return f"{hour:02d}:{minute:02d}"


class ExecutionModeRequest(BaseModel):
    """Changement de mode d'execution.

    Le passage en MT5_LIVE exige une phrase de confirmation exacte, en plus du
    deverrouillage prealable (CDC section 10).
    """

    mode: ExecutionMode
    confirmation: str | None = Field(default=None, max_length=128)


class LiveUnlockRequest(BaseModel):
    confirmation: str = Field(max_length=128)
    acknowledged_risks: bool = Field(default=False, alias="acknowledgedRisks")

    model_config = {"populate_by_name": True}


class PauseRequest(BaseModel):
    reason: str = Field(default="Pause demandee depuis l'application", max_length=255)
    minutes: int | None = Field(default=None, ge=1, le=10080)


class EmergencyRequest(BaseModel):
    """Confirmation forte exigee pour fermer toutes les positions."""

    confirmation: str = Field(max_length=64)
    suspend_automation: bool = Field(default=True, alias="suspendAutomation")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Signaux et positions
# ---------------------------------------------------------------------------

class SignalDecisionRequest(BaseModel):
    reason: str = Field(default="", max_length=255)


class ManualSignalRequest(BaseModel):
    """Test manuel du parser, ou rejeu d'un message dans le moteur complet."""

    text: str = Field(min_length=1, max_length=4000)
    channel_id: int | None = Field(default=None, alias="channelId")
    use_ai: bool = Field(default=True, alias="useAi")

    # Rejouer deux fois le meme identifiant permet de verifier la protection
    # anti-doublon : le second envoi doit etre refuse (CDC section 85).
    message_id: int | None = Field(default=None, alias="messageId", ge=1, le=2_000_000_000)

    model_config = {"populate_by_name": True}


class ModifyPositionRequest(BaseModel):
    stop_loss: float | None = Field(default=None, alias="stopLoss", gt=0)
    take_profit: float | None = Field(default=None, alias="takeProfit", gt=0)

    model_config = {"populate_by_name": True}


class ClosePositionRequest(BaseModel):
    volume: float | None = Field(default=None, gt=0, description="Vide = fermeture totale")
    percentage: float | None = Field(default=None, gt=0, le=100)


class BreakEvenRequest(BaseModel):
    offset_points: int = Field(default=0, alias="offsetPoints", ge=0, le=1000)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# OpenRouter et symboles
# ---------------------------------------------------------------------------

class OpenRouterKeyRequest(BaseModel):
    api_key: str | None = Field(default=None, alias="apiKey", max_length=256)

    model_config = {"populate_by_name": True}


class ProviderKeyRequest(BaseModel):
    """Depot de la cle d'un moteur compatible OpenAI.

    Une valeur vide efface la cle : c'est le seul moyen de la retirer, un
    champ absent signifiant « ne rien changer ».
    """

    api_key: str | None = Field(default=None, alias="apiKey", max_length=256)

    model_config = {"populate_by_name": True}


class OpenRouterModelRequest(BaseModel):
    auto_mode: bool = Field(default=True, alias="autoMode")
    text_model: str | None = Field(default=None, alias="textModel", max_length=128)
    vision_model: str | None = Field(default=None, alias="visionModel", max_length=128)

    model_config = {"populate_by_name": True}


class ChartAnalysisRequest(BaseModel):
    instrument: str | None = Field(default=None, max_length=32)
    question: str | None = Field(default=None, max_length=500)


class SymbolMappingRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=32)
    canonical: str = Field(min_length=1, max_length=32)
    broker_symbol: str | None = Field(default=None, alias="brokerSymbol", max_length=32)

    model_config = {"populate_by_name": True}


class SettingsImportRequest(BaseModel):
    """Import de reglages non sensibles. Aucun secret n'est jamais accepte ici."""

    payload: dict[str, Any]


class AISettingsRequest(BaseModel):
    """Reglages de l'intelligence hybride (CDC2 sections 95 et 110).

    Tous les champs sont facultatifs : seuls ceux fournis sont modifies.
    """

    # Valeurs contraintes : une chaine libre serait ecrite en base et
    # provoquerait une erreur a la relecture.
    mode: AIMode | None = None

    openrouter_enabled: bool | None = Field(default=None, alias="openRouterEnabled")

    ensemble_enabled: bool | None = Field(default=None, alias="ensembleEnabled")
    # Second avis : c'est le MODELE qui distingue les deux opinions, le
    # fournisseur etant le meme. Vide = un seul avis, et le consensus le dit.
    ensemble_secondary_model: str | None = Field(
        default=None, alias="ensembleSecondaryModel", max_length=128
    )

    # Moteurs compatibles OpenAI. Leurs cles passent par une route dediee :
    # elles n'ont rien a faire dans un objet de reglages affichables.
    groq_enabled: bool | None = Field(default=None, alias="groqEnabled")
    groq_model: str | None = Field(default=None, alias="groqModel", max_length=128)
    google_enabled: bool | None = Field(default=None, alias="googleEnabled")
    google_model: str | None = Field(default=None, alias="googleModel", max_length=128)
    require_consensus_for_auto_trade: bool | None = Field(
        default=None, alias="requireConsensus"
    )
    disagreement_behaviour: Literal["NO_TRADE", "MANUAL_REVIEW"] | None = Field(
        default=None, alias="disagreementBehaviour"
    )

    ai_trading_enabled: bool | None = Field(default=None, alias="aiTradingEnabled")
    telegram_trading_enabled: bool | None = Field(default=None, alias="telegramTradingEnabled")
    shadow_mode: bool | None = Field(default=None, alias="shadowMode")
    verify_signals_with_ai: bool | None = Field(
        default=None, alias="verifySignalsWithAi"
    )
    max_ai_trades_per_day: int | None = Field(default=None, alias="maxAiTradesPerDay", ge=0, le=50)
    max_telegram_trades_per_day: int | None = Field(
        default=None, alias="maxTelegramTradesPerDay", ge=0, le=100
    )
    max_trades_per_symbol_per_day: int | None = Field(
        default=None, alias="maxTradesPerSymbolPerDay", ge=0, le=50
    )
    min_opportunity_confidence: float | None = Field(
        default=None, alias="minOpportunityConfidence", ge=0.0, le=1.0
    )

    model_config = {"populate_by_name": True}
