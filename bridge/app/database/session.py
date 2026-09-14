"""Moteur de base de donnees asynchrone (SQLite ou PostgreSQL), sessions et schema."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

# Session SQLModel : elle derive de celle de SQLAlchemy et ajoute ``exec()``,
# qui renvoie directement les objets typees plutot que des lignes.
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _create_engine(settings: Settings) -> AsyncEngine:
    kwargs: dict[str, object] = {"echo": False, "future": True}
    if settings.testing:
        # Base en memoire partagee par toutes les connexions du test.
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    elif settings.uses_postgres:
        # Un pool modeste suffit : le Bridge sert un seul utilisateur.
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 5
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 1800
    else:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return create_async_engine(settings.database_url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _create_engine(get_settings())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session transactionnelle : commit automatique, rollback en cas d'erreur."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependance FastAPI."""
    async with session_scope() as session:
        yield session


async def init_database() -> None:
    """Cree le schema puis applique les migrations legeres."""
    from app import models  # noqa: F401  (enregistre les tables aupres de SQLModel)
    from app.database.migrations import run_migrations

    # Le Market Watcher (CDC3) declare ses propres tables, toutes prefixees
    # watcher_. Elles doivent etre connues de SQLModel avant create_all, sans
    # pour autant que app.models ait a connaitre le sous-systeme.
    from app.watcher import models as watcher_models  # noqa: F401

    settings = get_settings()
    engine = get_engine()
    async with engine.begin() as conn:
        # Reglages propres a SQLite : PostgreSQL applique deja ces garanties.
        if conn.dialect.name == "sqlite":
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    await run_migrations(engine)
    logger.info("Base de donnees prete : %s", settings.database_label)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def reset_engine_for_tests() -> None:
    """Force la recreation du moteur (utilise par la fixture pytest)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
