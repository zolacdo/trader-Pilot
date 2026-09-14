"""Tests du moteur de decision (CDC2 sections 2, 42, 44, 76 et 113).

Le fil conducteur : le systeme doit savoir ne rien faire. Un refus motive vaut
mieux qu'un trade force, et chaque refus doit rester lisible dans le journal.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction
from app.models.intelligence import (
    DecisionAction,
    DecisionSource,
    MarketRegime,
    NewsImpact,
    TrendState,
)
from app.repositories import decision_repo
from app.services.confidence.weights import ConfidenceComponent, ConfidenceWeights
from app.services.decision.circuit_breaker import (
    CircuitBreaker,
)
from app.services.decision.context import DecisionContext, DecisionThresholds
from app.services.decision.engine import DecisionEngine, position_risk_multiplier
from app.services.decision.guards import GuardCode
from app.services.decision.inputs import (
    AnalysisBundle,
    ConsensusView,
    CrossMarketView,
    HistoricalView,
    MacroView,
    NewsView,
    QuoteView,
    RegimeView,
    TechnicalView,
    TelegramView,
    TradeLevels,
)

PREFIX = "/api/v1"


def _niveaux(direction: Direction = Direction.BUY) -> TradeLevels:
    if direction is Direction.BUY:
        return TradeLevels(
            direction=Direction.BUY,
            entry_price=3500.0,
            entry_min=3498.0,
            entry_max=3502.0,
            stop_loss=3485.0,
            take_profits=[3530.0, 3545.0],
            expected_rr=3.0,
            first_target_rr=2.0,
            risk_distance=15.0,
            method="structure+atr",
        )
    return TradeLevels(
        direction=Direction.SELL,
        entry_price=3500.0,
        entry_min=3498.0,
        entry_max=3502.0,
        stop_loss=3515.0,
        take_profits=[3470.0],
        expected_rr=2.0,
        first_target_rr=2.0,
        risk_distance=15.0,
        method="structure+atr",
    )


def _lectures(
    note: float = 0.9,
    direction: Direction = Direction.BUY,
    **remplacements: object,
) -> AnalysisBundle:
    """Un contexte complet et coherent, que les tests degradent ensuite."""
    maintenant = utcnow()
    haussier = TrendState.BULLISH if direction is Direction.BUY else TrendState.BEARISH
    regime = (
        MarketRegime.TRENDING_UP if direction is Direction.BUY else MarketRegime.TRENDING_DOWN
    )
    defaut: dict[str, object] = {
        "quote": QuoteView(
            symbol="XAUUSD", bid=3500.0, ask=3500.30, spread_points=30, captured_at=maintenant
        ),
        "technical": TechnicalView(
            score=note,
            direction=direction,
            trend_d1=haussier,
            trend_h4=haussier,
            trend_h1=haussier,
            detail="Alignement multi-unités de temps.",
        ),
        "regime": RegimeView(regime=regime, score=note, detail="Tendance établie."),
        "historical": HistoricalView(score=note, direction=direction, matches=18, similarity=0.82),
        "macro": MacroView(score=note, direction=direction, detail="Contexte porteur."),
        "news": NewsView(score=note, blackout=False, impact=NewsImpact.LOW, analysable=True),
        "cross_market": CrossMarketView(score=note, direction=direction),
        "telegram": TelegramView(score=note, direction=direction, complete=True),
        "consensus": ConsensusView(score=note, direction=direction, available=True),
    }
    defaut.update(remplacements)
    return AnalysisBundle(symbol="XAUUSD", **defaut)  # type: ignore[arg-type]


def _contexte(
    note: float = 0.9,
    direction: Direction = Direction.BUY,
    lectures: AnalysisBundle | None = None,
    **remplacements: object,
) -> DecisionContext:
    base: dict[str, object] = {
        "symbol": "XAUUSD",
        "analysis": lectures if lectures is not None else _lectures(note, direction),
        "source": DecisionSource.AI_GENERATED,
        "proposed_direction": direction,
        "levels": _niveaux(direction),
        "strategy": "trend_following",
    }
    base.update(remplacements)
    return DecisionContext(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Actions nominales (CDC2 section 42)
# ---------------------------------------------------------------------------

def test_un_contexte_excellent_donne_strong_buy() -> None:
    verdict = DecisionEngine().decide(_contexte(note=0.92))

    assert verdict.action is DecisionAction.STRONG_BUY
    assert verdict.executable_action is DecisionAction.BUY
    assert verdict.confidence.score >= 85
    assert verdict.guards == []


def test_un_contexte_excellent_a_la_vente_donne_strong_sell() -> None:
    verdict = DecisionEngine().decide(_contexte(note=0.92, direction=Direction.SELL))

    assert verdict.action is DecisionAction.STRONG_SELL
    assert verdict.executable_action is DecisionAction.SELL


def test_un_contexte_correct_donne_buy() -> None:
    verdict = DecisionEngine().decide(_contexte(note=0.78))

    assert verdict.action is DecisionAction.BUY
    assert verdict.executable_action is DecisionAction.BUY


def test_un_contexte_moyen_donne_wait() -> None:
    """CDC2 section 2 : attendre est une reponse, pas un echec."""
    verdict = DecisionEngine().decide(_contexte(note=0.62))

    assert verdict.action is DecisionAction.WAIT
    assert verdict.executable_action is DecisionAction.NO_TRADE
    assert verdict.tradable is False
    assert "attend" in verdict.reason.lower()


def test_une_confiance_trop_faible_donne_no_trade() -> None:
    verdict = DecisionEngine().decide(_contexte(note=0.30))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.LOW_CONFIDENCE in {garde.code for garde in verdict.guards}


def test_sans_direction_le_moteur_attend() -> None:
    lectures = _lectures(note=0.9)
    lectures.technical = None
    lectures.historical = None
    lectures.cross_market = None
    lectures.telegram = None

    verdict = DecisionEngine().decide(
        _contexte(lectures=lectures, proposed_direction=None, levels=None)
    )

    assert verdict.direction is None
    assert verdict.action in {DecisionAction.NO_TRADE, DecisionAction.WAIT}
    assert verdict.executable_action is DecisionAction.NO_TRADE


def test_les_actions_sont_ramenees_a_buy_sell_no_trade() -> None:
    """CDC2 section 42 : avant execution, trois valeurs seulement."""
    executables = {
        DecisionEngine().decide(_contexte(note=0.95)).executable_action,
        DecisionEngine().decide(_contexte(note=0.78)).executable_action,
        DecisionEngine().decide(_contexte(note=0.62)).executable_action,
        DecisionEngine().decide(_contexte(note=0.20)).executable_action,
    }

    assert executables <= {DecisionAction.BUY, DecisionAction.SELL, DecisionAction.NO_TRADE}


# ---------------------------------------------------------------------------
# Confiance et risque (CDC2 section 44)
# ---------------------------------------------------------------------------

def test_la_confiance_ne_module_jamais_le_risque() -> None:
    """Meme a 99 %, le risque reste celui du RiskManager."""
    assert position_risk_multiplier(0.0) == 1.0
    assert position_risk_multiplier(50.0) == 1.0
    assert position_risk_multiplier(99.0) == 1.0
    assert position_risk_multiplier(100.0) == 1.0


def test_le_verdict_ne_porte_aucune_taille_de_position() -> None:
    verdict = DecisionEngine().decide(_contexte(note=0.99))

    champs = set(verdict.to_dict())
    assert not champs & {"volume", "lot", "riskPercent", "size", "positionSize"}


# ---------------------------------------------------------------------------
# Fail safe (CDC2 section 113)
# ---------------------------------------------------------------------------

def test_des_donnees_trop_anciennes_bloquent() -> None:
    lectures = _lectures()
    lectures.quote = QuoteView(
        symbol="XAUUSD",
        bid=3500.0,
        ask=3500.3,
        captured_at=utcnow() - timedelta(minutes=30),
    )

    verdict = DecisionEngine().decide(_contexte(lectures=lectures))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.STALE_MARKET_DATA in {garde.code for garde in verdict.guards}


def test_un_prix_incoherent_bloque() -> None:
    lectures = _lectures()
    lectures.quote = QuoteView(symbol="XAUUSD", bid=3500.0, ask=3400.0, captured_at=utcnow())

    verdict = DecisionEngine().decide(_contexte(lectures=lectures))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.INCONSISTENT_PRICE in {garde.code for garde in verdict.guards}


def test_un_desaccord_des_ia_bloque() -> None:
    lectures = _lectures()
    lectures.consensus = ConsensusView(
        score=0.8, direction=Direction.SELL, available=True, detail="local BUY / distant SELL"
    )

    verdict = DecisionEngine().decide(_contexte(lectures=lectures))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.AI_DISAGREEMENT in {garde.code for garde in verdict.guards}


def test_un_consensus_exige_mais_indisponible_demande_une_revue() -> None:
    lectures = _lectures()
    lectures.consensus = ConsensusView(score=None, available=False, blocks_auto_trade=True)

    verdict = DecisionEngine().decide(_contexte(lectures=lectures))

    assert verdict.action is DecisionAction.NEEDS_REVIEW
    assert verdict.executable_action is DecisionAction.NO_TRADE


def test_sans_consensus_produit_et_sans_exigence_la_decision_se_poursuit() -> None:
    lectures = _lectures()
    lectures.consensus = None

    verdict = DecisionEngine().decide(_contexte(lectures=lectures, consensus_required=False))

    assert verdict.action is DecisionAction.STRONG_BUY
    assert ConfidenceComponent.AI_CONSENSUS in verdict.confidence.missing


def test_une_news_critique_non_analysable_bloque() -> None:
    lectures = _lectures()
    lectures.news = NewsView(score=None, analysable=False, impact=NewsImpact.CRITICAL)

    verdict = DecisionEngine().decide(_contexte(lectures=lectures))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.NEWS_NOT_ANALYSABLE in {garde.code for garde in verdict.guards}


def test_un_blackout_actualites_bloque() -> None:
    lectures = _lectures()
    lectures.news = NewsView(
        score=0.2, blackout=True, minutes_to_event=8, impact=NewsImpact.HIGH
    )

    verdict = DecisionEngine().decide(_contexte(lectures=lectures))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.NEWS_BLACKOUT in {garde.code for garde in verdict.guards}


def test_mt5_instable_bloque() -> None:
    verdict = DecisionEngine().decide(_contexte(mt5_connected=False))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.MT5_UNSTABLE in {garde.code for garde in verdict.guards}


def test_un_signal_incomplet_bloque() -> None:
    verdict = DecisionEngine().decide(_contexte(signal_complete=False))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.INCOMPLETE_SIGNAL in {garde.code for garde in verdict.guards}


def test_un_risque_incalculable_bloque() -> None:
    verdict = DecisionEngine().decide(_contexte(risk_computable=False))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.RISK_NOT_COMPUTABLE in {garde.code for garde in verdict.guards}


def test_un_stop_loss_invalide_bloque() -> None:
    niveaux = _niveaux()
    niveaux.stop_loss = 3600.0  # au-dessus de l'entree pour un achat

    verdict = DecisionEngine().decide(_contexte(levels=niveaux))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.INVALID_STOP_LOSS in {garde.code for garde in verdict.guards}


def test_une_analyse_trop_partielle_bloque() -> None:
    lectures = _lectures()
    lectures.historical = None
    lectures.macro = None
    lectures.cross_market = None
    lectures.news = None

    verdict = DecisionEngine().decide(_contexte(lectures=lectures))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.INSUFFICIENT_ANALYSIS in {garde.code for garde in verdict.guards}


def test_le_trading_desactive_bloque() -> None:
    verdict = DecisionEngine().decide(_contexte(trading_enabled=False))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.TRADING_DISABLED in {garde.code for garde in verdict.guards}


def test_tous_les_motifs_de_refus_sont_listes() -> None:
    """L'utilisateur doit voir toutes les raisons, pas seulement la premiere."""
    verdict = DecisionEngine().decide(
        _contexte(mt5_connected=False, signal_complete=False, risk_computable=False)
    )

    codes = {garde.code for garde in verdict.guards}
    assert {
        GuardCode.MT5_UNSTABLE,
        GuardCode.INCOMPLETE_SIGNAL,
        GuardCode.RISK_NOT_COMPUTABLE,
    } <= codes
    assert len(verdict.negative_factors) >= 3


# ---------------------------------------------------------------------------
# Coupe-circuit (CDC2 section 86)
# ---------------------------------------------------------------------------

def test_un_coupe_circuit_arme_bloque_la_decision() -> None:
    disjoncteur = CircuitBreaker()
    disjoncteur.report_mt5(connected=False)

    verdict = DecisionEngine().decide(_contexte(breaker=disjoncteur.state))

    assert verdict.action is DecisionAction.NO_TRADE
    assert GuardCode.CIRCUIT_BREAKER in {garde.code for garde in verdict.guards}

# ---------------------------------------------------------------------------
# Seuils configurables
# ---------------------------------------------------------------------------

def test_des_seuils_plus_exigeants_transforment_un_buy_en_wait() -> None:
    strict = DecisionThresholds(strong=95.0, entry=90.0, wait=50.0)

    verdict = DecisionEngine().decide(_contexte(note=0.80, thresholds=strict))

    assert verdict.action is DecisionAction.WAIT


def test_le_seuil_de_confiance_le_plus_exigeant_l_emporte() -> None:
    verdict = DecisionEngine().decide(_contexte(note=0.80, min_confidence=0.90))

    assert verdict.action is DecisionAction.WAIT


def test_une_ponderation_differente_change_la_decision() -> None:
    lectures = _lectures(note=0.95)
    lectures.macro = MacroView(score=0.05, direction=Direction.BUY, detail="Macro contraire.")

    defaut = DecisionEngine().decide(_contexte(lectures=lectures))
    macro_dominante = DecisionEngine().with_weights(
        ConfidenceWeights(macro=0.60)
    ).decide(_contexte(lectures=lectures))

    assert defaut.confidence.score > macro_dominante.confidence.score


def test_des_seuils_incoherents_sont_refuses() -> None:
    with pytest.raises(ValueError):
        DecisionThresholds(strong=50.0, entry=80.0, wait=20.0)


# ---------------------------------------------------------------------------
# Journal (CDC2 section 76)
# ---------------------------------------------------------------------------

def test_un_trade_non_pris_produit_une_ligne_de_journal_motivee() -> None:
    verdict = DecisionEngine().decide(_contexte(mt5_connected=False))
    ligne = verdict.to_record()

    assert ligne.action is DecisionAction.NO_TRADE
    assert ligne.executed is False
    assert ligne.reason
    assert ligne.negative_factors


async def test_le_journal_expose_les_trades_non_pris(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    moteur = DecisionEngine()
    pris = moteur.decide(_contexte(note=0.95))
    refuse = moteur.decide(_contexte(note=0.95, mt5_connected=False))

    for verdict in (pris, refuse):
        enregistre = await decision_repo.save_decision(
            session, verdict.to_record(), verdict.confidence.to_decision_factors(0)
        )
        assert enregistre.id is not None
    await session.commit()

    reponse = await auth_client.get(f"{PREFIX}/decisions")
    assert reponse.status_code == 200
    charge = reponse.json()

    assert charge["total"] == 2
    assert charge["notTaken"] == 2
    actions = {item["action"] for item in charge["items"]}
    assert DecisionAction.NO_TRADE.value in actions
    non_pris = next(i for i in charge["items"] if i["action"] == DecisionAction.NO_TRADE.value)
    assert "MetaTrader" in (non_pris["reason"] or "")


async def test_le_detail_d_une_decision_montre_ses_facteurs(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    verdict = DecisionEngine().decide(_contexte(note=0.88))
    ligne = await decision_repo.save_decision(session, verdict.to_record())
    facteurs = verdict.confidence.to_decision_factors(ligne.id or 0)
    for facteur in facteurs:
        session.add(facteur)
    await session.commit()

    reponse = await auth_client.get(f"{PREFIX}/decisions/{ligne.id}")
    assert reponse.status_code == 200
    charge = reponse.json()

    assert charge["symbol"] == "XAUUSD"
    assert len(charge["factors"]) == len(ConfidenceComponent)
    noms = {facteur["name"] for facteur in charge["factors"]}
    assert ConfidenceComponent.TECHNICAL.value in noms


async def test_une_decision_inconnue_renvoie_404(auth_client: AsyncClient) -> None:
    reponse = await auth_client.get(f"{PREFIX}/decisions/987654")

    assert reponse.status_code == 404


async def test_le_journal_des_decisions_exige_un_appairage(client: AsyncClient) -> None:
    reponse = await client.get(f"{PREFIX}/decisions")

    assert reponse.status_code == 401
