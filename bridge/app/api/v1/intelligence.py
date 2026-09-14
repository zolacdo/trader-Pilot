"""Routes de pilotage de l'intelligence autonome (CDC2 §2, §18, §30, §34).

L'utilisateur doit pouvoir voir ce que le systeme fait tout seul, le relancer
a la demande, et le couper. Sans cela, l'autonomie serait une boite noire.

Aucune de ces routes n'envoie d'ordre : elles observent et declenchent des
analyses. Toutes exigent un appareil appaire.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.core import Device
from app.repositories import settings_repo
from app.services import journal
from app.services.intelligence.scheduler import (
    DEFAULT_CALENDAR_MINUTES,
    DEFAULT_NEWS_MINUTES,
    DEFAULT_SCAN_MINUTES,
    MAX_MINUTES,
    MIN_MINUTES,
    SETTING_CALENDAR,
    SETTING_ENABLED,
    SETTING_NEWS,
    SETTING_SCAN,
    intelligence_scheduler,
)
from app.services.security.auth import require_device

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

# Ce que declenche chaque cible de /intelligence/run.
CIBLES = {
    "scan": "analyse du marché",
    "news": "collecte des actualités",
    "calendar": "rappels du calendrier économique",
}


class IntervalsRequest(BaseModel):
    """Periodes des boucles, en minutes. Un champ absent reste inchange."""

    enabled: bool | None = None
    scanMinutes: float | None = None
    newsMinutes: float | None = None
    calendarMinutes: float | None = None


def _borne(valeur: float, nom: str) -> float:
    if not MIN_MINUTES <= valeur <= MAX_MINUTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"La période « {nom} » doit être comprise entre "
                f"{MIN_MINUTES:.0f} et {MAX_MINUTES:.0f} minutes."
            ),
        )
    return valeur


async def _intervals(session: AsyncSession) -> dict[str, Any]:
    async def lire(cle: str, defaut: float) -> float:
        brut = await settings_repo.get_setting(session, cle)
        if brut is None:
            return defaut
        try:
            return float(str(brut).strip())
        except (TypeError, ValueError):
            return defaut

    actif = await settings_repo.get_setting(session, SETTING_ENABLED)
    return {
        "enabled": True if actif is None else str(actif).strip().lower() not in {"0", "false", "non", "off"},
        "scanMinutes": await lire(SETTING_SCAN, DEFAULT_SCAN_MINUTES),
        "newsMinutes": await lire(SETTING_NEWS, DEFAULT_NEWS_MINUTES),
        "calendarMinutes": await lire(SETTING_CALENDAR, DEFAULT_CALENDAR_MINUTES),
    }


@router.get("/status")
async def intelligence_status(
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    """Etat des trois boucles et bilan du dernier tour d'analyse."""
    etat = intelligence_scheduler.state.to_dict()
    etat["started"] = intelligence_scheduler.started
    etat["intervals"] = await _intervals(session)
    return etat


@router.put("/intervals")
async def set_intervals(
    payload: IntervalsRequest,
    session: AsyncSession = Depends(get_session),
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    """Regle les periodes sans redemarrer le Bridge."""
    if payload.enabled is not None:
        await settings_repo.set_setting(session, SETTING_ENABLED, "1" if payload.enabled else "0")
    for valeur, cle, nom in (
        (payload.scanMinutes, SETTING_SCAN, "analyse du marché"),
        (payload.newsMinutes, SETTING_NEWS, "collecte des actualités"),
        (payload.calendarMinutes, SETTING_CALENDAR, "calendrier économique"),
    ):
        if valeur is not None:
            await settings_repo.set_setting(session, cle, str(_borne(float(valeur), nom)))
    return await _intervals(session)


@router.post("/run/{target}")
async def run_now(
    target: str,
    device: Device = Depends(require_device),
) -> dict[str, Any]:
    """Declenche immediatement une boucle, sans attendre sa periode.

    Utile apres avoir ajoute un instrument ou une source : l'utilisateur voit
    le resultat tout de suite plutot que d'attendre le prochain tour.
    """
    cible = target.strip().lower()
    if cible not in CIBLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cible inconnue : « {target} ». Valeurs acceptées : {', '.join(CIBLES)}.",
        )

    try:
        if cible == "scan":
            rapport = await intelligence_scheduler.run_scan_once()
            resultat: dict[str, Any] = rapport.to_dict()
        elif cible == "news":
            resultat = {"notifications": await intelligence_scheduler.run_news_once()}
        else:
            resultat = {"notifications": await intelligence_scheduler.run_calendar_once()}
    except Exception as exc:
        # Une panne d'un moteur se raconte, elle ne se masque pas derriere un
        # resultat vide qui laisserait croire que tout va bien.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{CIBLES[cible].capitalize()} impossible : {exc}",
        ) from exc

    await journal.log(
        event="intelligence_manual_run",
        message=f"{CIBLES[cible].capitalize()} lancée depuis l'application",
        category="intelligence",
    )
    return {"target": cible, "result": resultat}


__all__ = ["router"]
