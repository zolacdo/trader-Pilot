"""Tables transverses : reglages, appairage, journal, audit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.types import JSON, TypeDecorator
from sqlmodel import Field, SQLModel

from app.models.enums import (
    BreakEvenTrigger,
    EventLevel,
    ExecutionMode,
    MultiTpStrategy,
    TrailingMode,
)

SINGLETON_ID = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Rend une date comparable a ``utcnow()``.

    SQLite ne conserve pas le fuseau : une date relue depuis la base revient
    sans ``tzinfo`` et ne peut pas etre comparee a une date aware sans lever
    ``TypeError``. Les valeurs stockees sont toujours en UTC, on le reaffirme.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class UtcDateTime(TypeDecorator):
    """Colonne date/heure stockee en UTC, sans fuseau, quel que soit le moteur.

    Le code applicatif manipule des dates *aware* (``utcnow()``). SQLite
    ignorait simplement le fuseau a l'ecriture ; PostgreSQL, lui, refuse une
    date aware dans une colonne ``TIMESTAMP WITHOUT TIME ZONE``, et le Bridge
    tombait des la premiere mise a jour (« can't subtract offset-naive and
    offset-aware datetimes »).

    On normalise donc a l'ecriture : conversion en UTC puis retrait du fuseau.
    Les deux moteurs stockent alors exactement la meme valeur, et la relecture
    passe par ``as_utc()`` comme auparavant. Aucune information n'est perdue :
    la convention UTC est celle de tout le projet.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        """Relit une date en UTC explicite, symetriquement a l'ecriture.

        Sans cela la base rendait une date sans fuseau, et chaque
        ``.isoformat()`` de l'API produisait un horodatage muet. Le telephone
        l'interpretait alors dans SON fuseau : une notification d'il y a une
        minute s'affichait « il y a 1 h ».
        """
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def normalize_datetime_columns(metadata: Any) -> int:
    """Applique ``UtcDateTime`` a toutes les colonnes date/heure du schema.

    Plutot que d'annoter une centaine de champs un par un — et d'oublier le
    prochain — on parcourt le schema une fois, apres l'import des modeles.
    Les colonnes declarant explicitement un fuseau sont laissees intactes :
    leur auteur a voulu un ``timestamptz``.
    """
    modifiees = 0
    for table in metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, UtcDateTime):
                continue
            if isinstance(column.type, DateTime) and not column.type.timezone:
                column.type = UtcDateTime()
                modifiees += 1
    return modifiees


class AppSetting(SQLModel, table=True):
    """Cle/valeur generique (preferences non sensibles, etat interne)."""

    __tablename__ = "settings"

    key: str = Field(primary_key=True, max_length=128)
    value: str | None = Field(default=None, sa_column=Column(Text))
    updated_at: datetime = Field(default_factory=utcnow)


class Secret(SQLModel, table=True):
    """Secrets chiffres au repos (Fernet). Jamais exposes en clair par l'API."""

    __tablename__ = "secrets"

    key: str = Field(primary_key=True, max_length=128)
    ciphertext: str = Field(sa_column=Column(Text))
    hint: str = Field(default="", max_length=64, description="Affichage partiel, ex: sk-o...9f2a")
    updated_at: datetime = Field(default_factory=utcnow)


class Device(SQLModel, table=True):
    """Telephone appaire avec le Bridge."""

    __tablename__ = "devices"

    id: int | None = Field(default=None, primary_key=True)
    device_id: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(default="Android", max_length=128)
    platform: str = Field(default="android", max_length=32)
    token_hash: str = Field(max_length=128, description="SHA-256 du token porteur")
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime | None = Field(default=None)
    revoked: bool = Field(default=False)
    push_token: str | None = Field(default=None, max_length=512)


class RiskSettings(SQLModel, table=True):
    """Parametres du RiskManager. Ligne unique (id=1). Valeurs sures par defaut."""

    __tablename__ = "risk_settings"

    id: int | None = Field(default=SINGLETON_ID, primary_key=True)

    # --- interrupteurs principaux ---
    auto_trading_enabled: bool = Field(default=False)
    execution_mode: ExecutionMode = Field(default=ExecutionMode.PAPER)
    live_unlocked: bool = Field(default=False)

    # --- risque ---
    risk_percent: float = Field(default=0.5, description="% du solde risque par trade")
    max_daily_risk_percent: float = Field(default=3.0)
    max_daily_loss_percent: float = Field(default=3.0)
    max_drawdown_percent: float = Field(default=10.0)
    daily_profit_target_percent: float | None = Field(default=None)

    # --- dimensionnement dynamique ---
    # Le multiplicateur de qualite ne peut que REDUIRE risk_percent. Par
    # defaut il est eteint : les tailles restent celles que l'utilisateur a
    # configurees tant qu'il ne l'active pas explicitement.
    dynamic_risk_enabled: bool = Field(default=False)
    dynamic_risk_floor: float = Field(
        default=0.35, description="Plancher du multiplicateur de qualite"
    )

    # --- volumes et exposition ---
    max_lot: float = Field(default=0.10)
    max_positions: int = Field(default=3)
    max_positions_per_symbol: int = Field(default=1)
    max_total_exposure_lots: float = Field(default=1.0)

    # --- conditions de marche ---
    max_spread_points: int = Field(default=40)
    max_slippage_points: int = Field(default=20)
    max_signal_age_seconds: int = Field(default=300)

    # --- exigences sur le signal ---
    require_stop_loss: bool = Field(default=True)
    require_take_profit: bool = Field(default=False)
    min_risk_reward: float | None = Field(default=None)
    min_confidence: float = Field(default=0.85)

    # --- protections comportementales ---
    max_consecutive_losses: int = Field(default=3)
    pause_after_max_losses: bool = Field(default=True)
    pause_duration_minutes: int = Field(default=240)

    # --- fenetres autorisees ---
    trading_hours_start: str = Field(default="00:00", max_length=5)
    trading_hours_end: str = Field(default="23:59", max_length=5)
    trading_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], sa_column=Column(JSON))
    allowed_symbols: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # --- gestion des TP multiples ---
    multi_tp_strategy: MultiTpStrategy = Field(default=MultiTpStrategy.PARTIAL_CLOSE)
    split_ratios: list[float] = Field(default_factory=lambda: [40.0, 30.0, 30.0], sa_column=Column(JSON))

    # --- break even ---
    break_even_enabled: bool = Field(default=True)
    break_even_trigger: BreakEvenTrigger = Field(default=BreakEvenTrigger.TP1_HIT)
    break_even_r_multiple: float = Field(default=1.0)
    break_even_points: int = Field(default=100)
    break_even_offset_points: int = Field(default=5)

    # --- trailing stop ---
    # Le suivi est actif d'origine : sans lui, un gain acquis pouvait
    # redescendre entierement jusqu'au stop de depart. ATR_BASED plutot que des
    # points, parce qu'un nombre de points ne garde pas son sens d'un
    # instrument a l'autre (voir TrailingMode.ATR_BASED).
    trailing_mode: TrailingMode = Field(default=TrailingMode.ATR_BASED)
    trailing_distance_points: int = Field(default=200)
    trailing_step_points: int = Field(default=50)

    # --- trailing adosse a la volatilite (TrailingMode.ATR_BASED) ---
    # Distance normale du stop, en multiples de l'ATR de l'instrument.
    trailing_atr_multiple: float = Field(default=1.5)
    # Distance resserree, appliquee une fois le trade bien installe en profit.
    # C'est la partie « en fonction du profit deja acquis » : tant que le gain
    # est modeste on laisse respirer, ensuite on protege davantage.
    trailing_atr_tight_multiple: float = Field(default=0.75)
    # Gain, en multiples du risque initial, a partir duquel on resserre.
    trailing_tighten_after_r: float = Field(default=2.0)
    trailing_atr_period: int = Field(default=14)
    trailing_atr_timeframe: str = Field(default="M15", max_length=8)

    # --- paper trading ---
    paper_balance: float = Field(default=10000.0)
    paper_currency: str = Field(default="USD", max_length=8)
    paper_leverage: int = Field(default=500)

    updated_at: datetime = Field(default_factory=utcnow)


class TradingState(SQLModel, table=True):
    """Etat runtime du moteur de trading. Ligne unique (id=1)."""

    __tablename__ = "trading_state"

    id: int | None = Field(default=SINGLETON_ID, primary_key=True)
    paused: bool = Field(default=False)
    pause_reason: str | None = Field(default=None, max_length=255)
    paused_until: datetime | None = Field(default=None)
    consecutive_losses: int = Field(default=0)
    day_key: str | None = Field(default=None, max_length=10, description="AAAA-MM-JJ UTC")
    day_start_balance: float | None = Field(default=None)
    day_realized_pnl: float = Field(default=0.0)
    day_risked_percent: float = Field(default=0.0)
    peak_equity: float | None = Field(default=None)
    live_unlocked_at: datetime | None = Field(default=None)
    onboarding_completed: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=utcnow)


class JournalEntry(SQLModel, table=True):
    """Journal fonctionnel affiche dans l'application (CDC section 37)."""

    __tablename__ = "journal_entries"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    level: EventLevel = Field(default=EventLevel.INFO, index=True)
    category: str = Field(default="system", max_length=32, index=True)
    event: str = Field(max_length=64, index=True)
    message: str = Field(sa_column=Column(Text))
    channel_id: int | None = Field(default=None, index=True)
    signal_id: int | None = Field(default=None, index=True)
    data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class AuditLog(SQLModel, table=True):
    """Trace immuable des actions sensibles (CDC section 65)."""

    __tablename__ = "audit_logs"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    actor: str = Field(default="system", max_length=64)
    action: str = Field(max_length=64, index=True)
    target: str | None = Field(default=None, max_length=128)
    signal_id: int | None = Field(default=None, index=True)
    details: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
