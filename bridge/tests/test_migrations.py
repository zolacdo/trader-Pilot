"""Migrations legeres : idempotence et portabilite entre SQLite et PostgreSQL.

Le Bridge tourne desormais sur PostgreSQL en production et sur SQLite en
memoire pendant les tests. Tout ce que font les migrations doit donc etre
accepte par les deux moteurs.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import text

from app.database.migrations import SCHEMA_VERSION, database_version, run_migrations
from app.database.session import get_engine, init_database

MIGRATIONS_SOURCE = Path(__file__).resolve().parent.parent / "app" / "database" / "migrations.py"


async def test_migrations_appliquees_a_la_creation(session) -> None:
    assert await database_version(get_engine()) == SCHEMA_VERSION


async def test_migrations_rejouables_sans_doublon(session) -> None:
    """Un second demarrage ne doit ni echouer ni empiler les versions.

    C'est le chemin reel : le Bridge rejoue les migrations a chaque
    lancement.
    """
    engine = get_engine()
    await run_migrations(engine)
    await run_migrations(engine)

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE version = :v"),
            {"v": SCHEMA_VERSION},
        )
        assert result.scalar() == 1
    assert await database_version(engine) == SCHEMA_VERSION


async def test_init_database_deux_fois_de_suite() -> None:
    """La creation du schema suivie des migrations doit rester rejouable."""
    await init_database()
    await init_database()
    assert await database_version(get_engine()) == SCHEMA_VERSION


def test_aucun_parametre_passe_en_sql_brut() -> None:
    """``exec_driver_sql`` transmet la requete telle quelle au pilote.

    Chaque pilote attend sa propre syntaxe de parametre : ``?`` pour SQLite,
    ``$1`` pour asyncpg. Passer des parametres par ce chemin a deja empeche
    le Bridge de demarrer sur PostgreSQL (erreur de syntaxe sur ``%``). Les
    requetes parametrees doivent passer par ``conn.execute(text(...), {...})``,
    que SQLAlchemy traduit pour le moteur en place.
    """
    arbre = ast.parse(MIGRATIONS_SOURCE.read_text(encoding="utf-8"))
    fautifs = [
        node.lineno
        for node in ast.walk(arbre)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exec_driver_sql"
        and (len(node.args) > 1 or node.keywords)
    ]
    assert not fautifs, f"parametres passes en SQL brut, lignes {fautifs}"


def test_le_defaut_d_une_colonne_booleenne_est_portable() -> None:
    """Constat : PostgreSQL refuse « DEFAULT 1 » sur une colonne booleenne.

    Les migrations tournent au demarrage. Ecrire 1/0 partout passait les
    tests — qui utilisent SQLite — et aurait empeche le Bridge de se lancer
    en production des la prochaine colonne booleenne ajoutee a un modele.
    """
    from sqlalchemy import Boolean, Column

    from app.database.migrations import _render_default

    vrai = Column("actif", Boolean, default=True)
    faux = Column("actif", Boolean, default=False)

    assert _render_default(vrai, "postgresql") == "TRUE"
    assert _render_default(faux, "postgresql") == "FALSE"
    assert _render_default(vrai, "sqlite") == "1"
    assert _render_default(faux, "sqlite") == "0"


def test_les_autres_types_restent_inchanges() -> None:
    from sqlalchemy import Column, Float, Integer, String

    from app.database.migrations import _render_default

    assert _render_default(Column("n", Integer, default=7), "postgresql") == "7"
    assert _render_default(Column("x", Float, default=1.5), "postgresql") == "1.5"
    assert _render_default(Column("s", String, default="oui"), "postgresql") == "\'oui\'"
    # Une apostrophe dans la valeur ne doit pas casser la requete.
    assert _render_default(Column("s", String, default="l\'or"), "postgresql") == "\'l\'\'or\'"
    assert _render_default(Column("v", Integer), "postgresql") == "NULL"


# ---------------------------------------------------------------------------
# Valeurs d'enum : le trou que SQLite ne peut pas reveler
# ---------------------------------------------------------------------------
async def test_les_valeurs_d_enum_sont_synchronisees_au_demarrage(session) -> None:
    """La synchronisation doit etre cablee dans le chemin de demarrage.

    SQLite range les enums en texte : une valeur ajoutee cote Python y marche
    tout de suite. PostgreSQL cree un vrai type ENUM et refuse l'inconnu. Le
    14/09/2026, l'ajout de TrailingMode.ATR_BASED a passe 1942 tests puis a
    echoue en production. Aucun test SQLite ne peut reproduire ce refus : on
    verifie donc que la synchronisation est bien appelee.
    """
    source = MIGRATIONS_SOURCE.read_text(encoding="utf-8")
    arbre = ast.parse(source)
    corps = next(
        noeud
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.FunctionDef) and noeud.name == "_run_sync"
    )
    appels = {
        noeud.func.id
        for noeud in ast.walk(corps)
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
    }
    assert "_sync_enum_values" in appels


async def test_la_synchronisation_des_enums_ne_touche_pas_sqlite(session) -> None:
    """Sur SQLite il n'y a pas de type ENUM : la fonction doit s'abstenir."""
    from app.database.migrations import _sync_enum_values

    engine = get_engine()
    async with engine.begin() as conn:
        ajoutees = await conn.run_sync(_sync_enum_values)
    assert ajoutees == []


def test_la_valeur_d_enum_est_echappee_avant_le_sql() -> None:
    """Un libelle d'enum entre dans du DDL : il doit etre echappe."""
    source = MIGRATIONS_SOURCE.read_text(encoding="utf-8")
    debut = source.index("def _sync_enum_values")
    fin = source.index("def _current_version")
    corps = source[debut:fin]
    assert 'replace("\'", "\'\'")' in corps
    assert "ADD VALUE IF NOT EXISTS" in corps, "l'ajout doit rester idempotent"
