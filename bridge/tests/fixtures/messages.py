"""Jeu de messages Telegram realistes (CDC section 48).

Quatre familles, toutes typees et toutes accompagnees du resultat attendu :

* ``CLEAN_SIGNALS``     : signaux bien formes, formats varies ;
* ``FOLLOW_UP_MESSAGES``: messages de suivi rattaches a un signal existant ;
* ``NOISE_MESSAGES``    : bavardage de canal qui ne doit JAMAIS devenir un trade ;
* ``AMBIGUOUS_MESSAGES``: messages incomplets ou incoherents, jamais executables.

Les valeurs attendues ont ete relevees sur le comportement reel du parser
deterministe puis verifiees a la main, message par message.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import Direction, FollowUpAction, OrderType

# Espace insecable etroit et espace insecable : deux separateurs de milliers
# reellement rencontres dans les canaux francophones.
NBSP = "\u00a0"
EM_DASH = "\u2014"


@dataclass(frozen=True, slots=True)
class SignalCase:
    """Un message d'entree et l'interpretation exacte attendue."""

    label: str
    text: str
    symbol: str
    direction: Direction
    order_type: OrderType | None
    stop_loss: float | None
    take_profits: tuple[float, ...]
    entry_price: float | None = None
    entry_min: float | None = None
    entry_max: float | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class FollowUpCase:
    """Un message de suivi et l'action exacte attendue."""

    label: str
    text: str
    action: FollowUpAction
    symbol: str | None = None
    tp_index: int | None = None
    percentage: float | None = None
    price: float | None = None
    also_break_even: bool = False


@dataclass(frozen=True, slots=True)
class AmbiguousCase:
    """Message incomplet ou incoherent : jamais exploitable tel quel.

    Soit le parser refuse d'y voir un signal (``expected_signal`` False), soit
    le validateur strict le bloque avec au moins un code d'anomalie.
    """

    label: str
    text: str
    expected_signal: bool
    issue_codes: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# 1. Signaux propres
# ---------------------------------------------------------------------------

CLEAN_SIGNALS: tuple[SignalCase, ...] = (
    SignalCase(
        label="gold_buy_now",
        text="GOLD BUY NOW\nSL 3310\nTP 3330",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=OrderType.MARKET,
        stop_loss=3310.0,
        take_profits=(3330.0,),
        confidence=0.85,
    ),
    SignalCase(
        label="xauusd_zone_trois_tp",
        text="XAUUSD BUY 3320-3315\nSL 3300\nTP1 3330\nTP2 3345\nTP3 3360",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3300.0,
        take_profits=(3330.0, 3345.0, 3360.0),
        entry_min=3315.0,
        entry_max=3320.0,
        confidence=0.95,
    ),
    SignalCase(
        label="sell_gold_targets",
        text="Sell gold now @ 3341\nstop 3350\ntargets 3330, 3320, 3300",
        symbol="XAUUSD",
        direction=Direction.SELL,
        order_type=OrderType.MARKET,
        stop_loss=3350.0,
        take_profits=(3330.0, 3320.0, 3300.0),
        entry_price=3341.0,
        confidence=1.0,
    ),
    SignalCase(
        label="xau_slash_long",
        text="XAU/USD LONG\nEntry 3325\nSL 3310\nTP1 3340\nTP2 3355",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3310.0,
        take_profits=(3340.0, 3355.0),
        entry_price=3325.0,
        confidence=0.95,
    ),
    SignalCase(
        label="sell_gold_prix_inline",
        text="SELL GOLD 3350\nSL 3362\nTP 3330",
        symbol="XAUUSD",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=3362.0,
        take_profits=(3330.0,),
        entry_price=3350.0,
        confidence=0.95,
    ),
    SignalCase(
        label="buy_gold_zone_inline",
        text="BUY GOLD 3350-3345\nSL 3335\nTP1 3365",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3335.0,
        take_profits=(3365.0,),
        entry_min=3345.0,
        entry_max=3350.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_buy_limit",
        text="XAUUSD BUY LIMIT 3340\nSL 3325\nTP 3370",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=OrderType.BUY_LIMIT,
        stop_loss=3325.0,
        take_profits=(3370.0,),
        entry_price=3340.0,
        confidence=1.0,
    ),
    SignalCase(
        label="xauusd_sell_stop",
        text="XAUUSD SELL STOP 3320\nSL 3335\nTP 3290",
        symbol="XAUUSD",
        direction=Direction.SELL,
        order_type=OrderType.SELL_STOP,
        stop_loss=3335.0,
        take_profits=(3290.0,),
        entry_price=3320.0,
        confidence=1.0,
    ),
    SignalCase(
        label="us30_buy_stop",
        text="US30 BUY STOP 44500\nSL 44300\nTP 45000",
        symbol="US30",
        direction=Direction.BUY,
        order_type=OrderType.BUY_STOP,
        stop_loss=44300.0,
        take_profits=(45000.0,),
        entry_price=44500.0,
        confidence=1.0,
    ),
    SignalCase(
        label="eurusd_buy_decimales",
        text="EURUSD BUY\nENTRY 1.0820\nSL 1.0790\nTP 1.0840",
        symbol="EURUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=1.0790,
        take_profits=(1.0840,),
        entry_price=1.0820,
        confidence=0.95,
    ),
    SignalCase(
        label="eurusd_tp_indexes_decimaux",
        text="EURUSD BUY\nENTRY 1.0820\nSL 1.0790\nTP 1 1.0840\nTP 2 1.0870",
        symbol="EURUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=1.0790,
        take_profits=(1.0840, 1.0870),
        entry_price=1.0820,
        confidence=0.95,
    ),
    SignalCase(
        label="us30_sell_indice_avec_chiffre",
        text="US30 SELL 44250\nSL 44400\nTP 43900",
        symbol="US30",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=44400.0,
        take_profits=(43900.0,),
        entry_price=44250.0,
        confidence=0.95,
    ),
    SignalCase(
        label="nas100_buy_now",
        text="NAS100 BUY NOW\nSL 20050\nTP1 20250\nTP2 20400",
        symbol="NAS100",
        direction=Direction.BUY,
        order_type=OrderType.MARKET,
        stop_loss=20050.0,
        take_profits=(20250.0, 20400.0),
        confidence=0.85,
    ),
    SignalCase(
        label="nasdaq_alias",
        text="NASDAQ SELL\nENTRY 20150\nSL 20250\nTP 19900",
        symbol="NAS100",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=20250.0,
        take_profits=(19900.0,),
        entry_price=20150.0,
        confidence=0.95,
    ),
    SignalCase(
        label="ger40_sell",
        text="GER40 SELL\nENTRY 18250\nSL 18350\nTP 18050",
        symbol="GER40",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=18350.0,
        take_profits=(18050.0,),
        entry_price=18250.0,
        confidence=0.95,
    ),
    SignalCase(
        label="btcusd_buy",
        text="BTCUSD BUY 68000\nSL 67000\nTP 70000",
        symbol="BTCUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=67000.0,
        take_profits=(70000.0,),
        entry_price=68000.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xagusd_sell",
        text="XAGUSD SELL 31.50\nSL 31.90\nTP 30.80",
        symbol="XAGUSD",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=31.90,
        take_profits=(30.80,),
        entry_price=31.50,
        confidence=0.95,
    ),
    SignalCase(
        label="gbpjpy_zone_entree",
        text="GBPJPY BUY\nENTRY ZONE 195.20 - 195.60\nSTOP LOSS 194.80\nTARGETS 196.20, 196.80",
        symbol="GBPJPY",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=194.80,
        take_profits=(196.20, 196.80),
        entry_min=195.20,
        entry_max=195.60,
        confidence=0.95,
    ),
    SignalCase(
        label="usdjpy_deux_points",
        text="USDJPY SELL\nEntry: 155.20\nSL: 155.80\nTP1: 154.60\nTP2: 154.00",
        symbol="USDJPY",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=155.80,
        take_profits=(154.60, 154.00),
        entry_price=155.20,
        confidence=0.95,
    ),
    SignalCase(
        label="gold_emojis",
        text="\U0001f525\U0001f525 GOLD BUY NOW \U0001f525\U0001f525\n\U0001f4c9 SL 3310\n\U0001f3af TP 3330 \U0001f3af",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=OrderType.MARKET,
        stop_loss=3310.0,
        take_profits=(3330.0,),
        confidence=0.85,
    ),
    SignalCase(
        label="gold_decorations",
        text="★ XAUUSD SELL ★\n• SL 3365\n• TP1 3335\n• TP2 3320",
        symbol="XAUUSD",
        direction=Direction.SELL,
        order_type=OrderType.MARKET,
        stop_loss=3365.0,
        take_profits=(3335.0, 3320.0),
        confidence=0.85,
    ),
    SignalCase(
        label="gbpusd_minuscules",
        text="gbpusd buy\nentry 1.2650\nsl 1.2600\ntp 1.2750",
        symbol="GBPUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=1.2600,
        take_profits=(1.2750,),
        entry_price=1.2650,
        confidence=0.95,
    ),
    SignalCase(
        label="gold_lignes_vides",
        text="GOLD SELL\n\nENTRY 3350\n\nSL 3365\n\nTP1 3335\nTP2 3320\nTP3 3300",
        symbol="XAUUSD",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=3365.0,
        take_profits=(3335.0, 3320.0, 3300.0),
        entry_price=3350.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_virgule_decimale",
        text="XAUUSD BUY\nENTRY 3 320,50\nSL 3 310,00\nTP 3 340,00",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3310.0,
        take_profits=(3340.0,),
        entry_price=3320.50,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_espace_insecable",
        text=f"XAUUSD BUY\nENTRY 3{NBSP}320.50\nSL 3{NBSP}310.00\nTP 3{NBSP}340.00",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3310.0,
        take_profits=(3340.0,),
        entry_price=3320.50,
        confidence=0.95,
    ),
    SignalCase(
        label="us30_separateur_milliers",
        text="SELL US30\nENTRY 44,250.0\nSL 44,400.0\nTP 43,900.0",
        symbol="US30",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=44400.0,
        take_profits=(43900.0,),
        entry_price=44250.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_tiret_long",
        text=f"XAUUSD BUY 3320{EM_DASH}3315\nSL 3300\nTP 3350",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3300.0,
        take_profits=(3350.0,),
        entry_min=3315.0,
        entry_max=3320.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_suffixe_broker",
        text="XAUUSDm BUY\nENTRY 3320\nSL 3305\nTP 3350",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3305.0,
        take_profits=(3350.0,),
        entry_price=3320.0,
        confidence=0.95,
    ),
    SignalCase(
        label="gu_alias_court",
        text="GU BUY\nENTRY 1.2650\nSL 1.2600\nTP 1.2750",
        symbol="GBPUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=1.2600,
        take_profits=(1.2750,),
        entry_price=1.2650,
        confidence=0.95,
    ),
    SignalCase(
        label="gj_alias_court",
        text="GJ SELL\nENTRY 195.50\nSL 196.00\nTP 194.50",
        symbol="GBPJPY",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=196.00,
        take_profits=(194.50,),
        entry_price=195.50,
        confidence=0.95,
    ),
    SignalCase(
        label="cable_alias",
        text="CABLE BUY NOW\nSL 1.2600\nTP 1.2720",
        symbol="GBPUSD",
        direction=Direction.BUY,
        order_type=OrderType.MARKET,
        stop_loss=1.2600,
        take_profits=(1.2720,),
        confidence=0.85,
    ),
    SignalCase(
        label="audusd_buy",
        text="AUDUSD BUY\nENTRY 0.6550\nSL 0.6520\nTP 0.6600",
        symbol="AUDUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=0.6520,
        take_profits=(0.6600,),
        entry_price=0.6550,
        confidence=0.95,
    ),
    SignalCase(
        label="gold_stop_loss_en_toutes_lettres",
        text="GOLD SELL\nENTRY 3350\nSTOP LOSS 3365\nTAKE PROFIT 3320",
        symbol="XAUUSD",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=3365.0,
        take_profits=(3320.0,),
        entry_price=3350.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_fleches",
        text="XAUUSD BUY\nENTRY -> 3320\nSL -> 3310\nTP -> 3340",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3310.0,
        take_profits=(3340.0,),
        entry_price=3320.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_valeurs_ligne_suivante",
        text="XAUUSD BUY\nENTRY\n3320\nSL\n3310\nTP\n3340",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3310.0,
        take_profits=(3340.0,),
        entry_price=3320.0,
        confidence=0.95,
    ),
    SignalCase(
        label="gold_barres_verticales",
        text="GOLD BUY | ENTRY 3320 | SL 3310 | TP 3340",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3310.0,
        take_profits=(3340.0,),
        entry_price=3320.0,
        confidence=0.95,
    ),
    SignalCase(
        label="eurusd_sell_limit_inverse",
        text="SELL LIMIT EURUSD 1.0900\nSL 1.0940\nTP 1.0820",
        symbol="EURUSD",
        direction=Direction.SELL,
        order_type=OrderType.SELL_LIMIT,
        stop_loss=1.0940,
        take_profits=(1.0820,),
        entry_price=1.0900,
        confidence=1.0,
    ),
    SignalCase(
        label="gbpusd_short",
        text="GBPUSD SHORT\nENTRY 1.2650\nSL 1.2700\nTP1 1.2600\nTP2 1.2550",
        symbol="GBPUSD",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=1.2700,
        take_profits=(1.2600, 1.2550),
        entry_price=1.2650,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_market",
        text="XAUUSD BUY MARKET\nSL 3300\nTP 3400",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=OrderType.MARKET,
        stop_loss=3300.0,
        take_profits=(3400.0,),
        confidence=0.85,
    ),
    SignalCase(
        label="xauusd_cmp",
        text="XAUUSD BUY CMP\nSL 3300\nTP 3400",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=OrderType.MARKET,
        stop_loss=3300.0,
        take_profits=(3400.0,),
        confidence=0.85,
    ),
    SignalCase(
        label="gold_arobase",
        text="GOLD BUY @ 3320\nSL @ 3308\nTP @ 3345",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3308.0,
        take_profits=(3345.0,),
        entry_price=3320.0,
        confidence=0.95,
    ),
    SignalCase(
        label="gold_signe_egal",
        text="GOLD SELL\nENTRY = 3350\nSL = 3365\nTP = 3330",
        symbol="XAUUSD",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=3365.0,
        take_profits=(3330.0,),
        entry_price=3350.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_zone_mot_cle",
        text="XAUUSD SELL\nENTRY ZONE 3350 - 3356\nSL 3365\nTP1 3335\nTP2 3320",
        symbol="XAUUSD",
        direction=Direction.SELL,
        order_type=None,
        stop_loss=3365.0,
        take_profits=(3335.0, 3320.0),
        entry_min=3350.0,
        entry_max=3356.0,
        confidence=0.95,
    ),
    SignalCase(
        label="xauusd_tp_multiples_meme_ligne",
        text="XAUUSD BUY 3320\nSL 3310\nTP 3330 3340 3350",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3310.0,
        take_profits=(3330.0, 3340.0, 3350.0),
        entry_price=3320.0,
        confidence=0.95,
    ),
    SignalCase(
        label="cdc_scenario_82",
        text="XAUUSD BUY\nENTRY 3320\nSL 3310\nTP1 3330\nTP2 3340",
        symbol="XAUUSD",
        direction=Direction.BUY,
        order_type=None,
        stop_loss=3310.0,
        take_profits=(3330.0, 3340.0),
        entry_price=3320.0,
        confidence=0.95,
    ),
)


# ---------------------------------------------------------------------------
# 2. Messages de suivi
# ---------------------------------------------------------------------------

FOLLOW_UP_MESSAGES: tuple[FollowUpCase, ...] = (
    FollowUpCase("tp1_hit", "TP1 HIT", FollowUpAction.TP_HIT, tp_index=1),
    FollowUpCase("tp2_hit", "TP2 HIT", FollowUpAction.TP_HIT, tp_index=2),
    FollowUpCase(
        "target_2_reached", "TARGET 2 REACHED", FollowUpAction.TP_HIT, tp_index=2
    ),
    FollowUpCase("close_gold", "CLOSE GOLD", FollowUpAction.CLOSE_ALL, symbol="XAUUSD"),
    FollowUpCase("close_xauusd", "CLOSE XAUUSD", FollowUpAction.CLOSE_ALL, symbol="XAUUSD"),
    FollowUpCase("close_now", "CLOSE NOW", FollowUpAction.CLOSE_ALL),
    FollowUpCase(
        "close_all_positions", "Close all positions now", FollowUpAction.CLOSE_ALL
    ),
    FollowUpCase("close_50", "CLOSE 50%", FollowUpAction.CLOSE_PARTIAL, percentage=50.0),
    FollowUpCase("close_half", "CLOSE HALF", FollowUpAction.CLOSE_PARTIAL, percentage=50.0),
    FollowUpCase("book_30", "Book 30% profit", FollowUpAction.CLOSE_PARTIAL, percentage=30.0),
    FollowUpCase("move_sl_to_be", "MOVE SL TO BE", FollowUpAction.MOVE_SL_BE),
    FollowUpCase("sl_be", "SL BE", FollowUpAction.MOVE_SL_BE),
    FollowUpCase("break_even", "BREAK EVEN", FollowUpAction.MOVE_SL_BE),
    FollowUpCase("risk_free", "risk free now", FollowUpAction.MOVE_SL_BE),
    FollowUpCase("move_sl_prix", "MOVE SL 3350", FollowUpAction.MOVE_SL, price=3350.0),
    FollowUpCase("move_tp1", "MOVE TP1 TO 3360", FollowUpAction.MOVE_TP, tp_index=1, price=3360.0),
    FollowUpCase(
        "cancel_gold", "CANCEL GOLD", FollowUpAction.CANCEL_PENDING, symbol="XAUUSD"
    ),
    FollowUpCase("delete_pending", "DELETE PENDING", FollowUpAction.CANCEL_PENDING),
    FollowUpCase(
        "cancel_pending_gold",
        "Cancel the pending order on gold",
        FollowUpAction.CANCEL_PENDING,
        symbol="XAUUSD",
    ),
    FollowUpCase("running_pips", "RUNNING +50 PIPS", FollowUpAction.INFO),
    FollowUpCase("hold", "HOLD", FollowUpAction.INFO),
    FollowUpCase(
        "tp1_hit_move_sl_be",
        "TP1 HIT MOVE SL BE",
        FollowUpAction.TP_HIT,
        tp_index=1,
        also_break_even=True,
    ),
    FollowUpCase("sl_hit", "SL HIT", FollowUpAction.SL_HIT),
)


# ---------------------------------------------------------------------------
# 3. Bruit : jamais de trade
# ---------------------------------------------------------------------------

NOISE_MESSAGES: tuple[tuple[str, str], ...] = (
    ("bonjour_famille", "GOOD MORNING FAMILY \U0001f525"),
    ("opinion_haussiere", "Gold is looking very bullish today"),
    ("resultats_semaine", "Results of the week: +450 pips"),
    ("promo_vip", "Join our VIP channel now for premium signals"),
    ("felicitations", "Congratulations everyone on todays profits"),
    ("message_vide", ""),
    ("emojis_seuls", "\U0001f525\U0001f525\U0001f525"),
    ("surveillance_or", "we are watching gold closely"),
    ("volatilite", "Market is very volatile today, stay safe"),
    ("message_epingle", "Please read the pinned message before trading"),
    ("bravo_equipe", "Well done team, great session"),
    ("analyse_dollar", "Our analysis of the dollar index shows strength"),
    ("bon_weekend", "Have a nice weekend everyone"),
    ("croissance_compte", "The account grew from 1000 to 2500 this month"),
)


# ---------------------------------------------------------------------------
# 4. Messages ambigus ou incoherents
# ---------------------------------------------------------------------------

AMBIGUOUS_MESSAGES: tuple[AmbiguousCase, ...] = (
    AmbiguousCase(
        label="buy_sans_instrument",
        text="BUY NOW\nSL 3310\nTP 3330",
        expected_signal=False,
        issue_codes=("NO_ACTION",),
    ),
    AmbiguousCase(
        label="prix_sans_direction",
        text="GOLD 3320 3310 3330",
        expected_signal=False,
        issue_codes=("NO_ACTION",),
    ),
    AmbiguousCase(
        label="sl_mauvais_cote_achat",
        text="XAUUSD BUY 3320\nSL 3340\nTP 3350",
        expected_signal=True,
        issue_codes=("SL_WRONG_SIDE",),
    ),
    AmbiguousCase(
        label="sl_et_tp_mauvais_cote_vente",
        text="XAUUSD SELL 3320\nSL 3300\nTP 3350",
        expected_signal=True,
        issue_codes=("SL_WRONG_SIDE", "TP_WRONG_SIDE"),
    ),
    AmbiguousCase(
        label="sl_absurde_trop_loin",
        text="EURUSD BUY 1.0820\nSL 0.5000\nTP 1.0870",
        expected_signal=True,
        issue_codes=("SL_TOO_FAR",),
    ),
    AmbiguousCase(
        label="virgule_a_quatre_decimales_mal_lue",
        # "1,0820" n'est ni un separateur de milliers (3 chiffres) ni une
        # decimale courte : la valeur est mal lue (1.0). Le validateur doit
        # imperativement bloquer plutot que de laisser passer un faux prix.
        text="BUY EURUSD @ 1,0820\nSL 1,0790\nTP 1,0870",
        expected_signal=True,
        issue_codes=("SL_TOO_CLOSE",),
    ),
    AmbiguousCase(
        label="ordre_en_attente_sans_prix",
        text="XAUUSD BUY LIMIT\nSL 3300\nTP 3350",
        expected_signal=True,
        issue_codes=("PENDING_WITHOUT_PRICE",),
    ),
    AmbiguousCase(
        label="tp_du_mauvais_cote",
        text="XAUUSD BUY\nENTRY 3320\nSL 3310\nTP 3300",
        expected_signal=True,
        issue_codes=("TP_WRONG_SIDE",),
    ),
)


ALL_MESSAGE_COUNT = (
    len(CLEAN_SIGNALS) + len(FOLLOW_UP_MESSAGES) + len(NOISE_MESSAGES) + len(AMBIGUOUS_MESSAGES)
)
