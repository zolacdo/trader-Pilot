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
from app.models.enums import TrailingMode
from app.services.risk.quality import MAX_QUALITY_FLOOR

logger = get_logger(__name__)

SCHEMA_VERSION = 4


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


def _sync_enum_values(conn: Connection) -> list[str]:
    """Ajoute aux types ENUM PostgreSQL les valeurs apparues cote Python.

    SQLite range les enums dans une colonne texte : une nouvelle valeur y
    fonctionne immediatement, et les tests ne voient donc rien. PostgreSQL, lui,
    cree un vrai type ENUM et refuse toute valeur inconnue de lui.

    Constate le 14/09/2026 : l'ajout de ``TrailingMode.ATR_BASED`` passait les
    1942 tests puis echouait en production sur
    « valeur en entree invalide pour le enum trailingmode ». La synchronisation
    est donc faite pour TOUS les types, pas seulement celui-la : le prochain
    enum ajoute ne doit pas reproduire la meme panne.

    ``ADD VALUE IF NOT EXISTS`` est idempotent et, depuis PostgreSQL 12,
    autorise dans une transaction tant que la valeur n'y est pas utilisee.
    """
    if conn.dialect.name != "postgresql":
        return []

    added: list[str] = []
    seen: set[str] = set()
    for table in SQLModel.metadata.sorted_tables:
        for column in table.columns:
            name = getattr(column.type, "name", None)
            labels = getattr(column.type, "enums", None)
            if not name or not labels or name in seen:
                continue
            seen.add(name)
            rows = conn.execute(
                text(
                    "SELECT e.enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = :name"
                ),
                {"name": name},
            )
            existing = {row[0] for row in rows}
            if not existing:
                # Le type n'existe pas encore : create_all le creera complet.
                continue
            for label in labels:
                if label in existing:
                    continue
                quoted = str(label).replace("'", "''")
                try:
                    conn.exec_driver_sql(
                        f'ALTER TYPE "{name}" ADD VALUE IF NOT EXISTS \'{quoted}\''
                    )
                except Exception as exc:
                    # Une valeur non ajoutee ne doit pas empecher le demarrage :
                    # elle sera signalee, et seule son utilisation echouera.
                    logger.warning("Valeur %s.%s non ajoutee : %s", name, label, exc)
                    continue
                added.append(f"{name}.{label}")
    return added


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


def _migration_002(conn: Connection) -> None:
    """Active le suivi du stop sur les comptes restes sur l'ancien defaut.

    ``DISABLED`` etait la valeur d'origine : le break even ramenait le stop a
    l'entree une fois, puis plus rien ne bougeait, et un gain pouvait
    redescendre entierement. Un compte qui a choisi un autre mode garde le
    sien : seul l'ancien defaut bascule.

    L'ordre compte. ``_sync_enum_values`` tourne avant les migrations
    numerotees, donc ``ATR_BASED`` existe deja dans le type ENUM PostgreSQL
    quand cette requete s'execute. Passer par la table de ``SQLModel`` plutot
    que par du SQL brut laisse SQLAlchemy convertir la valeur selon le moteur,
    la ou un parametre texte serait refuse par l'enum PostgreSQL.
    """
    table = SQLModel.metadata.tables["risk_settings"]
    conn.execute(
        table.update()
        .where(table.c.trailing_mode == TrailingMode.DISABLED)
        .values(trailing_mode=TrailingMode.ATR_BASED)
    )


def _migration_003(conn: Connection) -> None:
    """Ramene un plancher de risque dynamique qui neutralisait la modulation.

    A 1,0, ``dynamic_risk_floor`` servait de borne basse ET de borne haute
    dans ``quality.py`` : le multiplicateur valait toujours 1, les cinq
    facteurs de qualite etaient calcules puis jetes, et l'interrupteur restait
    affiche actif. Le 14/09/2026, les quatre positions parties au stop
    portaient « qualite 1.00 (plus penalisant : rendement_risque 0.50) » dans
    leur journal d'audit -- la contradiction en toutes lettres.

    On ne force pas le defaut de 0,35 : le compte garde la reduction la plus
    faible que le modele autorise desormais, et l'utilisateur reste maitre du
    reglage. Pour eteindre la modulation, ``dynamic_risk_enabled`` existe.
    """
    table = SQLModel.metadata.tables["risk_settings"]
    conn.execute(
        table.update()
        .where(table.c.dynamic_risk_floor > MAX_QUALITY_FLOOR)
        .values(dynamic_risk_floor=MAX_QUALITY_FLOOR)
    )


def _migration_004(conn: Connection) -> None:
    """Efface les R multiples produits par une formule dimensionnellement fausse.

    ``resultat / (distance de prix x volume)`` divisait des dollars par une
    grandeur qui n'en est pas : il y manquait la valeur du contrat. L'erreur
    valait donc exactement cette valeur -- 100 sur l'or, 100 000 sur l'euro, et
    1 sur les indices, ou la formule tombait juste par hasard. En base le
    14/09/2026 : -100, -100, -99,989, -100000 et +28688 pour des positions
    parties au stop, qui valent toutes -1 R.

    On n'en recalcule aucun : la valeur juste demande la taille du contrat, que
    seul le terminal connait, et un R invente pollue ``learning/performance``
    -- qui en fait des sommes -- plus surement qu'un trou. Les colonnes brutes
    (entree, stop initial, volume, resultat) restent intactes : le chiffre est
    reconstituable, et les positions fermees apres cette version sont mesurees
    par ``TradingEngine.risk_reference``.
    """
    table = SQLModel.metadata.tables["trades"]
    conn.execute(
        table.update().where(table.c.r_multiple.is_not(None)).values(r_multiple=None)
    )


MIGRATIONS: dict[int, Callable[[Connection], None]] = {
    1: _migration_001,
    2: _migration_002,
    3: _migration_003,
    4: _migration_004,
}


def _run_sync(conn: Connection) -> None:
    added = _sync_missing_columns(conn)
    if added:
        logger.info("Colonnes ajoutees par migration: %s", ", ".join(added))

    labels = _sync_enum_values(conn)
    if labels:
        logger.info("Valeurs d'enum ajoutees par migration: %s", ", ".join(labels))

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
