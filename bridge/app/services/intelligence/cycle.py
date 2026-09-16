"""Un tour complet d'analyse autonome (CDC2 §2, §18, §40 a §47, §84).

Enchainement : scan de la watchlist, assemblage du dossier, recherche d'une
opportunite, decision motivee, journalisation, simulation, notification.

Deux principes gouvernent ce fichier :

1. **Ne rien ouvrir n'est pas une panne.** La plupart des tours se terminent
   sans aucune opportunite. C'est le fonctionnement attendu (CDC2 §2).
2. **Aucun ordre n'est envoye ici.** Ce cycle observe, explique et enregistre.
   Le passage a l'execution reste soumis au RiskManager et au moteur de
   trading, qui ont leurs propres garde-fous.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.intelligence import (
    AITaskKind,
    DecisionAction,
    DecisionRecord,
    DecisionSource,
)
from app.repositories import ai_repo, decision_repo, news_repo, settings_repo
from app.services import journal
from app.services.ai.service import ai_service
from app.services.confidence.weights import ConfidenceComponent
from app.services.decision import DecisionContext, DecisionThresholds
from app.services.decision.circuit_breaker import circuit_breaker
from app.services.decision.engine import DecisionOutcome, decision_engine
from app.services.decision.inputs import ConsensusView
from app.services.decision.shadow import build_shadow_trade, marginal_context
from app.services.economic_calendar.engine import economic_calendar_engine
from app.services.intelligence.assembly import build_bundle
from app.services.market_data.engine import MarketDataEngine
from app.services.market_data.provider import market_engine
from app.services.market_scanner.runner import run_scan
from app.services.market_scanner.scanner import ScanResult
from app.services.notifications import templates
from app.services.notifications.service import notification_service
from app.services.opportunities.generator import OpportunityDraft, opportunity_generator
from app.services.opportunities.narrative import (
    SYSTEM_PROMPT as NARRATIVE_SYSTEM_PROMPT,
)
from app.services.opportunities.narrative import build_prompt, consensus_view
from app.services.trading.engine import trading_engine

logger = get_logger(__name__)


@dataclass(slots=True)
class SymbolOutcome:
    """Ce que le tour a produit pour un instrument."""

    symbol: str
    action: DecisionAction | None = None
    confidence: float | None = None
    decision_id: int | None = None
    opportunity_id: int | None = None
    notified: bool = False
    skipped: str | None = None


@dataclass(slots=True)
class CycleReport:
    """Bilan d'un tour, affichable et testable."""

    scanned: int = 0
    analysed: int = 0
    opportunities: int = 0
    qualified: int = 0
    notifications: int = 0
    shadow_trades: int = 0
    consensus_failures: int = 0
    outcomes: list[SymbolOutcome] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "analysed": self.analysed,
            "opportunities": self.opportunities,
            "qualified": self.qualified,
            "notifications": self.notifications,
            "shadowTrades": self.shadow_trades,
            "consensusFailures": self.consensus_failures,
            "error": self.error,
            "symbols": [
                {
                    "symbol": item.symbol,
                    "action": item.action.value if item.action else None,
                    "confidence": item.confidence,
                    "decisionId": item.decision_id,
                    "opportunityId": item.opportunity_id,
                    "notified": item.notified,
                    "skipped": item.skipped,
                }
                for item in self.outcomes
            ],
        }


async def _persist_decision(
    session: AsyncSession,
    outcome: DecisionOutcome,
    *,
    opportunity_id: int | None,
    snapshot_id: int | None,
    shadow: bool,
) -> DecisionRecord:
    """Journalise la decision et sa decomposition, prise ou non (CDC2 §76)."""
    record = outcome.to_record(
        opportunity_id=opportunity_id, snapshot_id=snapshot_id, shadow=shadow
    )
    facteurs = [factor.to_model(0) for factor in outcome.confidence.factors]
    return await decision_repo.save_decision(session, record, facteurs)


def _component_score(draft: OpportunityDraft, component: ConfidenceComponent) -> float | None:
    """Note d'une composante, ramenee sur 0-1, ou ``None`` si absente."""
    facteur = draft.confidence.factor(component)
    if facteur is None or facteur.score is None:
        return None
    return facteur.score / 100.0


async def _notify_opportunity(
    session: AsyncSession,
    draft: OpportunityDraft,
    decision_id: int | None,
    opportunity_id: int | None,
) -> bool:
    """Previent l'utilisateur d'une opportunite qualifiee (CDC2 §54).

    La notification informe : elle ne permet aucune action financiere directe,
    conformement au CDC2 §94. Elle renvoie vers l'ecran d'analyse.
    """
    brouillon = templates.opportunity_detected(
        symbol=draft.symbol,
        direction=draft.direction,
        confidence=draft.confidence.ratio,
        technical=_component_score(draft, ConfidenceComponent.TECHNICAL),
        historical=_component_score(draft, ConfidenceComponent.HISTORICAL),
        opportunity_id=opportunity_id,
    )
    evenement = await notification_service.notify(
        brouillon.category,
        brouillon.priority,
        brouillon.title,
        brouillon.body,
        data=brouillon.data,
        symbol=draft.symbol,
        decision_id=decision_id,
        confidence=draft.confidence.ratio,
        collapse_key=f"opportunity:{draft.symbol}",
        session=session,
    )
    return evenement is not None


async def _consensus_for(
    draft: OpportunityDraft, report: CycleReport
) -> ConsensusView | None:
    """Demande leur avis aux moteurs d'IA sur une opportunite deja chiffree.

    Les niveaux sont fournis au modele, jamais demandes : aucune reponse d'IA
    ne peut modifier une entree, un stop ou une cible (CDC2 section 41).

    Retourne ``None`` quand aucun moteur ne repond : la composante est alors
    comptee comme absente, ce qui fait baisser la couverture et donc le score.
    C'est volontaire — un doute non leve doit peser, pas disparaitre.
    """
    try:
        resultat = await ai_service.consensus(
            build_prompt(draft),
            system=NARRATIVE_SYSTEM_PROMPT,
            task=AITaskKind.OPPORTUNITY_REVIEW,
            deterministic_direction=draft.direction,
            deterministic_score=draft.confidence.ratio,
        )
    except Exception as exc:
        logger.info("Consensus IA indisponible pour %s : %s", draft.symbol, exc)
        report.consensus_failures += 1
        return None
    return consensus_view(resultat, ai_service.requires_manual_review(resultat))


async def _analyse_symbol(
    session: AsyncSession,
    result: ScanResult,
    *,
    engine: MarketDataEngine | None,
    thresholds: DecisionThresholds,
    min_confidence: float,
    shadow_mode: bool,
    consensus_required: bool,
    report: CycleReport,
    peers: list[str],
) -> SymbolOutcome:
    """Analyse un instrument de bout en bout."""
    issue = SymbolOutcome(symbol=result.symbol)

    bundle, structure = await build_bundle(session, result, engine=engine, peers=peers)
    if structure is None or not structure.usable:
        # Sans prix ni volatilite mesurable, aucun niveau n'est calculable.
        issue.skipped = "structure de prix incalculable"
        return issue

    draft = opportunity_generator.generate(bundle, structure)
    if draft is None:
        # Cas le plus frequent : aucun setup. On ne journalise pas une decision
        # par instrument et par tour, sinon le journal deviendrait illisible ;
        # le contexte reste trace par le snapshot du scanner.
        issue.skipped = "aucun setup"
        return issue

    report.opportunities += 1

    # Consensus IA (CDC2 sections 11 et 45).
    #
    # Sans cet appel, le garde-fou « consensus exige » refusait toute entree en
    # boucle : il reclamait une analyse que personne ne produisait. On ne le
    # demande que pour une opportunite deja formee — inutile de consommer un
    # quota pour un instrument sans setup.
    bundle.consensus = await _consensus_for(draft, report)

    contexte = DecisionContext(
        symbol=result.symbol,
        analysis=bundle,
        source=DecisionSource.AI_GENERATED,
        proposed_direction=draft.direction,
        levels=draft.levels,
        strategy=draft.strategy,
        consensus_required=consensus_required,
        breaker=circuit_breaker.state,
        mt5_connected=trading_engine.mt5_connected,
        trading_enabled=not shadow_mode,
        thresholds=thresholds,
        min_confidence=min_confidence,
    )
    verdict = decision_engine.decide(contexte)
    issue.action = verdict.action
    issue.confidence = round(verdict.confidence.score, 2)

    opportunite = None
    if draft.qualified or verdict.tradable:
        opportunite = await decision_repo.save_opportunity(
            session, draft.to_model(broker_symbol=result.broker_symbol)
        )
        issue.opportunity_id = opportunite.id
        report.qualified += 1

    enregistrement = await _persist_decision(
        session,
        verdict,
        opportunity_id=opportunite.id if opportunite else None,
        snapshot_id=None,
        shadow=shadow_mode,
    )
    issue.decision_id = enregistrement.id

    if shadow_mode:
        simulation = build_shadow_trade(
            verdict, draft.levels, decision_id=enregistrement.id
        )
        simulation.broker_symbol = result.broker_symbol
        await decision_repo.save_shadow_trade(session, simulation)
        report.shadow_trades += 1
    elif not verdict.tradable:
        # Bande marginale. On rejoue la meme decision avec l'exigence de
        # confiance abaissee d'un cran : si elle passe alors, le seuil etait le
        # SEUL obstacle, et cette opportunite merite d'etre mesuree pendant que
        # le trading continue normalement.
        #
        # C'est le capteur qui manquait pour abaisser le seuil autrement qu'a
        # l'aveugle : les opportunites sous le seuil sont ecartees avant
        # d'exister, et le shadow mode ne les enregistre que lorsqu'il est
        # actif -- donc quand plus rien ne part au broker, sans rien a quoi les
        # comparer.
        marge = decision_engine.decide(marginal_context(contexte))
        if marge.tradable:
            simulation = build_shadow_trade(
                marge, draft.levels, decision_id=enregistrement.id
            )
            simulation.marginal = True
            simulation.broker_symbol = result.broker_symbol
            await decision_repo.save_shadow_trade(session, simulation)
            report.shadow_trades += 1

    if opportunite is not None and draft.qualified:
        issue.notified = await _notify_opportunity(
            session, draft, enregistrement.id, opportunite.id
        )
        if issue.notified:
            report.notifications += 1

    return issue


async def run_cycle(
    session: AsyncSession,
    *,
    engine: MarketDataEngine | None = None,
    limit: int | None = None,
) -> CycleReport:
    """Un tour complet d'analyse autonome sur la watchlist.

    Ne leve jamais : une panne d'un instrument ne doit pas arreter le tour, et
    une panne du tour ne doit pas arreter le Bridge.
    """
    report = CycleReport()
    data_engine = engine or market_engine()
    if data_engine is None:
        report.error = "Aucun service de marché attaché."
        return report

    ai_settings = await ai_repo.get_settings(session)
    risk_settings = await settings_repo.get_risk_settings(session)

    # Le mode observation reste actif tant que l'utilisateur n'a pas autorise
    # l'IA a trader ET que le trading automatique n'est pas arme (CDC2 §83).
    shadow_mode = (
        ai_settings.shadow_mode
        or not ai_settings.ai_trading_enabled
        or not risk_settings.auto_trading_enabled
    )

    try:
        # ``persist=True`` : le scan enregistre lui-meme snapshot et changement
        # de regime, on ne duplique pas ce travail ici.
        results = await run_scan(session, engine=data_engine, limit=limit)
    except Exception as exc:
        logger.warning("Scan impossible : %s", exc)
        report.error = str(exc)[:200]
        return report

    report.scanned = len(results)
    thresholds = DecisionThresholds()
    # Les autres instruments scannes servent de reference inter-marches : on
    # mesure si celui-ci suit le mouvement general ou s'en detache.
    peers = [item.symbol for item in results if item.usable]

    for result in results:
        if not result.usable:
            report.outcomes.append(
                SymbolOutcome(symbol=result.symbol, skipped=result.error or "données absentes")
            )
            continue
        try:
            issue = await _analyse_symbol(
                session,
                result,
                engine=data_engine,
                thresholds=thresholds,
                min_confidence=ai_settings.min_opportunity_confidence,
                shadow_mode=shadow_mode,
                consensus_required=ai_settings.require_consensus_for_auto_trade,
                report=report,
                peers=peers,
            )
        except Exception as exc:
            logger.warning("Analyse de %s interrompue : %s", result.symbol, exc)
            issue = SymbolOutcome(symbol=result.symbol, skipped=f"erreur : {exc}"[:120])
        report.analysed += 1
        report.outcomes.append(issue)

    if report.qualified:
        await journal.log(
            event="intelligence_cycle",
            message=(
                f"{report.qualified} opportunité(s) qualifiée(s) sur "
                f"{report.analysed} instrument(s) analysé(s)"
            ),
            category="intelligence",
        )
    return report


async def notify_upcoming_events(session: AsyncSession) -> int:
    """Rappels avant publication economique (CDC2 §34, §63)."""
    pending = await economic_calendar_engine.due_notifications(session)
    envoyes = 0
    for rappel in pending:
        evenement = rappel.event
        brouillon = templates.economic_event_upcoming(
            title=evenement.title,
            currency=evenement.currency,
            scheduled_at=evenement.scheduled_at,
            minutes_before=rappel.minutes_remaining,
            impact=evenement.impact,
            forecast=evenement.forecast,
            previous=evenement.previous,
            event_id=evenement.id,
        )
        envoi = await notification_service.notify(
            brouillon.category,
            brouillon.priority,
            brouillon.title,
            brouillon.body,
            data=brouillon.data,
            collapse_key=f"economic:{evenement.id}",
            session=session,
        )
        if envoi is not None:
            envoyes += 1
    return envoyes


async def notify_major_news(session: AsyncSession, news_ids: list[int]) -> int:
    """Alerte sur les actualites a fort impact venant d'etre collectees."""
    envoyes = 0
    for news_id in news_ids:
        actualite = await news_repo.get_news(session, news_id)
        if actualite is None:
            continue
        brouillon = templates.high_impact_news(
            headline=actualite.title,
            affected=list(actualite.affected_assets or []),
            interpretation=actualite.summary,
            source=actualite.source,
            published_at=actualite.published_at,
            impact=actualite.impact,
            news_id=actualite.id,
        )
        envoi = await notification_service.notify(
            brouillon.category,
            brouillon.priority,
            brouillon.title,
            brouillon.body,
            data=brouillon.data,
            news_id=actualite.id,
            collapse_key=f"news:{actualite.id}",
            session=session,
        )
        if envoi is not None:
            envoyes += 1
    return envoyes


__all__ = ["CycleReport", "SymbolOutcome", "notify_major_news", "notify_upcoming_events", "run_cycle"]
