"""La liste des signaux ne montre que des signaux.

Constate a l'ecran le 12/09/2026 : quatre cartes vides, sans symbole, sans
entree, sans stop, a 0 % de confiance. C'etaient une publicite pour une video,
un message de recrutement, un bilan de journee et une vantardise (« Copy
trading today: +$382 profit »).

Le moteur les avait correctement classes NO_ACTION. Le defaut etait ailleurs :
sans onglet choisi, la liste n'appliquait aucun filtre et renvoyait tout.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Direction, SignalStatus
from app.models.trading import Signal

PREFIX = "/api/v1/signals"


async def _poser(session: AsyncSession, **champs: object) -> Signal:
    base: dict[str, object] = {
        "channel_id": None,
        "telegram_message_id": None,
        "idempotency_key": None,
        "raw_text": "texte",
        "status": SignalStatus.PARSED,
    }
    base.update(champs)
    signal = Signal(**base)  # type: ignore[arg-type]
    session.add(signal)
    await session.flush()
    return signal


async def test_un_message_sans_ordre_n_apparait_pas_dans_la_liste(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    """Le cas exact vu par l'utilisateur : une publicite affichee comme signal."""
    await _poser(
        session,
        raw_text="Featured Trading Video - watch here",
        status=SignalStatus.NO_ACTION,
        idempotency_key="pub-1",
    )
    await _poser(
        session,
        raw_text="BUY XAUUSD 4372",
        normalized_symbol="XAUUSD",
        direction=Direction.BUY,
        status=SignalStatus.PARSED,
        idempotency_key="vrai-1",
    )
    await session.commit()

    reponse = await auth_client.get(PREFIX)
    assert reponse.status_code == 200
    items = reponse.json()["items"]

    statuts = {item["status"] for item in items}
    assert SignalStatus.NO_ACTION.value not in statuts, (
        f"un message sans ordre est affiche : {statuts}"
    )
    assert any(item["normalizedSymbol"] == "XAUUSD" for item in items), (
        "le vrai signal a disparu en meme temps"
    )


async def test_l_onglet_refuses_ne_melange_pas_les_deux(
    auth_client: AsyncClient, session: AsyncSession
) -> None:
    """Un message qui n'a jamais porte d'ordre n'est pas un signal refuse.

    Les confondre empechait de lire la vraie liste des refus : sur quatre
    cartes, aucune ne disait pourquoi un ordre avait ete ecarte.
    """
    await _poser(
        session,
        raw_text="SESSION REPORT",
        status=SignalStatus.NO_ACTION,
        idempotency_key="bilan-1",
    )
    await _poser(
        session,
        raw_text="BUY GOLD",
        normalized_symbol="XAUUSD",
        status=SignalStatus.REJECTED,
        rejection_detail="Spread trop eleve",
        idempotency_key="refuse-1",
    )
    await session.commit()

    reponse = await auth_client.get(PREFIX, params={"group": "rejected"})
    assert reponse.status_code == 200
    statuts = [item["status"] for item in reponse.json()["items"]]

    assert SignalStatus.REJECTED.value in statuts
    assert SignalStatus.NO_ACTION.value not in statuts


@pytest.mark.parametrize(
    "groupe",
    ["accepted", "executed", "rejected", "error", "review", "observed"],
)
async def test_aucun_onglet_ne_fait_remonter_les_messages_sans_ordre(
    auth_client: AsyncClient, session: AsyncSession, groupe: str
) -> None:
    await _poser(
        session,
        raw_text="Copy trading today: +$382 profit",
        status=SignalStatus.NO_ACTION,
        idempotency_key=f"vantardise-{groupe}",
    )
    await session.commit()

    reponse = await auth_client.get(PREFIX, params={"group": groupe})
    assert reponse.status_code == 200
    statuts = [item["status"] for item in reponse.json()["items"]]
    assert SignalStatus.NO_ACTION.value not in statuts


async def test_un_filtre_inconnu_reste_refuse(auth_client: AsyncClient) -> None:
    """Garde-fou : le resserrage ne doit pas avaler la validation du filtre."""
    reponse = await auth_client.get(PREFIX, params={"group": "nimporte-quoi"})
    assert reponse.status_code == 400


async def test_les_statuts_visibles_couvrent_tout_sauf_les_messages_sans_ordre() -> None:
    """Si un statut est ajoute un jour, il doit etre visible par defaut.

    Construire la liste par exclusion plutot que par enumeration evite qu'un
    nouveau statut disparaisse silencieusement de l'ecran.
    """
    from app.api.v1.signals import HIDDEN_STATUSES, VISIBLE_STATUSES

    assert set(VISIBLE_STATUSES) | set(HIDDEN_STATUSES) == set(SignalStatus)
    assert set(VISIBLE_STATUSES) & set(HIDDEN_STATUSES) == set()
