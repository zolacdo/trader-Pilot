"""Defauts confirmes par l'audit, avec leur scenario de declenchement.

Chaque test decrit un comportement observe puis juge faux. Ils echouent contre
le code d'origine et passent une fois le defaut corrige : c'est ce qui permet
de verifier qu'une correction repare bien ce qu'elle pretend reparer.
"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.core import utcnow
from app.models.enums import Direction, ExecutionMode, PositionState
from app.models.trading import TradeRecord
from app.repositories import trade_repo
from app.services.trading.position_manager import PositionManager

# ---------------------------------------------------------------------------
# 1. Une lecture de positions en echec ne doit pas valoir « aucune position »
# ---------------------------------------------------------------------------

class _WorkerSimule:
    """Remplace le processus MetaTrader. ``reponse`` est ce que MT5 renverrait."""

    def __init__(self, reponse) -> None:
        self.reponse = reponse
        self.appels: list[str] = []

    async def call(self, command: str, *args, **kwargs):
        self.appels.append(command)
        return self.reponse


def _service_avec(reponse):
    """Service MT5 reel, mais dont le processus enfant est simule."""
    from app.services.mt5.real_service import RealMetaTraderService

    service = RealMetaTraderService.__new__(RealMetaTraderService)
    service._worker = _WorkerSimule(reponse)
    service._require_package = lambda: None
    return service


async def test_une_lecture_de_positions_en_echec_est_signalee() -> None:
    """Scenario : MetaTrader hoquette pendant un cycle de suivi.

    ``positions_get()`` rend ``None`` quand l'appel echoue, et un tuple vide
    quand le compte n'a aucune position. La couche service confondait les
    deux. La reconciliation prenait donc l'echec pour la preuve que tout
    avait ete ferme : elle marquait CLOSED en base des positions encore
    ouvertes chez le courtier, publiait des evenements de fermeture et
    inscrivait un resultat realise invente.
    """
    from app.services.mt5.interface import MetaTraderError

    service = _service_avec(None)
    with pytest.raises(MetaTraderError):
        await service.positions()

    ordres = _service_avec(None)
    with pytest.raises(MetaTraderError):
        await ordres.orders()


async def test_un_compte_sans_position_reste_une_liste_vide() -> None:
    """Le cas legitime doit rester distinguable de l'echec."""
    service = _service_avec(())
    assert await service.positions() == []

    ordres = _service_avec(())
    assert await ordres.orders() == []


async def test_la_reconciliation_renonce_quand_la_lecture_leve(
    session: AsyncSession,
) -> None:
    """Une lecture qui leve ne doit fermer aucune position en base."""

    class _BrokerEnPanne:
        async def positions(self, symbol: str | None = None):
            raise RuntimeError("terminal injoignable")

        async def history_deals(self, since, until=None):
            return []

    trade = TradeRecord(
        ticket=5001,
        symbol="XAUUSD",
        broker_symbol="XAUUSDm",
        direction=Direction.BUY,
        volume=0.05,
        open_price=2650.0,
        current_price=2655.0,
        profit=25.0,
        state=PositionState.OPEN,
        execution_mode=ExecutionMode.MT5_DEMO,
        opened_at=utcnow(),
    )
    session.add(trade)
    await session.flush()

    manager = PositionManager(_BrokerEnPanne())
    assert await manager.sync_with_broker(session, ExecutionMode.MT5_DEMO) == []

    relu = await trade_repo.get_trade(session, trade.id)
    assert relu is not None and relu.state is PositionState.OPEN


# ---------------------------------------------------------------------------
# 2. L'ecoute Telegram doit demarrer aussi apres une connexion depuis l'app
# ---------------------------------------------------------------------------

async def test_les_routes_telegram_pilotent_l_ecoute() -> None:
    """Scenario : l'utilisateur connecte Telegram depuis son telephone.

    L'ecoute n'etait demarree qu'au lancement du Bridge. Apres une connexion
    faite depuis l'application, aucun message n'arrivait jamais — jusqu'au
    redemarrage suivant, sans que rien ne l'explique.
    """
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "telegram.py"
    arbre = ast.parse(source.read_text(encoding="utf-8"))

    appels: set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Attribute):
            appels.add(noeud.attr)

    assert "start_listener" in appels, (
        "aucune route Telegram ne demarre l'ecoute : une connexion faite depuis "
        "l'application ne recevrait aucun message"
    )
    assert "stop_listener" in appels, (
        "aucune route Telegram n'arrete l'ecoute : un listener continuerait de "
        "tourner apres une deconnexion"
    )


# ---------------------------------------------------------------------------
# 3. Une composante opposee sans conviction ne doit pas devenir un appui
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("note", "attendu_max"),
    [(0.0, 0.5), (0.1, 0.5), (0.5, 0.5)],
)
def test_une_composante_opposee_ne_depasse_jamais_le_neutre(
    note: float, attendu_max: float
) -> None:
    """Scenario : une lecture technique faible pointe a la vente, on envisage
    un achat.

    La regle « sa force devient une force contraire » etait appliquee comme
    ``1 - note``. Une conviction nulle (0,0) devenait donc un appui MAXIMAL
    (1,0) a la direction opposee : le score de confiance montait grace a une
    composante qui disait exactement l'inverse.
    """
    from app.services.confidence.engine import aligned_score

    valeur = aligned_score(note, Direction.SELL, Direction.BUY)
    assert valeur is not None
    assert valeur <= attendu_max, (
        f"une composante opposee de force {note} vaut {valeur} : elle ne doit "
        "jamais valoir plus que le point neutre"
    )


def test_une_composante_alignee_garde_sa_force() -> None:
    """La correction ne doit pas affaiblir le cas normal."""
    from app.services.confidence.engine import aligned_score

    assert aligned_score(0.9, Direction.BUY, Direction.BUY) == pytest.approx(0.9)
    assert aligned_score(0.0, Direction.BUY, Direction.BUY) == pytest.approx(0.0)


def test_une_composante_sans_direction_est_reprise_telle_quelle() -> None:
    """Regime, actualites, macro : ce sont des contextes, pas des directions."""
    from app.services.confidence.engine import aligned_score

    assert aligned_score(0.7, None, Direction.BUY) == pytest.approx(0.7)
    assert aligned_score(0.7, Direction.SELL, None) == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# 4. Un ordre en attente declenche doit devenir une position suivie
# ---------------------------------------------------------------------------

async def test_un_ordre_en_attente_declenche_devient_une_position(
    session: AsyncSession,
) -> None:
    """Scenario : un signal pose un ordre limite, le marche vient le chercher.

    L'ordre etait enregistre puis oublie : rien ne le convertissait en
    position suivie. Ni break-even, ni trailing, ni resultat, ni comptage du
    risque du jour — alors qu'une position reelle etait ouverte chez le
    courtier.
    """
    from app.models.enums import OrderType
    from app.models.trading import PendingOrderRecord

    ordre = PendingOrderRecord(
        ticket=7001,
        symbol="XAUUSD",
        broker_symbol="XAUUSDm",
        direction=Direction.BUY,
        order_type=OrderType.BUY_LIMIT,
        volume=0.05,
        price=2640.0,
        execution_mode=ExecutionMode.MT5_DEMO,
        created_at=utcnow(),
    )
    session.add(ordre)
    await session.flush()

    class _BrokerQuiRemplit:
        """L'ordre a disparu des ordres en attente et une position porte son ticket."""

        async def positions(self, symbol: str | None = None):
            from app.services.mt5.interface import PositionInfo

            return [
                PositionInfo(
                    ticket=7001,
                    symbol="XAUUSDm",
                    direction=Direction.BUY,
                    volume=0.05,
                    price_open=2640.0,
                    price_current=2652.0,
                    profit=60.0,
                    opened_at=utcnow(),
                )
            ]

        async def orders(self, symbol: str | None = None):
            return []

        async def history_deals(self, since, until=None):
            return []

    manager = PositionManager(_BrokerQuiRemplit())
    await manager.sync_with_broker(session, ExecutionMode.MT5_DEMO)

    suivies = await trade_repo.open_trades(session, ExecutionMode.MT5_DEMO)
    assert any(trade.ticket == 7001 for trade in suivies), (
        "l'ordre en attente s'est rempli chez le courtier mais n'est suivi par "
        "aucune position : le systeme est aveugle sur une position reelle"
    )


# ---------------------------------------------------------------------------
# 5. Toute fermeture doit alimenter les compteurs de risque
# ---------------------------------------------------------------------------

class _BrokerQuiFerme:
    """Courtier qui accepte la fermeture et rend un resultat realise."""

    def __init__(self, realise: float = -320.0) -> None:
        self.realise = realise

    async def close_position(self, ticket: int, volume: float | None = None):
        from app.services.mt5.interface import TradeResult

        return TradeResult(ok=True, retcode=10009, message="ferme", volume=volume or 0.05)

    async def positions(self, symbol: str | None = None):
        return []

    async def history_deals(self, since, until=None):
        from app.services.mt5.interface import DealInfo

        return [
            DealInfo(
                ticket=1,
                order=1,
                position_id=9001,
                symbol="XAUUSDm",
                volume=0.05,
                price=2640.0,
                profit=self.realise,
                time=utcnow(),
            )
        ]


async def test_une_fermeture_sur_ordre_du_canal_compte_dans_le_risque(
    session: AsyncSession,
) -> None:
    """Scenario : le canal publie « close now » sur une position perdante.

    ``_close()`` marquait le trade CLOSED sans inscrire son resultat, et la
    reconciliation ne repasse que sur les positions ENCORE OUVERTES : le trade
    n'atteignait donc jamais le comptage du risque.

    La limite de perte journaliere et le disjoncteur de pertes consecutives
    restaient a zero. Trois clotures perdantes d'affilee, et le signal suivant
    passait encore tous les controles.
    """
    from app.services.trading.position_manager import ManagementResult, PositionManager

    trade = TradeRecord(
        ticket=9001,
        symbol="XAUUSD",
        broker_symbol="XAUUSDm",
        direction=Direction.BUY,
        volume=0.05,
        initial_volume=0.05,
        open_price=2650.0,
        current_price=2640.0,
        profit=-320.0,
        state=PositionState.OPEN,
        execution_mode=ExecutionMode.MT5_DEMO,
        opened_at=utcnow(),
    )
    session.add(trade)
    await session.flush()

    manager = PositionManager(_BrokerQuiFerme())
    resultat = ManagementResult()
    await manager._close(session, trade, None, "ordre du canal", resultat)

    assert trade.state is PositionState.CLOSED
    assert trade.realized_pnl != 0.0, (
        "une position fermee sans resultat inscrit reste invisible pour la "
        "limite de perte journaliere"
    )
    assert resultat.closed, (
        "la fermeture doit remonter a l'appelant, sinon personne ne peut "
        "l'ajouter aux compteurs de risque"
    )


async def test_l_arret_d_urgence_compte_ses_pertes(session: AsyncSession) -> None:
    """Un arret d'urgence ferme souvent en perte : cela doit se compter."""
    import ast
    from pathlib import Path as _Path

    source = _Path(__file__).resolve().parent.parent / "app" / "services" / "trading" / "engine.py"
    arbre = ast.parse(source.read_text(encoding="utf-8"))

    fonction = next(
        (
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.AsyncFunctionDef) and noeud.name == "close_all_positions"
        ),
        None,
    )
    assert fonction is not None

    appels = {
        noeud.func.attr
        for noeud in ast.walk(fonction)
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute)
    }
    assert "_apply_closed_trades" in appels, (
        "l'arret d'urgence ferme sans rien compter : la perte n'apparait ni "
        "dans la limite journaliere ni dans les pertes consecutives"
    )


# ---------------------------------------------------------------------------
# 6. Un message de gestion n'ouvre pas une seconde position
# ---------------------------------------------------------------------------

async def test_un_message_de_gestion_ne_devient_pas_un_nouveau_signal(
    session: AsyncSession,
) -> None:
    """Scenario : le canal securise une position ouverte.

        « BUY XAUUSD — TP1 HIT, move SL to BE »

    Le rattachement a un signal existant n'etait tente QUE si le message ne se
    lisait pas comme un signal. Celui-ci portait le sens de la position : il
    etait donc pris pour un nouvel ordre d'achat. Une SECONDE position
    s'ouvrait sur le meme instrument — l'exposition doublait — et l'ordre de
    mise a break even etait perdu.
    """
    from app.models.enums import ChannelMode, SignalStatus
    from app.models.telegram import Channel, ChannelSettings
    from app.models.trading import Signal
    from app.repositories import signal_repo
    from app.services.signals import pipeline

    canal = Channel(telegram_id=-1001, title="Canal d'essai", monitored=True)
    session.add(canal)
    await session.flush()
    session.add(ChannelSettings(channel_id=canal.id, mode=ChannelMode.OBSERVE))
    await session.flush()

    parent = Signal(
        channel_id=canal.id,
        telegram_message_id=1,
        idempotency_key="parent-1",
        raw_text="BUY XAUUSD 2650 SL 2640 TP1 2670",
        symbol="XAUUSD",
        normalized_symbol="XAUUSD",
        direction=Direction.BUY,
        entry_price=2650.0,
        stop_loss=2640.0,
        status=SignalStatus.OPEN,
        message_date=utcnow(),
    )
    await signal_repo.create(session, parent)

    resultat = await pipeline.process_message(
        session,
        text="BUY XAUUSD — TP1 HIT, move SL to BE",
        channel=canal,
        message_id=2,
        message_date=utcnow(),
        reply_to_message_id=1,
        allow_ai=False,
    )

    assert resultat.action == "follow_up", (
        f"le message de gestion a ete traite comme « {resultat.action} » : "
        "une seconde position se serait ouverte sur le meme instrument"
    )
    assert resultat.parent_signal is not None
    assert resultat.parent_signal.id == parent.id


async def test_une_action_de_gestion_sans_parent_reste_un_signal(
    session: AsyncSession,
) -> None:
    """Le correctif ne doit pas avaler un vrai signal.

    Sans position a gerer, le message doit reprendre le chemin normal.
    """
    from app.models.enums import ChannelMode
    from app.models.telegram import Channel, ChannelSettings
    from app.services.signals import pipeline

    canal = Channel(telegram_id=-1002, title="Canal neuf", monitored=True)
    session.add(canal)
    await session.flush()
    session.add(ChannelSettings(channel_id=canal.id, mode=ChannelMode.OBSERVE))
    await session.flush()

    resultat = await pipeline.process_message(
        session,
        text="BUY XAUUSD 2650 SL 2640 TP1 2670 TP2 2690",
        channel=canal,
        message_id=1,
        message_date=utcnow(),
        allow_ai=False,
    )

    assert resultat.action == "new_signal", (
        f"un signal complet a ete classe « {resultat.action} » : il serait perdu"
    )


# ---------------------------------------------------------------------------
# 7. Un titre de notification identifie son evenement
# ---------------------------------------------------------------------------

def test_deux_publications_du_meme_creneau_ont_des_titres_distincts() -> None:
    """Scenario : 14h30, trois chiffres americains publies ensemble.

    L'anti-doublon compare le titre EXACT dans une fenetre de temps. Le
    gabarit produisait « ÉVÉNEMENT ÉCONOMIQUE » pour toute publication : seule
    la premiere alerte passait, les autres etaient avalees et perdues.
    """
    from app.services.notifications import templates

    cpi = templates.economic_event_upcoming(
        title="Core CPI m/m", currency="USD", minutes_before=30, event_id=1
    )
    ventes = templates.economic_event_upcoming(
        title="Retail Sales m/m", currency="USD", minutes_before=30, event_id=2
    )

    assert cpi.title != ventes.title, (
        "deux publications differentes portent le meme titre : la seconde sera "
        "prise pour un doublon et perdue"
    )
    assert "Core CPI" in cpi.title
    assert "Retail Sales" in ventes.title


def test_deux_actualites_a_fort_impact_ont_des_titres_distincts() -> None:
    """Un lot de depeches ne doit pas se reduire a une seule notification."""
    from app.services.notifications import templates

    une = templates.high_impact_news(headline="La Fed relève ses taux", impact="HIGH", news_id=1)
    deux = templates.high_impact_news(headline="L'OPEP réduit sa production", impact="HIGH", news_id=2)

    assert une.title != deux.title
    assert "Fed" in une.title
    assert "OPEP" in deux.title


def test_un_titre_tres_long_reste_dans_les_limites() -> None:
    """La colonne du titre fait 255 caracteres : on ne la deborde pas."""
    from app.services.notifications import templates

    brouillon = templates.high_impact_news(headline="A" * 400, impact="HIGH")
    assert len(brouillon.title) <= 255


# ---------------------------------------------------------------------------
# 8. Chaine d'actualites : lecture, deduplication, identite d'un evenement
# ---------------------------------------------------------------------------

def test_un_flux_rss_1_est_lu_et_non_declare_vide() -> None:
    """Scenario : une source institutionnelle publie en RSS 1.0 (RDF).

    La recherche ne couvrait que RSS 2.0 et Atom. Un flux RDF ressortait donc
    VIDE, et la source etait declaree « OK » : une panne silencieuse, la pire
    espece — on croit suivre une source qui ne rapporte jamais rien.
    """
    from app.services.news.providers import RssNewsProvider
    from app.services.news.sources import NewsOptions, NewsSource

    flux = (
        '<?xml version="1.0"?>'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns="http://purl.org/rss/1.0/">'
        "<channel><title>Institut</title></channel>"
        "<item><title>Publication du taux directeur</title>"
        "<link>https://exemple.test/a</link>"
        "<description>Communique officiel.</description></item>"
        "</rdf:RDF>"
    )

    source = NewsSource(key="rdf", name="Institut", url="https://exemple.test/rss")
    provider = RssNewsProvider(source, NewsOptions(), client=None)
    articles = provider.parse(flux)

    assert articles, "un flux RSS 1.0 ne doit pas etre lu comme vide"
    assert articles[0].title == "Publication du taux directeur"


def test_deux_chiffres_differents_ne_sont_pas_un_doublon() -> None:
    """Scenario : la banque centrale releve de 25 points, puis de 50.

    L'empreinte ecartait tout mot de deux lettres ou moins. « 25 » et « 50 »
    disparaissaient donc, et les deux depeches obtenaient la MEME empreinte :
    la seconde etait regroupee comme un doublon de la premiere et n'etait
    jamais signalee.
    """
    from app.services.news.dedup import title_fingerprint

    vingt_cinq = title_fingerprint("Fed raises rates by 25 bp")
    cinquante = title_fingerprint("Fed raises rates by 50 bp")

    assert vingt_cinq != cinquante, (
        "deux decisions de taux differentes partagent la meme empreinte"
    )


def test_une_reformulation_reste_un_doublon() -> None:
    """Le correctif ne doit pas faire passer une reformulation pour un fait neuf."""
    from app.services.news.dedup import title_fingerprint

    une = title_fingerprint("La Fed relève ses taux de 25 points de base")
    deux = title_fingerprint("de base, la Fed relève ses taux de 25 points")
    assert une == deux


def test_un_evenement_decale_garde_son_identite() -> None:
    """Scenario : une publication annoncee a 14h30 tombe a 14h32.

    L'identifiant etait derive de l'heure exacte : le moindre decalage creait
    une SECONDE ligne en base. L'ancienne gardait ses rappels deja envoyes et
    continuait d'annoncer une heure perimee.
    """
    from datetime import UTC, datetime

    from app.services.economic_calendar.provider import _stable_id

    annonce = datetime(2026, 9, 11, 14, 30, tzinfo=UTC)
    reel = datetime(2026, 9, 11, 14, 32, tzinfo=UTC)
    assert _stable_id("Core CPI m/m", annonce) == _stable_id("Core CPI m/m", reel)

    # Deux jours differents restent deux evenements differents.
    lendemain = datetime(2026, 9, 12, 14, 30, tzinfo=UTC)
    assert _stable_id("Core CPI m/m", annonce) != _stable_id("Core CPI m/m", lendemain)


# ---------------------------------------------------------------------------
# 9. La couverture d'analyse peut atteindre le minimum exige
# ---------------------------------------------------------------------------

class _MoteurAvecHistorique:
    """Moteur de marche qui sert des bougies deterministes.

    Assez d'historique pour que les analogues et les correlations soient
    reellement calculables : c'est la condition pour que la couverture monte.
    """

    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols

    async def symbol_info(self, symbol: str, refresh: bool = False):
        from app.services.mt5.interface import SymbolInfo

        return SymbolInfo(name=symbol, digits=2, point=0.01)

    async def candles(self, symbol: str, timeframe, bars: int = 100):
        from datetime import timedelta

        from app.services.mt5.interface import Candle

        frame = getattr(timeframe, "value", str(timeframe))
        minutes = {"H1": 60, "H4": 240, "D1": 1440}.get(frame, 60)
        # Serie reproductible : une tendance douce, un peu de relief.
        base = 2600.0 + (hash(symbol) % 100)
        fin = utcnow()
        serie = []
        for index in range(bars):
            moment = fin - timedelta(minutes=minutes * (bars - index))
            derive = index * 0.15
            relief = ((index * 37) % 23) * 0.4
            ouverture = base + derive + relief
            serie.append(
                Candle(
                    time=moment,
                    open=ouverture,
                    high=ouverture + 1.2,
                    low=ouverture - 1.1,
                    close=ouverture + 0.3,
                    tick_volume=100 + index,
                )
            )
        return serie


async def test_la_couverture_peut_atteindre_le_minimum_exige(session: AsyncSession) -> None:
    """Constat : le cycle autonome plafonnait a 50 % de couverture.

    Les analogues historiques et les correlations inter-marches n'etaient
    calcules par personne. Le minimum exige etant de 60 %, AUCUNE decision ne
    pouvait aboutir — quel que soit le marche. L'ecran l'annoncait sous la
    forme « Analyse trop partielle : 45 % ».
    """
    from app.services.confidence.engine import ConfidenceEngine
    from app.services.decision.context import DecisionThresholds
    from app.services.intelligence.assembly import build_bundle
    from app.services.market_scanner.scanner import ScanResult

    resultat = ScanResult(
        symbol="XAUUSD",
        broker_symbol="XAUUSDm",
        scanned_at=utcnow(),
        atr=4.5,
        atr_ratio=0.18,
        support=2630.0,
        resistance=2680.0,
        price=2650.0,
        bid=2649.8,
        ask=2650.2,
        spread_points=40,
        regime_confidence=0.8,
        alignment=0.9,
        setup_potential=0.8,
        setup_direction=Direction.BUY,
    )

    moteur = _MoteurAvecHistorique(["XAUUSD", "EURUSD", "GBPUSD"])
    dossier, _ = await build_bundle(
        session, resultat, engine=moteur, peers=["XAUUSD", "EURUSD", "GBPUSD"]
    )

    confiance = ConfidenceEngine().evaluate(
        dossier.components(Direction.BUY, source="AI_GENERATED")
    )
    minimum = DecisionThresholds().minimum_coverage

    assert confiance.coverage >= minimum, (
        f"couverture {confiance.coverage:.0%} sous le minimum de {minimum:.0%} : "
        f"aucune decision ne peut aboutir. Manquantes : "
        f"{[c.value for c in confiance.missing]}"
    )


# ---------------------------------------------------------------------------
# 10. Un bilan de journee n'est pas un signal, une heure n'est pas un prix
# ---------------------------------------------------------------------------

# Message reellement recu du canal « Forex Signals Trading », le 11/09 a 15h08.
BILAN_DE_JOURNEE = """SESSION REPORT

Friday, 11 September 2026

Results:
Accuracy: 92.00%
Wins: 12
Losses: 1

Trades:
Day Session
12:05 - EUR/USD - Sell
12:20 - AUD/CHF - Buy
12:35 - GBP/USD - Buy
13:00 - AUD/CAD - Buy
13:15 - AUD/CHF - Buy
14:00 - AUD/JPY - Sell
14:15 - EUR/JPY - Buy
14:30 - EUR/JPY - Sell
15:00 - AUD/NZD - Sell
15:15 - AUD/CHF - Buy
15:30 - USD/CAD - Sell
16:00 - EUR/JPY - Sell
16:25 - AUD/USD - Sell"""


def test_un_bilan_de_journee_n_est_pas_un_signal() -> None:
    """Constat en production : ce bilan a produit « EURUSD SELL, entree 12,0 ».

    Le parser a retenu le PREMIER ordre de la liste — un trade deja passe — et
    pris l'heure « 12:05 » pour un prix, sur une paire qui cote 1,16. Seule la
    confiance a 0,60, sous le minimum de 0,85, a empeche que ce faux signal
    parte a l'execution. C'etait une chance, pas une protection.
    """
    from app.services.signals import deterministic_parser

    lu = deterministic_parser.parse(BILAN_DE_JOURNEE)

    assert not lu.is_signal, (
        f"un recapitulatif a ete lu comme un ordre : {lu.symbol} {lu.direction} "
        f"entree {lu.entry_price}"
    )
    assert "recapitulatif_plusieurs_directions" in lu.warnings


def test_une_heure_n_est_jamais_lue_comme_un_prix() -> None:
    """« 12:05 » ne doit pas devenir une entree a 12,0."""
    from app.services.signals import deterministic_parser

    lu = deterministic_parser.parse("12:05 EUR/USD Sell")
    assert lu.entry_price != 12.0, "l'heure a ete prise pour un prix"

    # Un vrai prix sur la meme ligne reste lu.
    vrai = deterministic_parser.parse("09:30 SELL GOLD 3350")
    assert vrai.entry_price == 3350.0


def test_un_signal_ordinaire_reste_lu() -> None:
    """Les deux corrections ne doivent pas avaler un signal legitime."""
    from app.services.signals import deterministic_parser

    lu = deterministic_parser.parse(
        "BUY XAUUSD\nENTRY 2650\nSL 2640\nTP1 2670\nTP2 2690"
    )
    assert lu.is_signal
    assert lu.symbol == "XAUUSD"
    assert lu.direction is Direction.BUY
    assert lu.entry_price == 2650.0
    assert lu.stop_loss == 2640.0


def test_un_signal_mentionnant_sa_propre_cloture_reste_lu() -> None:
    """Un seul sens, meme repete, reste un ordre exploitable."""
    from app.services.signals import deterministic_parser

    lu = deterministic_parser.parse(
        "BUY GOLD 3350\nSL 3340\nTP 3370\nBUY ZONE 3348-3352"
    )
    assert lu.is_signal
    assert lu.direction is Direction.BUY
