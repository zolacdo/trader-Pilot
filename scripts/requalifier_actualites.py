"""Reclasse les actualites deja stockees avec le vocabulaire courant.

Pourquoi : le niveau d'impact est fige a la collecte. Quand le vocabulaire est
corrige — par exemple parce que « rate hike » classait en critique un simple
commentaire sur des probabilites — les depeches deja en base gardent leur
ancien niveau et continuent de bloquer le systeme jusqu'a ce qu'elles sortent
de la fenetre d'analyse.

Ce script rejoue uniquement la regle deterministe, celle-la meme qu'applique
``NewsRelevanceEngine._detect_impact``. Il ne reinvente rien et n'appelle
aucun moteur d'intelligence artificielle.

Usage, depuis la racine du depot :

    bridge\\.venv\\Scripts\\python.exe scripts\\requalifier_actualites.py --dry-run
    bridge\\.venv\\Scripts\\python.exe scripts\\requalifier_actualites.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bridge"))

from app import models  # noqa: E402,F401  (enregistre les tables)
from app.config.settings import get_settings  # noqa: E402
from app.database.session import dispose_engine, session_scope  # noqa: E402
from app.models.intelligence import NewsEvent, NewsImpact  # noqa: E402
from app.services.news.taxonomy import (  # noqa: E402
    CRITICAL_KEYWORDS,
    HIGH_KEYWORDS,
    MEDIUM_KEYWORDS,
    find_keywords,
    normalize,
)
from sqlmodel import select  # noqa: E402


def niveau_pour(event: NewsEvent) -> tuple[NewsImpact, str]:
    """Meme regle que le prefiltre de collecte, sur le texte deja stocke."""
    texte = normalize(f"{event.title} {event.summary or ''}")
    for mots, niveau, libelle in (
        (CRITICAL_KEYWORDS, NewsImpact.CRITICAL, "critiques"),
        (HIGH_KEYWORDS, NewsImpact.HIGH, "à fort impact"),
        (MEDIUM_KEYWORDS, NewsImpact.MEDIUM, "d'impact modéré"),
    ):
        trouves = find_keywords(texte, mots)
        if trouves:
            return niveau, f"mots-clés {libelle} repérés ({', '.join(trouves[:3])})"
    if event.source and event.affected_assets:
        return NewsImpact.MEDIUM, "source institutionnelle citant un instrument suivi"
    return NewsImpact.LOW, "aucun mot-clé d'impact identifié : impact non déterminable, laissé à LOW"


async def requalifier(dry_run: bool) -> int:
    print(f"[INFO] Base : {get_settings().database_label}")
    changements = 0
    total = 0

    async with session_scope() as session:
        result = await session.exec(select(NewsEvent))
        for event in result.all():
            total += 1
            niveau, motif = niveau_pour(event)
            if niveau is event.impact:
                continue
            changements += 1
            fleche = f"{event.impact.value} -> {niveau.value}"
            print(f"  {fleche:24} {event.title[:70]}")
            if not dry_run:
                event.impact = niveau
                event.reason = f"Requalification déterministe : {motif}"[:500]
                session.add(event)

    print()
    print(f"[INFO] {total} actualité(s) examinée(s), {changements} reclassée(s)")
    if dry_run:
        print("[INFO] Simulation : aucune écriture effectuée.")
    await dispose_engine()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Simule sans rien écrire")
    args = parser.parse_args()
    os.environ.pop("TESTING", None)
    return asyncio.run(requalifier(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
