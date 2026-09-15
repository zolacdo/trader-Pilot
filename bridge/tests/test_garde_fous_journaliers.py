"""Les garde-fous journaliers doivent survivre a la cloture d'une position.

Constate en production le 14/09/2026 : le compte est passe de 540,41 a 386,38
dollars dans la journee (-28,5 %) avec ``max_daily_loss_percent = 50`` et
``max_drawdown_percent = 10``. Aucun des deux garde-fous ne s'est declenche,
et ``day_start_balance`` valait toujours 540,41 pour un solde de 386,38.

La cause n'est pas dans les garde-fous eux-memes mais dans l'ordre du cycle de
suivi. ``ensure_day_rollover`` recevait le solde du courtier -- deja ampute de
la perte -- avant que ``_apply_closed_trades`` n'ait ajoute cette perte a
``day_realized_pnl``. Le detecteur de mouvement externe voyait donc un ecart de
la taille exacte du trade, concluait a un depot ou un retrait, reecrivait
``day_start_balance`` et effacait ``peak_equity``.

Plus la perte etait grosse, plus surement elle depassait la tolerance et
effacait la memoire des garde-fous charges de l'arreter. Les quatre pertes du
14/09 (-48, -40, -43,18, -36,08) depassaient toutes largement les 5 % du solde.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import settings_repo


async def _etat_du_jour(
    session: AsyncSession,
    *,
    solde_du_matin: float,
    realise: float,
    plus_haut: float | None,
) -> None:
    etat = await settings_repo.get_trading_state(session)
    etat.day_key = settings_repo.today_key()
    etat.day_start_balance = solde_du_matin
    etat.day_realized_pnl = realise
    etat.peak_equity = plus_haut
    await settings_repo.save_trading_state(session, etat)


class TestClotureNonEncoreComptabilisee:
    """Le cas exact du 14/09 : le solde a bouge, le compteur pas encore."""

    async def test_le_repere_du_matin_ne_bouge_pas(self, session: AsyncSession) -> None:
        """Une perte de 48 $ sur 540 $ n'est pas un retrait de 48 $.

        C'est le scenario du trade #3225201437 : `ensure_day_rollover` est
        appele avec le solde d'apres cloture, alors que `day_realized_pnl`
        vaut encore zero.
        """
        await _etat_du_jour(session, solde_du_matin=540.41, realise=0.0, plus_haut=540.41)

        etat = await settings_repo.ensure_day_rollover(session, 492.41)

        assert etat.day_start_balance == 540.41

    async def test_le_plus_haut_dequity_survit(self, session: AsyncSession) -> None:
        """Sans lui, `max_drawdown_percent` n'a plus aucune reference."""
        await _etat_du_jour(session, solde_du_matin=540.41, realise=0.0, plus_haut=540.41)

        etat = await settings_repo.ensure_day_rollover(session, 492.41)

        assert etat.peak_equity == 540.41

    async def test_la_perte_du_jour_reste_mesurable_apres_comptabilisation(
        self, session: AsyncSession
    ) -> None:
        """Le cycle complet : rollover avec le nouveau solde, puis comptabilisation.

        A la fin, la perte du jour doit valoir la perte reelle -- c'est
        exactement ce que `_check_daily_limits` compare a la limite.
        """
        await _etat_du_jour(session, solde_du_matin=540.41, realise=0.0, plus_haut=540.41)

        await settings_repo.ensure_day_rollover(session, 492.41)
        etat = await settings_repo.get_trading_state(session)
        etat.day_realized_pnl += -48.0
        await settings_repo.save_trading_state(session, etat)

        etat = await settings_repo.get_trading_state(session)
        perte_pourcent = abs(etat.day_realized_pnl) / etat.day_start_balance * 100
        assert round(perte_pourcent, 2) == 8.88

    async def test_une_serie_de_pertes_cumule_au_lieu_de_se_reinitialiser(
        self, session: AsyncSession
    ) -> None:
        """La journee du 14/09, rejouee : quatre pertes doivent s'additionner.

        Avec le recalage intempestif, chaque cloture repartait de zero et la
        limite de perte journaliere restait inatteignable.
        """
        await _etat_du_jour(session, solde_du_matin=540.41, realise=0.0, plus_haut=540.41)

        solde = 540.41
        for perte in (-48.0, -40.0, -43.18, -36.08):
            solde += perte
            await settings_repo.ensure_day_rollover(session, solde)
            etat = await settings_repo.get_trading_state(session)
            etat.day_realized_pnl += perte
            await settings_repo.save_trading_state(session, etat)

        etat = await settings_repo.get_trading_state(session)
        assert etat.day_start_balance == 540.41
        assert round(etat.day_realized_pnl, 2) == -167.26
        assert round(abs(etat.day_realized_pnl) / etat.day_start_balance * 100, 1) == 31.0


class TestMouvementExterneReel:
    """Un vrai depot doit toujours etre detecte -- on ne casse pas l'existant."""

    async def test_un_rechargement_recale_toujours(self, session: AsyncSession) -> None:
        await _etat_du_jour(session, solde_du_matin=50.0, realise=0.0, plus_haut=50.0)

        etat = await settings_repo.reconcile_external_balance_move(session, 500.0)

        assert etat.day_start_balance == 500.0
        assert etat.peak_equity is None

    async def test_le_realise_du_jour_est_conserve(self, session: AsyncSession) -> None:
        await _etat_du_jour(session, solde_du_matin=100.0, realise=-20.0, plus_haut=None)

        etat = await settings_repo.reconcile_external_balance_move(session, 580.0)

        assert etat.day_realized_pnl == -20.0
        assert etat.day_start_balance == 600.0

    async def test_une_perte_deja_comptabilisee_ne_recale_rien(
        self, session: AsyncSession
    ) -> None:
        """Le cas sain : compteur et solde sont d'accord, rien ne bouge."""
        await _etat_du_jour(session, solde_du_matin=540.41, realise=-48.0, plus_haut=540.41)

        etat = await settings_repo.reconcile_external_balance_move(session, 492.41)

        assert etat.day_start_balance == 540.41
        assert etat.peak_equity == 540.41
