"""Reglage autonome de l'exigence du moteur de decision.

Demande du 16/09/2026 : « il doit le changer, pas besoin de la presence d'un
humain ». La regle CDC2 qui reservait toute evolution de configuration a une
decision humaine ne vaut donc plus. ``recorder.py`` continue de ne faire que
mesurer -- c'est une separation des roles, pas une interdiction : c'est ici,
et seulement ici, que la mesure devient un reglage.

DEUX MESURES, DEUX SENS. Une perte constatee justifie de **lever** l'exigence :
la preuve est la, dans les trades reellement clos. La **baisser** demande de
savoir ce que le seuil ecarte, et ces opportunites sont refusees avant
d'exister -- le shadow mode du CDC2 ne les enregistrait que lorsqu'il etait
actif, c'est-a-dire quand plus rien ne part au broker, donc sans rien a quoi
les comparer.

C'est la bande marginale qui a comble ce vide : une opportunite ecartee pour
la seule raison du seuil est desormais enregistree et suivie pendant que le
systeme trade. Le regleur defait donc ses propres hausses sur la performance
reelle, et descend sous la reference posee par l'humain sur la preuve de cette
bande -- jamais l'une pour l'autre, deux compteurs le garantissent. Il
s'arrete a ``MARGINAL_FLOOR``, plancher partage avec la bande : en dessous,
l'exigence cesserait d'etre selective, ce qui est un changement de nature.

Les memes garde-fous que le watcher, et pour les memes raisons : un pas
unitaire, un plafond, une bande morte contre le broutage, et l'exigence d'une
preuve neuve pour chaque pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.repositories import ai_repo, decision_repo, pattern_repo, settings_repo
from app.services import journal

# ``MARGINAL_FLOOR`` vient de la : c'est a la fois le plancher du regleur et
# celui de la bande qui l'autorise a descendre. Deux constantes de meme sens
# dans deux fichiers finiraient par diverger, et la bande mesurerait alors un
# espace different de celui que le seuil peut occuper.
from app.services.decision.shadow import MARGINAL_FLOOR, ShadowStats, compute_stats

logger = get_logger(__name__)

# Fenetre de mesure, en jours.
WINDOW_DAYS = 90
# Aucune conclusion sous ce nombre de trades clos : plus tot, on reglerait sur
# du bruit. Meme valeur que le watcher, meme raison.
MIN_SAMPLE = 10
# Bande morte, en R. Une esperance qui oscille autour de zero ferait monter
# puis descendre l'exigence sans fin.
MIN_EDGE = 0.10
# Un pas de deux centiemes de confiance. De 0,75 a 0,95 il faut donc dix pas,
# chacun paye d'une preuve neuve.
STEP = 0.02
# Au-dela, l'exigence n'accepterait plus rien : ce ne serait plus un reglage
# mais un arret deguise, et un arret doit se decider, pas se subir.
CEILING = 0.95

SETTING_BASELINE = "learning.confidence_baseline"
SETTING_SAMPLE = "learning.tuner_sample"
# Un compteur par population, la lecon du regleur du watcher : la bande
# marginale et les trades reels sont deux mesures distinctes, et un compteur
# commun ferait passer l'une pour la repetition de l'autre.
SETTING_MARGINAL_SAMPLE = "learning.tuner_marginal_sample"


@dataclass(slots=True)
class Adjustment:
    """Ce que le regleur a change, et sur quels chiffres."""

    key: str
    sample: int
    before: float
    after: float
    message: str


def _since_day(days: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(days=days)).date().isoformat()


async def _measure(session: AsyncSession) -> tuple[int, float]:
    """Trades clos de la fenetre et resultat net en R, toutes strategies."""
    rows = await pattern_repo.list_strategy_performance(
        session, since_day=_since_day(WINDOW_DAYS)
    )
    trades = sum(row.trades for row in rows)
    net_r = sum(row.net_r for row in rows)
    return trades, net_r


async def _marginal_band(session: AsyncSession) -> ShadowStats:
    """Ce que valent les opportunites ecartees pour la seule raison du seuil."""
    trades = await decision_repo.list_shadow_trades(
        session, since=datetime.now(tz=UTC) - timedelta(days=WINDOW_DAYS)
    )
    return compute_stats([item for item in trades if item.marginal])


async def tune(session: AsyncSession) -> list[Adjustment]:
    """Regle l'exigence de confiance d'apres ce que chaque bande a donne."""
    trades, net_r = await _measure(session)
    bande = await _marginal_band(session)
    # La bande marginale est prouvee quand elle a assez d'issues ET un
    # avantage franc. C'est elle, et elle seule, qui autorise a descendre sous
    # la reference posee par l'humain.
    bande_prouvee = bande.closed >= MIN_SAMPLE and (bande.average_r or 0.0) > MIN_EDGE

    reglages = await ai_repo.get_settings(session)
    courant = float(reglages.min_opportunity_confidence)
    # La reference est saisie au premier passage : c'est la valeur que
    # l'humain avait posee.
    reference = float(await settings_repo.get_setting(session, SETTING_BASELINE, courant))
    moyenne = net_r / trades if trades else 0.0

    if trades >= MIN_SAMPLE and moyenne < -MIN_EDGE:
        cible, sens, compteur, echantillon = (
            courant + STEP,
            "relevee",
            SETTING_SAMPLE,
            trades,
        )
        justification = f"{trades} trade(s) clos a {moyenne:+.2f} R de moyenne"
    elif trades >= MIN_SAMPLE and moyenne > MIN_EDGE and courant > reference:
        # Le regleur defait sa propre hausse : la performance s'est redressee.
        cible, sens, compteur, echantillon = (
            courant - STEP,
            "abaissee",
            SETTING_SAMPLE,
            trades,
        )
        justification = f"{trades} trade(s) clos a {moyenne:+.2f} R de moyenne"
    elif bande_prouvee and courant > MARGINAL_FLOOR:
        # Descente sous la reference, sur preuve de la bande mesuree.
        cible, sens, compteur, echantillon = (
            courant - STEP,
            "abaissee",
            SETTING_MARGINAL_SAMPLE,
            bande.closed,
        )
        justification = (
            f"{bande.closed} simulation(s) de la bande a {bande.average_r:+.2f} R de moyenne"
        )
    else:
        return []

    dernier = int(await settings_repo.get_setting(session, compteur, 0) or 0)
    if echantillon <= dernier:
        # Un pas doit etre paye d'un denouement neuf, sinon la meme mesure
        # ferait marcher l'exigence jusqu'a sa borne.
        return []

    plancher = MARGINAL_FLOOR if bande_prouvee else reference
    cible = round(min(max(cible, plancher), CEILING), 4)
    if abs(cible - courant) < 1e-9:
        # Deja contre sa borne : rien a ecrire.
        return []

    await ai_repo.update_settings(session, {"min_opportunity_confidence": cible})
    await settings_repo.set_setting(session, SETTING_BASELINE, reference)
    await settings_repo.set_setting(session, compteur, echantillon)

    message = (
        f"Exigence de confiance {sens} de {courant:.2f} a {cible:.2f} : "
        f"{justification} sur {WINDOW_DAYS} jours."
    )
    logger.info("Reglage autonome : %s", message)
    await journal.log(event="learning_tuned", message=message, category="system")
    return [
        Adjustment(
            key="min_opportunity_confidence",
            sample=echantillon,
            before=courant,
            after=cible,
            message=message,
        )
    ]


__all__ = [
    "CEILING",
    "MIN_EDGE",
    "MIN_SAMPLE",
    "STEP",
    "Adjustment",
    "tune",
]
