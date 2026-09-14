"""Une surveillance en cours se suit ; elle ne se republie pas.

Mesure du 13/09/2026 : BTCUSD est reste en WATCH_BUY sans interruption de
05:31 a 06:07, soit vingt-cinq analyses consecutives a 90 secondes d'ecart.
Repeter l'annonce a chaque tour n'apprend rien au lecteur et noie le canal --
et surtout, cela laisse croire a plusieurs occasions distinctes la ou il n'y
en a qu'une, toujours la meme.

La surveillance se clot des qu'une analyse posterieure conclut autre chose :
le marche a franchi son declencheur, il est retombe, ou il a change de sens.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.watcher import repository
from app.watcher.models import RiskVerdict, VolatilityLevel, WatcherDecision

SYMBOLE = "BTCUSD"


async def _analyse(
    session: AsyncSession,
    decision: WatcherDecision,
    *,
    alerte: bool = False,
    score: float = 60.0,
    decalage_minutes: int = 0,
) -> None:
    """Enregistre une analyse, en forcant sa date pour ordonner le recit."""
    analyse = await repository.record_analysis(
        session,
        symbol=SYMBOLE,
        decision=decision,
        score=score,
        bias="NEUTRAL",
        price=100.0,
        volatility=VolatilityLevel.NORMAL,
        risk_verdict=RiskVerdict.APPROVED,
        alert_sent=alerte,
    )
    if decalage_minutes:
        analyse.created_at = utcnow() + timedelta(minutes=decalage_minutes)
        session.add(analyse)
        await session.flush()


class TestSurveillanceOuverte:
    async def test_sans_aucune_alerte_rien_n_est_ouvert(self, session: AsyncSession) -> None:
        assert await repository.watch_still_open(session, SYMBOLE) is None

    async def test_une_alerte_recente_tient_la_surveillance_ouverte(
        self, session: AsyncSession
    ) -> None:
        await _analyse(session, WatcherDecision.WATCH_BUY, alerte=True)

        assert await repository.watch_still_open(session, SYMBOLE) == "WATCH_BUY"

    async def test_la_repetition_du_meme_etat_ne_clot_pas_la_surveillance(
        self, session: AsyncSession
    ) -> None:
        """Le cas reel : vingt-cinq WATCH_BUY d'affilee restent une surveillance."""
        await _analyse(session, WatcherDecision.WATCH_BUY, alerte=True)
        for minute in range(1, 6):
            await _analyse(session, WatcherDecision.WATCH_BUY, decalage_minutes=minute)

        assert await repository.watch_still_open(session, SYMBOLE) == "WATCH_BUY"

    async def test_un_retour_au_calme_clot_la_surveillance(
        self, session: AsyncSession
    ) -> None:
        await _analyse(session, WatcherDecision.WATCH_BUY, alerte=True)
        await _analyse(session, WatcherDecision.NO_TRADE, decalage_minutes=5)

        assert await repository.watch_still_open(session, SYMBOLE) is None

    async def test_un_changement_de_sens_clot_la_surveillance(
        self, session: AsyncSession
    ) -> None:
        """Surveiller une hausse puis une baisse, ce sont deux sujets distincts."""
        await _analyse(session, WatcherDecision.WATCH_BUY, alerte=True)
        await _analyse(session, WatcherDecision.WATCH_SELL, decalage_minutes=5)

        assert await repository.watch_still_open(session, SYMBOLE) is None

    async def test_un_autre_instrument_n_influence_rien(
        self, session: AsyncSession
    ) -> None:
        await _analyse(session, WatcherDecision.WATCH_BUY, alerte=True)
        await repository.record_analysis(
            session,
            symbol="ETHUSD",
            decision=WatcherDecision.NO_TRADE,
            score=10.0,
            bias="NEUTRAL",
            price=100.0,
            volatility=VolatilityLevel.NORMAL,
            risk_verdict=RiskVerdict.APPROVED,
        )

        assert await repository.watch_still_open(session, SYMBOLE) == "WATCH_BUY"
        assert await repository.watch_still_open(session, "ETHUSD") is None

    async def test_une_analyse_anterieure_ne_clot_pas_la_surveillance(
        self, session: AsyncSession
    ) -> None:
        """Seule la suite compte : le passe ne peut pas clore le present."""
        await _analyse(session, WatcherDecision.NO_TRADE, decalage_minutes=-10)
        await _analyse(session, WatcherDecision.WATCH_BUY, alerte=True)

        assert await repository.watch_still_open(session, SYMBOLE) == "WATCH_BUY"


def _lisible(texte: str) -> str:
    """Rend le texte comparable : le formateur separe les milliers par une
    espace fine insecable (U+202F), invisible mais differente d'une espace."""
    return texte.replace("\u202f", " ").replace("\u00a0", " ")


# ---------------------------------------------------------------------------
# Le message doit dire QUEL sens il guette
# ---------------------------------------------------------------------------
class TestMessageDeSurveillance:
    """Cas reel du 13/09/2026, signale par l'utilisateur.

    BTCUSD etait sous surveillance a la VENTE, declencheur sous 77 035.22. Le
    message affichait pourtant aussi « Confirmation achat : > 77 103.55 »,
    alors que le prix cotait deja 77 131.90. Le lecteur voyait donc un seuil
    d'achat deja franchi et attendait un signal qui ne pouvait pas venir : ce
    n'etait pas ce sens-la qu'on surveillait.
    """

    def test_une_surveillance_vente_ne_montre_que_le_seuil_vente(self) -> None:
        from app.models.enums import Direction
        from app.watcher import formatter

        texte = formatter.watch_message(
            symbol="BTCUSD",
            current_price=77131.90,
            score=55.5,
            buy_trigger=77103.55,
            sell_trigger=77035.22,
            digits=2,
            direction=Direction.SELL,
        )

        lisible = _lisible(texte)
        assert "SURVEILLANCE VENTE" in lisible
        assert "77 035.22" in lisible
        assert "77 103.55" not in lisible, "le seuil du sens oppose ne doit pas figurer"
        assert "Confirmation achat" not in lisible

    def test_une_surveillance_achat_ne_montre_que_le_seuil_achat(self) -> None:
        from app.models.enums import Direction
        from app.watcher import formatter

        texte = formatter.watch_message(
            symbol="BTCUSD",
            current_price=77000.0,
            score=60.0,
            buy_trigger=77103.55,
            sell_trigger=77035.22,
            digits=2,
            direction=Direction.BUY,
        )

        lisible = _lisible(texte)
        assert "SURVEILLANCE ACHAT" in lisible
        assert "77 103.55" in lisible
        assert "77 035.22" not in lisible

    def test_la_levee_dit_que_le_declencheur_n_a_pas_ete_touche(self) -> None:
        """Sans ce message, « reevalue a la confirmation » reste une promesse en l'air."""
        from app.models.enums import Direction
        from app.watcher import formatter

        texte = formatter.watch_closed_message(
            symbol="BTCUSD",
            direction=Direction.SELL,
            trigger=77035.22,
            current_price=77100.96,
            digits=2,
            reason="Score 50.4 sous le minimum exige (70.0).",
        )

        lisible = _lisible(texte)
        assert "SURVEILLANCE LEV" in lisible
        assert "pas ete touche" in lisible
        assert "77 035.22" in lisible
        assert "plus surveille" in lisible

    def test_la_confirmation_relie_le_signal_a_sa_surveillance(self) -> None:
        """Une surveillance doit raconter ses DEUX issues, pas seulement l'echec.

        Sans ce message, la seule trace d'une confirmation etait le signal
        lui-meme, et rien ne le reliait a la surveillance annoncee plus tot.
        """
        from app.models.enums import Direction
        from app.watcher import formatter

        texte = formatter.watch_confirmed_message(
            symbol="BTCUSD",
            direction=Direction.SELL,
            trigger=77035.22,
            current_price=77020.10,
            digits=2,
        )

        lisible = _lisible(texte)
        assert "SURVEILLANCE CONFIRM" in lisible
        assert "a ete touche" in lisible
        assert "77 035.22" in lisible
        assert "signal correspondant suit" in lisible

    def test_les_deux_issues_ne_disent_pas_la_meme_chose(self) -> None:
        """Confondre « confirmee » et « levee » serait pire que le silence."""
        from app.models.enums import Direction
        from app.watcher import formatter

        confirmee = formatter.watch_confirmed_message(
            symbol="BTCUSD",
            direction=Direction.BUY,
            trigger=77103.55,
            current_price=77150.0,
            digits=2,
        )
        levee = formatter.watch_closed_message(
            symbol="BTCUSD",
            direction=Direction.BUY,
            trigger=77103.55,
            current_price=77000.0,
            digits=2,
        )

        assert "CONFIRM" in confirmee and "LEV" not in confirmee
        assert "LEV" in levee and "CONFIRM" not in levee
        assert "n'a pas ete touche" in levee
        assert "n'a pas ete touche" not in confirmee


class TestSignalPublieNEstPasUneSurveillance:
    """``alert_sent`` est vrai pour TOUTE publication, signal compris.

    Sans distinguer la decision, un signal publie passait pour une
    surveillance ouverte : le tour suivant annoncait une « surveillance
    levee » qui n'avait jamais commence, et bloquait au passage toute vraie
    alerte de surveillance sur cet instrument.
    """

    async def test_un_signal_publie_n_ouvre_aucune_surveillance(
        self, session: AsyncSession
    ) -> None:
        await _analyse(session, WatcherDecision.SELL, alerte=True, score=78.0)

        assert await repository.watch_still_open(session, SYMBOLE) is None

    async def test_une_surveillance_anterieure_a_un_signal_reste_visible(
        self, session: AsyncSession
    ) -> None:
        """Le filtre porte sur la decision, pas sur l'ordre des lignes."""
        await _analyse(session, WatcherDecision.WATCH_BUY, alerte=True)

        assert await repository.watch_still_open(session, SYMBOLE) == "WATCH_BUY"
