"""Enumerations et tables de l'intelligence de marche (CDC2).

Ces structures servent a expliquer chaque decision : ce que le systeme a vu,
avec quelles sources, quels modeles, et pourquoi il a conclu. Rien ici ne
declenche un ordre : le RiskManager reste la derniere barriere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Text, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.core import utcnow
from app.models.enums import Direction, StrEnum

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"


class MarketRegime(StrEnum):
    """Regime observe sur un instrument (CDC2 section 21)."""

    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    BREAKOUT = "BREAKOUT"
    NEWS_DRIVEN = "NEWS_DRIVEN"
    UNCERTAIN = "UNCERTAIN"


class TrendState(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class DecisionAction(StrEnum):
    """Sortie du moteur de decision (CDC2 section 42)."""

    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WAIT = "WAIT"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    NO_TRADE = "NO_TRADE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class DecisionSource(StrEnum):
    """Origine d'une decision, pour comparer les performances (CDC2 section 49)."""

    TELEGRAM = "TELEGRAM"
    AI_GENERATED = "AI_GENERATED"
    MANUAL = "MANUAL"


class AIProviderKind(StrEnum):
    """Fournisseurs d'inference distants (CDC2 section 4).

    Le moteur local a ete retire : il imposait a l'utilisateur d'heberger un
    serveur d'inference sur une machine qui fait deja tourner MetaTrader,
    PostgreSQL et le Bridge.

    Trois fournisseurs distants le remplacent. Leur interet n'est pas la
    variete pour elle-meme : OpenRouter plafonne les modeles gratuits a 50
    requetes par jour, plafond atteint des la mi-journee, ce qui rendait toute
    confrontation impossible. Des quotas INDEPENDANTS rendent le second avis
    reellement disponible -- et un desaccord informatif plutot qu'accidentel.
    """

    OPENROUTER = "OPENROUTER"
    # Deux moteurs distants supplementaires, parlant le dialecte OpenAI. Leur
    # interet n'est pas la variete pour elle-meme : ce sont des quotas et des
    # modes de panne INDEPENDANTS, ce qui rend un desaccord informatif.
    GROQ = "GROQ"
    GOOGLE = "GOOGLE"


class AIMode(StrEnum):
    """Nombre d'avis sollicites avant une decision (CDC2 section 9).

    Arbitrer entre deux fournisseurs n'a plus de sens. Ce qui reste reglable,
    c'est le nombre de modeles OpenRouter confrontes sur une meme question.
    """

    SINGLE = "SINGLE"
    ENSEMBLE = "ENSEMBLE"


class AITaskKind(StrEnum):
    """Nature de la tache : le routeur s'en sert pour choisir le moteur."""

    SIGNAL_PARSE = "SIGNAL_PARSE"
    NEWS_CLASSIFY = "NEWS_CLASSIFY"
    NEWS_SUMMARY = "NEWS_SUMMARY"
    MARKET_ANALYSIS = "MARKET_ANALYSIS"
    MACRO_ANALYSIS = "MACRO_ANALYSIS"
    VISION = "VISION"
    OPPORTUNITY_REVIEW = "OPPORTUNITY_REVIEW"


class ConsensusOutcome(StrEnum):
    """Resultat de la confrontation des deux intelligences (CDC2 section 12)."""

    CONSENSUS = "CONSENSUS"
    PARTIAL_CONSENSUS = "PARTIAL_CONSENSUS"
    DISAGREEMENT = "DISAGREEMENT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class NewsImpact(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class NewsSentiment(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class VerificationStatus(StrEnum):
    UNCONFIRMED = "UNCONFIRMED"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    CONFIRMED = "CONFIRMED"


class NotificationCategory(StrEnum):
    """Categories de notifications (CDC2 section 51)."""

    TRADE = "TRADE"
    SIGNAL = "SIGNAL"
    OPPORTUNITY = "OPPORTUNITY"
    NEWS = "NEWS"
    ECONOMIC = "ECONOMIC"
    RISK = "RISK"
    SYSTEM = "SYSTEM"
    DAILY_REPORT = "DAILY_REPORT"
    AI_SYSTEM = "AI_SYSTEM"


class NotificationPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ShadowOutcome(StrEnum):
    """Ce que le systeme AURAIT fait, sans envoyer d'ordre (CDC2 section 84)."""

    WOULD_BUY = "WOULD_BUY"
    WOULD_SELL = "WOULD_SELL"
    WOULD_SKIP = "WOULD_SKIP"


class ServiceHealth(StrEnum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


# ---------------------------------------------------------------------------
# Donnees de marche
# ---------------------------------------------------------------------------

class WatchlistItem(SQLModel, table=True):
    """Instrument que TradePilot a le droit d'observer (CDC2 section 17).

    Le symbole broker n'est jamais suppose : il est resolu depuis la liste
    reelle des symboles MT5.
    """

    __tablename__ = "watchlist"

    id: int | None = Field(default=None, primary_key=True)
    canonical: str = Field(index=True, unique=True, max_length=32)
    broker_symbol: str | None = Field(default=None, max_length=32)
    enabled: bool = Field(default=True)
    available: bool = Field(default=False, description="Confirme present chez le broker")
    scan_priority: int = Field(default=5, ge=1, le=10)
    allow_ai_trading: bool = Field(default=False)
    allow_telegram_trading: bool = Field(default=True)
    notify_news: bool = Field(default=True)
    notify_opportunities: bool = Field(default=True)
    notify_volatility: bool = Field(default=True)
    last_scanned_at: datetime | None = Field(default=None)
    added_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MarketSnapshot(SQLModel, table=True):
    """Photographie chiffree d'un instrument a un instant (CDC2 section 47).

    Sert de memoire de contexte : c'est sur ces enregistrements que le moteur
    historique cherche des situations comparables.
    """

    __tablename__ = "market_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=32)
    captured_at: datetime = Field(default_factory=utcnow, index=True)

    bid: float | None = Field(default=None)
    ask: float | None = Field(default=None)
    spread_points: int | None = Field(default=None)

    regime: MarketRegime = Field(default=MarketRegime.UNCERTAIN)
    trend_d1: TrendState = Field(default=TrendState.NEUTRAL)
    trend_h4: TrendState = Field(default=TrendState.NEUTRAL)
    trend_h1: TrendState = Field(default=TrendState.NEUTRAL)

    # Caracteristiques normalisees, comparables d'un instrument a l'autre.
    features: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    technical_score: float | None = Field(default=None)
    historical_score: float | None = Field(default=None)
    macro_score: float | None = Field(default=None)
    news_score: float | None = Field(default=None)
    cross_market_score: float | None = Field(default=None)
    telegram_score: float | None = Field(default=None)
    local_ai_score: float | None = Field(default=None)
    openrouter_score: float | None = Field(default=None)
    ai_consensus: ConsensusOutcome | None = Field(default=None)
    global_score: float | None = Field(default=None)
    decision: DecisionAction | None = Field(default=None)


class MarketRegimeRecord(SQLModel, table=True):
    """Historique des changements de regime, utile aux analyses."""

    __tablename__ = "market_regimes"

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=32)
    timeframe: Timeframe = Field(default=Timeframe.H1)
    regime: MarketRegime = Field(default=MarketRegime.UNCERTAIN)
    detected_at: datetime = Field(default_factory=utcnow, index=True)
    atr: float | None = Field(default=None)
    atr_ratio: float | None = Field(default=None)
    detail: str | None = Field(default=None, max_length=255)


class CrossMarketState(SQLModel, table=True):
    """Correlations recentes entre instruments (CDC2 section 25)."""

    __tablename__ = "cross_market_states"

    id: int | None = Field(default=None, primary_key=True)
    computed_at: datetime = Field(default_factory=utcnow, index=True)
    base_symbol: str = Field(index=True, max_length=32)
    correlations: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    window_days: int = Field(default=30)
    note: str | None = Field(default=None, max_length=255)


# ---------------------------------------------------------------------------
# Analyse historique
# ---------------------------------------------------------------------------

class HistoricalPattern(SQLModel, table=True):
    """Resultat d'une recherche de situations comparables (CDC2 section 22)."""

    __tablename__ = "historical_patterns"

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=32)
    computed_at: datetime = Field(default_factory=utcnow, index=True)
    reference_features: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    matches: int = Field(default=0)
    similarity_mean: float = Field(default=0.0)
    positive: int = Field(default=0)
    negative: int = Field(default=0)
    neutral: int = Field(default=0)

    average_move: float | None = Field(default=None)
    average_mae: float | None = Field(default=None)
    average_mfe: float | None = Field(default=None)
    horizon_hours: int = Field(default=4)
    distribution: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    disclaimer: str = Field(
        default="Statistiques historiques indicatives : elles ne predisent aucune performance future.",
        max_length=255,
    )


# ---------------------------------------------------------------------------
# Actualites et calendrier
# ---------------------------------------------------------------------------

class NewsEvent(SQLModel, table=True):
    """Actualite collectee et qualifiee (CDC2 sections 29 et 77)."""

    __tablename__ = "news_events"

    id: int | None = Field(default=None, primary_key=True)
    raw_hash: str = Field(index=True, unique=True, max_length=64)
    source: str = Field(max_length=128)
    title: str = Field(sa_column=Column(Text))
    url: str | None = Field(default=None, max_length=1024)
    published_at: datetime | None = Field(default=None, index=True)
    received_at: datetime = Field(default_factory=utcnow, index=True)

    summary: str | None = Field(default=None, sa_column=Column(Text))
    category: str | None = Field(default=None, max_length=64)
    countries: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    entities: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    affected_assets: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    affected_currencies: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    impact: NewsImpact = Field(default=NewsImpact.LOW, index=True)
    sentiment: NewsSentiment = Field(default=NewsSentiment.NEUTRAL)
    confidence: float = Field(default=0.0)
    reason: str | None = Field(default=None, max_length=500)

    verification: VerificationStatus = Field(default=VerificationStatus.UNCONFIRMED)
    duplicate_of: int | None = Field(default=None, index=True)
    confirmations: int = Field(default=1)

    ai_provider_used: AIProviderKind | None = Field(default=None)
    ai_model_used: str | None = Field(default=None, max_length=128)


class NewsAssetLink(SQLModel, table=True):
    """Lien explicite entre une actualite et un instrument surveille."""

    __tablename__ = "news_asset_links"
    __table_args__ = (UniqueConstraint("news_id", "symbol", name="uq_news_asset"),)

    id: int | None = Field(default=None, primary_key=True)
    news_id: int = Field(index=True, foreign_key="news_events.id")
    symbol: str = Field(index=True, max_length=32)
    relevance: float = Field(default=0.0)


class EconomicEvent(SQLModel, table=True):
    """Evenement du calendrier economique (CDC2 section 33)."""

    __tablename__ = "economic_events"
    __table_args__ = (UniqueConstraint("external_id", name="uq_economic_event"),)

    id: int | None = Field(default=None, primary_key=True)
    external_id: str = Field(max_length=128)
    scheduled_at: datetime = Field(index=True)
    country: str | None = Field(default=None, max_length=8)
    currency: str | None = Field(default=None, max_length=8, index=True)
    title: str = Field(max_length=255)
    impact: NewsImpact = Field(default=NewsImpact.LOW, index=True)
    forecast: str | None = Field(default=None, max_length=64)
    previous: str | None = Field(default=None, max_length=64)
    actual: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=128)
    notified_minutes: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Opportunites et decisions
# ---------------------------------------------------------------------------

class AiOpportunity(SQLModel, table=True):
    """Opportunite generee par le systeme lui-meme (CDC2 section 40).

    Les niveaux proviennent toujours de calculs deterministes : structure,
    volatilite, supports/resistances. L'IA explique, elle n'invente pas.
    """

    __tablename__ = "ai_opportunities"

    id: int | None = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=32)
    broker_symbol: str | None = Field(default=None, max_length=32)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    expires_at: datetime | None = Field(default=None)

    direction: Direction
    strategy: str | None = Field(default=None, max_length=64)
    entry_min: float | None = Field(default=None)
    entry_max: float | None = Field(default=None)
    entry_price: float | None = Field(default=None)
    stop_loss: float | None = Field(default=None)
    take_profits: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    expected_rr: float | None = Field(default=None)

    confidence: float = Field(default=0.0)
    status: str = Field(default="PENDING", max_length=32, index=True)
    reasons: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    negative_factors: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    snapshot_id: int | None = Field(default=None, index=True)
    decision_id: int | None = Field(default=None, index=True)
    signal_id: int | None = Field(default=None, index=True)


class DecisionRecord(SQLModel, table=True):
    """Trace d'une decision, y compris les trades NON pris (CDC2 section 76)."""

    __tablename__ = "decision_records"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    symbol: str = Field(index=True, max_length=32)
    source: DecisionSource = Field(default=DecisionSource.AI_GENERATED, index=True)
    action: DecisionAction = Field(default=DecisionAction.NO_TRADE, index=True)
    direction: Direction | None = Field(default=None)

    global_score: float = Field(default=0.0)
    confidence: float = Field(default=0.0)
    regime: MarketRegime | None = Field(default=None)

    reason: str | None = Field(default=None, sa_column=Column(Text))
    positive_factors: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    negative_factors: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    signal_id: int | None = Field(default=None, index=True)
    opportunity_id: int | None = Field(default=None, index=True)
    snapshot_id: int | None = Field(default=None, index=True)
    trade_id: int | None = Field(default=None, index=True)
    executed: bool = Field(default=False)
    shadow: bool = Field(default=False, index=True)


class DecisionFactor(SQLModel, table=True):
    """Composante chiffree d'une decision : d'ou vient chaque point."""

    __tablename__ = "decision_factors"

    id: int | None = Field(default=None, primary_key=True)
    decision_id: int = Field(index=True, foreign_key="decision_records.id")
    name: str = Field(max_length=48)
    score: float = Field(default=0.0)
    weight: float = Field(default=0.0)
    contribution: float = Field(default=0.0)
    detail: str | None = Field(default=None, max_length=500)


class ShadowTrade(SQLModel, table=True):
    """Ce que le systeme aurait fait sans envoyer d'ordre (CDC2 section 84)."""

    __tablename__ = "shadow_trades"

    id: int | None = Field(default=None, primary_key=True)
    decision_id: int | None = Field(default=None, index=True)
    symbol: str = Field(index=True, max_length=32)
    outcome: ShadowOutcome = Field(default=ShadowOutcome.WOULD_SKIP, index=True)
    direction: Direction | None = Field(default=None)
    entry_price: float | None = Field(default=None)
    stop_loss: float | None = Field(default=None)
    take_profit: float | None = Field(default=None)
    volume: float | None = Field(default=None)
    opened_at: datetime = Field(default_factory=utcnow, index=True)
    closed_at: datetime | None = Field(default=None)
    close_price: float | None = Field(default=None)
    r_multiple: float | None = Field(default=None)
    result: str | None = Field(default=None, max_length=32)
    source: DecisionSource = Field(default=DecisionSource.AI_GENERATED)

    # Bande marginale : opportunite ecartee pour la SEULE raison du seuil de
    # confiance, enregistree pendant que le trading continue normalement.
    # C'est le capteur qui rend defendable une baisse de ce seuil -- sans lui,
    # personne ne sait ce que vaut ce qu'on s'apprete a laisser passer.
    marginal: bool = Field(default=False, index=True)
    # Nom du symbole chez le courtier. ``symbol`` porte le canonique, que le
    # terminal ne connait pas : sans celui-ci, aucune bougie ne peut etre
    # demandee et la simulation resterait ouverte a vie.
    broker_symbol: str | None = Field(default=None, max_length=64)


class StrategyPerformance(SQLModel, table=True):
    """Performance agregee par strategie et par origine (CDC2 section 49)."""

    __tablename__ = "strategy_performance"

    id: int | None = Field(default=None, primary_key=True)
    day: str = Field(index=True, max_length=10)
    strategy: str = Field(max_length=64, index=True)
    source: DecisionSource = Field(default=DecisionSource.AI_GENERATED)
    trades: int = Field(default=0)
    wins: int = Field(default=0)
    losses: int = Field(default=0)
    net_r: float = Field(default=0.0)
    net_pnl: float = Field(default=0.0)
    max_drawdown: float = Field(default=0.0)
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Intelligence artificielle
# ---------------------------------------------------------------------------

class AIProviderMetric(SQLModel, table=True):
    """Fiabilite mesuree d'OpenRouter par tache (CDC2 section 14).

    Le routeur s'en sert pour juger la sante du fournisseur : un taux de JSON
    invalide ou de delais depasses qui grimpe signale un modele a remplacer.
    """

    __tablename__ = "ai_provider_metrics"
    __table_args__ = (UniqueConstraint("provider", "task", name="uq_provider_task"),)

    id: int | None = Field(default=None, primary_key=True)
    provider: AIProviderKind = Field(index=True)
    task: AITaskKind = Field(index=True)
    model: str | None = Field(default=None, max_length=128)

    calls: int = Field(default=0)
    successes: int = Field(default=0)
    valid_json: int = Field(default=0)
    timeouts: int = Field(default=0)
    errors: int = Field(default=0)
    disagreements: int = Field(default=0)
    hallucinations_blocked: int = Field(default=0)

    total_latency_ms: int = Field(default=0)
    last_latency_ms: int | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=255)
    last_used_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def success_rate(self) -> float:
        return round(self.successes / self.calls, 3) if self.calls else 0.0

    @property
    def average_latency_ms(self) -> int:
        return int(self.total_latency_ms / self.successes) if self.successes else 0


class AIRoutingEvent(SQLModel, table=True):
    """Pourquoi le routeur a retenu tel modele pour telle tache."""

    __tablename__ = "ai_routing_events"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    task: AITaskKind = Field(index=True)
    mode: AIMode = Field(default=AIMode.ENSEMBLE)
    chosen: AIProviderKind | None = Field(default=None)
    # Les deux tentatives portent le meme fournisseur : sans le modele, la
    # trace ne dirait plus lequel a repondu ni lequel a ete ecarte.
    chosen_model: str | None = Field(default=None, max_length=128)
    fallback_used: bool = Field(default=False)
    reason: str | None = Field(default=None, max_length=255)
    latency_ms: int | None = Field(default=None)
    success: bool = Field(default=True)


class AIConsensusRecord(SQLModel, table=True):
    """Confrontation de deux modeles sur une meme question (CDC2 section 12).

    Seules les sorties structurees sont conservees : jamais le raisonnement
    interne des modeles.
    """

    __tablename__ = "ai_consensus_records"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    decision_id: int | None = Field(default=None, index=True)
    task: AITaskKind = Field(default=AITaskKind.OPPORTUNITY_REVIEW)
    outcome: ConsensusOutcome = Field(default=ConsensusOutcome.INSUFFICIENT_DATA, index=True)

    # Les deux avis viennent d'OpenRouter : seul le modele les distingue.
    primary_model: str | None = Field(default=None, max_length=128)
    primary_direction: Direction | None = Field(default=None)
    primary_confidence: float | None = Field(default=None)
    primary_latency_ms: int | None = Field(default=None)
    primary_summary: str | None = Field(default=None, sa_column=Column(Text))

    secondary_model: str | None = Field(default=None, max_length=128)
    secondary_direction: Direction | None = Field(default=None)
    secondary_confidence: float | None = Field(default=None)
    secondary_latency_ms: int | None = Field(default=None)
    secondary_summary: str | None = Field(default=None, sa_column=Column(Text))

    final_direction: Direction | None = Field(default=None)
    final_confidence: float | None = Field(default=None)
    detail: str | None = Field(default=None, max_length=500)


class AISettings(SQLModel, table=True):
    """Configuration de l'intelligence. Ligne unique (id=1).

    Rien n'est code en dur : les modeles sont choisis dynamiquement parmi les
    modeles gratuits d'OpenRouter (CDC2 section 6).
    """

    __tablename__ = "ai_settings"

    id: int | None = Field(default=1, primary_key=True)
    # ENSEMBLE par defaut : require_consensus_for_auto_trade vaut True, et un
    # avis unique ne constitue jamais un consensus. Demarrer en SINGLE
    # bloquerait donc tout trade automatique en silence.
    mode: AIMode = Field(default=AIMode.ENSEMBLE)

    # --- OpenRouter ---
    openrouter_enabled: bool = Field(default=True)

    # --- moteurs compatibles OpenAI (Groq, Google AI Studio) ---
    # Leurs cles vivent dans le coffre chiffre, jamais ici : ce modele ne
    # porte que ce qui peut etre affiche sans risque.
    groq_enabled: bool = Field(default=False)
    groq_model: str = Field(default="", max_length=128)
    google_enabled: bool = Field(default=False)
    google_model: str = Field(default="", max_length=128)

    # --- ensemble : deux modeles OpenRouter confrontes ---
    ensemble_enabled: bool = Field(default=True)
    # Modele du second avis. Vide = choisi automatiquement parmi les modeles
    # gratuits classes, en excluant le modele principal.
    ensemble_secondary_model: str = Field(default="", max_length=128)
    require_consensus_for_auto_trade: bool = Field(default=True)
    # A la moindre contradiction sur une decision financiere : pas de trade.
    disagreement_behaviour: str = Field(default="NO_TRADE", max_length=16)

    # --- garde-fous d'exploitation ---
    ai_trading_enabled: bool = Field(default=False)
    telegram_trading_enabled: bool = Field(default=True)
    shadow_mode: bool = Field(default=True)

    # Second avis d'une IA sur « ce message est-il vraiment un ordre ? ».
    # Droit de VETO uniquement : peut refuser un faux signal, jamais en creer.
    verify_signals_with_ai: bool = Field(default=False)
    max_ai_trades_per_day: int = Field(default=3)
    max_telegram_trades_per_day: int = Field(default=10)
    max_trades_per_symbol_per_day: int = Field(default=2)
    min_opportunity_confidence: float = Field(default=0.75)

    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class NotificationEvent(SQLModel, table=True):
    """Notification produite par le Bridge (CDC2 sections 51 et 67)."""

    __tablename__ = "notification_events"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    category: NotificationCategory = Field(index=True)
    priority: NotificationPriority = Field(default=NotificationPriority.MEDIUM, index=True)
    title: str = Field(max_length=255)
    body: str = Field(sa_column=Column(Text))
    data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    symbol: str | None = Field(default=None, max_length=32, index=True)
    decision_id: int | None = Field(default=None, index=True)
    news_id: int | None = Field(default=None, index=True)

    pushed: bool = Field(default=False, description="Envoye en push distant")
    push_error: str | None = Field(default=None, max_length=255)
    read_at: datetime | None = Field(default=None)


class NotificationPreference(SQLModel, table=True):
    """Reglages par categorie : ce qui merite une alerte sur le telephone."""

    __tablename__ = "notification_preferences"

    id: int | None = Field(default=None, primary_key=True)
    category: NotificationCategory = Field(index=True, unique=True)
    enabled: bool = Field(default=True)
    push_enabled: bool = Field(default=True)
    minimum_priority: NotificationPriority = Field(default=NotificationPriority.HIGH)
    quiet_hours_start: str | None = Field(default=None, max_length=5)
    quiet_hours_end: str | None = Field(default=None, max_length=5)
    critical_bypasses_quiet_hours: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=utcnow)
