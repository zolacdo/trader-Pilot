"""Remet la liste des flux d'actualites sur la configuration courante.

Les sources sont enregistrees en base au premier demarrage. Corriger la liste
par defaut dans le code ne suffit donc pas : les anciennes adresses restent
stockees et continuent d'echouer a chaque collecte.

Ce script applique la liste du code, en conservant les flux que vous avez
ajoutes vous-meme et l'interrupteur de chaque flux connu.

Usage, depuis la racine du depot :

    bridge\\.venv\\Scripts\\python.exe scripts\\reparer_sources_actualites.py
    bridge\\.venv\\Scripts\\python.exe scripts\\reparer_sources_actualites.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bridge"))

from app import models  # noqa: E402,F401
from app.config.settings import get_settings  # noqa: E402
from app.database.session import dispose_engine, session_scope  # noqa: E402
from app.services.news.sources import (  # noqa: E402
    DEFAULT_SOURCES,
    load_sources,
    save_sources,
)

# Flux qui faisaient partie des sources livrees et qui ont ete retires. Sans
# cette liste, ils seraient pris pour des ajouts de l'utilisateur et
# conserves indefiniment alors qu'ils echouent a chaque collecte.
RETIREES: dict[str, str] = {
    "imf_news": "le site du FMI refuse les lectures automatisees (HTTP 403)",
    "yahoo_finance": "articles vieux d'un jour et demi",
    "bea_releases": "mediane des articles superieure a un an",
    "bis_speeches": "aucune date d'article lisible dans le flux",
    "cnbc_finance": "mediane des articles a huit jours, remplace par CNBC a la une",
}


async def main(dry_run: bool) -> int:
    print(f"[INFO] Base : {get_settings().database_label}")
    async with session_scope() as session:
        stockees = {source.key: source for source in await load_sources(session)}
        officielles = {source.key: source for source in DEFAULT_SOURCES}

        finales = []
        for cle, reference in officielles.items():
            ancienne = stockees.get(cle)
            if ancienne is None:
                print(f"[NOUVEAU]  {reference.name}")
            else:
                if ancienne.url != reference.url:
                    print(f"[ADRESSE]  {reference.name}")
                    print(f"           {ancienne.url}")
                    print(f"        -> {reference.url}")
                # L'interrupteur appartient a l'utilisateur : on le conserve.
                reference.enabled = ancienne.enabled
            finales.append(reference)

        for cle, source in stockees.items():
            if cle in officielles:
                continue
            motif = RETIREES.get(cle)
            if motif:
                print(f"[RETIRE]   {source.name} : {motif}")
                continue
            print(f"[CONSERVE] {source.name} (ajoute a la main)")
            finales.append(source)

        print()
        print(f"[INFO] {len(finales)} flux au total.")
        if dry_run:
            print("[INFO] Simulation : aucune ecriture effectuee.")
        else:
            await save_sources(session, finales)
            print("[OK]   Liste enregistree.")

    await dispose_engine()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Simule sans rien ecrire")
    args = parser.parse_args()
    os.environ.pop("TESTING", None)
    raise SystemExit(asyncio.run(main(args.dry_run)))
