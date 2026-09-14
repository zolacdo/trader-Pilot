"""Copie la base SQLite du Bridge vers PostgreSQL, sans rien perdre.

Pourquoi ce script : la base contient des donnees qu'on ne peut pas recreer
facilement — la session Telegram chiffree, les appareils appaires, les canaux
suivis, les reglages de risque et tout l'historique de decisions. Basculer sur
une base vide obligerait a tout reconfigurer.

Usage, depuis la racine du depot :

    bridge\\.venv\\Scripts\\python.exe scripts\\migrate_to_postgres.py
    bridge\\.venv\\Scripts\\python.exe scripts\\migrate_to_postgres.py --dry-run

Le script refuse d'ecraser des donnees existantes sauf avec --force.
Arretez le Bridge avant de le lancer.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
BRIDGE = REPO / "bridge"
sys.path.insert(0, str(BRIDGE))

from app import models  # noqa: F401  (enregistre toutes les tables)
from app.config.settings import get_settings
from sqlalchemy import Integer, func, insert, inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

OK = "[OK]"
KO = "[ERREUR]"
INFO = "[INFO]"


def sqlite_url(settings) -> str:
    chemin = settings.db_path
    if not chemin.exists():
        raise SystemExit(f"{KO} Base SQLite introuvable : {chemin}")
    return f"sqlite+aiosqlite:///{chemin.as_posix()}"


async def compter(engine, table) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(select(func.count()).select_from(table))
        return int(result.scalar() or 0)


async def lire_tout(engine, table) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        result = await conn.execute(select(table))
        return [dict(row._mapping) for row in result]


async def ecrire(engine, table, lignes: list[dict[str, Any]]) -> int:
    """Insere les lignes et retourne le nombre de lignes ecartees.

    SQLite n'appliquait pas toujours les cles etrangeres : la base source peut
    contenir des lignes orphelines. PostgreSQL les refuse, a juste titre. On
    les ecarte une par une plutot que de perdre toute la table.
    """
    if not lignes:
        return 0

    try:
        async with engine.begin() as conn:
            # Par paquets : une insertion unique de milliers de lignes peut
            # depasser la limite de parametres du pilote.
            for debut in range(0, len(lignes), 500):
                await conn.execute(insert(table), lignes[debut : debut + 500])
        return 0
    except IntegrityError:
        pass

    ecartees = 0
    for ligne in lignes:
        try:
            async with engine.begin() as conn:
                await conn.execute(insert(table), [ligne])
        except IntegrityError as exc:
            ecartees += 1
            cle = ligne.get("id", "?")
            raison = str(exc.orig).split("DETAIL:")[-1].strip()[:110]
            print(f"        ligne orpheline ecartee (id={cle}) : {raison}")
    return ecartees


async def recaler_sequences(engine) -> list[str]:
    """Remet les compteurs d'auto-increment au-dela des identifiants copies.

    Sans cela, la premiere insertion PostgreSQL entrerait en conflit avec un
    identifiant deja present.
    """
    recalees: list[str] = []
    async with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            # python_type leve NotImplementedError sur JSON et Enum : on teste
            # le type SQL, qui est la seule chose qui compte pour une sequence.
            colonnes = [
                c
                for c in table.primary_key.columns
                if c.autoincrement and isinstance(c.type, Integer)
            ]
            for colonne in colonnes:
                sequence = await conn.exec_driver_sql(
                    f"SELECT pg_get_serial_sequence('{table.name}', '{colonne.name}')"
                )
                nom = sequence.scalar()
                if not nom:
                    continue
                await conn.exec_driver_sql(
                    f"SELECT setval('{nom}', COALESCE((SELECT MAX({colonne.name}) FROM {table.name}), 0) + 1, false)"
                )
                recalees.append(f"{table.name}.{colonne.name}")
    return recalees


async def migrer(dry_run: bool, force: bool) -> int:
    settings = get_settings()
    if not settings.uses_postgres:
        raise SystemExit(
            f"{KO} PostgreSQL n'est pas configure dans bridge/.env "
            "(DB_HOST, DB_DATABASE, DB_USERNAME, DB_PASSWORD)."
        )

    print(f"{INFO} Source      : {settings.db_path}")
    print(f"{INFO} Destination : {settings.database_label}")
    print()

    source = create_async_engine(sqlite_url(settings), echo=False)
    cible = create_async_engine(settings.database_url, echo=False)

    try:
        # --- schema cible ---
        async with cible.begin() as conn:
            existantes = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            if not dry_run:
                await conn.run_sync(SQLModel.metadata.create_all)

        deja_remplies: list[str] = []
        if existantes:
            for table in SQLModel.metadata.sorted_tables:
                if table.name in existantes and await compter(cible, table):
                    deja_remplies.append(table.name)

        if deja_remplies and not force and not dry_run:
            print(f"{KO} La base PostgreSQL contient deja des donnees :")
            for nom in deja_remplies[:10]:
                print(f"        {nom}")
            print()
            print("        Relancez avec --force pour les remplacer, ou videz la base.")
            return 1

        # --- copie table par table, dans l'ordre des dependances ---
        total = 0
        vides = 0
        orphelines_totales = 0
        for table in SQLModel.metadata.sorted_tables:
            try:
                lignes = await lire_tout(source, table)
            except (OperationalError, ProgrammingError) as exc:
                # Table absente de l'ancienne base : normal pour les tables
                # ajoutees par une version plus recente.
                print(f"{INFO} {table.name:28} ignoree (absente de la source) : {type(exc).__name__}")
                continue

            if not lignes:
                vides += 1
                continue

            if dry_run:
                print(f"{INFO} {table.name:28} {len(lignes):>6} ligne(s) a copier")
            else:
                if force and table.name in deja_remplies:
                    async with cible.begin() as conn:
                        await conn.exec_driver_sql(
                            f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'
                        )
                ecartees = await ecrire(cible, table, lignes)
                copiees = await compter(cible, table)
                attendu = len(lignes) - ecartees
                marque = OK if copiees == attendu else KO
                suffixe = f"  ({ecartees} orpheline(s) ecartee(s))" if ecartees else ""
                print(f"{marque} {table.name:28} {copiees:>6} / {len(lignes)}{suffixe}")
                orphelines_totales += ecartees
            total += len(lignes)

        print()
        print(f"{INFO} {total} ligne(s) au total, {vides} table(s) vide(s)")
        if orphelines_totales:
            print(f"{INFO} {orphelines_totales} ligne(s) orpheline(s) ecartee(s) : "
                  "elles referencaient des enregistrements supprimes.")

        if not dry_run:
            recalees = await recaler_sequences(cible)
            print(f"{INFO} {len(recalees)} compteur(s) d'identifiant recale(s)")
            print()
            print(f"{OK} Migration terminee.")
            print("       Relancez le Bridge : il utilisera desormais PostgreSQL.")
        else:
            print()
            print(f"{INFO} Simulation : aucune ecriture effectuee.")
        return 0
    finally:
        await source.dispose()
        await cible.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migre la base du Bridge de SQLite vers PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", help="Simule sans rien ecrire")
    parser.add_argument("--force", action="store_true", help="Remplace les donnees deja presentes")
    args = parser.parse_args()

    os.environ.pop("TESTING", None)
    return asyncio.run(migrer(args.dry_run, args.force))


if __name__ == "__main__":
    raise SystemExit(main())
