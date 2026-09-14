"""Une pause arrivee a echeance ne doit plus s'afficher comme une pause.

Le coupe-circuit pose une pause datee. Le RiskManager respectait bien cette
date -- il laissait repasser les ordres une fois l'echeance franchie -- mais le
drapeau ``paused`` restait vrai en base, et c'est celui-la que l'application
lit. Le 13/09/2026, le telephone annoncait encore « trader auto en pause »
treize heures apres la fin de la pause, alors que le moteur, lui, aurait
accepte un ordre.

Deux verites pour un seul etat : c'est cette divergence que ces tests ferment.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.repositories import settings_repo


async def _poser_pause(
    session: AsyncSession, *, echeance_minutes: int | None, motif: str = "3 pertes consecutives"
) -> None:
    state = await settings_repo.get_trading_state(session)
    state.paused = True
    state.pause_reason = motif
    state.paused_until = (
        utcnow() + timedelta(minutes=echeance_minutes) if echeance_minutes is not None else None
    )
    await settings_repo.save_trading_state(session, state)


class TestPauseEchue:
    async def test_une_pause_depassee_est_levee(self, session: AsyncSession) -> None:
        """Le cas reel : echeance franchie depuis treize heures."""
        await _poser_pause(session, echeance_minutes=-13 * 60)

        state = await settings_repo.get_trading_state(session)

        assert state.paused is False
        assert state.pause_reason is None
        assert state.paused_until is None

    async def test_une_pause_qui_vient_d_expirer_est_levee(
        self, session: AsyncSession
    ) -> None:
        await _poser_pause(session, echeance_minutes=-1)

        state = await settings_repo.get_trading_state(session)

        assert state.paused is False

    async def test_la_levee_est_ecrite_en_base(self, session: AsyncSession) -> None:
        """Sinon l'affichage se corrigerait a la lecture et rien ne changerait."""
        await _poser_pause(session, echeance_minutes=-60)

        await settings_repo.get_trading_state(session)
        session.expire_all()
        relu = await settings_repo.get_trading_state(session)

        assert relu.paused is False


class TestPauseEncoreValide:
    async def test_une_pause_en_cours_est_conservee(self, session: AsyncSession) -> None:
        """Lever une pause encore valide serait bien pire que l'inverse."""
        await _poser_pause(session, echeance_minutes=30)

        state = await settings_repo.get_trading_state(session)

        assert state.paused is True
        assert state.pause_reason == "3 pertes consecutives"

    async def test_une_pause_sans_echeance_ne_s_eteint_jamais_seule(
        self, session: AsyncSession
    ) -> None:
        """Une pause posee a la main se leve a la main, pas par le temps."""
        await _poser_pause(session, echeance_minutes=None, motif="Arret demande")

        state = await settings_repo.get_trading_state(session)

        assert state.paused is True
        assert state.pause_reason == "Arret demande"

    async def test_un_etat_sans_pause_reste_intact(self, session: AsyncSession) -> None:
        state = await settings_repo.get_trading_state(session)
        state.paused = False
        state.paused_until = utcnow() - timedelta(hours=5)
        await settings_repo.save_trading_state(session, state)

        relu = await settings_repo.get_trading_state(session)

        assert relu.paused is False
