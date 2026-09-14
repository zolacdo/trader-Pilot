"""Entretien de la boite de reception et collecte continue.

Constate le 12/09/2026 : 84 notifications accumulees en dix-huit heures, que
rien ne nettoyait. La fonction de purge existait pourtant -- elle n'etait
appelee par personne, et n'effacait que ce qui avait deja ete lu, donc jamais
les depeches ignorees.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import utcnow
from app.models.intelligence import (
    NotificationCategory,
    NotificationEvent,
    NotificationPriority,
)
from app.repositories import notification_repo
from app.services.intelligence import scheduler

PREFIX = "/api/v1/notifications"


async def _poser(session: AsyncSession, *, age_heures: float, lue: bool) -> NotificationEvent:
    instant = utcnow() - timedelta(hours=age_heures)
    event = NotificationEvent(
        category=NotificationCategory.NEWS,
        priority=NotificationPriority.LOW,
        title="Depeche",
        body="corps",
        created_at=instant,
        read_at=instant if lue else None,
    )
    session.add(event)
    await session.flush()
    return event


# ---------------------------------------------------------------------------
# Purge automatique
# ---------------------------------------------------------------------------

async def test_une_notification_non_lue_et_ancienne_est_effacee(
    session: AsyncSession,
) -> None:
    """L'ancienne purge exigeait qu'elle soit lue : elle ne nettoyait rien.

    Une depeche jamais ouverte restait donc indefiniment, et c'est exactement
    ce qui remplissait la liste.
    """
    await _poser(session, age_heures=6, lue=False)
    await session.flush()

    efface = await notification_repo.purge_older_than(session, utcnow() - timedelta(hours=4))

    assert efface == 1


async def test_une_notification_recente_est_conservee(session: AsyncSession) -> None:
    await _poser(session, age_heures=1, lue=False)
    await session.flush()

    efface = await notification_repo.purge_older_than(session, utcnow() - timedelta(hours=4))

    assert efface == 0


async def test_l_ancien_comportement_reste_accessible(session: AsyncSession) -> None:
    """``only_read`` conserve ce qui n'a pas ete vu, pour qui le souhaite."""
    await _poser(session, age_heures=6, lue=False)
    await _poser(session, age_heures=6, lue=True)
    await session.flush()

    efface = await notification_repo.purge_older_than(
        session, utcnow() - timedelta(hours=4), only_read=True
    )

    assert efface == 1


@pytest.mark.parametrize("age", [4.1, 12.0, 72.0])
async def test_tout_ce_qui_depasse_la_fenetre_part(
    session: AsyncSession, age: float
) -> None:
    await _poser(session, age_heures=age, lue=False)
    await session.flush()

    efface = await notification_repo.purge_older_than(session, utcnow() - timedelta(hours=4))
    assert efface == 1


# ---------------------------------------------------------------------------
# Vidage a la demande
# ---------------------------------------------------------------------------

async def test_l_utilisateur_peut_tout_effacer(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    await _poser(session, age_heures=0.1, lue=False)
    await _poser(session, age_heures=0.2, lue=True)
    await session.commit()

    reponse = await auth_client.delete(PREFIX)

    assert reponse.status_code == 200
    assert reponse.json()["deleted"] == 2
    assert reponse.json()["unread"] == 0

    reste = await auth_client.get(PREFIX)
    assert reste.json()["items"] == []


async def test_vider_une_boite_deja_vide_ne_casse_rien(auth_client: AsyncClient) -> None:
    reponse = await auth_client.delete(PREFIX)
    assert reponse.status_code == 200
    assert reponse.json()["deleted"] == 0


# ---------------------------------------------------------------------------
# Collecte continue
# ---------------------------------------------------------------------------

async def test_une_periode_nulle_demande_le_continu(session: AsyncSession) -> None:
    """Zero doit garder son sens : le tour suivant part des que possible.

    ``_read_minutes`` ramene toute valeur sous une minute a une minute, ce qui
    rendait le continu inexprimable.
    """
    from app.repositories import settings_repo

    await settings_repo.set_setting(session, scheduler.SETTING_NEWS, "0")
    await session.commit()

    minutes = await scheduler._read_minutes_allowing_zero(scheduler.SETTING_NEWS, 20.0)
    assert minutes == 0.0


async def test_une_periode_normale_reste_bornee(session: AsyncSession) -> None:
    """Le continu ne doit pas ouvrir la porte a des periodes absurdes."""
    from app.repositories import settings_repo

    await settings_repo.set_setting(session, scheduler.SETTING_NEWS, "0.2")
    await session.commit()

    minutes = await scheduler._read_minutes_allowing_zero(scheduler.SETTING_NEWS, 20.0)
    assert minutes == scheduler.MIN_MINUTES


def test_le_repos_plancher_empeche_l_emballement() -> None:
    """Un tour qui echoue instantanement ne doit pas marteler les sources.

    Sans ce plancher, un flux injoignable declencherait des centaines de
    tentatives par minute et ferait bloquer l'adresse.
    """
    assert scheduler.CONTINUOUS_FLOOR_SECONDS > 0
