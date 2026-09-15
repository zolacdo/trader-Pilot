"""Les comptes deja en service sont rattrapes sans rouvrir les reglages.

Deux corrections du 14/09/2026 laissent derriere elles des donnees qui
mentent, et qu'une installation existante ne verra jamais disparaitre toute
seule :

1. ``dynamic_risk_floor`` a 1,0 neutralisait la modulation du risque tout en
   l'affichant active ;
2. les ``r_multiple`` deja inscrits ont ete calcules par une formule
   dimensionnellement fausse -- un resultat en dollars divise par une distance
   de prix. Ils alimentent ``learning/performance.py``, qui en fait des sommes.
   Un seul -100000 suffit a detruire l'agregat de son canal.
"""

from __future__ import annotations

from sqlalchemy import text

from app.database.migrations import run_migrations
from app.database.session import get_engine
from app.models.core import RiskSettings
from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import TradeRecord
from app.repositories import settings_repo
from app.services.risk.quality import DEFAULT_QUALITY_FLOOR, MAX_QUALITY_FLOOR


async def _rembobine_le_schema(version: int) -> None:
    async with get_engine().begin() as conn:
        await conn.execute(
            text("DELETE FROM schema_migrations WHERE version >= :v"), {"v": version}
        )


async def _plancher_en_base() -> float | None:
    async with get_engine().connect() as conn:
        result = await conn.execute(text("SELECT dynamic_risk_floor FROM risk_settings"))
        return result.scalar()


async def _r_multiples_en_base() -> list[float | None]:
    async with get_engine().connect() as conn:
        result = await conn.execute(text("SELECT r_multiple FROM trades ORDER BY id"))
        return [row[0] for row in result.fetchall()]


async def _compte_avec_plancher(session, plancher: float) -> None:
    settings = await settings_repo.get_risk_settings(session)
    settings.dynamic_risk_floor = plancher
    settings.dynamic_risk_enabled = True
    session.add(settings)
    await session.commit()
    await _rembobine_le_schema(3)


class TestPlancherNeutralisant:
    def test_une_installation_neuve_module_deja(self) -> None:
        assert RiskSettings().dynamic_risk_floor == DEFAULT_QUALITY_FLOOR

    async def test_un_plancher_neutralisant_est_ramene_a_sa_borne(self, session) -> None:
        await _compte_avec_plancher(session, 1.0)

        await run_migrations(get_engine())

        assert await _plancher_en_base() == MAX_QUALITY_FLOOR

    async def test_un_plancher_choisi_par_lutilisateur_est_respecte(self, session) -> None:
        """La migration ne remet personne d'autorite sur le defaut."""
        await _compte_avec_plancher(session, 0.50)

        await run_migrations(get_engine())

        assert await _plancher_en_base() == 0.50


class TestRMultiplesFausses:
    async def _trades_du_14_septembre(self, session) -> None:
        """Quatre positions reelles, avec les R que l'ancienne formule a ecrits."""
        valeurs = [
            ("XAUUSDm", 4267.0, 4255.0, 0.04, -48.0, -100.0),
            ("EURUSDm", 1.15262, 1.15387, 0.34, -43.18, -100000.0),
            ("US30m", 52350.0, 52220.0, 0.29, 36.6, 0.971),
            ("XAUUSDm", 4286.916, 4275.0, 0.01, 0.25, 2.098),
        ]
        for index, (symbole, entree, stop, volume, resultat, r) in enumerate(valeurs):
            session.add(
                TradeRecord(
                    ticket=3225201437 + index,
                    symbol=symbole,
                    direction=Direction.BUY,
                    execution_mode=ExecutionMode.MT5_DEMO,
                    state=PositionState.CLOSED,
                    open_price=entree,
                    initial_stop_loss=stop,
                    initial_volume=volume,
                    volume=volume,
                    realized_pnl=resultat,
                    r_multiple=r,
                )
            )
        await session.commit()
        await _rembobine_le_schema(4)

    async def test_les_valeurs_calculees_par_lancienne_formule_sont_effacees(
        self, session
    ) -> None:
        """Un R faux pollue les agregats plus surement qu'un trou.

        On n'en recalcule aucun : la valeur exacte demande la taille du
        contrat, que seule MetaTrader connait. Les colonnes brutes restent
        intactes, le chiffre reste donc reconstituable.
        """
        await self._trades_du_14_septembre(session)

        await run_migrations(get_engine())

        assert await _r_multiples_en_base() == [None, None, None, None]

    async def test_les_donnees_brutes_de_la_position_sont_intactes(self, session) -> None:
        await self._trades_du_14_septembre(session)

        await run_migrations(get_engine())

        async with get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT open_price, initial_stop_loss, initial_volume, realized_pnl "
                    "FROM trades ORDER BY id LIMIT 1"
                )
            )
            ligne = result.fetchone()
        assert ligne is not None
        assert list(ligne) == [4267.0, 4255.0, 0.04, -48.0]
