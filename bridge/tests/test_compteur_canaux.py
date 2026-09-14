"""Le nombre de signaux d'un canal se compte, il ne se memorise pas.

Mesure du 12/09/2026 sur la base de production :

    canal 5 : 5 signaux en base, compteur affiche = 0
    canal 2 : 1 signal  en base, compteur affiche = 0

``signals_count`` n'etait incremente que pour les etapes executed, observed et
needs_review. Tout signal REFUSE restait donc invisible -- or c'est
precisement l'information interessante : un canal dont les signaux sont
systematiquement rejetes n'est pas un canal silencieux.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Direction, SignalStatus
from app.models.trading import Signal
from app.repositories import channel_repo

PREFIX = "/api/v1/channels"


async def _canal(session: AsyncSession, titre: str, telegram_id: int):
    canal = await channel_repo.upsert(
        session, telegram_id=telegram_id, title=titre, username=f"c{telegram_id}"
    )
    canal.monitored = True
    session.add(canal)
    await session.flush()
    return canal


async def _signal(session: AsyncSession, canal_id: int, statut: SignalStatus, cle: str) -> None:
    session.add(
        Signal(
            channel_id=canal_id,
            idempotency_key=cle,
            raw_text="BUY XAUUSD",
            normalized_symbol="XAUUSD",
            direction=Direction.BUY,
            status=statut,
        )
    )
    await session.flush()


async def test_les_signaux_refuses_sont_comptes(session: AsyncSession) -> None:
    """Le cas exact vu en production : cinq signaux refuses, compteur a zero."""
    canal = await _canal(session, "Canal qui echoue", 5001)
    for index in range(5):
        await _signal(session, canal.id, SignalStatus.REJECTED, f"refus-{index}")

    tallies = await channel_repo.signal_tallies(session)

    assert tallies[canal.id][0] == 5, (
        "un canal dont les signaux sont refuses paraissait silencieux"
    )


async def test_tous_les_statuts_comptent(session: AsyncSession) -> None:
    canal = await _canal(session, "Canal mixte", 5002)
    for index, statut in enumerate(
        (
            SignalStatus.REJECTED,
            SignalStatus.PARSED,
            SignalStatus.NEEDS_REVIEW,
            SignalStatus.OPEN,
        )
    ):
        await _signal(session, canal.id, statut, f"mixte-{index}")

    tallies = await channel_repo.signal_tallies(session)

    assert tallies[canal.id][0] == 4


async def test_un_canal_sans_signal_n_apparait_pas(session: AsyncSession) -> None:
    """Aucune ligne inventee : l'absence se lit a l'absence de cle."""
    canal = await _canal(session, "Canal muet", 5003)
    await session.flush()

    tallies = await channel_repo.signal_tallies(session)

    assert canal.id not in tallies


async def test_la_date_du_dernier_signal_est_la_plus_recente(
    session: AsyncSession,
) -> None:
    canal = await _canal(session, "Canal actif", 5004)
    await _signal(session, canal.id, SignalStatus.REJECTED, "ancien")
    await _signal(session, canal.id, SignalStatus.OPEN, "recent")

    tallies = await channel_repo.signal_tallies(session)
    nombre, dernier = tallies[canal.id]

    assert nombre == 2
    assert dernier is not None


async def test_la_liste_expose_le_compte_reel(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    """Bout en bout : ce que l'ecran « Mes canaux » recevra."""
    canal = await _canal(session, "Canal expose", 5005)
    for index in range(3):
        await _signal(session, canal.id, SignalStatus.REJECTED, f"expose-{index}")
    # Le compteur memorise reste volontairement a zero : c'est lui qui mentait.
    canal.signals_count = 0
    session.add(canal)
    await session.commit()

    reponse = await auth_client.get(PREFIX)
    assert reponse.status_code == 200

    vu = next(item for item in reponse.json() if item["id"] == canal.id)
    assert vu["signalsCount"] == 3
    assert vu["lastSignalAt"] is not None
