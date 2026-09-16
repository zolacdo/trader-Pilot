"""Apprentissage autonome du watcher (CDC3 section 41).

Trois leviers, mesures puis actionnes sans intervention :

* **ecarter** un type d'entree ou un instrument qui n'a jamais gagne ;
* **regler le seuil** de publication dans les deux sens -- il baisse quand la
  bande mesuree sous lui rapporte, il monte quand le publie perd ;
* **deplacer les poids** du critere le plus trompeur vers le plus fiable, a
  somme constante.

Trois regles dont ce module ne sort jamais :

1. aucune decision sous ``MIN_SAMPLE``. Sur une vingtaine d'operations, tout
   ajustement fin ajusterait du bruit ;
2. aucune ecriture hors des bornes declarees dans la configuration. Un
   parametre sans borne ecrite ne peut pas etre touche du tout -- pour les
   seuils c'est ``learning_bounds``, pour les poids la bande
   ``weight_floor`` / ``weight_ceiling`` ;
3. aucune decision silencieuse. Chaque ecriture est journalisee avec son
   chiffrage, et l'ordonnanceur la publie dans le canal ;
3bis. aucun pas sans preuve franche ni preuve neuve. Une bande morte
   (``MIN_EDGE``, ``MIN_DISCRIMINATION``) evite le broutage d'un regulateur
   qui oscille autour de zero, et un pas n'est autorise que si l'echantillon
   a grossi depuis le precedent -- sinon la meme mesure ferait marcher le
   reglage jusqu'a sa borne, heure apres heure ;
4. aucun bannissement sur la foi du seul suivi. Le suivi ne modelise pas le
   trailing : son resultat est un plancher du resultat reel. Quand une
   position existe dans ``trades``, c'est elle qui dit si le signal a gagne.

Une decision n'est qu'un reglage en base : elle se defait depuis
l'application, sans toucher au code. Et ce module ne connait pas le moteur
d'execution -- il ne peut pas passer d'ordre, c'est structurel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.services import journal
from app.watcher import performance, repository
from app.watcher.config import DEFAULT_WEIGHTS, WatcherConfig, update_config
from app.watcher.models import STRATEGY_VERSION
from app.watcher.performance import MIN_SAMPLE

logger = get_logger(__name__)


@dataclass(slots=True)
class Decision:
    """Ce que l'apprentissage a decide, et sur quels chiffres."""

    key: str
    kind: str
    # Nombre d'operations denouees qui portent la decision. C'est la seule
    # grandeur qui la rend contestable : sans elle, « ecarte » ou « abaisse »
    # n'est qu'une affirmation.
    sample: int
    message: str


# Un point par decision, pas un bond. Le seuil met donc cinq heures a
# descendre de 70 a 65, chaque pas etant re-mesure : une commande qui saute
# d'un coup ne laisse jamais voir l'effet du pas precedent.
THRESHOLD_STEP = 1.0
# Meme prudence pour les poids, avec en plus une contrainte de somme : le
# point retire a un critere est donne a un autre, jamais cree.
WEIGHT_STEP = 1.0

# Bandes mortes. Une esperance qui oscille autour de zero ferait descendre
# puis remonter le seuil a chaque heure, indefiniment : il faut un ecart franc
# pour agir. 0,10 R sur dix operations fait 1 R cumule -- mince, mais c'est un
# signe ; en dessous, c'est du bruit centre.
MIN_EDGE = 0.10
# Meme raison pour les poids : deux centiemes d'ecart de ratio moyen entre
# gagnants et perdants ne designent pas un critere trompeur.
MIN_DISCRIMINATION = 0.10


def clamp(config: WatcherConfig, name: str, value: float) -> float | None:
    """Ramene une valeur dans ses bornes, ou refuse de l'ecrire.

    Un parametre dont la borne n'est pas declaree rend ``None`` : sans limite
    ecrite, rien ne dit jusqu'ou la boucle aurait le droit d'aller, et deviner
    serait exactement ce que les garde-fous doivent empecher.
    """
    bounds = (config.learning_bounds or {}).get(name)
    if not bounds or len(bounds) != 2:
        return None
    low, high = float(bounds[0]), float(bounds[1])
    if low > high:
        logger.warning("Bornes de %s inversees : aucun ajustement ecrit.", name)
        return None
    return min(max(value, low), high)


async def review(session: AsyncSession, config: WatcherConfig) -> list[Decision]:
    """Ecarte ce qui n'a jamais gagne. Ne decide rien sous ``MIN_SAMPLE``."""
    if not config.learning_enabled:
        return []

    since = utcnow() - timedelta(days=max(1, config.learning_window_days))
    # Uniquement la version courante : un signal mesure « sur position
    # entiere » porte un -1 R plein la ou le compte avait encaisse sa tranche
    # a TP1. Apprendre dessus reviendrait a apprendre sur du faux.
    closed = await repository.closed_signals(
        session, since=since, strategy_version=STRATEGY_VERSION
    )
    traces = await repository.post_mortems(session, since=since)
    # Le suivi ne modelise pas le trailing : son resultat est un plancher du
    # resultat reel. On demande donc au compte, quand il a quelque chose a
    # dire, avant de declarer une clef sterile.
    trades = await repository.closed_trades_since(session, since)
    gagnants = {
        signal.id for signal in closed if signal.id is not None and _a_gagne(signal, trades)
    }

    deja_ecartes = {str(item).upper() for item in config.disabled_entry_types or []}
    surveilles = {str(item).upper() for item in config.symbols or []}

    decisions = [
        decision
        for decision in _sterile(closed, traces, "entry_type", gagnants)
        if decision.key not in deja_ecartes
    ]
    # Un instrument hors de la liste surveillee n'a pas a etre « ecarte » :
    # la decision serait vide, et le canal recevrait une annonce sans objet.
    decisions += [
        decision
        for decision in _sterile(closed, traces, "symbol", gagnants)
        if decision.key in surveilles
    ]
    changes: dict[str, Any] = {}
    types = [decision.key for decision in decisions if decision.kind == "entry_type"]
    if types:
        changes["disabled_entry_types"] = sorted(deja_ecartes | set(types))
    symbols = [decision.key for decision in decisions if decision.kind == "symbol"]
    if symbols:
        changes["symbols"] = [
            item for item in config.symbols if str(item).upper() not in set(symbols)
        ]
    if changes:
        await update_config(session, changes)

    # Le seuil se regle a part : il ne depend pas de ce qui precede, et les
    # deux ecritures ne touchent pas les memes clefs.
    seuil = await _adjust_threshold(session, config)
    if seuil is not None:
        decisions.append(seuil)

    # Les poids se reglent sur une autre grandeur -- le pouvoir discriminant
    # de chaque critere -- et n'ecrivent pas la meme clef que le seuil.
    poids = await _adjust_weights(session, config)
    if poids is not None:
        decisions.append(poids)

    for decision in decisions:
        logger.info("Apprentissage : %s", decision.message)
        await journal.log(
            event="watcher_learning",
            message=decision.message,
            category="system",
        )
    return decisions


def _mean_ratios(signals: list[Any]) -> dict[str, float]:
    """Ratio moyen de chaque critere sur ces operations.

    Un critere absent de assez d'operations est ecarte : une moyenne sur trois
    mesures ne dit rien, et le comparer a une moyenne sur vingt serait pire
    que de l'ignorer.
    """
    total: dict[str, float] = {}
    compte: dict[str, int] = {}
    for signal in signals:
        criteria = (signal.score_breakdown or {}).get("criteria") or []
        for item in criteria:
            key = str(item.get("key") or "")
            ratio = item.get("ratio")
            if not key or not isinstance(ratio, (int, float)):
                continue
            total[key] = total.get(key, 0.0) + float(ratio)
            compte[key] = compte.get(key, 0) + 1
    return {key: total[key] / compte[key] for key in total if compte[key] >= MIN_SAMPLE}


def _discrimination(gagnants: list[Any], perdants: list[Any]) -> dict[str, float]:
    """Pouvoir discriminant de chaque critere, en ecart de ratio moyen.

    Positif : le critere etait haut quand l'operation marchait. Negatif : il
    etait haut quand elle ratait -- il ne mesure pas ce qu'il croit mesurer.
    """
    moyennes_g = _mean_ratios(gagnants)
    moyennes_p = _mean_ratios(perdants)
    communs = set(moyennes_g) & set(moyennes_p)
    return {key: moyennes_g[key] - moyennes_p[key] for key in communs}


async def _adjust_weights(
    session: AsyncSession, config: WatcherConfig
) -> Decision | None:
    """Transfere un point de poids du critere le plus trompeur au plus fiable.

    Un transfert, jamais une inflation : la somme des poids ne bouge pas, donc
    la couverture -- qui se mesure contre ce total -- garde son sens. Deux
    poids seulement changent par decision, et chacun reste dans la bande
    ``weight_floor`` / ``weight_ceiling``.

    Il faut les deux populations, chacune au-dessus de ``MIN_SAMPLE`` : sans
    perdants, aucun critere n'est prouve fiable ; sans gagnants, aucun n'est
    prouve trompeur.
    """
    since = utcnow() - timedelta(days=max(1, config.learning_window_days))
    closed = await repository.closed_signals(
        session, since=since, strategy_version=STRATEGY_VERSION
    )
    gagnants = [item for item in closed if (item.result_r or 0.0) > 0]
    perdants = [item for item in closed if (item.result_r or 0.0) < 0]
    if len(gagnants) < MIN_SAMPLE or len(perdants) < MIN_SAMPLE:
        return None

    pouvoir = _discrimination(gagnants, perdants)
    if len(pouvoir) < 2:
        return None
    fiable = max(pouvoir, key=lambda key: pouvoir[key])
    trompeur = min(pouvoir, key=lambda key: pouvoir[key])
    if (
        fiable == trompeur
        or pouvoir[trompeur] > -MIN_DISCRIMINATION
        or pouvoir[fiable] < MIN_DISCRIMINATION
    ):
        # Sans critere franchement trompeur ET franchement fiable, il n'y a
        # rien a reprendre a personne.
        return None

    echantillon = len(gagnants) + len(perdants)
    if echantillon <= config.weights_last_sample:
        # Meme exigence que pour le seuil : un pas, un denouement neuf.
        return None

    poids = {key: config.weight(key) for key in DEFAULT_WEIGHTS}
    if poids.get(trompeur, 0.0) - WEIGHT_STEP < config.weight_floor:
        return None
    if poids.get(fiable, 0.0) + WEIGHT_STEP > config.weight_ceiling:
        return None
    poids[trompeur] -= WEIGHT_STEP
    poids[fiable] += WEIGHT_STEP
    await update_config(
        session, {"weights": poids, "weights_last_sample": echantillon}
    )

    return Decision(
        key=f"{trompeur} -> {fiable}",
        kind="weight",
        sample=echantillon,
        message=(
            f"Poids deplace de {trompeur} vers {fiable} : sur {len(gagnants)} gain(s) "
            f"et {len(perdants)} perte(s), {trompeur} etait plus haut dans les pertes "
            f"({pouvoir[trompeur]:+.2f}) et {fiable} dans les gains "
            f"({pouvoir[fiable]:+.2f})."
        ),
    )


async def _adjust_threshold(
    session: AsyncSession, config: WatcherConfig
) -> Decision | None:
    """Regle le seuil de publication d'apres ce que chaque bande rapporte.

    Deux mesures, deux sens. La bande fantome -- ce que le systeme aurait
    publie si le seuil avait ete plus bas -- justifie une baisse quand elle
    gagne. Ce qui a reellement ete publie justifie une hausse quand il perd.
    Aucune des deux ne parle sous ``MIN_SAMPLE`` operations, et les deux se
    limitent a la version de strategie courante : un resultat mesure « sur
    position entiere » ne decrit pas la meme chose et ferait bouger le seuil
    sur du faux.

    Une limite assumee : ces moyennes sont en R suivis, et le suivi ne
    modelise pas le trailing. Elles sont donc un plancher du resultat reel.
    L'effet est negligeable sur les perdants -- un trade arrete au break even
    vaut ce qu'il dit -- mais un gagnant longuement suivi est sous-estime.
    La hausse de seuil est donc legerement trop prompte, jamais l'inverse.
    """
    reel = await performance.compute(
        session,
        config.learning_window_days,
        shadow=False,
        strategy_version=STRATEGY_VERSION,
    )
    fantome = await performance.compute(
        session,
        config.learning_window_days,
        shadow=True,
        strategy_version=STRATEGY_VERSION,
    )

    baisser = fantome.overall.significant and (fantome.overall.average_r or 0.0) > MIN_EDGE
    monter = reel.overall.significant and (reel.overall.average_r or 0.0) < -MIN_EDGE

    if baisser and monter:
        # Monter abandonnerait une bande rentable ; baisser ajouterait du
        # volume a des signaux qui perdent. Ni l'un ni l'autre n'est
        # defendable, et choisir au hasard serait pire que s'abstenir.
        logger.info(
            "Seuil inchange : la bande mesuree gagne (%s R) alors que le publie "
            "perd (%s R). Aucun des deux sens n'est defendable.",
            fantome.overall.average_r,
            reel.overall.average_r,
        )
        return None
    if not baisser and not monter:
        return None

    bande = fantome.overall if baisser else reel.overall
    if bande.trades <= config.threshold_last_sample:
        # Un pas doit etre paye d'un denouement neuf. Sinon la meme mesure
        # ferait marcher le seuil jusqu'a sa borne, heure apres heure.
        return None

    cible = config.minimum_score + (-THRESHOLD_STEP if baisser else THRESHOLD_STEP)
    valeur = clamp(config, "minimum_score", cible)
    if valeur is None or abs(valeur - config.minimum_score) < 0.01:
        # Borne absente, ou seuil deja contre sa borne : rien a ecrire.
        return None

    await update_config(
        session, {"minimum_score": valeur, "threshold_last_sample": bande.trades}
    )
    return Decision(
        key="minimum_score",
        kind="threshold",
        sample=bande.trades,
        message=(
            f"Seuil de publication {'abaisse' if baisser else 'releve'} de "
            f"{config.minimum_score:.0f} a {valeur:.0f} : {bande.trades} operation(s) "
            f"a {bande.average_r:+.2f} R de moyenne sur la bande "
            f"{'mesuree sous le seuil' if baisser else 'publiee'}."
        ),
    )


def _a_gagne(signal: Any, trades: list[Any]) -> bool:
    """Ce signal a-t-il gagne ? Le compte tranche s'il a quelque chose a dire.

    L'appariement reprend la regle de ``matching_trade`` : meme symbole, meme
    sens, position ouverte a partir du signal. Il est approximatif -- rien ne
    relie ``trades`` a ``watcher_signals`` -- mais son erreur va dans un seul
    sens : elle peut transformer une perte suivie en gain reel, jamais
    l'inverse. Elle rend donc le bannissement plus prudent, ce qui est le bon
    sens pour une action automatique.
    """
    reel = _real_pnl(signal, trades)
    if reel is not None:
        return reel > 0
    return (signal.result_r or 0.0) > 0


def _real_pnl(signal: Any, trades: list[Any]) -> float | None:
    """P&L de la position nee de ce signal, ou ``None`` si aucun ordre n'est parti."""
    created = as_utc(signal.created_at)
    for trade in trades:
        if trade.symbol != signal.broker_symbol or trade.direction is not signal.direction:
            continue
        opened = as_utc(trade.opened_at)
        if created is not None and opened is not None and opened < created:
            continue
        return float(trade.realized_pnl or 0.0)
    return None


def _sterile(
    closed: list[Any], traces: list[Any], kind: str, gagnants: set[int]
) -> list[Decision]:
    """Clefs totalisant ``MIN_SAMPLE`` operations denouees sans un seul gain."""
    total: dict[str, int] = {}
    gains: dict[str, int] = {}
    for signal in closed:
        key = _key_of(signal, kind)
        total[key] = total.get(key, 0) + 1
        if signal.id in gagnants:
            gains[key] = gains.get(key, 0) + 1

    pertes: dict[str, int] = {}
    for trace in traces:
        key = _key_of(trace, kind)
        pertes[key] = pertes.get(key, 0) + 1

    libelle = "Type d'entree" if kind == "entry_type" else "Instrument"
    decisions: list[Decision] = []
    for key, compte in sorted(total.items()):
        if compte < MIN_SAMPLE or gains.get(key, 0) > 0:
            continue
        decisions.append(
            Decision(
                key=key,
                kind=kind,
                sample=pertes.get(key, compte),
                message=(
                    f"{libelle} {key} ecarte : {compte} operation(s) denouee(s) "
                    f"sans un seul gain."
                ),
            )
        )
    return decisions


def _key_of(item: Any, kind: str) -> str:
    """Valeur de regroupement, que le champ porte un enum ou une chaine."""
    valeur = getattr(item, kind)
    return str(getattr(valeur, "value", valeur)).upper()


__all__ = ["Decision", "clamp", "review"]
