"""Migrations legeres pour SQLite.

SQLite ne sait pas modifier une colonne existante. La strategie retenue :

1. ``SQLModel.metadata.create_all`` cree les tables absentes ;
2. ``_sync_missing_columns`` ajoute les colonnes ajoutees par une nouvelle version ;
3. les migrations numerotees gerent les cas particuliers (donnees a transformer).

Les anciennes donnees ne sont jamais supprimees (CDC section 76).
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel

from app.config.logging_config import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1


def _existing_columns(conn: Connection, table: str) -> set[str]:
    """Colonnes reelles de la table, quel que soit le moteur."""
    return {column["name"] for column in inspect(conn).get_columns(table)}


def _table_exists(conn: Connection, table: str) -> bool:
    return inspect(conn).has_table(table)


def _render_default(column, dialect: str) -> str:
    """Valeur par defaut SQL pour une colonne ajoutee a chaud.

    Le litteral depend du moteur : PostgreSQL exige TRUE/FALSE pour un
    booleen et refuse 1/0, la ou SQLite accepte les deux. Ecrire 1/0
    partout passait donc les tests (SQLite) et cassait le demarrage en
    production des qu'une colonne booleenne etait ajoutee a un modele.
    """
    if column.default is not None and getattr(column.default, "is_scalar", False):
        value = column.default.arg
        if isinstance(value, bool):
            if dialect == "postgresql":
                return "TRUE" if value else "FALSE"
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
    return "NULL"


def _sync_missing_columns(conn: Connection) -> list[str]:
    """Ajoute les colonnes presentes dans les modeles mais absentes en base."""
    applied: list[str] = []
    for table in SQLModel.metadata.sorted_tables:
        if not _table_exists(conn, table.name):
            continue
        present = _existing_columns(conn, table.name)
        for column in table.columns:
            if column.name in present:
                continue
            column_type = column.type.compile(dialect=conn.dialect)
            default = _render_default(column, conn.dialect.name)
            quote = conn.dialect.identifier_preparer.quote
            statement = (
                f"ALTER TABLE {quote(table.name)} ADD COLUMN "
                f"{quote(column.name)} {column_type} DEFAULT {default}"
            )
            conn.exec_driver_sql(statement)
            applied.append(f"{table.name}.{column.name}")
    return applied


def _current_version(conn: Connection) -> int:
    conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    row = conn.exec_driver_sql("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0]) if row else 0


def _mark_version(conn: Connection, version: int) -> None:
    """Enregistre la version appliquee, sans dupliquer si elle existe deja.

    On passe par ``text()`` et un parametre nomme plutot que par
    ``exec_driver_sql`` : ce dernier transmet la requete telle quelle au
    pilote, or chaque pilote attend sa propre syntaxe de parametre (``?``
    pour SQLite, ``$1`` pour asyncpg). SQLAlchemy fait la traduction.

    ``ON CONFLICT DO NOTHING`` est compris par PostgreSQL et par SQLite
    depuis la version 3.24 : une seule requete suffit pour les deux.
    """
    conn.execute(
        text("INSERT INTO schema_migrations (version) VALUES (:version) ON CONFLICT DO NOTHING"),
        {"version": version},
    )


def _migration_001(conn: Connection) -> None:
    """Version initiale : index utiles non couverts par les modeles."""
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_signals_channel_status ON signals (channel_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_trades_state_mode ON trades (state, execution_mode)",
        "CREATE INDEX IF NOT EXISTS ix_journal_created_level ON journal_entries (created_at, level)",
        "CREATE INDEX IF NOT EXISTS ix_messages_channel_date ON messages (channel_id, message_date)",
    ]
    for statement in statements:
        conn.exec_driver_sql(statement)


MIGRATIONS: dict[int, Callable[[Connection], None]] = {
    1: _migration_001,
}


def _run_sync(conn: Connection) -> None:
    added = _sync_missing_columns(conn)
    if added:
        logger.info("Colonnes ajoutees par migration: %s", ", ".join(added))

    version = _current_version(conn)
    for target in sorted(MIGRATIONS):
        if target > version:
            logger.info("Application de la migration %s", target)
            MIGRATIONS[target](conn)
            _mark_version(conn, target)
    if conn.dialect.name == "sqlite":
        conn.exec_driver_sql("PRAGMA optimize")


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(_run_sync)


async def database_version(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT COALESCE(MAX(version), 0) FROM schema_migrations"))
        row = result.fetchone()
        return int(row[0]) if row else 0


__all__ = ["SCHEMA_VERSION", "database_version", "run_migrations"]
