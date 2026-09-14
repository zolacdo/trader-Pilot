"""Le suivi du stop est actif d'origine, et le reste apres mise a jour.

Le mode de suivi valait ``DISABLED``. Un gain pouvait donc monter puis
redescendre jusqu'au stop d'origine sans que rien ne le retienne : le break
even ramenait le stop a l'entree une fois, puis plus rien ne bougeait.

Deux choses a garantir : une installation neuve demarre avec le suivi adosse
a l'ATR, et une installation existante restee sur ``DISABLED`` y bascule sans
que l'utilisateur ait a rouvrir ses reglages.
"""

from __future__ import annotations

from sqlalchemy import text

from app.database.migrations import SCHEMA_VERSION, run_migrations
from app.database.session import get_engine
from app.models.core import RiskSettings
from app.models.enums import TrailingMode
from app.repositories import settings_repo


async def _compte_deja_en_service(session, mode: TrailingMode) -> None:
    """Materialise la ligne de reglages et rembobine la version du schema."""
    settings = await settings_repo.get_risk_settings(session)
    settings.trailing_mode = mode
    session.add(settings)
    await session.commit()
    async with get_engine().begin() as conn:
        await conn.execute(
            text("DELETE FROM schema_migrations WHERE version >= :v"), {"v": 2}
        )


async def _mode_en_base() -> str | None:
    async with get_engine().connect() as conn:
        result = await conn.execute(text("SELECT trailing_mode FROM risk_settings"))
        return result.scalar()


def test_une_installation_neuve_suit_deja_le_prix() -> None:
    assert RiskSettings().trailing_mode is TrailingMode.ATR_BASED


async def test_une_installation_restee_desactivee_bascule(session) -> None:
    """La migration rattrape les comptes deja en service."""
    await _compte_deja_en_service(session, TrailingMode.DISABLED)

    await run_migrations(get_engine())

    assert await _mode_en_base() == TrailingMode.ATR_BASED.value


async def test_un_mode_choisi_par_l_utilisateur_est_respecte(session) -> None:
    """La migration ne remet pas tout le monde sur l'ATR.

    Seul le mode ``DISABLED``, qui etait l'ancien defaut, bascule. Un mode
    choisi volontairement reste en place.
    """
    await _compte_deja_en_service(session, TrailingMode.R_BASED)

    await run_migrations(get_engine())

    assert await _mode_en_base() == TrailingMode.R_BASED.value


def test_la_version_du_schema_a_avance() -> None:
    assert SCHEMA_VERSION >= 2
