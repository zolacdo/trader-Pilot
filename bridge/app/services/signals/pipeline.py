"""Pipeline d'analyse d'un message Telegram.

    MESSAGE -> NORMALISATION -> PARSER DETERMINISTE -> (si ambigu) OPENROUTER
            -> VALIDATEUR STRICT -> SIGNAL STRUCTURE

Le parser deterministe passe toujours en premier : il est rapide, previsible
et n'utilise aucun quota. L'IA n'intervient que sur un message reellement
ambigu, et sa sortie repasse par le meme validateur local (CDC sections 16,
20, 21 et 49).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.enums import EventLevel, ParserSource, SignalStatus
from app.models.telegram import Channel
from app.models.trading import Signal
from app.repositories import channel_repo, settings_repo, signal_repo
from app.services import journal
from app.services.ai.service import ai_service
from app.services.events import EventType, event_bus
from app.services.openrouter.service import openrouter_service
from app.services.signals import (
    deterministic_parser,
    follow_up_parser,
    validator,
    verification,
)
from app.services.signals.models import ParsedSignal, ValidationResult
from app.services.signals.normalizer import content_hash, normalize_upper

logger = get_logger(__name__)

# En dessous de ce score, un message est considere comme ambigu et peut
# justifier un appel a l'IA.
AI_FALLBACK_THRESHOLD = 0.85


@dataclass(slots=True)
class PipelineResult:
    action: str  # new_signal | follow_up | no_action | duplicate | ignored
    signal: Signal | None = None
    parsed: ParsedSignal | None = None
    validation: ValidationResult | None = None
    parent_signal: Signal | None = None
    detail: str = ""

    @property
    def is_tradable(self) -> bool:
        return self.action == "new_signal" and self.signal is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "signalId": self.signal.id if self.signal else None,
            "parentSignalId": self.parent_signal.id if self.parent_signal else None,
            "parsed": self.parsed.to_dict() if self.parsed else None,
            "validation": self.validation.to_dict() if self.validation else None,
            "detail": self.detail,
        }


# Marqueurs d'intention de trade, cherches comme des MOTS ENTIERS. La
# recherche par sous-chaine enregistrait n'importe quelle publicite : BE se
# trouve dans BEGINNER et dans YOUTUBE, TP dans HTTPS. L'utilisateur voyait
# alors des cartes vides dans sa liste de signaux.
_TRADE_MARKER_RE = re.compile(
    r"\b(?:BUY|SELL|LONG|SHORT|ENTRY|ENTRIES|TARGET|TARGETS|CLOSE|CLOSED"
    r"|BE|BREAKEVEN|TP\d*|SL|STOP\s*LOSS|TAKE\s*PROFIT)\b"
)


def _looks_worth_recording(text: str) -> bool:
    """Evite de remplir la base avec les messages de convivialite."""
    upper = normalize_upper(text)
    if not upper:
        return False
    return _TRADE_MARKER_RE.search(upper) is not None


# Canal dans lequel le Market Watcher publie. La cle est lue en base plutot
# qu'importee depuis ``app.watcher`` : les services ne doivent pas dependre du
# sous-systeme, qui depend deja d'eux.
SETTING_WATCHER_CHANNEL = "watcher.telegram_channel_id"


def has_minimum_order_content(parsed: ParsedSignal) -> bool:
    """Le message porte-t-il un ordre exploitable, et pas seulement un avis ?

    Le minimum vital d'un ordre : un instrument, un sens, un prix d'entree et
    un stop. Un message qui n'a pas ces quatre elements ne decrit pas une
    operation — il commente le marche.
    """
    entry = parsed.entry_price if parsed.entry_price is not None else parsed.entry_min
    return bool(
        parsed.symbol
        and parsed.direction is not None
        and entry is not None
        and parsed.stop_loss is not None
    )


async def _is_own_watcher_broadcast(
    session: AsyncSession, channel: Channel | None, text: str
) -> bool:
    """Message d'information publie par notre propre Market Watcher ?

    Le watcher publie huit sortes de messages dans son canal et une seule est
    un ordre : les sept autres — mise sous surveillance, surveillance levee,
    TP atteint, alerte d'actualite, message de demarrage — contiennent un
    instrument et un mot de direction, donc le parseur les lisait comme des
    signaux. Ils arrivaient dans la liste avec entree, stop et objectifs vides,
    refuses pour « confiance insuffisante ».

    Le tri ne se fait PAS sur les titres : ils ont deja ete reformules une fois
    depuis leur ecriture. Il se fait sur le contenu minimal d'un ordre, qu'un
    message d'information n'a par nature jamais.
    """
    if channel is None or not getattr(channel, "telegram_id", None):
        return False
    try:
        stored = await settings_repo.get_setting(session, SETTING_WATCHER_CHANNEL, None)
    except Exception as exc:  # un reglage illisible ne doit rien bloquer
        logger.debug("Canal du watcher illisible : %s", exc)
        return False
    if stored is None or int(stored) != int(channel.telegram_id):
        return False
    # Parseur local uniquement : aucun quota d'IA ne doit etre depense pour
    # decider qu'un message de surveillance n'est pas un ordre.
    parsed = deterministic_parser.parse(text)
    return not has_minimum_order_content(parsed)


async def _run_ai_fallback(
    session: AsyncSession, text: str, deterministic: ParsedSignal
) -> tuple[ParsedSignal | None, str | None]:
    """Appelle l'IA uniquement si le message reste ambigu.

    OpenRouter est le seul moteur depuis le retrait de l'IA locale : son mode
    outil produit l'extraction la plus fiable dont on dispose.
    """
    ai_signal, error = await openrouter_service.parse_signal(session, text)
    if ai_signal is None:
        return None, error
    if not ai_signal.is_signal:
        return ai_signal, None

    # L'IA ne peut jamais contredire une lecture locale certaine : si le parser
    # deterministe avait deja identifie l'instrument et la direction, l'IA ne
    # sert qu'a completer les valeurs manquantes.
    if deterministic.is_signal:
        if deterministic.symbol and ai_signal.symbol != deterministic.symbol:
            ai_signal.symbol = deterministic.symbol
            ai_signal.add_warning("ia_symbole_ignore_au_profit_du_parser_local")
        if deterministic.direction and ai_signal.direction != deterministic.direction:
            ai_signal.direction = deterministic.direction
            ai_signal.add_warning("ia_direction_ignoree_au_profit_du_parser_local")
    return ai_signal, None


async def analyze_text(
    session: AsyncSession,
    text: str,
    channel_id: int | None = None,
    allow_ai: bool = True,
) -> tuple[ParsedSignal, ValidationResult]:
    """Analyse pure d'un texte : parser local, repli IA, validation.

    N'ecrit aucun signal en base : utilise aussi par l'analyse de canal et par
    l'ecran de test manuel.
    """
    aliases = await channel_repo.channel_aliases(session, channel_id)
    parsed = deterministic_parser.parse(text, aliases)
    validation = validator.validate(validator.sanitize(parsed))

    needs_ai = allow_ai and (
        not parsed.is_signal or not validation.ok or parsed.confidence < AI_FALLBACK_THRESHOLD
    )
    # Inutile d'interroger l'IA sur un message qui ne ressemble a rien.
    if needs_ai and not _looks_worth_recording(text):
        needs_ai = False

    if needs_ai and openrouter_service.configured:
        ai_signal, error = await _run_ai_fallback(session, text, parsed)
        if ai_signal is not None and ai_signal.is_signal:
            ai_validation = validator.validate(validator.sanitize(ai_signal))
            if ai_validation.ok:
                # On garde la lecture locale si elle etait deja valide et plus sure.
                if not (validation.ok and parsed.confidence >= ai_signal.confidence):
                    ai_signal.format_signature = parsed.format_signature
                    ai_signal.message_date = parsed.message_date
                    return ai_signal, ai_validation
            else:
                parsed.add_warning("sortie_ia_invalide_ignoree")
        elif error:
            parsed.add_warning("ia_indisponible")
            logger.info("Repli IA indisponible : %s", error)

    # Second avis : une IA relit le message et peut REFUSER un faux signal.
    # Elle ne peut jamais en creer un, donc elle ne contourne aucun controle.
    if allow_ai and parsed.is_signal:
        reglages = await ai_service.configure(session)
        if reglages.verify_signals_with_ai:
            verdict = await verification.verifier(parsed, text)
            if verdict.veto:
                logger.info("Message ecarte par la verification IA : %s", verdict.detail)
                parsed.is_signal = False
                parsed.add_warning(f"verification_ia_{verdict.nature}")
                validation = validator.validate(validator.sanitize(parsed))
            elif not verdict.disponible:
                parsed.add_warning("verification_ia_indisponible")

    return parsed, validation


async def process_message(
    session: AsyncSession,
    text: str,
    channel: Channel | None = None,
    message_id: int | None = None,
    message_date: datetime | None = None,
    reply_to_message_id: int | None = None,
    allow_ai: bool = True,
    manual: bool = False,
) -> PipelineResult:
    """Traite un message entrant et produit au plus un signal."""
    channel_id = channel.id if channel else None

    # ------------------------------------------------------------------
    # 0. Nos propres messages d'information
    # ------------------------------------------------------------------
    # Ce controle passe AVANT tout le reste, pour deux raisons precises :
    # avant le repli IA, sinon chaque mise sous surveillance consommerait du
    # quota pour rien ; et avant le parseur de suivi, sinon un « TP1 atteint »
    # publie par le watcher pour son propre signal irait se rattacher a une
    # position ouverte par un canal externe et declencherait une cloture
    # partielle sur le mauvais trade.
    if await _is_own_watcher_broadcast(session, channel, text):
        first_line = text.strip().splitlines()[0][:80] if text.strip() else "(vide)"
        logger.info("Message d'information du Market Watcher ignore : %s", first_line)
        return PipelineResult(
            action="ignored",
            detail="Message d'information du Market Watcher : aucun ordre exploitable",
        )

    # ------------------------------------------------------------------
    # 1. Idempotence : un meme message ne produit jamais deux signaux
    # ------------------------------------------------------------------
    key = signal_repo.build_idempotency_key(channel_id, message_id, content_hash(text))
    existing = await signal_repo.find_by_idempotency_key(session, key)
    if existing is not None:
        logger.info("Message deja traite (signal %s) : aucun nouvel ordre", existing.id)
        return PipelineResult(
            action="duplicate", signal=existing, detail="Message deja traite precedemment"
        )

    # ------------------------------------------------------------------
    # 2. Analyse
    # ------------------------------------------------------------------
    parsed, validation = await analyze_text(session, text, channel_id, allow_ai=allow_ai)
    parsed.message_date = message_date

    # ------------------------------------------------------------------
    # 3. Message de suivi rattache a un signal existant
    # ------------------------------------------------------------------
    # On tente le rattachement MEME quand le message se lit comme un signal :
    # « BUY XAUUSD - TP1 HIT, move SL to BE » porte le sens de la position et
    # etait pris pour un nouvel ordre d'achat. Une seconde position s'ouvrait
    # alors sur le meme instrument au lieu de securiser la premiere.
    aliases = await channel_repo.channel_aliases(session, channel_id)
    follow_up = follow_up_parser.parse_follow_up(text, aliases)
    if follow_up is not None:
        parent = await signal_repo.find_parent_signal(
            session, channel_id, reply_to_message_id, follow_up.symbol
        )
        if parent is None:
            if parsed.is_signal:
                # Action de gestion reconnue, mais aucune position a gerer :
                # le message vaut alors comme signal a part entiere, et le
                # chemin normal reprend plus bas.
                logger.info(
                    "Action de suivi %s sans signal parent : le message est traite "
                    "comme un signal a part entiere",
                    follow_up.action.value,
                )
            else:
                await journal.record(
                    session,
                    event="follow_up_orphan",
                    message=(
                        f"Message de suivi ({follow_up.action.value}) sans signal "
                        "correspondant"
                    ),
                    level=EventLevel.WARNING,
                    category="signal",
                    channel_id=channel_id,
                )
                return PipelineResult(
                    action="no_action",
                    parsed=parsed,
                    detail="Message de suivi non rattachable a un signal actif",
                )
        else:
            parsed.follow_up = follow_up
            signal = Signal(
                channel_id=channel_id,
                telegram_message_id=message_id,
                reply_to_message_id=reply_to_message_id,
                idempotency_key=key,
                message_date=message_date,
                raw_text=text[:4000],
                symbol=follow_up.symbol or parent.symbol,
                normalized_symbol=follow_up.symbol or parent.normalized_symbol,
                direction=parent.direction,
                confidence=follow_up.confidence,
                parser_source=ParserSource.DETERMINISTIC,
                status=SignalStatus.PARSED,
                original_signal_id=parent.id,
                follow_up_action=follow_up.action,
                follow_up_payload=follow_up.to_dict(),
            )
            await signal_repo.create(session, signal)
            await signal_repo.add_event(
                session,
                signal.id,
                stage="parser",
                message=(
                    f"Message de suivi {follow_up.action.value} rattache au "
                    f"signal {parent.id}"
                ),
                data=follow_up.to_dict(),
            )
            event_bus.publish(EventType.SIGNAL_NEW, {"signalId": signal.id, "followUp": True})
            return PipelineResult(
                action="follow_up", signal=signal, parsed=parsed, parent_signal=parent
            )

    # ------------------------------------------------------------------
    # 4. Aucune intention de trade
    # ------------------------------------------------------------------
    if not parsed.is_signal:
        if not _looks_worth_recording(text):
            return PipelineResult(action="ignored", parsed=parsed, detail="Message sans rapport")

        # Aucune ligne dans la table des signaux : ce message n'en est pas un.
        # L'y inscrire remplissait la liste de cartes vides -- publicites,
        # bilans de journee, vantardises -- qui noyaient les vrais signaux.
        # La trace va au journal, dont c'est precisement le role.
        await journal.record(
            session,
            event="message_sans_ordre",
            message=(
                "Message lu sans intention de trade : "
                f"{text.strip().splitlines()[0][:80] if text.strip() else '(vide)'}"
            ),
            category="signal",
            channel_id=channel_id,
            data={"warnings": parsed.warnings, "symbol": parsed.symbol},
        )
        return PipelineResult(
            action="no_action",
            parsed=parsed,
            validation=validation,
            detail="Aucune intention de trade explicite",
        )

    # ------------------------------------------------------------------
    # 5. Signal structure
    # ------------------------------------------------------------------
    status = SignalStatus.PARSED
    detail = ""
    if not validation.ok:
        status = SignalStatus.NEEDS_REVIEW
        blocking = validation.first_blocking
        detail = blocking.message if blocking else "Signal incoherent"

    signal = Signal(
        channel_id=channel_id,
        telegram_message_id=message_id,
        reply_to_message_id=reply_to_message_id,
        idempotency_key=key,
        message_date=message_date,
        raw_text=text[:4000],
        symbol=parsed.symbol_raw,
        normalized_symbol=parsed.symbol,
        direction=parsed.direction,
        order_type=parsed.order_type,
        entry_min=parsed.entry_min,
        entry_max=parsed.entry_max,
        entry_price=parsed.entry_price,
        stop_loss=parsed.stop_loss,
        take_profits=list(parsed.take_profits),
        confidence=parsed.confidence,
        parser_source=parsed.source,
        ai_model=parsed.ai_model,
        status=status,
    )
    await signal_repo.create(session, signal)
    await signal_repo.add_event(
        session,
        signal.id,
        stage="parser",
        success=validation.ok,
        status=status,
        message=detail or f"Signal interprete par {parsed.source.value} (confiance {parsed.confidence:.2f})",
        data={"parsed": parsed.to_dict(), "validation": validation.to_dict()},
    )

    if channel_id is not None:
        await channel_repo.record_parse_success(
            session, channel_id, parsed.format_signature, used_ai=parsed.source is ParserSource.AI
        )
        if parsed.symbol_raw and parsed.symbol and parsed.symbol_raw != parsed.symbol:
            await channel_repo.add_symbol_alias(session, channel_id, parsed.symbol_raw, parsed.symbol)

    await journal.record(
        session,
        event="signal_parsed",
        message=(
            f"{parsed.symbol} {parsed.direction.value if parsed.direction else '?'} "
            f"(confiance {parsed.confidence:.2f}, {parsed.source.value})"
        ),
        category="signal",
        channel_id=channel_id,
        signal_id=signal.id,
    )
    event_bus.publish(
        EventType.SIGNAL_NEW,
        {
            "signalId": signal.id,
            "channelId": channel_id,
            "symbol": parsed.symbol,
            "direction": parsed.direction.value if parsed.direction else None,
            "confidence": parsed.confidence,
            "status": status.value,
        },
    )

    if status is SignalStatus.NEEDS_REVIEW:
        event_bus.publish(
            EventType.SIGNAL_NEEDS_REVIEW, {"signalId": signal.id, "reason": detail}
        )
        if manual:
            return PipelineResult(
                action="new_signal", signal=signal, parsed=parsed, validation=validation, detail=detail
            )
        return PipelineResult(
            action="no_action", signal=signal, parsed=parsed, validation=validation, detail=detail
        )

    return PipelineResult(action="new_signal", signal=signal, parsed=parsed, validation=validation)


def parsed_from_signal(signal: Signal) -> ParsedSignal:
    """Reconstruit un ``ParsedSignal`` a partir de la ligne persistee."""
    return ParsedSignal(
        is_signal=signal.direction is not None and signal.normalized_symbol is not None,
        symbol_raw=signal.symbol,
        symbol=signal.normalized_symbol,
        direction=signal.direction,
        order_type=signal.order_type,
        entry_min=signal.entry_min,
        entry_max=signal.entry_max,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        take_profits=list(signal.take_profits or []),
        confidence=signal.confidence,
        source=signal.parser_source,
        ai_model=signal.ai_model,
        message_date=signal.message_date,
    )
