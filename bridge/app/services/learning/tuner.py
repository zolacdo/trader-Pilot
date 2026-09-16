"""Reglage autonome de l'exigence du moteur de decision.

Demande du 16/09/2026 : « il doit le changer, pas besoin de la presence d'un
humain ». La regle CDC2 qui reservait toute evolution de configuration a une
decision humaine ne vaut donc plus. ``recorder.py`` continue de ne faire que
mesurer -- c'est une separation des roles, pas une interdiction : c'est ici,
et seulement ici, que la mesure devient un reglage.

UNE ASYMETRIE ASSUMEE, faute de capteur. Une perte mesuree justifie de
**lever** l'exigence : la preuve est la, dans les trades reellement clos. Rien
ne mesure en revanche ce qui se passe SOUS le seuil -- ces opportunites sont
ecartees avant d'exister, et le shadow mode du CDC2 ne les enregistre que
lorsqu'il est actif, c'est-a-dire quand plus rien ne part au broker. Il n'y a
donc aucune population simultanee a comparer, comme le fait la bande fantome
du watcher.

Le regleur peut donc toujours defaire ses propres hausses quand la performance
se redresse -- c'est le sens « baisser » -- mais il ne descend pas sous la
reference posee par l'humain. Le jour ou un capteur couvrira cette zone, le
plancher pourra ceder ; le construire d'abord, l'ouvrir ensuite.

Les memes garde-fous que le watcher, et pour les memes raisons : un pas
unitaire, un plafond, une bande morte contre le broutage, et l'exigence d'une
preuve neuve pour chaque pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.repositories import ai_repo, pattern_repo, settings_repo
from app.services import journal

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


async def tune(session: AsyncSession) -> list[Adjustment]:
    """Regle l'exigence de confiance d'apres ce que les trades ont donne."""
    trades, net_r = await _measure(session)
    if trades < MIN_SAMPLE:
        return []

    moyenne = net_r / trades
    reglages = await ai_repo.get_settings(session)
    courant = float(reglages.min_opportunity_confidence)

    # La reference est saisie au premier passage : c'est la valeur que
    # l'humain avait posee, et le regleur n'ira jamais en dessous sans capteur.
    reference = float(await settings_repo.get_setting(session, SETTING_BASELINE, courant))
    dernier = int(await settings_repo.get_setting(session, SETTING_SAMPLE, 0) or 0)
    if trades <= dernier:
        # Un pas doit etre paye d'un denouement neuf, sinon la meme mesure
        # ferait marcher l'exigence jusqu'a son plafond.
        return []

    if moyenne < -MIN_EDGE:
        cible = courant + STEP
        sens = "relevee"
    elif moyenne > MIN_EDGE and courant > reference:
        cible = courant - STEP
        sens = "abaissee"
    else:
        return []

    cible = round(min(max(cible, reference), CEILING), 4)
    if abs(cible - courant) < 1e-9:
        # Deja contre sa reference ou son plafond : rien a ecrire.
        return []

    await ai_repo.update_settings(session, {"min_opportunity_confidence": cible})
    await settings_repo.set_setting(session, SETTING_BASELINE, reference)
    await settings_repo.set_setting(session, SETTING_SAMPLE, trades)

    message = (
        f"Exigence de confiance {sens} de {courant:.2f} a {cible:.2f} : "
        f"{trades} trade(s) clos a {moyenne:+.2f} R de moyenne sur "
        f"{WINDOW_DAYS} jours."
    )
    logger.info("Reglage autonome : %s", message)
    await journal.log(event="learning_tuned", message=message, category="system")
    return [
        Adjustment(
            key="min_opportunity_confidence",
            sample=trades,
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
