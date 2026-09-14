"""Deux signaux simultanes ne doivent pas contourner les plafonds d'exposition.

Les plafonds — ``max_positions``, ``max_positions_per_symbol``,
``max_total_exposure_lots`` — comparent un compte de positions a une limite.
Ils ne valent donc que si deux signaux ne peuvent pas lire l'etat du compte en
meme temps.

Le 14/09/2026, PARAMOUR a publie trois messages XAUUSD en quatre-vingt-dix
secondes. Les trois ont ete evalues en parallele, chacun a lu « aucune position
sur XAUUSDm », et trois positions se sont ouvertes alors que
``max_positions_per_symbol`` valait 1. Deux portaient le meme horodatage
d'ouverture a la microseconde pres — la signature d'une course.

Ce que ces tests mesurent : l'exclusion mutuelle elle-meme. Rejouer le scenario
complet avec trois vraies sessions en parallele n'est pas possible ici — la base
de test est un SQLite en memoire servi par une connexion unique
(``StaticPool``), ou deux transactions concurrentes se marchent dessus. C'est un
artefact de l'environnement de test, absent en production ou chaque session a sa
propre connexion PostgreSQL. On observe donc directement la propriete qui
protege les plafonds : le corps de l'evaluation ne tourne jamais deux fois a la
fois.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.trading.engine import ProcessOutcome, TradingEngine

ENGINE_SOURCE = (
    Path(__file__).resolve().parent.parent / "app" / "services" / "trading" / "engine.py"
)


class CompteurDeChevauchement:
    """Remplace le corps de l'evaluation et note s'il tourne en double.

    Le ``sleep(0)`` rend la main a la boucle : sans verrou, la tache suivante
    entre pendant que la premiere est encore la, et ``maximum`` monte a deux.
    """

    def __init__(self) -> None:
        self.en_cours = 0
        self.maximum = 0

    async def __call__(self, *args: object, **kwargs: object) -> ProcessOutcome:
        self.en_cours += 1
        self.maximum = max(self.maximum, self.en_cours)
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return ProcessOutcome(stage="ignored", detail="sonde")
        finally:
            self.en_cours -= 1


class TestSerialisationEffective:
    async def test_deux_evaluations_simultanees_ne_se_chevauchent_pas(self) -> None:
        """Le cas reel, reduit a ce qui compte : deux appels en parallele."""
        engine = TradingEngine()
        sonde = CompteurDeChevauchement()
        engine._process_signal = sonde  # type: ignore[method-assign]

        await asyncio.gather(
            engine.process_signal(None, None),  # type: ignore[arg-type]
            engine.process_signal(None, None),  # type: ignore[arg-type]
        )

        assert sonde.maximum == 1, (
            f"{sonde.maximum} evaluations simultanees : les plafonds d'exposition "
            "peuvent etre franchis"
        )

    async def test_trois_evaluations_simultanees_non_plus(self) -> None:
        """Trois messages, comme PARAMOUR en a publie ce jour-la."""
        engine = TradingEngine()
        sonde = CompteurDeChevauchement()
        engine._process_signal = sonde  # type: ignore[method-assign]

        await asyncio.gather(
            *(engine.process_signal(None, None) for _ in range(3))  # type: ignore[arg-type]
        )

        assert sonde.maximum == 1

    async def test_la_sonde_verrait_le_defaut(self) -> None:
        """Temoin : sans le verrou, le chevauchement est bien detecte.

        Sans ce test, les deux precedents passeraient meme si la sonde etait
        incapable de voir quoi que ce soit.
        """
        sonde = CompteurDeChevauchement()

        await asyncio.gather(sonde(), sonde(), sonde())

        assert sonde.maximum == 3


class TestSerialisation:
    def test_l_evaluation_est_bien_sous_verrou(self) -> None:
        """Verrouille le cablage : un refactor ne doit pas reperdre le verrou."""
        code = ENGINE_SOURCE.read_text(encoding="utf-8")
        assert "async with self._lock:\n            return await self._process_signal(" in code

    def test_l_analyse_reste_concurrente(self) -> None:
        """Seule l'execution est serialisee.

        Analyser peut attendre une reponse d'IA pendant plusieurs secondes :
        tenir le verrou pendant ce temps figerait tout le moteur.
        """
        code = ENGINE_SOURCE.read_text(encoding="utf-8")
        debut = code.index("async def handle_message")
        fin = code.index("async def process_signal")
        assert "self._lock" not in code[debut:fin]
