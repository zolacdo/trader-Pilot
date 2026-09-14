"""Pipeline d'analyse : idempotence, rattachement des suivis, apprentissage.

Le pipeline ecrit en base : chaque test part d'une base vierge fournie par la
fixture ``database``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import FollowUpAction, ParserSource, SignalStatus
from app.models.telegram import Channel
from app.repositories import channel_repo, signal_repo
from app.services.openrouter.service import OpenRouterService, openrouter_service
from app.services.signals import pipeline

NOW = datetime(2025, 6, 4, 12, 0, tzinfo=UTC)

SIGNAL_TEXT = "XAUUSD BUY\nENTRY 3320\nSL 3310\nTP1 3330\nTP2 3340"
GOLD_TEXT = "GOLD BUY NOW\nSL 3310\nTP 3330"


async def make_channel(session: AsyncSession, telegram_id: int = 1001) -> Channel:
    channel = await channel_repo.upsert(
        session, telegram_id=telegram_id, title="Canal de test", username="canaltest"
    )
    assert channel.id is not None
    return channel


# ---------------------------------------------------------------------------
# Idempotence (CDC sections 26 et 85)
# ---------------------------------------------------------------------------

async def test_le_meme_message_ne_produit_qu_un_seul_signal(session: AsyncSession) -> None:
    channel = await make_channel(session)

    first = await pipeline.process_message(
        session, SIGNAL_TEXT, channel=channel, message_id=42, message_date=NOW, allow_ai=False
    )
    second = await pipeline.process_message(
        session, SIGNAL_TEXT, channel=channel, message_id=42, message_date=NOW, allow_ai=False
    )

    assert first.action == "new_signal"
    assert second.action == "duplicate"
    assert second.signal is not None
    assert second.signal.id == first.signal.id
    assert len(await signal_repo.list_signals(session, limit=50)) == 1


async def test_idempotence_sur_le_contenu_sans_identifiant_de_message(
    session: AsyncSession,
) -> None:
    channel = await make_channel(session)

    first = await pipeline.process_message(session, SIGNAL_TEXT, channel=channel, allow_ai=False)
    # Meme contenu, mise en forme differente : la cle de contenu est identique.
    second = await pipeline.process_message(
        session, "  xauusd buy \n entry: 3320 \n sl: 3310 \n tp1: 3330 \n tp2: 3340 ",
        channel=channel, allow_ai=False,
    )

    assert first.action == "new_signal"
    assert second.action == "duplicate"


async def test_deux_messages_differents_produisent_deux_signaux(session: AsyncSession) -> None:
    channel = await make_channel(session)
    first = await pipeline.process_message(
        session, SIGNAL_TEXT, channel=channel, message_id=1, allow_ai=False
    )
    second = await pipeline.process_message(
        session, "EURUSD SELL\nENTRY 1.0900\nSL 1.0940\nTP 1.0820",
        channel=channel, message_id=2, allow_ai=False,
    )
    assert first.action == second.action == "new_signal"
    assert first.signal.id != second.signal.id


# ---------------------------------------------------------------------------
# Signaux structures
# ---------------------------------------------------------------------------

async def test_un_signal_valide_est_persiste_avec_ses_valeurs(session: AsyncSession) -> None:
    channel = await make_channel(session)
    result = await pipeline.process_message(
        session, SIGNAL_TEXT, channel=channel, message_id=7, message_date=NOW, allow_ai=False
    )

    signal = result.signal
    assert signal is not None
    assert signal.status is SignalStatus.PARSED
    assert signal.normalized_symbol == "XAUUSD"
    assert signal.entry_price == 3320.0
    assert signal.stop_loss == 3310.0
    assert signal.take_profits == [3330.0, 3340.0]
    assert signal.parser_source is ParserSource.DETERMINISTIC
    assert signal.message_date == NOW

    events = await signal_repo.events_for(session, signal.id)
    assert any(event.stage == "parser" for event in events)


async def test_un_signal_incoherent_part_en_revue(session: AsyncSession) -> None:
    channel = await make_channel(session)
    result = await pipeline.process_message(
        session, "XAUUSD BUY 3320\nSL 3340\nTP 3350", channel=channel, message_id=8, allow_ai=False
    )
    assert result.signal is not None
    assert result.signal.status is SignalStatus.NEEDS_REVIEW
    assert result.action == "no_action"
    assert result.validation is not None and result.validation.ok is False


async def test_mode_manuel_retourne_le_signal_en_revue(session: AsyncSession) -> None:
    channel = await make_channel(session)
    result = await pipeline.process_message(
        session, "XAUUSD BUY 3320\nSL 3340\nTP 3350",
        channel=channel, message_id=9, allow_ai=False, manual=True,
    )
    assert result.action == "new_signal"
    assert result.signal is not None
    assert result.signal.status is SignalStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# Messages sans intention de trade
# ---------------------------------------------------------------------------

async def test_le_bavardage_est_ignore_sans_ecriture(session: AsyncSession) -> None:
    channel = await make_channel(session)
    result = await pipeline.process_message(
        session, "Gold is looking very bullish today", channel=channel, message_id=10, allow_ai=False
    )
    assert result.action == "ignored"
    assert result.signal is None
    assert await signal_repo.list_signals(session, limit=10) == []


async def test_un_message_proche_d_un_signal_n_est_pas_enregistre(
    session: AsyncSession,
) -> None:
    """Un message qui parle de trading sans en ordonner un n'est pas un signal.

    Il etait enregistre en NO_ACTION pour garder une trace, mais cette trace
    remplissait la liste que l'utilisateur consulte : des cartes sans symbole,
    sans entree, sans stop, a 0 % de confiance. La trace vit desormais au
    journal ; la table des signaux ne contient que des signaux.
    """
    channel = await make_channel(session)
    result = await pipeline.process_message(
        session, "We will look for a BUY setup later today",
        channel=channel, message_id=11, allow_ai=False,
    )
    assert result.action == "no_action"
    assert result.signal is None
    assert await signal_repo.list_signals(session, limit=10) == []


# ---------------------------------------------------------------------------
# Rattachement des messages de suivi
# ---------------------------------------------------------------------------

async def test_suivi_rattache_par_reponse_telegram(session: AsyncSession) -> None:
    channel = await make_channel(session)
    parent = await pipeline.process_message(
        session, SIGNAL_TEXT, channel=channel, message_id=100, allow_ai=False
    )
    assert parent.signal is not None

    result = await pipeline.process_message(
        session, "TP1 HIT", channel=channel, message_id=101,
        reply_to_message_id=100, allow_ai=False,
    )

    assert result.action == "follow_up"
    assert result.parent_signal is not None
    assert result.parent_signal.id == parent.signal.id
    assert result.signal is not None
    assert result.signal.follow_up_action is FollowUpAction.TP_HIT
    assert result.signal.original_signal_id == parent.signal.id


async def test_suivi_rattache_par_symbole(session: AsyncSession) -> None:
    channel = await make_channel(session)
    parent = await pipeline.process_message(
        session, SIGNAL_TEXT, channel=channel, message_id=200, allow_ai=False
    )
    assert parent.signal is not None
    # Le signal doit etre actif pour qu'un suivi puisse s'y rattacher.
    await signal_repo.set_status(
        session, parent.signal, SignalStatus.OPEN, stage="test", message="position ouverte"
    )

    result = await pipeline.process_message(
        session, "CLOSE GOLD NOW", channel=channel, message_id=201, allow_ai=False
    )

    assert result.action == "follow_up"
    assert result.parent_signal is not None
    assert result.parent_signal.id == parent.signal.id
    assert result.signal is not None
    assert result.signal.follow_up_action is FollowUpAction.CLOSE_ALL
    assert result.signal.normalized_symbol == "XAUUSD"


async def test_suivi_orphelin_ne_declenche_aucune_action(session: AsyncSession) -> None:
    channel = await make_channel(session)
    result = await pipeline.process_message(
        session, "TP1 HIT", channel=channel, message_id=300, allow_ai=False
    )
    assert result.action == "no_action"
    assert result.signal is None
    assert "non rattachable" in result.detail


async def test_suivi_ambigu_sans_instrument_avec_plusieurs_signaux_actifs(
    session: AsyncSession,
) -> None:
    """Deux positions ouvertes, aucun instrument cite : on refuse de choisir."""
    channel = await make_channel(session)
    for message_id, text in (
        (400, SIGNAL_TEXT),
        (401, "EURUSD SELL\nENTRY 1.0900\nSL 1.0940\nTP 1.0820"),
    ):
        result = await pipeline.process_message(
            session, text, channel=channel, message_id=message_id, allow_ai=False
        )
        assert result.signal is not None
        await signal_repo.set_status(
            session, result.signal, SignalStatus.OPEN, stage="test", message="ouverte"
        )

    result = await pipeline.process_message(
        session, "CLOSE NOW", channel=channel, message_id=402, allow_ai=False
    )
    assert result.action == "no_action"


# ---------------------------------------------------------------------------
# Apprentissage du profil de canal (CDC section 53)
# ---------------------------------------------------------------------------

async def test_le_profil_de_canal_apprend_le_gabarit(session: AsyncSession) -> None:
    channel = await make_channel(session)
    await pipeline.process_message(
        session, SIGNAL_TEXT, channel=channel, message_id=500, allow_ai=False
    )

    profile = await channel_repo.get_profile(session, channel.id)
    assert profile.deterministic_success == 1
    assert profile.ai_fallback_count == 0
    assert profile.last_successful_format == "BUY|ENTRY|SL|TP1|TP2"
    assert "BUY|ENTRY|SL|TP1|TP2" in profile.known_formats
    assert profile.confidence == 1.0


async def test_le_profil_de_canal_memorise_les_alias(session: AsyncSession) -> None:
    channel = await make_channel(session)
    await pipeline.process_message(
        session, GOLD_TEXT, channel=channel, message_id=501, allow_ai=False
    )

    aliases = await channel_repo.channel_aliases(session, channel.id)
    assert aliases.get("GOLD") == "XAUUSD"


async def test_un_alias_de_canal_est_reutilise_par_le_parser(session: AsyncSession) -> None:
    channel = await make_channel(session)
    await channel_repo.add_symbol_alias(session, channel.id, "ZEDAX", "GER40")

    parsed, validation = await pipeline.analyze_text(
        session, "ZEDAX BUY\nENTRY 18250\nSL 18150\nTP 18500", channel.id, allow_ai=False
    )
    assert parsed.symbol == "GER40"
    assert validation.ok is True


# ---------------------------------------------------------------------------
# L'IA n'est jamais appelee sans autorisation explicite
# ---------------------------------------------------------------------------

def _fail_if_called(*args: object, **kwargs: object) -> None:
    raise AssertionError("OpenRouter ne doit jamais etre appele ici")


async def test_analyze_text_sans_ia_n_appelle_jamais_openrouter(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(OpenRouterService, "configured", property(lambda self: True))
    monkeypatch.setattr(openrouter_service, "parse_signal", _fail_if_called)

    # Message volontairement ambigu : c'est exactement le cas ou l'IA serait
    # sollicitee si elle etait autorisee.
    parsed, validation = await pipeline.analyze_text(
        session, "gold buy area 3320 sl maybe 3310", None, allow_ai=False
    )
    assert parsed.source is ParserSource.DETERMINISTIC
    assert validation is not None


async def test_process_message_sans_ia_n_appelle_jamais_openrouter(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(OpenRouterService, "configured", property(lambda self: True))
    monkeypatch.setattr(openrouter_service, "parse_signal", _fail_if_called)

    channel = await make_channel(session)
    result = await pipeline.process_message(
        session, "gold buy area 3320 sl maybe 3310",
        channel=channel, message_id=600, allow_ai=False,
    )
    assert result.action in {"new_signal", "no_action", "ignored"}


async def test_le_repli_ia_est_bien_branche_quand_il_est_autorise(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preuve que le garde-fou precedent teste bien quelque chose."""
    monkeypatch.setattr(OpenRouterService, "configured", property(lambda self: True))
    monkeypatch.setattr(openrouter_service, "parse_signal", _fail_if_called)

    with pytest.raises(AssertionError):
        await pipeline.analyze_text(
            session, "gold buy area 3320 sl maybe 3310", None, allow_ai=True
        )


async def test_un_message_de_bavardage_n_interroge_jamais_l_ia(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CDC section 20 : aucun quota gratuit gaspille sur du bavardage."""
    monkeypatch.setattr(OpenRouterService, "configured", property(lambda self: True))
    monkeypatch.setattr(openrouter_service, "parse_signal", _fail_if_called)

    parsed, _ = await pipeline.analyze_text(
        session, "GOOD MORNING FAMILY", None, allow_ai=True
    )
    assert parsed.is_signal is False


# ---------------------------------------------------------------------------
# Reconstruction d'un ParsedSignal depuis la base
# ---------------------------------------------------------------------------

async def test_parsed_from_signal(session: AsyncSession) -> None:
    channel = await make_channel(session)
    result = await pipeline.process_message(
        session, SIGNAL_TEXT, channel=channel, message_id=700, message_date=NOW, allow_ai=False
    )
    assert result.signal is not None

    parsed = pipeline.parsed_from_signal(result.signal)
    assert parsed.is_signal is True
    assert parsed.symbol == "XAUUSD"
    assert parsed.entry_price == 3320.0
    assert parsed.stop_loss == 3310.0
    assert parsed.take_profits == [3330.0, 3340.0]
    assert parsed.message_date == NOW


def test_pipeline_result_serialisable() -> None:
    result = pipeline.PipelineResult(action="ignored", detail="Message sans rapport")
    payload = result.to_dict()
    assert payload["action"] == "ignored"
    assert payload["signalId"] is None
    assert result.is_tradable is False
