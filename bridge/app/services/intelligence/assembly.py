"""Assemblage des lectures de marche en un dossier de decision (CDC2 §36, §42).

Chaque module amont — scanner, actualites, analogues historiques, correlations
— produit sa propre vue. Personne ne les reunit : c'est le role de ce fichier.
Il ne calcule rien lui-meme, il traduit.

Regle appliquee partout : une donnee absente reste ``None``. Elle sera comptee
comme absente par le moteur de confiance, ce qui fait baisser la couverture.
Elle n'est jamais remplacee par une valeur neutre inventee, car une couverture
faible doit se voir et bloquer l'entree (CDC2 §43, §113).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import get_logger
from app.models.core import as_utc, utcnow
from app.models.enums import Direction
from app.models.intelligence import NewsEvent, NewsImpact, NewsSentiment, Timeframe
from app.repositories import news_repo
from app.services.cross_market.analyzer import CrossMarketAnalyzer
from app.services.decision.inputs import (
    AnalysisBundle,
    CrossMarketView,
    HistoricalView,
    MacroView,
    NewsView,
    PriceStructure,
    QuoteView,
    RegimeView,
    TechnicalView,
)
from app.services.historical_patterns.engine import HistoricalPatternEngine
from app.services.historical_patterns.interface import LookAheadError, load_history
from app.services.intelligence.candles import RangeCandleProvider
from app.services.market_data.engine import MarketDataEngine
from app.services.market_scanner.scanner import ScanResult
from app.services.news.risk_mode import evaluate_for_session
from app.services.news.taxonomy import currencies_for_symbol
from app.services.technical_analysis.engine import TechnicalAnalysis

logger = get_logger(__name__)

# Au-dela de cette anciennete, une actualite ne pese plus sur la lecture.
NEWS_WINDOW_HOURS = 12

# Profondeur d'historique fouillee pour trouver des situations comparables.
#
# Attention : ce n'est PAS cette valeur qui limite la recherche. Le moteur de
# marche plafonne chaque serie a 1500 bougies, et c'est ce plafond qui fixe la
# fenetre reellement fouillee. Demander 730 jours ne change donc rien -- sinon
# de faire echouer le chargement D1, ce qui a deja tue le processus MT5.
HISTORIQUE_JOURS = 300

# Horizon de veille du calendrier economique. Au-dela, une publication ne pese
# plus sur une decision prise maintenant.
MACRO_EVENT_HORIZON_HOURS = 24

# Penalite appliquee a la note macro selon l'importance de la publication la
# plus proche. Une banque centrale qui parle rend toute conviction fragile.
MACRO_EVENT_PENALTY = {
    NewsImpact.CRITICAL: 0.80,
    NewsImpact.HIGH: 0.50,
    NewsImpact.MEDIUM: 0.20,
    NewsImpact.LOW: 0.0,
}

# Fenetre des actualites macro retenues pour l'orientation.
MACRO_NEWS_WINDOW_HOURS = 24

# Ecart minimal entre actualites haussieres et baissieres pour oser une
# direction. En dessous, le sentiment n'est pas net et se taire vaut mieux.
MACRO_SENTIMENT_MARGIN = 2

# Au-dela, la mesure de correlation coute plus qu'elle n'apporte.
CORRELATION_MAX = 6

# En dessous, l'echantillon est trop maigre : mieux vaut declarer la
# composante absente que de conclure sur deux precedents.
MIN_ANALOGUES = 5

# Unite de temps sur laquelle les situations comparables sont cherchees.
#
# H4 et non H1. Le moteur de marche sert au plus 1500 bougies par serie : en
# H1 cela couvre 62 jours, en H4 pres de 250 -- quatre fois plus d'histoire
# pour exactement le meme cout de chargement.
#
# Mesure du 12/09/2026 sur trois instruments, 300 jours demandes :
#
#     instrument   H1    H4
#     BTCUSD        3   186
#     XAUUSD       58   165
#     EURUSD      136   172
#
# Sur BTCUSD, H1 ne trouvait que 3 analogues pour un minimum de 5 : la
# composante ressortait absente a chaque decision, et l'analyse n'atteignait
# jamais le taux de couverture exige.
ANALOGUES_BASE_TIMEFRAME = "H4"

# Un seul moteur d'analogues, reutilise : il ne porte aucun etat par instrument.
pattern_engine = HistoricalPatternEngine(base_timeframe=ANALOGUES_BASE_TIMEFRAME)

# Poids de l'impact d'une actualite dans la note de contexte « actualites ».
# Note haute = contexte favorable (calme) ; note basse = contexte charge.
IMPACT_PENALTY = {
    NewsImpact.LOW: 0.05,
    NewsImpact.MEDIUM: 0.15,
    NewsImpact.HIGH: 0.35,
    NewsImpact.CRITICAL: 0.60,
}


def reference_analysis(result: ScanResult) -> TechnicalAnalysis | None:
    """Analyse de l'unite de temps qui a servi de reference au scan.

    Le scanner note cette unite dans ses caracteristiques ; on la relit plutot
    que de la redeviner, pour que structure et score parlent du meme graphique.
    """
    if result.view is None:
        return None
    libelle = result.features.get("timeframe")
    if libelle:
        try:
            analysis = result.view.analysis_for(Timeframe(libelle))
        except ValueError:
            analysis = None
        if analysis is not None:
            return analysis
    for verdict in result.view.verdicts:
        if verdict.analysis is not None and verdict.analysis.usable:
            return verdict.analysis
    return None


def quote_view(result: ScanResult) -> QuoteView:
    return QuoteView(
        symbol=result.symbol,
        bid=result.bid,
        ask=result.ask,
        spread_points=result.spread_points,
        captured_at=result.scanned_at,
    )


def technical_view(result: ScanResult) -> TechnicalView:
    """Traduit le potentiel de setup mesure par le scanner.

    ``setup_potential`` est deja une note 0-1 issue de criteres explicites
    (alignement, declencheur, rapport gain/risque, regime). On la reprend sans
    la retoucher : la retravailler ici la rendrait intracable.
    """
    return TechnicalView(
        score=result.setup_potential,
        direction=result.setup_direction,
        trend_d1=result.trend_d1,
        trend_h4=result.trend_h4,
        trend_h1=result.trend_h1,
        detail=" ".join(result.reasons)[:400] or None,
        computed_at=result.scanned_at,
    )


def regime_view(result: ScanResult) -> RegimeView:
    return RegimeView(
        regime=result.regime,
        score=result.regime_confidence,
        detail=result.regime_detail or None,
    )


def price_structure(
    result: ScanResult,
    analysis: TechnicalAnalysis | None,
    *,
    digits: int = 5,
    point: float | None = None,
) -> PriceStructure | None:
    """Niveaux mesures sur le graphique, jamais proposes par une IA.

    Sans prix ni ATR, aucun plan n'est calculable : on rend ``None`` plutot
    qu'une structure incomplete qui donnerait un stop arbitraire.
    """
    if result.price is None or result.atr is None or result.atr <= 0:
        return None

    supports: list[float] = []
    resistances: list[float] = []
    hauts: list[float] = []
    bas: list[float] = []
    if analysis is not None:
        supports = [cluster.price for cluster in analysis.levels.supports]
        resistances = [cluster.price for cluster in analysis.levels.resistances]
        if analysis.levels.support is not None:
            supports.append(analysis.levels.support)
        if analysis.levels.resistance is not None:
            resistances.append(analysis.levels.resistance)
        hauts = [swing.price for swing in analysis.swings if swing.kind == "HIGH"]
        bas = [swing.price for swing in analysis.swings if swing.kind == "LOW"]

    if result.support is not None:
        supports.append(result.support)
    if result.resistance is not None:
        resistances.append(result.resistance)

    return PriceStructure(
        symbol=result.symbol,
        last_price=result.price,
        atr=result.atr,
        digits=digits,
        point=point,
        supports=sorted(set(supports)),
        resistances=sorted(set(resistances)),
        swing_high=max(hauts) if hauts else None,
        swing_low=min(bas) if bas else None,
        spread_points=result.spread_points,
        computed_at=result.scanned_at,
    )


async def macro_view(session: AsyncSession, symbol: str) -> MacroView:
    """Lecture macroeconomique d'un instrument (CDC2 section 28).

    Deux mesures, tirees de donnees deja collectees :

    * le RISQUE D'EVENEMENT -- une publication majeure imminente sur l'une des
      devises du symbole abaisse la note sans donner de direction. Une banque
      centrale qui parle dans l'heure rend toute conviction fragile ;
    * l'ORIENTATION -- le sentiment des actualites macroeconomiques recentes
      sur ces devises, retenu seulement s'il est net.

    Un symbole dont les devises sont inconnues ne produit rien : deviner
    vaudrait moins que se taire.
    """
    devises = currencies_for_symbol(symbol)
    if not devises:
        return MacroView(
            score=None, detail=f"Devises inconnues pour {symbol} : aucune lecture macro."
        )

    maintenant = utcnow()

    # --- risque d'evenement ---
    try:
        evenements = await news_repo.list_economic_events(
            session,
            start=maintenant,
            end=maintenant + timedelta(hours=MACRO_EVENT_HORIZON_HOURS),
            limit=60,
        )
    except Exception as exc:
        logger.debug("Calendrier illisible pour %s : %s", symbol, exc)
        evenements = []

    concernes = [
        event
        for event in evenements
        if (event.currency or "").strip().upper() in devises
    ]
    penalite = max(
        (MACRO_EVENT_PENALTY.get(event.impact, 0.0) for event in concernes), default=0.0
    )

    # --- orientation ---
    try:
        recentes = await news_repo.recent_news(
            session, maintenant - timedelta(hours=MACRO_NEWS_WINDOW_HOURS)
        )
    except Exception as exc:
        logger.debug("Actualites illisibles pour %s : %s", symbol, exc)
        recentes = []

    macro = [
        item
        for item in recentes
        if devises & {code.upper() for code in (item.affected_currencies or [])}
        and item.impact in (NewsImpact.HIGH, NewsImpact.CRITICAL)
    ]
    haussieres = sum(1 for item in macro if item.sentiment is NewsSentiment.BULLISH)
    baissieres = sum(1 for item in macro if item.sentiment is NewsSentiment.BEARISH)

    direction = None
    ecart = haussieres - baissieres
    if abs(ecart) >= MACRO_SENTIMENT_MARGIN:
        direction = Direction.BUY if ecart > 0 else Direction.SELL

    note = max(0.0, 1.0 - penalite)
    if concernes:
        prochain = min(concernes, key=lambda event: event.scheduled_at)
        minutes = max(0, int((prochain.scheduled_at - maintenant).total_seconds() // 60))
        detail = (
            f"{len(concernes)} publication(s) a venir sur {', '.join(sorted(devises))} ; "
            f"la plus proche dans {minutes} min ({prochain.impact.value})."
        )
    else:
        detail = (
            f"Aucune publication majeure attendue sur {', '.join(sorted(devises))} "
            f"dans les {MACRO_EVENT_HORIZON_HOURS} h."
        )

    if macro:
        detail += f" {len(macro)} actualite(s) macro : {haussieres} haussiere(s), {baissieres} baissiere(s)."

    return MacroView(score=note, direction=direction, detail=detail[:300])


async def news_view(session: AsyncSession, symbol: str) -> NewsView:
    """Contexte d'actualite d'un instrument (CDC2 §27, §35, §62).

    La note repond a « le terrain est-il degage ? », pas a « faut-il acheter ? ».
    Un blocage avant publication majeure n'est pas une opinion : c'est un refus.
    """
    bloque, raison = await evaluate_for_session(session, symbol)

    depuis = utcnow() - timedelta(hours=NEWS_WINDOW_HOURS)
    try:
        recentes = await news_repo.recent_news(session, depuis)
    except Exception as exc:  # une panne de lecture ne doit pas bloquer le cycle
        logger.debug("Lecture des actualites impossible pour %s : %s", symbol, exc)
        return NewsView(score=None, blackout=bloque, detail=raison, analysable=False)

    devises = currencies_for_symbol(symbol)
    liees = [item for item in recentes if _concerne(item, symbol, devises)]
    if not liees:
        # Aucune actualite rattachee : le terrain est degage, et cela se mesure.
        return NewsView(
            score=None if bloque else 0.75,
            blackout=bloque,
            detail=raison or "Aucune actualité rattachée sur les dernières heures.",
        )

    pire = max(liees, key=lambda item: IMPACT_PENALTY.get(item.impact, 0.0))
    penalite = IMPACT_PENALTY.get(pire.impact, 0.0)
    return NewsView(
        score=max(0.0, 1.0 - penalite),
        blackout=bloque,
        impact=pire.impact,
        detail=raison or f"{len(liees)} actualité(s) rattachée(s), impact maximal {pire.impact.value}.",
    )


def _concerne(item: NewsEvent, symbol: str, devises: set[str]) -> bool:
    """L'actualite touche-t-elle reellement cet instrument ?

    Le rattachement doit etre explicite : instrument nomme, ou devise du
    couple citee. Une actualite classee critique mais rattachee a aucun actif
    ne compte pas ici : sinon une seule depeche mondiale ferait passer tous
    les instruments en impact critique et bloquerait le systeme entier
    (CDC2 §27). Le contexte global reste visible dans l'ecran Actualites.
    """
    if item.affected_assets and symbol in item.affected_assets:
        return True
    if devises and item.affected_currencies:
        return bool(devises & set(item.affected_currencies))
    return False


async def historical_view(
    result: ScanResult, engine: MarketDataEngine | None
) -> HistoricalView:
    """Analogues historiques mesures sur les bougies du courtier.

    Le moteur cherche des situations passees comparables et regarde ce qui
    s'est produit ensuite. Il ne devine rien : sans historique suffisant, la
    composante ressort absente et la couverture du score baisse.
    """
    if engine is None or result.price is None:
        return HistoricalView(score=None, detail="Aucun service de marché attaché.")

    provider = RangeCandleProvider(engine, broker_symbol=result.broker_symbol)
    fin = as_utc(result.scanned_at) or utcnow()
    debut = fin - timedelta(days=HISTORIQUE_JOURS)
    try:
        historique = await load_history(provider, result.symbol, ("H1", "H4", "D1"), debut, fin)
        analyse = pattern_engine.analyse(
            historique,
            as_of=fin,
            direction=result.setup_direction,
            spread_points=result.spread_points,
        )
    except LookAheadError:
        # Se taire serait pire : une fuite de donnee future fausserait tout.
        raise
    except Exception as exc:
        logger.info("Analogues historiques indisponibles pour %s : %s", result.symbol, exc)
        return HistoricalView(score=None, detail=f"Analyse historique impossible : {exc}"[:300])

    if analyse is None or analyse.matches < MIN_ANALOGUES:
        trouves = 0 if analyse is None else analyse.matches
        return HistoricalView(
            score=None,
            matches=trouves,
            detail=(
                f"{trouves} situation(s) comparable(s) seulement : trop peu pour "
                f"conclure (minimum {MIN_ANALOGUES})."
            ),
        )

    resume = analyse.horizon_summary(analyse.horizon_hours)
    echantillons = resume.get("samples") or 0
    if echantillons < MIN_ANALOGUES:
        return HistoricalView(
            score=None,
            matches=analyse.matches,
            similarity=analyse.similarity_mean,
            detail=(
                "Situations comparables trouvées, mais aucune n'a encore atteint "
                "son horizon : rien à en conclure."
            ),
        )

    hausses = resume.get("positive") or 0
    baisses = resume.get("negative") or 0
    tranches = hausses + baisses
    if not tranches:
        return HistoricalView(
            score=None,
            matches=analyse.matches,
            similarity=analyse.similarity_mean,
            detail="Toutes les suites comparables sont restées neutres : aucun enseignement.",
        )

    # La part dominante donne la direction ; sa netteté donne la force.
    if hausses >= baisses:
        direction = Direction.BUY
        part = hausses / tranches
    else:
        direction = Direction.SELL
        part = baisses / tranches

    return HistoricalView(
        score=max(0.0, min(1.0, part)),
        direction=direction,
        matches=analyse.matches,
        similarity=analyse.similarity_mean,
        detail=(
            f"{analyse.matches} situation(s) comparable(s), {echantillons} avec une suite "
            f"connue : {hausses} en hausse, {baisses} en baisse "
            f"(horizon {analyse.horizon_hours:g} h)."
        ),
    )


async def cross_market_view(
    result: ScanResult, engine: MarketDataEngine | None, pairs: list[str]
) -> CrossMarketView:
    """Lecture inter-marches : cet instrument suit-il ou contredit ses voisins ?

    Sans instrument de comparaison, la composante reste absente plutot que
    d'inventer une correlation avec rien.
    """
    voisins = [symbol for symbol in pairs if symbol != result.symbol][:CORRELATION_MAX]
    if engine is None or not voisins:
        return CrossMarketView(
            score=None,
            detail="Aucun autre instrument suivi : contexte inter-marchés non mesurable.",
        )

    provider = RangeCandleProvider(engine)
    analyzer = CrossMarketAnalyzer(provider)
    try:
        rapport = await analyzer.analyse([result.symbol, *voisins])
    except Exception as exc:
        logger.info("Contexte inter-marchés indisponible pour %s : %s", result.symbol, exc)
        return CrossMarketView(score=None, detail=f"Corrélations impossibles : {exc}"[:300])

    matrice = getattr(rapport, "recent_matrix", None) or {}
    liees = matrice.get(result.symbol) or {}
    mesures = [
        abs(float(valeur))
        for autre, valeur in liees.items()
        if autre != result.symbol and isinstance(valeur, (int, float))
    ]
    if not mesures:
        return CrossMarketView(
            score=None,
            detail="Pas assez d'historique commun pour mesurer une corrélation.",
        )

    # Un instrument tres correle a ses voisins offre peu de diversification :
    # le contexte est moins porteur. Un instrument independant l'est davantage.
    moyenne = sum(mesures) / len(mesures)
    return CrossMarketView(
        score=max(0.0, min(1.0, 1.0 - moyenne)),
        detail=(
            f"Corrélation moyenne de {moyenne:.2f} avec {len(mesures)} instrument(s) suivi(s)."
        ),
    )


async def build_bundle(
    session: AsyncSession,
    result: ScanResult,
    *,
    engine: MarketDataEngine | None = None,
    peers: list[str] | None = None,
) -> tuple[AnalysisBundle, PriceStructure | None]:
    """Reunit toutes les lectures disponibles pour un instrument.

    ``peers`` sont les autres instruments suivis : ils servent a mesurer le
    contexte inter-marches. Sans eux, cette composante reste absente.
    """
    analysis = reference_analysis(result)

    digits, point = 5, None
    if engine is not None:
        info = await engine.symbol_info(result.broker_symbol or result.symbol)
        if info is not None:
            digits, point = info.digits, info.point

    bundle = AnalysisBundle(
        symbol=result.symbol,
        quote=quote_view(result),
        technical=technical_view(result),
        regime=regime_view(result),
        historical=await historical_view(result, engine),
        macro=await macro_view(session, result.symbol),
        news=await news_view(session, result.symbol),
        cross_market=await cross_market_view(result, engine, peers or []),
    )
    return bundle, price_structure(result, analysis, digits=digits, point=point)


def direction_of(bundle: AnalysisBundle, result: ScanResult) -> Direction | None:
    """Direction envisagee : celle du scanner si elle existe, sinon le vote."""
    return result.setup_direction or bundle.suggested_direction()


def quote_age_ok(bundle: AnalysisBundle, *, max_seconds: float = 300.0) -> bool:
    if bundle.quote is None:
        return False
    age = bundle.quote.age_seconds(utcnow())
    return age is not None and age <= max_seconds


__all__ = [
    "build_bundle",
    "cross_market_view",
    "direction_of",
    "historical_view",
    "macro_view",
    "news_view",
    "price_structure",
    "quote_age_ok",
    "quote_view",
    "reference_analysis",
    "regime_view",
    "technical_view",
]
