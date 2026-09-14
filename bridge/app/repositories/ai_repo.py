"""Persistance de la configuration IA et de la fiabilite des moteurs."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.core import SINGLETON_ID, utcnow
from app.models.intelligence import (
    AIConsensusRecord,
    AIProviderKind,
    AIProviderMetric,
    AIRoutingEvent,
    AISettings,
    AITaskKind,
)

# Reglages que seul l'utilisateur peut changer explicitement : ils ne doivent
# jamais etre modifies par un traitement automatique.
PROTECTED_FIELDS = {"id", "updated_at"}


async def get_settings(session: AsyncSession) -> AISettings:
    """Reglages IA, crees a la premiere demande.

    Deux appels vraiment simultanes sur une base NEUVE peuvent tenter
    l'insertion en meme temps et l'un echouera. Le cas ne se produit qu'au
    tout premier demarrage : ensuite la ligne existe et la lecture suffit.
    Le corriger proprement demanderait un point de sauvegarde, dont le
    comportement differe entre SQLite et PostgreSQL. Laisse tel quel,
    sciemment, plutot que de fragiliser un chemin traverse par chaque message.
    """
    settings = await session.get(AISettings, SINGLETON_ID)
    if settings is None:
        settings = AISettings(id=SINGLETON_ID)
        session.add(settings)
        await session.flush()
    return settings


async def update_settings(session: AsyncSession, changes: dict[str, Any]) -> AISettings:
    settings = await get_settings(session)
    for key, value in changes.items():
        if key in PROTECTED_FIELDS or value is None:
            continue
        if hasattr(settings, key):
            setattr(settings, key, value)
    settings.updated_at = utcnow()
    session.add(settings)
    await session.flush()
    return settings


# ---------------------------------------------------------------------------
# Fiabilite mesuree des moteurs (CDC2 section 14)
# ---------------------------------------------------------------------------

async def get_metric(
    session: AsyncSession, provider: AIProviderKind, task: AITaskKind
) -> AIProviderMetric:
    result = await session.exec(
        select(AIProviderMetric).where(
            AIProviderMetric.provider == provider, AIProviderMetric.task == task
        )
    )
    metric = result.first()
    if metric is None:
        metric = AIProviderMetric(provider=provider, task=task)
        session.add(metric)
        await session.flush()
    return metric


async def record_call(
    session: AsyncSession,
    provider: AIProviderKind,
    task: AITaskKind,
    *,
    model: str | None = None,
    success: bool,
    valid_json: bool = False,
    latency_ms: int | None = None,
    timeout: bool = False,
    error: str | None = None,
) -> AIProviderMetric:
    """Enregistre le resultat d'un appel : c'est ce qui nourrit le routeur."""
    metric = await get_metric(session, provider, task)
    metric.calls += 1
    if model:
        metric.model = model
    if success:
        metric.successes += 1
        if latency_ms is not None:
            metric.total_latency_ms += latency_ms
            metric.last_latency_ms = latency_ms
    elif timeout:
        metric.timeouts += 1
    else:
        metric.errors += 1
    if valid_json:
        metric.valid_json += 1
    if error:
        metric.last_error = error[:255]
    metric.last_used_at = utcnow()
    metric.updated_at = utcnow()
    session.add(metric)
    await session.flush()
    return metric


async def record_disagreement(
    session: AsyncSession, task: AITaskKind
) -> None:
    """Un desaccord oppose deux modeles du meme fournisseur.

    La metrique est donc portee par OpenRouter, une seule fois : la compter
    deux fois doublerait artificiellement le taux de desaccord.
    """
    metric = await get_metric(session, AIProviderKind.OPENROUTER, task)
    metric.disagreements += 1
    metric.updated_at = utcnow()
    session.add(metric)
    await session.flush()


async def record_blocked_hallucination(
    session: AsyncSession, provider: AIProviderKind, task: AITaskKind
) -> None:
    """Une valeur inventee a ete rejetee avant d'atteindre le trading."""
    metric = await get_metric(session, provider, task)
    metric.hallucinations_blocked += 1
    metric.updated_at = utcnow()
    session.add(metric)
    await session.flush()


async def list_metrics(session: AsyncSession) -> list[AIProviderMetric]:
    result = await session.exec(select(AIProviderMetric))
    return list(result.all())


async def record_routing(
    session: AsyncSession,
    task: AITaskKind,
    mode: Any,
    chosen: AIProviderKind | None,
    *,
    fallback_used: bool = False,
    reason: str | None = None,
    latency_ms: int | None = None,
    success: bool = True,
) -> AIRoutingEvent:
    event = AIRoutingEvent(
        task=task,
        mode=mode,
        chosen=chosen,
        fallback_used=fallback_used,
        reason=(reason or "")[:255] or None,
        latency_ms=latency_ms,
        success=success,
    )
    session.add(event)
    await session.flush()
    return event


async def last_routing_event(session: AsyncSession) -> AIRoutingEvent | None:
    result = await session.exec(
        select(AIRoutingEvent).order_by(AIRoutingEvent.created_at.desc()).limit(1)
    )
    return result.first()


async def save_consensus(session: AsyncSession, record: AIConsensusRecord) -> AIConsensusRecord:
    session.add(record)
    await session.flush()
    return record


async def get_consensus(session: AsyncSession, decision_id: int) -> AIConsensusRecord | None:
    result = await session.exec(
        select(AIConsensusRecord)
        .where(AIConsensusRecord.decision_id == decision_id)
        .order_by(AIConsensusRecord.created_at.desc())
        .limit(1)
    )
    return result.first()
