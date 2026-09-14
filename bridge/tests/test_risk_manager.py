"""RiskManager : une barriere par regle, un motif de refus par barriere.

C'est la couche la plus importante du projet : aucun ordre ne part sans son
accord, et aucune sortie d'IA ne peut la contourner (CDC sections 23 et 25).
Chaque test isole UNE regle et verifie le ``RejectionReason`` exact.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.models.core import RiskSettings, TradingState
from app.models.enums import (
    ChannelMode,
    Direction,
    ExecutionMode,
    OrderType,
    ParserSource,
    RejectionReason,
)
from app.models.telegram import ChannelSettings
from app.services.mt5.interface import AccountInfo, PositionInfo, SymbolInfo, Tick
from app.services.risk.manager import RiskContext, RiskManager, resolve_settings
from app.services.signals.models import ParsedSignal
from app.services.trading.paper import PaperTradingService

# Mercredi 4 juin 2025, 12h00 UTC : jour et heure autorises par defaut.
NOW = datetime(2025, 6, 4, 12, 0, tzinfo=UTC)
BALANCE = 10000.0


def make_settings(**kwargs: object) -> RiskSettings:
    """Reglages surs par defaut, avec le trading automatique deja actif."""
    settings = RiskSettings(auto_trading_enabled=True, paper_balance=BALANCE)
    for key, value in kwargs.items():
        setattr(settings, key, value)
    return settings


def make_state(**kwargs: object) -> TradingState:
    state = TradingState(day_start_balance=BALANCE, peak_equity=BALANCE)
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


def make_channel(**kwargs: object) -> ChannelSettings:
    channel = ChannelSettings(channel_id=1, enabled=True, mode=ChannelMode.AUTO)
    for key, value in kwargs.items():
        setattr(channel, key, value)
    return channel


def make_signal(**kwargs: object) -> ParsedSignal:
    """Achat XAUUSD parfaitement structure : entree 3320, SL 3310, TP 3340."""
    base: dict[str, object] = {
        "is_signal": True,
        "symbol_raw": "XAUUSD",
        "symbol": "XAUUSD",
        "direction": Direction.BUY,
        "order_type": OrderType.MARKET,
        "entry_price": 3320.0,
        "stop_loss": 3310.0,
        "take_profits": [3340.0],
        "confidence": 0.95,
    }
    base.update(kwargs)
    return ParsedSignal(**base)  # type: ignore[arg-type]


def make_account(trade_mode: int | None = 0, trade_allowed: bool = True) -> AccountInfo:
    return AccountInfo(
        login=99000001,
        server="Test-Server",
        balance=BALANCE,
        equity=BALANCE,
        margin=0.0,
        margin_free=BALANCE,
        trade_mode=trade_mode,
        trade_allowed=trade_allowed,
    )


async def make_context(paper: PaperTradingService, **kwargs: object) -> RiskContext:
    """Contexte nominal : XAUUSD cote a 3350, aucune position ouverte."""
    symbol = await paper.symbol_info("XAUUSD")
    tick = await paper.symbol_tick("XAUUSD")
    assert symbol is not None and tick is not None

    context = RiskContext(
        settings=make_settings(),
        state=make_state(),
        channel=None,
        account=None,
        symbol=symbol,
        tick=tick,
        open_positions=[],
        mt5_connected=True,
        now=NOW,
    )
    for key, value in kwargs.items():
        setattr(context, key, value)
    return context


def open_position(symbol: str = "XAUUSD", volume: float = 0.05, ticket: int = 1) -> PositionInfo:
    return PositionInfo(
        ticket=ticket,
        symbol=symbol,
        direction=Direction.BUY,
        volume=volume,
        price_open=3320.0,
        price_current=3320.0,
    )


# ---------------------------------------------------------------------------
# Chemin nominal
# ---------------------------------------------------------------------------

async def test_chemin_nominal_approuve_avec_le_bon_lot(paper: PaperTradingService) -> None:
    """0.5 % de 10 000 = 50 USD ; 10 dollars de stop = 1000 USD/lot -> 0.05 lot."""
    context = await make_context(paper)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)

    assert decision.approved is True, decision.detail
    assert decision.reason is None
    assert decision.lot is not None
    assert decision.lot.volume == pytest.approx(0.05)
    assert decision.lot.loss_at_stop == pytest.approx(50.0)
    assert decision.entry_price == pytest.approx(3320.0)
    assert decision.risk_reward == pytest.approx(2.0)
    assert all(check.passed for check in decision.checks)


async def test_la_decision_est_serialisable_pour_l_audit(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    payload = decision.to_dict()
    assert payload["approved"] is True
    assert payload["reason"] is None
    assert payload["lot"]["volume"] == pytest.approx(0.05)
    assert payload["checks"]


# ---------------------------------------------------------------------------
# 1. Interrupteurs generaux
# ---------------------------------------------------------------------------

async def test_auto_trading_off(paper: PaperTradingService) -> None:
    context = await make_context(paper, settings=make_settings(auto_trading_enabled=False))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.AUTO_TRADING_OFF


async def test_trading_paused(paper: PaperTradingService) -> None:
    state = make_state(paused=True, pause_reason="Pause manuelle")
    context = await make_context(paper, state=state)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.TRADING_PAUSED
    assert decision.detail == "Pause manuelle"


async def test_pause_avec_date_naive_relue_de_la_base(paper: PaperTradingService) -> None:
    """Regression : SQLite relit ``paused_until`` sans fuseau horaire."""
    naive = (NOW + timedelta(hours=1)).replace(tzinfo=None)
    context = await make_context(paper, state=make_state(paused=True, paused_until=naive))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.TRADING_PAUSED


async def test_pause_expiree_laisse_passer(paper: PaperTradingService) -> None:
    state = make_state(paused=True, paused_until=NOW - timedelta(minutes=1))
    context = await make_context(paper, state=state)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is True


# ---------------------------------------------------------------------------
# 2. Canal
# ---------------------------------------------------------------------------

async def test_channel_disabled(paper: PaperTradingService) -> None:
    context = await make_context(paper, channel=make_channel(enabled=False))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.CHANNEL_DISABLED


async def test_channel_observe_mode(paper: PaperTradingService) -> None:
    context = await make_context(paper, channel=make_channel(mode=ChannelMode.OBSERVE))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.CHANNEL_OBSERVE_MODE


async def test_channel_observe_mode_contourne_par_validation_manuelle(
    paper: PaperTradingService,
) -> None:
    """L'utilisateur peut executer un signal observe, mais explicitement."""
    context = await make_context(
        paper, channel=make_channel(mode=ChannelMode.OBSERVE), manual_override=True
    )
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is True


# ---------------------------------------------------------------------------
# 3. Compte et mode d'execution
# ---------------------------------------------------------------------------

async def test_account_mismatch_compte_reel_en_mode_demo(paper: PaperTradingService) -> None:
    context = await make_context(paper, account=make_account(trade_mode=2))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.MT5_DEMO)
    assert decision.approved is False
    assert decision.reason is RejectionReason.ACCOUNT_MISMATCH
    assert "REEL" in decision.detail


async def test_account_mismatch_compte_indetermine(paper: PaperTradingService) -> None:
    context = await make_context(paper, account=make_account(trade_mode=None))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.MT5_DEMO)
    assert decision.approved is False
    assert decision.reason is RejectionReason.ACCOUNT_MISMATCH
    assert "demo ou reel" in decision.detail


async def test_live_not_unlocked(paper: PaperTradingService) -> None:
    context = await make_context(paper, account=make_account(trade_mode=2))
    assert context.settings.live_unlocked is False
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.MT5_LIVE)
    assert decision.approved is False
    assert decision.reason is RejectionReason.LIVE_NOT_UNLOCKED


async def test_mt5_disconnected(paper: PaperTradingService) -> None:
    context = await make_context(paper, account=make_account(), mt5_connected=False)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.MT5_DEMO)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MT5_DISCONNECTED


async def test_trading_interdit_sur_le_compte(paper: PaperTradingService) -> None:
    context = await make_context(paper, account=make_account(trade_allowed=False))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.MT5_DEMO)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MT5_DISCONNECTED


# ---------------------------------------------------------------------------
# 4. Contenu du signal
# ---------------------------------------------------------------------------

async def test_no_action_sur_un_message_sans_intention(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    decision = await RiskManager(paper).evaluate(
        ParsedSignal(is_signal=False), context, ExecutionMode.PAPER
    )
    assert decision.approved is False
    assert decision.reason is RejectionReason.NO_ACTION


async def test_low_confidence(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    decision = await RiskManager(paper).evaluate(
        make_signal(confidence=0.40), context, ExecutionMode.PAPER
    )
    assert decision.approved is False
    assert decision.reason is RejectionReason.LOW_CONFIDENCE


async def test_direction_not_allowed_achat(paper: PaperTradingService) -> None:
    context = await make_context(paper, channel=make_channel(copy_buy=False))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.DIRECTION_NOT_ALLOWED


async def test_direction_not_allowed_vente(paper: PaperTradingService) -> None:
    context = await make_context(paper, channel=make_channel(copy_sell=False))
    signal = make_signal(direction=Direction.SELL, stop_loss=3330.0, take_profits=[3300.0])
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.DIRECTION_NOT_ALLOWED


async def test_symbol_not_allowed(paper: PaperTradingService) -> None:
    context = await make_context(paper, settings=make_settings(allowed_symbols=["EURUSD"]))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.SYMBOL_NOT_ALLOWED


async def test_missing_stop_loss(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    assert context.settings.require_stop_loss is True
    decision = await RiskManager(paper).evaluate(
        make_signal(stop_loss=None), context, ExecutionMode.PAPER
    )
    assert decision.approved is False
    assert decision.reason is RejectionReason.MISSING_STOP_LOSS


async def test_missing_stop_loss_meme_si_non_obligatoire(paper: PaperTradingService) -> None:
    """Sans stop loss, la taille de position est indeterminable : refus quand meme."""
    context = await make_context(paper, settings=make_settings(require_stop_loss=False))
    decision = await RiskManager(paper).evaluate(
        make_signal(stop_loss=None), context, ExecutionMode.PAPER
    )
    assert decision.approved is False
    assert decision.reason is RejectionReason.MISSING_STOP_LOSS


async def test_missing_take_profit(paper: PaperTradingService) -> None:
    context = await make_context(paper, settings=make_settings(require_take_profit=True))
    decision = await RiskManager(paper).evaluate(
        make_signal(take_profits=[]), context, ExecutionMode.PAPER
    )
    assert decision.approved is False
    assert decision.reason is RejectionReason.MISSING_TAKE_PROFIT


# ---------------------------------------------------------------------------
# 5. Fraicheur du signal
# ---------------------------------------------------------------------------

async def test_signal_expired(paper: PaperTradingService) -> None:
    """CDC section 87 : un vieux signal ne part jamais apres un redemarrage."""
    context = await make_context(paper)
    signal = make_signal(message_date=NOW - timedelta(minutes=10))
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.SIGNAL_EXPIRED


async def test_signal_recent_accepte(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    signal = make_signal(message_date=NOW - timedelta(seconds=30))
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is True


async def test_date_de_message_naive_traitee_en_utc(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    signal = make_signal(message_date=(NOW - timedelta(hours=2)).replace(tzinfo=None))
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.reason is RejectionReason.SIGNAL_EXPIRED


# ---------------------------------------------------------------------------
# 6. Fenetres horaires
# ---------------------------------------------------------------------------

async def test_outside_trading_days(paper: PaperTradingService) -> None:
    """Samedi 7 juin 2025 : hors des jours autorises (lundi a vendredi)."""
    samedi = datetime(2025, 6, 7, 12, 0, tzinfo=UTC)
    context = await make_context(paper, now=samedi)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.OUTSIDE_TRADING_DAYS


async def test_outside_trading_hours(paper: PaperTradingService) -> None:
    settings = make_settings(trading_hours_start="08:00", trading_hours_end="17:00")
    context = await make_context(paper, settings=settings, now=NOW.replace(hour=20))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.OUTSIDE_TRADING_HOURS


async def test_fenetre_horaire_a_cheval_sur_minuit(paper: PaperTradingService) -> None:
    settings = make_settings(trading_hours_start="22:00", trading_hours_end="06:00")
    dedans = await make_context(paper, settings=settings, now=NOW.replace(hour=23))
    dehors = await make_context(paper, settings=settings, now=NOW.replace(hour=12))
    assert (await RiskManager(paper).evaluate(make_signal(), dedans, ExecutionMode.PAPER)).approved
    decision = await RiskManager(paper).evaluate(make_signal(), dehors, ExecutionMode.PAPER)
    assert decision.reason is RejectionReason.OUTSIDE_TRADING_HOURS


# ---------------------------------------------------------------------------
# 7. Instrument et conditions de marche
# ---------------------------------------------------------------------------

async def test_symbol_not_found(paper: PaperTradingService) -> None:
    context = await make_context(paper, symbol=None)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.SYMBOL_NOT_FOUND


async def test_market_closed_symbole_non_negociable(paper: PaperTradingService) -> None:
    gold = await paper.symbol_info("XAUUSD")
    assert gold is not None
    context = await make_context(paper, symbol=replace(gold, trade_mode=0))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MARKET_CLOSED


async def test_market_closed_sans_cotation(paper: PaperTradingService) -> None:
    context = await make_context(paper, tick=None)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MARKET_CLOSED


async def test_spread_too_high(paper: PaperTradingService) -> None:
    """Le spread simule de XAUUSD vaut 20 points : le plafond est mis a 5."""
    context = await make_context(paper, settings=make_settings(max_spread_points=5))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.SPREAD_TOO_HIGH


# ---------------------------------------------------------------------------
# 8. Coherence des prix
# ---------------------------------------------------------------------------

async def test_invalid_stop_loss_mauvais_cote(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    signal = make_signal(stop_loss=3330.0, take_profits=[3400.0])
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.INVALID_STOP_LOSS


async def test_invalid_stop_loss_trop_proche_du_prix(paper: PaperTradingService) -> None:
    """Le broker simule exige 20 points : 5 points seulement sont proposes."""
    context = await make_context(paper)
    signal = make_signal(entry_price=3320.0, stop_loss=3319.95)
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.INVALID_STOP_LOSS
    assert "20 points" in decision.detail


async def test_rr_too_low(paper: PaperTradingService) -> None:
    """Risque 10 dollars, gain 5 dollars : ratio 0.5 pour un minimum de 3."""
    context = await make_context(paper, settings=make_settings(min_risk_reward=3.0))
    signal = make_signal(take_profits=[3325.0])
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.RR_TOO_LOW


async def test_rr_suffisant_accepte(paper: PaperTradingService) -> None:
    context = await make_context(paper, settings=make_settings(min_risk_reward=1.5))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is True
    assert decision.risk_reward == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 9. Limites journalieres et drawdown
# ---------------------------------------------------------------------------

async def test_daily_loss_limit(paper: PaperTradingService) -> None:
    """CDC section 84 : 4 % de perte du jour pour une limite de 3 %."""
    state = make_state(day_realized_pnl=-400.0)
    context = await make_context(paper, state=state)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.DAILY_LOSS_LIMIT


async def test_daily_risk_limit(paper: PaperTradingService) -> None:
    context = await make_context(paper, state=make_state(day_risked_percent=3.5))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.DAILY_RISK_LIMIT


async def test_daily_profit_target(paper: PaperTradingService) -> None:
    settings = make_settings(daily_profit_target_percent=2.0)
    context = await make_context(paper, settings=settings, state=make_state(day_realized_pnl=250.0))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.DAILY_PROFIT_TARGET


async def test_max_drawdown(paper: PaperTradingService) -> None:
    """Sommet a 12 000, capital a 10 000 : 16.7 % de baisse pour un maximum de 10 %."""
    state = make_state(peak_equity=12000.0)
    context = await make_context(paper, state=state)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MAX_DRAWDOWN


async def test_consecutive_losses(paper: PaperTradingService) -> None:
    context = await make_context(paper, state=make_state(consecutive_losses=3))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.CONSECUTIVE_LOSSES


# ---------------------------------------------------------------------------
# 10. Exposition
# ---------------------------------------------------------------------------

async def test_max_positions(paper: PaperTradingService) -> None:
    positions = [open_position("EURUSD", ticket=1), open_position("GBPUSD", ticket=2),
                 open_position("US30", ticket=3)]
    context = await make_context(paper, open_positions=positions)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MAX_POSITIONS


async def test_max_positions_symbol(paper: PaperTradingService) -> None:
    """Une seule position par instrument : XAUUSD est deja pris."""
    context = await make_context(paper, open_positions=[open_position("XAUUSD")])
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MAX_POSITIONS_SYMBOL


async def test_max_exposure(paper: PaperTradingService) -> None:
    settings = make_settings(max_positions=10, max_positions_per_symbol=5)
    positions = [open_position("EURUSD", volume=0.6, ticket=1),
                 open_position("GBPUSD", volume=0.5, ticket=2)]
    context = await make_context(paper, settings=settings, open_positions=positions)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MAX_EXPOSURE


# ---------------------------------------------------------------------------
# 11. Volume
# ---------------------------------------------------------------------------

async def test_invalid_volume_trop_petit(paper: PaperTradingService) -> None:
    """0.05 % de 10 000 = 5 USD : 0.005 lot, sous le minimum broker de 0.01."""
    context = await make_context(paper, settings=make_settings(risk_percent=0.05))
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.INVALID_VOLUME


async def test_aucun_service_de_marche(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    decision = await RiskManager(None).evaluate(make_signal(), context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.MT5_DISCONNECTED


async def test_insufficient_margin(paper: PaperTradingService) -> None:
    """Marge requise 33.20 USD pour une marge libre de 1 USD."""
    account = make_account()
    account.margin_free = 1.0
    context = await make_context(paper, account=account)
    decision = await RiskManager(paper).evaluate(make_signal(), context, ExecutionMode.MT5_DEMO)
    assert decision.approved is False
    assert decision.reason is RejectionReason.INSUFFICIENT_MARGIN


# ---------------------------------------------------------------------------
# Une sortie d'IA ne contourne rien
# ---------------------------------------------------------------------------

async def test_une_sortie_d_ia_reste_soumise_a_toutes_les_regles(
    paper: PaperTradingService,
) -> None:
    """CDC section 49 : l'IA n'a jamais le dernier mot.

    Un signal lu par un modele plafonne a 0.80 de confiance ; avec le seuil par
    defaut de 0.85 il est refuse, exactement comme n'importe quel autre signal.
    """
    signal = make_signal(source=ParserSource.AI, ai_model="fake/model:free", confidence=0.80)
    context = await make_context(paper)
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is RejectionReason.LOW_CONFIDENCE


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"settings": "auto_off"}, RejectionReason.AUTO_TRADING_OFF),
        ({"state": "paused"}, RejectionReason.TRADING_PAUSED),
        ({"channel": "observe"}, RejectionReason.CHANNEL_OBSERVE_MODE),
    ],
)
async def test_une_sortie_d_ia_ne_contourne_aucune_barriere(
    paper: PaperTradingService, kwargs: dict[str, str], expected: RejectionReason
) -> None:
    overrides: dict[str, object] = {}
    if kwargs.get("settings") == "auto_off":
        overrides["settings"] = make_settings(auto_trading_enabled=False)
    if kwargs.get("state") == "paused":
        overrides["state"] = make_state(paused=True)
    if kwargs.get("channel") == "observe":
        overrides["channel"] = make_channel(mode=ChannelMode.OBSERVE)

    context = await make_context(paper, **overrides)
    signal = make_signal(source=ParserSource.AI, ai_model="fake/model:free", confidence=0.95)
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is False
    assert decision.reason is expected


# ---------------------------------------------------------------------------
# Fusion des reglages globaux et des overrides de canal
# ---------------------------------------------------------------------------

def test_resolve_settings_un_champ_null_utilise_le_reglage_global() -> None:
    settings = make_settings(risk_percent=0.5, max_lot=0.10, min_confidence=0.85)
    channel = make_channel(risk_percent=None, max_lot=0.25, min_confidence=None)
    effective = resolve_settings(settings, channel)
    assert effective.risk_percent == 0.5
    assert effective.max_lot == 0.25
    assert effective.min_confidence == 0.85
    assert effective.mode is ChannelMode.AUTO


def test_resolve_settings_sans_canal_utilise_tout_le_global() -> None:
    settings = make_settings(allowed_symbols=["XAUUSD"])
    effective = resolve_settings(settings, None)
    assert effective.allowed_symbols == ["XAUUSD"]
    assert effective.copy_buy is True
    assert effective.copy_sell is True
    # Sans canal identifie, le mode par defaut reste le plus prudent.
    assert effective.mode is ChannelMode.OBSERVE


def test_resolve_settings_liste_de_symboles_du_canal_prioritaire() -> None:
    settings = make_settings(allowed_symbols=["XAUUSD", "EURUSD"])
    channel = make_channel(allowed_symbols=["US30"])
    assert resolve_settings(settings, channel).allowed_symbols == ["US30"]


# ---------------------------------------------------------------------------
# Prix de reference
# ---------------------------------------------------------------------------

async def test_zone_d_entree_utilise_le_marche_quand_il_est_dedans(
    paper: PaperTradingService,
) -> None:
    """Le cours simule de XAUUSD est 3350 : il tombe dans la zone 3340-3360."""
    context = await make_context(paper)
    signal = make_signal(entry_price=None, entry_min=3340.0, entry_max=3360.0,
                         stop_loss=3330.0, take_profits=[3380.0])
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is True
    tick = context.tick
    assert tick is not None
    assert decision.entry_price == pytest.approx(tick.ask)


async def test_zone_d_entree_hors_marche_prend_la_borne_favorable(
    paper: PaperTradingService,
) -> None:
    context = await make_context(paper)
    signal = make_signal(entry_price=None, entry_min=3300.0, entry_max=3310.0,
                         stop_loss=3290.0, take_profits=[3330.0])
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is True
    assert decision.entry_price == pytest.approx(3300.0)


async def test_sans_prix_ecrit_le_marche_fait_foi(paper: PaperTradingService) -> None:
    context = await make_context(paper)
    signal = make_signal(entry_price=None, stop_loss=3330.0, take_profits=[3380.0])
    decision = await RiskManager(paper).evaluate(signal, context, ExecutionMode.PAPER)
    assert decision.approved is True
    tick = context.tick
    assert tick is not None
    assert decision.entry_price == pytest.approx(tick.ask)


def test_le_solde_de_reference_vient_du_compte_quand_il_existe() -> None:
    settings = make_settings(paper_balance=500.0)
    context = RiskContext(settings=settings, state=make_state(), account=make_account())
    assert context.balance == pytest.approx(BALANCE)
    assert context.equity == pytest.approx(BALANCE)

    sans_compte = RiskContext(settings=settings, state=make_state())
    assert sans_compte.balance == pytest.approx(500.0)


def test_symbol_info_tradable() -> None:
    assert SymbolInfo(name="X", trade_mode=4).tradable is True
    assert SymbolInfo(name="X", trade_mode=0).tradable is False
    assert SymbolInfo(name="X", trade_mode=3).tradable is False


def test_tick_spread_points() -> None:
    tick = Tick(symbol="XAUUSD", bid=3350.0, ask=3350.20)
    assert tick.spread_points(0.01) == 20
    assert tick.spread_points(0.0) == 0
