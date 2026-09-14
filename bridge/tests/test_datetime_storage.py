"""Stockage des dates : meme comportement sous SQLite et sous PostgreSQL.

Le code applicatif manipule des dates *aware* en UTC. SQLite ignorait le
fuseau a l'ecriture, PostgreSQL le refusait : le Bridge tombait des la
premiere mise a jour. La normalisation est desormais centralisee dans
``UtcDateTime``, applique a tout le schema.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable
from sqlmodel import SQLModel, select

from app.models.core import Device, UtcDateTime, as_utc, utcnow


def _bind(value: datetime | None) -> datetime | None:
    return UtcDateTime().process_bind_param(value, postgresql.dialect())


def test_date_aware_convertie_en_utc_naif() -> None:
    aware = datetime(2026, 9, 11, 6, 4, 23, tzinfo=UTC)
    assert _bind(aware) == datetime(2026, 9, 11, 6, 4, 23)
    assert _bind(aware).tzinfo is None


def test_fuseau_non_utc_ramene_a_utc_avant_retrait() -> None:
    """Un decalage ne doit pas etre simplement efface : l'heure changerait."""
    paris = datetime(2026, 9, 11, 8, 4, 23, tzinfo=timezone(timedelta(hours=2)))
    assert _bind(paris) == datetime(2026, 9, 11, 6, 4, 23)


def test_date_naive_et_valeur_absente_inchangees() -> None:
    naive = datetime(2026, 9, 11, 6, 4, 23)
    assert _bind(naive) == naive
    assert _bind(None) is None


def test_tout_le_schema_est_normalise() -> None:
    """Un modele ajoute plus tard ne doit pas echapper au balayage.

    Sans cette garantie, une seule colonne oubliee suffirait a rompre le
    Bridge sous PostgreSQL, et les tests — qui tournent sous SQLite, plus
    permissif — ne le verraient pas.
    """
    oubliees = [
        f"{table.name}.{column.name}"
        for table in SQLModel.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, DateTime)
        and not isinstance(column.type, UtcDateTime)
        and not column.type.timezone
    ]
    assert not oubliees, f"colonnes date/heure non normalisees : {oubliees}"


def test_le_schema_sql_reste_inchange() -> None:
    """La normalisation porte sur l'ecriture, pas sur le type des colonnes.

    Important : la base PostgreSQL existante ne doit pas avoir besoin d'etre
    migree.
    """
    table = Device.__table__
    for dialect, attendu in ((postgresql.dialect(), "TIMESTAMP"), (sqlite.dialect(), "DATETIME")):
        ddl = str(CreateTable(table).compile(dialect=dialect)).upper()
        assert f"LAST_SEEN_AT {attendu}" in ddl
        assert "WITH TIME ZONE" not in ddl


async def test_aller_retour_en_base(session) -> None:
    """Ecrire une date aware puis la relire doit rendre le meme instant."""
    moment = utcnow()
    session.add(
        Device(
            device_id="test-horodatage",
            token_hash="x" * 64,
            last_seen_at=moment,
        )
    )
    await session.commit()

    result = await session.exec(select(Device).where(Device.device_id == "test-horodatage"))
    relu = result.one()
    assert as_utc(relu.last_seen_at) == moment


async def test_la_date_relue_porte_son_fuseau(session) -> None:
    """Constate sur le telephone : « il y a 1 h » pour une alerte d'il y a 1 min.

    L'API appelle ``.isoformat()`` sur les dates de la base. Sans fuseau,
    l'horodatage publie est muet et le telephone l'interprete dans le sien —
    le decalage vaut alors son propre offset.
    """
    moment = utcnow()
    session.add(Device(device_id="fuseau", token_hash="y" * 64, last_seen_at=moment))
    await session.commit()

    result = await session.exec(select(Device).where(Device.device_id == "fuseau"))
    relu = result.one()
    assert relu.last_seen_at is not None
    assert relu.last_seen_at.tzinfo is not None
    assert relu.last_seen_at.isoformat().endswith("+00:00")
    assert relu.last_seen_at == moment
