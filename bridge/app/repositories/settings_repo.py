"""Acces aux reglages : risque, etat du moteur, cle/valeur, mapping de symboles."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import SINGLETON_ID, AppSetting, RiskSettings, TradingState, as_utc, utcnow
from app.models.trading import SymbolMapping


async def get_risk_settings(session: AsyncSession) -> RiskSettings:
    settings = await session.get(RiskSettings, SINGLETON_ID)
    if settings is None:
        settings = RiskSettings(id=SINGLETON_ID)
        session.add(settings)
        await session.flush()
    return settings


async def update_risk_settings(session: AsyncSession, changes: dict[str, Any]) -> RiskSettings:
    settings = await get_risk_settings(session)
    protected = {"id", "live_unlocked", "updated_at"}
    for key, value in changes.items():
        if key in protected or value is None:
            continue
        if hasattr(settings, key):
            setattr(settings, key, value)
    settings.updated_at = utcnow()
    session.add(settings)
    await session.flush()
    return settings


async def get_trading_state(session: AsyncSession) -> TradingState:
    """Etat du trading, avec les pauses echues deja levees.

    Le coupe-circuit pose une pause avec une echeance. Le RiskManager, lui,
    respectait bien cette echeance -- il laissait passer les ordres des qu'elle
    etait franchie. Mais le drapeau ``paused`` restait vrai en base, et c'est
    lui que l'application affiche : le 13/09/2026, le telephone annoncait
    encore « en pause » treize heures apres la fin de la pause.

    Lever l'echeance ici met tout le monde d'accord sur un seul etat, celui
    qu'on lit et celui qu'on applique.
    """
    state = await session.get(TradingState, SINGLETON_ID)
    if state is None:
        state = TradingState(id=SINGLETON_ID)
        session.add(state)
        await session.flush()
        return state

    limite = as_utc(state.paused_until)
    if state.paused and limite is not None and limite <= utcnow():
        state.paused = False
        state.pause_reason = None
        state.paused_until = None
        session.add(state)
        await session.flush()
    return state


async def save_trading_state(session: AsyncSession, state: TradingState) -> TradingState:
    state.updated_at = utcnow()
    session.add(state)
    await session.flush()
    return state


async def reset_account_baselines(session: AsyncSession) -> TradingState:
    """Oublie les reperes lies au compte : plus haut d'equity et solde du jour.

    A appeler a chaque changement de mode d'execution. Le compte papier, le
    compte de demonstration et le compte reel n'ont ni le meme solde ni la
    meme histoire : garder les reperes de l'un pour mesurer l'autre produit
    des chiffres absurdes. Passer de 10 000 en papier a 50 en demo affichait
    99,5 % de drawdown, et la limite de perte maximale aurait refuse tous les
    ordres.

    Les deux reperes sont recalcules au cycle suivant a partir du compte
    reellement actif.
    """
    state = await get_trading_state(session)
    state.peak_equity = None
    state.day_start_balance = None
    state.day_key = None
    state.updated_at = utcnow()
    return await save_trading_state(session, state)


def today_key(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%d")


async def ensure_day_rollover(session: AsyncSession, current_balance: float | None) -> TradingState:
    """Reinitialise les compteurs journaliers au changement de jour UTC.

    Ne juge JAMAIS l'ecart entre le solde et les compteurs : appele en tete de
    cycle, le solde recu vient du courtier et inclut deja les positions
    fermees a l'instant, que ``day_realized_pnl`` ne connait pas encore. C'est
    le role de ``reconcile_external_balance_move``, appele une fois les
    clotures comptabilisees.
    """
    state = await get_trading_state(session)
    key = today_key()
    if state.day_key != key:
        state.day_key = key
        state.day_start_balance = current_balance
        state.day_realized_pnl = 0.0
        state.day_risked_percent = 0.0
        # Le sommet d'equite tombe avec les autres compteurs du jour. La
        # verification du drawdown vit dans ``_check_daily_limits`` : le garder
        # d'un jour sur l'autre faisait d'une limite JOURNALIERE un plafond a
        # vie, et une fois franchie elle ne relachait plus jamais.
        #
        # Constate le 16/09/2026 : sommet 472,79, solde 424,65, soit 10,18 %
        # pour une limite a 10 %. Tous les ordres etaient refuses et aucune
        # position n'etait ouverte, donc rien ne pouvait regagner les 0,86 $
        # manquants. Un arret definitif, pas un coupe-circuit.
        #
        # Le meme remede existait pour le changement de mode d'execution, et sa
        # docstring decrivait deja la meme panne. Il se reconstruit au tour
        # suivant sur l'equite reelle du jour qui commence.
        state.peak_equity = None
        state.updated_at = utcnow()
        session.add(state)
        await session.flush()
    elif state.day_start_balance is None and current_balance is not None:
        state.day_start_balance = current_balance
        session.add(state)
        await session.flush()
    return state


async def reconcile_external_balance_move(
    session: AsyncSession, current_balance: float | None
) -> TradingState:
    """Recale les reperes du jour apres un mouvement d'argent externe.

    Hors trading, le solde ne bouge pas : il vaut le solde du matin plus le
    realise du jour. Tout ecart vient d'un mouvement externe -- rechargement
    du compte demo, depot, retrait. Garder l'ancien repere mesurerait les
    pertes du jour sur un capital qui n'existe plus : apres un passage de 50 a
    500, une limite a 8 % aurait arrete la journee des 4 dollars perdus au
    lieu de 40.

    **A n'appeler qu'une fois les clotures du cycle comptabilisees.** Tant que
    ``day_realized_pnl`` ignore une position fermee, l'ecart vaut exactement le
    resultat de cette position et la confusion est totale : le 14/09/2026, les
    quatre pertes de la journee (-48, -40, -43,18, -36,08 sur un compte de
    540 $) depassaient toutes la tolerance de 5 %. Chacune a donc reecrit
    ``day_start_balance`` et efface ``peak_equity`` -- autrement dit, plus la
    perte etait grosse, plus surement elle effacait la memoire des deux
    garde-fous charges de l'arreter. Le compte a perdu 28,5 % dans la journee
    sans que ``max_daily_loss_percent`` (50 %) ni ``max_drawdown_percent``
    (10 %) ne puissent se declencher une seule fois.
    """
    state = await get_trading_state(session)
    if current_balance is None or state.day_start_balance is None:
        return state
    if state.day_key != today_key():
        return state

    attendu = state.day_start_balance + state.day_realized_pnl
    tolerance = max(5.0, abs(attendu) * 0.05)
    if abs(current_balance - attendu) > tolerance:
        state.day_start_balance = current_balance - state.day_realized_pnl
        state.peak_equity = None
        state.updated_at = utcnow()
        session.add(state)
        await session.flush()
    return state


# ---------------------------------------------------------------------------
# Cle / valeur generique
# ---------------------------------------------------------------------------

async def get_setting(session: AsyncSession, key: str, default: Any = None) -> Any:
    record = await session.get(AppSetting, key)
    if record is None or record.value is None:
        return default
    try:
        return json.loads(record.value)
    except json.JSONDecodeError:
        return record.value


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    record = await session.get(AppSetting, key)
    if record is None:
        session.add(AppSetting(key=key, value=payload, updated_at=utcnow()))
    else:
        record.value = payload
        record.updated_at = utcnow()
        session.add(record)
    await session.flush()


# ---------------------------------------------------------------------------
# Mapping de symboles
# ---------------------------------------------------------------------------

async def list_symbol_mappings(session: AsyncSession) -> list[SymbolMapping]:
    result = await session.exec(select(SymbolMapping).order_by(SymbolMapping.alias))
    return list(result.all())


async def get_mapping_by_alias(session: AsyncSession, alias: str) -> SymbolMapping | None:
    result = await session.exec(
        select(SymbolMapping).where(SymbolMapping.alias == alias.upper(), SymbolMapping.enabled == True)
    )
    return result.first()


async def upsert_symbol_mapping(
    session: AsyncSession,
    alias: str,
    canonical: str,
    broker_symbol: str | None = None,
    auto_detected: bool = False,
) -> SymbolMapping:
    alias_key = alias.strip().upper()
    result = await session.exec(select(SymbolMapping).where(SymbolMapping.alias == alias_key))
    mapping = result.first()
    if mapping is None:
        mapping = SymbolMapping(
            alias=alias_key,
            canonical=canonical.strip().upper(),
            broker_symbol=broker_symbol,
            auto_detected=auto_detected,
        )
    else:
        mapping.canonical = canonical.strip().upper()
        if broker_symbol is not None:
            mapping.broker_symbol = broker_symbol
        mapping.auto_detected = auto_detected
    mapping.updated_at = utcnow()
    session.add(mapping)
    await session.flush()
    return mapping


async def delete_symbol_mapping(session: AsyncSession, mapping_id: int) -> bool:
    mapping = await session.get(SymbolMapping, mapping_id)
    if mapping is None:
        return False
    await session.delete(mapping)
    await session.flush()
    return True


async def broker_symbol_for(session: AsyncSession, canonical: str) -> str | None:
    result = await session.exec(
        select(SymbolMapping).where(
            SymbolMapping.canonical == canonical.upper(),
            SymbolMapping.broker_symbol != None,  # noqa: E711
            SymbolMapping.enabled == True,
        )
    )
    mapping = result.first()
    return mapping.broker_symbol if mapping else None
