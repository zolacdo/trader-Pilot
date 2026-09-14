"""Configure la source du calendrier economique (CDC2 section 33).

Source retenue : le flux hebdomadaire de Forex Factory, publie sur
``nfs.faireconomy.media``. Raisons du choix :

* il est public et ne demande ni cle, ni compte, ni contournement ;
* son ``robots.txt`` n'interdit rien (``Disallow:`` vide) ;
* il est au format JSON, stable depuis des annees, et couvre toutes les
  devises majeures avec prevision et valeur precedente ;
* il porte un niveau d'importance (Low / Medium / High / Holiday) qui
  correspond directement aux trois niveaux du CDC2.

Particularites prises en compte dans la configuration ci-dessous :

* le champ nomme ``country`` contient en realite un code de devise (« AUD »,
  « USD ») : il alimente donc ``currency``, et le pays est declare absent
  plutot que rempli avec une valeur fausse ;
* la source ne fournit aucun identifiant : le provider en derive un a partir
  de l'intitule et de l'horaire, stable d'un rafraichissement a l'autre.

Usage, depuis la racine du depot :

    bridge\\.venv\\Scripts\\python.exe scripts\\configurer_calendrier.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bridge"))

from app import models  # noqa: E402,F401
from app.config.settings import get_settings  # noqa: E402
from app.database.session import dispose_engine, session_scope  # noqa: E402
from app.services.economic_calendar.engine import economic_calendar_engine  # noqa: E402
from app.services.economic_calendar.sources import (  # noqa: E402
    CalendarSource,
    load_options,
    save_sources,
)

SOURCE = CalendarSource(
    key="forexfactory",
    name="Forex Factory — calendrier de la semaine",
    url="https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    enabled=True,
    items_path="",
    field_map={
        "external_id": "",  # la source n'en fournit pas
        "scheduled_at": "date",
        "title": "title",
        "currency": "country",  # le champ « country » porte le code devise
        "country": "",  # pas de pays reel : on ne le devine pas
        "impact": "impact",
        "forecast": "forecast",
        "previous": "previous",
        "actual": "actual",
    },
    impact_map={
        "low": "LOW",
        "medium": "MEDIUM",
        "high": "HIGH",
        "holiday": "LOW",
        "non-economic": "LOW",
    },
)


async def main() -> int:
    print(f"[INFO] Base : {get_settings().database_label}")
    async with session_scope() as session:
        await save_sources(session, [SOURCE])
        options = await load_options(session)
        print(f"[OK]   Source enregistree : {SOURCE.name}")
        print(f"       Rappels avant evenement : {sorted(options.notify_offsets)} minutes")

        rapport = await economic_calendar_engine.refresh(session)
        print()
        print(f"[INFO] {rapport.fetched} evenement(s) lu(s)")
        print(f"[INFO] {rapport.created} cree(s), {rapport.updated} mis a jour")
        for erreur in rapport.errors:
            print(f"[ERREUR] {erreur}")

    await dispose_engine()
    return 0


if __name__ == "__main__":
    os.environ.pop("TESTING", None)
    raise SystemExit(asyncio.run(main()))
