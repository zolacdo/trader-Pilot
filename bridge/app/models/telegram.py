"""Tables Telegram : compte, canaux, reglages, analyses, messages."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Column, Text, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from app.models.core import utcnow
from app.models.enums import ChannelMode, MultiTpStrategy


class TelegramAccount(SQLModel, table=True):
    """Compte utilisateur Telegram appaire au Bridge. Ligne unique (id=1).

    Ni l'API hash ni la session ne sont stockes ici : ils vivent dans la table
    ``secrets`` (chiffres) et dans un fichier de session protege.
    """

    __tablename__ = "telegram_account"

    id: int | None = Field(default=1, primary_key=True)
    api_id: int | None = Field(default=None)
    phone: str | None = Field(default=None, max_length=32)
    user_id: int | None = Field(default=None, sa_type=BigInteger)
    username: str | None = Field(default=None, max_length=64)
    first_name: str | None = Field(default=None, max_length=128)
    authorized: bool = Field(default=False)
    last_connected_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=255)
    updated_at: datetime = Field(default_factory=utcnow)


class Channel(SQLModel, table=True):
    """Canal Telegram connu du systeme (surveille ou seulement analyse)."""

    __tablename__ = "channels"

    id: int | None = Field(default=None, primary_key=True)
    # Les identifiants Telegram depassent l'entier 32 bits (ex: -1002202904800).
    telegram_id: int = Field(sa_type=BigInteger, index=True, unique=True)
    access_hash: str | None = Field(default=None, max_length=64)
    username: str | None = Field(default=None, max_length=64, index=True)
    title: str = Field(default="", max_length=255)
    description: str | None = Field(default=None, sa_column=Column(Text))
    members_count: int | None = Field(default=None)
    is_public: bool = Field(default=True)
    joined: bool = Field(default=False)
    monitored: bool = Field(default=False, index=True)
    photo_path: str | None = Field(default=None, max_length=255)
    added_at: datetime = Field(default_factory=utcnow)
    last_message_at: datetime | None = Field(default=None)
    last_signal_at: datetime | None = Field(default=None)
    last_seen_message_id: int | None = Field(default=None)
    signals_count: int = Field(default=0)


class ChannelSettings(SQLModel, table=True):
    """Overrides par canal. Un champ NULL signifie : utiliser le reglage global."""

    __tablename__ = "channel_settings"

    id: int | None = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True, unique=True, foreign_key="channels.id")

    enabled: bool = Field(default=True)
    mode: ChannelMode = Field(default=ChannelMode.OBSERVE)

    copy_buy: bool = Field(default=True)
    copy_sell: bool = Field(default=True)

    risk_percent: float | None = Field(default=None)
    max_positions: int | None = Field(default=None)
    max_lot: float | None = Field(default=None)
    max_spread_points: int | None = Field(default=None)
    max_signal_age_seconds: int | None = Field(default=None)
    min_confidence: float | None = Field(default=None)
    require_stop_loss: bool | None = Field(default=None)
    require_take_profit: bool | None = Field(default=None)
    multi_tp_strategy: MultiTpStrategy | None = Field(default=None)
    allowed_symbols: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    updated_at: datetime = Field(default_factory=utcnow)


class ChannelAnalysis(SQLModel, table=True):
    """Rapport d'analyse technique d'un canal (CDC sections 13 et 14)."""

    __tablename__ = "channel_analysis"

    id: int | None = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True, foreign_key="channels.id")
    created_at: datetime = Field(default_factory=utcnow, index=True)
    messages_scanned: int = Field(default=0)
    signal_like_messages: int = Field(default=0)
    parsed_messages: int = Field(default=0)
    follow_up_messages: int = Field(default=0)
    close_messages: int = Field(default=0)
    modify_messages: int = Field(default=0)
    duplicate_signals: int = Field(default=0)

    structure_quality: float = Field(default=0.0, description="% de signaux structures")
    with_stop_loss_rate: float = Field(default=0.0)
    with_take_profit_rate: float = Field(default=0.0)
    parseable_rate: float = Field(default=0.0)
    average_take_profits: float = Field(default=0.0)
    signals_per_day: float = Field(default=0.0)
    first_message_at: datetime | None = Field(default=None)
    last_message_at: datetime | None = Field(default=None)

    symbols: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    directions: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    backtest: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    notes: str | None = Field(default=None, sa_column=Column(Text))


class ChannelParserProfile(SQLModel, table=True):
    """Apprentissage des formats recurrents d'un canal (CDC section 53)."""

    __tablename__ = "channel_parser_profiles"

    id: int | None = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True, unique=True, foreign_key="channels.id")
    symbol_aliases: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    known_formats: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    last_successful_format: str | None = Field(default=None, max_length=64)
    deterministic_success: int = Field(default=0)
    ai_fallback_count: int = Field(default=0)
    confidence: float = Field(default=0.0)
    updated_at: datetime = Field(default_factory=utcnow)


class TelegramMessage(SQLModel, table=True):
    """Message brut recu ou recupere pour analyse."""

    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("channel_id", "message_id", name="uq_message_channel"),)

    id: int | None = Field(default=None, primary_key=True)
    channel_id: int = Field(index=True, foreign_key="channels.id")
    message_id: int = Field(sa_type=BigInteger, index=True)
    reply_to_message_id: int | None = Field(default=None, sa_type=BigInteger, index=True)
    text: str = Field(sa_column=Column(Text))
    message_date: datetime = Field(index=True)
    received_at: datetime = Field(default_factory=utcnow)
    edited: bool = Field(default=False)
    processed: bool = Field(default=False, index=True)
    is_historical: bool = Field(default=False)


class PublishedMessage(SQLModel, table=True):
    """Message que le Bridge a lui-meme publie sur Telegram.

    Le canal de publication fait partie des canaux surveilles : le Bridge
    relit donc sa propre production. Ses annonces de trade portent un ordre
    complet — symbole, sens, entree, stop, objectifs — que le parseur lit
    comme un nouveau signal. Le 14/09/2026, un seul vrai signal XAUUSD a
    ainsi produit quatre ordres : chaque execution publiait une annonce, qui
    etait relue, qui declenchait une execution.

    Ce registre coupe la boucle a la racine. Il ne repose sur aucune
    reconnaissance de texte : on note l'identifiant rendu par Telegram a
    l'envoi, et on refuse ce meme identifiant au retour. Aucune reformulation
    ne peut le contourner.
    """

    __tablename__ = "published_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uq_published_message"),
    )

    id: int | None = Field(default=None, primary_key=True)
    chat_id: int = Field(sa_type=BigInteger, index=True)
    message_id: int = Field(sa_type=BigInteger, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chatId": self.chat_id,
            "messageId": self.message_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
