"""Les reperes du jour doivent suivre le compte, pas l'inverse.

Hors trading, le solde ne bouge pas : il vaut le solde du matin plus le
realise du jour. Tout ecart vient d'un mouvement externe -- rechargement d'un
compte demo, depot, retrait. Garder l'ancien repere reviendrait a mesurer les
pertes du jour sur un capital qui n'existe plus.

Constate en production le 11/09/2026 : le compte est passe de 50 a 500 dollars
sans changement de mode, ``day_start_balance`` est reste a 50, et la limite de
perte journaliere de 8 % se serait declenchee des 4 dollars perdus au lieu
de 40.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import settings_repo


async def test_un_rechargement_de_compte_recale_le_repere(session: AsyncSession) -> None:
    etat = await settings_repo.get_trading_state(session)
    etat.day_key = settings_repo.today_key()
    etat.day_start_balance = 50.0
    etat.day_realized_pnl = 0.0
    etat.peak_equity = 50.0
    await settings_repo.save_trading_state(session, etat)

    recale = await settings_repo.ensure_day_rollover(session, 500.0)

    assert recale.day_start_balance == 500.0
    # Le plus haut d'equity doit etre reconstruit a partir du compte actif.
    assert recale.peak_equity is None


async def test_le_realise_du_jour_est_conserve_au_recalage(session: AsyncSession) -> None:
    """Un depot ne doit pas effacer le resultat deja realise dans la journee."""
    etat = await settings_repo.get_trading_state(session)
    etat.day_key = settings_repo.today_key()
    etat.day_start_balance = 100.0
    etat.day_realized_pnl = -20.0
    await settings_repo.save_trading_state(session, etat)

    # 80 attendus (100 - 20) ; le compte en affiche 580 : 500 ont ete deposes.
    recale = await settings_repo.ensure_day_rollover(session, 580.0)

    assert recale.day_realized_pnl == -20.0
    # Le repere doit rester coherent : perte du jour toujours mesurable.
    assert recale.day_start_balance == 600.0


async def test_une_perte_ordinaire_ne_declenche_aucun_recalage(session: AsyncSession) -> None:
    """Le solde qui baisse a cause des trades n'est pas un mouvement externe.

    Sans cette distinction, le garde-fou effacerait les pertes qu'il est
    precisement charge de mesurer.
    """
    etat = await settings_repo.get_trading_state(session)
    etat.day_key = settings_repo.today_key()
    etat.day_start_balance = 500.0
    etat.day_realized_pnl = -30.0
    etat.peak_equity = 500.0
    await settings_repo.save_trading_state(session, etat)

    inchange = await settings_repo.ensure_day_rollover(session, 470.0)

    assert inchange.day_start_balance == 500.0
    assert inchange.peak_equity == 500.0


async def test_les_frais_ne_declenchent_aucun_recalage(session: AsyncSession) -> None:
    """Swap et commissions font deriver le solde de quelques unites."""
    etat = await settings_repo.get_trading_state(session)
    etat.day_key = settings_repo.today_key()
    etat.day_start_balance = 500.0
    etat.day_realized_pnl = 0.0
    await settings_repo.save_trading_state(session, etat)

    inchange = await settings_repo.ensure_day_rollover(session, 497.5)

    assert inchange.day_start_balance == 500.0
