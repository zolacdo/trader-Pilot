"""Le cycle autonome passe des ordres — par le même chemin que tout le reste.

Jusqu'ici il analysait, décidait, notifiait, et s'arrêtait là. Autorisé le
16/09/2026, il remet désormais sa décision au moteur de trading exactement
comme un signal reçu d'un canal : parser, validation, RiskManager,
``order_check``, puis ``order_send``. Aucun chemin d'exécution parallèle n'est
créé — c'est ce qui garantit que les plafonds d'exposition, les limites
journalières et le coupe-circuit valent aussi pour lui.

Trois garde-fous, dans cet ordre, et le premier compte : le mode observation
signifie que RIEN ne part au broker. Un réglage qui l'ignorerait viderait ce
mode de son sens.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Direction
from app.repositories import settings_repo
from app.services.decision.inputs import TradeLevels
from app.services.intelligence import execution
from app.services.trading.engine import ProcessOutcome


class MoteurEspion:
    """Remplace le moteur de trading : il note l'appel, il n'ordonne rien."""

    def __init__(self, outcome: ProcessOutcome | None = None) -> None:
        self.appels: list[dict[str, Any]] = []
        self._outcome = outcome or ProcessOutcome(
            stage="executed", executed=True, signal_id=7
        )

    async def handle_message(self, session: AsyncSession, **kwargs: Any) -> ProcessOutcome:
        self.appels.append(kwargs)
        return self._outcome


@pytest.fixture
def espion(monkeypatch: pytest.MonkeyPatch) -> MoteurEspion:
    moteur = MoteurEspion()
    monkeypatch.setattr(execution, "trading_engine", moteur)
    return moteur


def _niveaux() -> TradeLevels:
    return TradeLevels(
        direction=Direction.BUY,
        entry_price=3350.0,
        entry_min=3349.0,
        entry_max=3351.0,
        stop_loss=3340.0,
        take_profits=[3360.0, 3370.0],
    )


async def _autoriser(session: AsyncSession) -> None:
    await settings_repo.set_setting(session, execution.SETTING_AUTO_TRADE, True)


async def test_le_reglage_est_coupe_par_defaut(session: AsyncSession) -> None:
    """Un défaut qui tradeuse ferait trader quiconque démarre ce dépôt.

    Le réglage s'allume explicitement, en base ; le code ne le suppose jamais.
    """
    assert await execution.auto_trade_enabled(session) is False


async def test_sans_autorisation_rien_ne_part(
    session: AsyncSession, espion: MoteurEspion
) -> None:
    rapport = await execution.execute_decision(
        session, "XAUUSD", _niveaux(), shadow_mode=False
    )

    assert rapport.attempted is False
    assert espion.appels == []


async def test_le_mode_observation_n_execute_rien(
    session: AsyncSession, espion: MoteurEspion
) -> None:
    """Observer veut dire que rien ne part : le réglage ne passe pas devant."""
    await _autoriser(session)

    rapport = await execution.execute_decision(
        session, "XAUUSD", _niveaux(), shadow_mode=True
    )

    assert rapport.attempted is False
    assert 'observation' in rapport.detail.lower()
    assert espion.appels == []


async def test_une_decision_autorisee_part_vers_le_moteur(
    session: AsyncSession, espion: MoteurEspion
) -> None:
    await _autoriser(session)

    rapport = await execution.execute_decision(
        session, "XAUUSD", _niveaux(), shadow_mode=False
    )

    assert rapport.attempted is True
    assert rapport.executed is True
    assert rapport.signal_id == 7
    assert len(espion.appels) == 1
    # Remise directe : sans ce drapeau le registre des publications propres
    # refuserait l'exécution.
    assert espion.appels[0]['internal_handoff'] is True


async def test_le_texte_remis_porte_le_plan_complet(
    session: AsyncSession, espion: MoteurEspion
) -> None:
    """Le moteur doit lire un plan, pas une intention."""
    await _autoriser(session)

    await execution.execute_decision(session, "XAUUSD", _niveaux(), shadow_mode=False)

    texte = espion.appels[0]['text']
    assert texte.splitlines()[0] == 'BUY XAUUSD'
    assert 'Entry 3350' in texte
    assert 'SL 3340' in texte
    assert 'TP1 3360' in texte
    assert 'TP2 3370' in texte


def test_le_texte_n_invente_aucune_precision() -> None:
    """« 1.15396 » reste tel quel, « 3350 » ne devient pas « 3350.00000 »."""
    niveaux = TradeLevels(
        direction=Direction.SELL,
        entry_price=1.15396,
        entry_min=1.153,
        entry_max=1.154,
        stop_loss=1.15800,
        take_profits=[1.15000],
    )

    texte = execution.signal_text("EURUSD", niveaux)

    assert texte.splitlines()[0] == 'SELL EURUSD'
    assert 'Entry 1.15396' in texte
    assert 'SL 1.158' in texte
    assert 'TP1 1.15' in texte


async def test_sans_niveaux_rien_ne_part(
    session: AsyncSession, espion: MoteurEspion
) -> None:
    await _autoriser(session)

    rapport = await execution.execute_decision(session, "XAUUSD", None, shadow_mode=False)

    assert rapport.attempted is False
    assert espion.appels == []


def test_la_bande_mesuree_couvre_tout_l_espace_ouvrable() -> None:
    """Une fenêtre fixe sous le seuil peut rater toute la distribution.

    Mesuré le 16/09/2026 : dix décisions d'affilée entre 0,352 et 0,471 de
    confiance, pour un seuil à 0,60. Une bande de 0,10 mesurait
    « 0,50 à 0,60 » — vide, donc aucune preuve, donc un seuil immobile et un
    cycle qui n'ouvrira jamais rien. Un état stable où il ne trade ni
    n'apprend.

    La bande descend maintenant jusqu'au plancher absolu du régleur : elle
    couvre exactement l'espace que le seuil pourrait un jour occuper, ni plus
    (ce serait mesurer l'inatteignable) ni moins.
    """
    from dataclasses import dataclass

    from app.services.decision.shadow import MARGINAL_FLOOR, marginal_context

    @dataclass(slots=True)
    class FauxContexte:
        min_confidence: float

    assert marginal_context(FauxContexte(min_confidence=0.60)).min_confidence == (
        pytest.approx(MARGINAL_FLOOR)
    )
    # Déjà au plancher : la bande est vide par construction, et c'est correct.
    assert marginal_context(
        FauxContexte(min_confidence=MARGINAL_FLOOR)
    ).min_confidence == pytest.approx(MARGINAL_FLOOR)


async def test_une_panne_du_moteur_ne_leve_pas(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sinon l'échec d'un ordre emporterait le tour d'analyse entier."""

    class MoteurEnPanne:
        async def handle_message(self, *args: Any, **kwargs: Any) -> ProcessOutcome:
            raise RuntimeError("terminal MetaTrader injoignable")

    monkeypatch.setattr(execution, "trading_engine", MoteurEnPanne())
    await _autoriser(session)

    rapport = await execution.execute_decision(
        session, "XAUUSD", _niveaux(), shadow_mode=False
    )

    assert rapport.stage == 'error'
    assert rapport.executed is False
    assert 'MetaTrader' in rapport.detail
