"""Configuration centrale du Bridge TradePilot.

Toutes les valeurs proviennent de variables d'environnement ou du fichier
``bridge/.env``. Aucun secret n'est ecrit en dur ici.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BRIDGE_ROOT = Path(__file__).resolve().parents[2]
API_VERSION = "v1"
APP_VERSION = "1.0.0"


class Settings(BaseSettings):
    """Reglages du Bridge charges depuis l'environnement."""

    model_config = SettingsConfigDict(
        env_file=(BRIDGE_ROOT / ".env", BRIDGE_ROOT.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- serveur ----
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 8787
    log_level: str = "INFO"
    data_dir: Path = Path("./data")

    # ---- base de donnees ----
    # PostgreSQL est utilise des que db_host est renseigne. Sinon le Bridge
    # retombe sur SQLite dans DATA_DIR : aucune installation n'est imposee.
    db_host: str = ""
    db_port: int = 5432
    db_database: str = ""
    db_username: str = ""
    db_password: str = ""

    # ---- securite ----
    master_key: str = ""
    pairing_code: str = ""
    cors_origins: str = ""

    # ---- ngrok ----
    ngrok_enabled: bool = False
    ngrok_authtoken: str = ""
    ngrok_domain: str = ""
    ngrok_region: str = "eu"
    ngrok_binary: str = ""

    # ---- MetaTrader 5 ----
    mt5_terminal_path: str = ""
    mt5_login: str = ""
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_poll_interval: float = 2.0

    # ---- Telegram ----
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_phone: str = ""

    # ---- OpenRouter ----
    openrouter_api_key: str = ""
    openrouter_preferred_text_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    openrouter_preferred_vision_model: str = ""
    openrouter_free_only: bool = True

    # ---- divers ----
    testing: bool = Field(default=False, description="Active le mode test (base en memoire)")

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            return "INFO"
        return level

    @field_validator("data_dir")
    @classmethod
    def _absolute_data_dir(cls, value: Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = (BRIDGE_ROOT / path).resolve()
        return path

    # ---- chemins derives ----
    @property
    def db_path(self) -> Path:
        return self.data_dir / "tradepilot.sqlite3"

    @property
    def uses_postgres(self) -> bool:
        """PostgreSQL des qu'un hote et une base sont renseignes."""
        return bool(self.db_host.strip() and self.db_database.strip())

    @property
    def database_url(self) -> str:
        if self.testing:
            # Les tests restent sur SQLite en memoire : rapides et isoles.
            return "sqlite+aiosqlite:///:memory:"
        if self.uses_postgres:
            from urllib.parse import quote_plus

            user = quote_plus(self.db_username.strip())
            password = quote_plus(self.db_password)
            host = self.db_host.strip()
            return (
                f"postgresql+asyncpg://{user}:{password}"
                f"@{host}:{self.db_port}/{self.db_database.strip()}"
            )
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"

    @property
    def database_label(self) -> str:
        """Description lisible, sans mot de passe, pour le diagnostic."""
        if self.testing:
            return "SQLite (memoire, tests)"
        if self.uses_postgres:
            return f"PostgreSQL {self.db_host}:{self.db_port}/{self.db_database}"
        return f"SQLite {self.db_path}"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def master_key_file(self) -> Path:
        return self.data_dir / "master.key"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.log_dir, self.sessions_dir, self.data_dir / "bin"):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def public_base_url(self) -> str | None:
        """URL publique attendue lorsque le tunnel ngrok utilise un domaine reserve."""
        if not self.ngrok_domain:
            return None
        domain = self.ngrok_domain.strip()
        if domain.startswith("http://") or domain.startswith("https://"):
            return domain.rstrip("/")
        return f"https://{domain}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.testing:
        settings.ensure_directories()
    return settings


def reload_settings() -> Settings:
    """Vide le cache (utile apres modification du .env ou dans les tests)."""
    get_settings.cache_clear()
    return get_settings()


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
