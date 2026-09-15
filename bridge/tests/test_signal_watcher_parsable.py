"""Ce que le watcher remet au moteur doit se relire sans ambiguite.

Le watcher publiait un texte pour l'oeil et donnait CE MEME texte au moteur.
Le format detaille annote chaque objectif de son rapport de risque :

    TP1 : 1.34474  (1:1.0)

Le parseur lisait les deux nombres. Le 14/09/2026, un GBPUSD SELL est arrive
avec les objectifs [3.0, 2.0, 1.34474, 1.34169, 1.33865, 1.0] et a ete refuse
pour « TP1 doit etre sous l'entree ». Le signal partait en validation manuelle
alors qu'il etait parfaitement calcule.

Le format simple ne porte que les niveaux. Ces tests verrouillent l'aller-retour
complet : ce que le formateur ecrit, le parseur doit le relire a l'identique.
"""

from __future__ import annotations

import pytest

from app.models.enums import Direction
from app.services.signals import deterministic_parser, validator
from app.watcher import formatter
from app.watcher.models import EntryType, WatcherDecision, WatcherSignal, WatcherStatus


def signal(
    direction: Direction,
    entree: float,
    stop: float,
    cibles: list[float],
    symbole: str = "GBPUSD",
    digits: int = 5,
) -> WatcherSignal:
    return WatcherSignal(
        symbol=symbole,
        broker_symbol=f"{symbole}m",
        direction=direction,
        decision=WatcherDecision.SELL if direction is Direction.SELL else WatcherDecision.BUY,
        status=WatcherStatus.CREATED,
        timeframe="M15",
        entry_type=EntryType.BREAKOUT,
        entry=entree,
        stop_loss=stop,
        digits=digits,
        take_profit_1=cibles[0],
        take_profit_2=cibles[1],
        take_profit_3=cibles[2],
        risk_distance=abs(entree - stop),
        # Les rapports ronds sont precisement ceux qui polluaient le parsing.
        risk_reward_1=1.0,
        risk_reward_2=2.0,
        risk_reward_3=3.0,
        score=72.0,
        confidence=72,
    )


VENTE = signal(Direction.SELL, 1.34778, 1.35082, [1.34474, 1.34169, 1.33865])
ACHAT = signal(Direction.BUY, 1.34778, 1.34474, [1.35082, 1.35386, 1.35690])

# Instrument a prix groupe : le formateur y insere une espace fine comme
# separateur de milliers. GBPUSD, a cinq decimales, n'en a pas et ne
# couvrait donc pas ce cas — pourtant celui de l'or et des indices.
OR_VENTE = signal(
    Direction.SELL, 3350.00, 3354.57, [3347.13, 3338.33, 3335.64],
    symbole="XAUUSD", digits=2,
)
OR_ACHAT = signal(
    Direction.BUY, 3350.00, 3345.43, [3352.87, 3361.67, 3364.36],
    symbole="XAUUSD", digits=2,
)


class TestFormatSimple:
    @pytest.mark.parametrize(
        "cas",
        [VENTE, ACHAT, OR_VENTE, OR_ACHAT],
        ids=["vente", "achat", "or_vente", "or_achat"],
    )
    def test_les_niveaux_se_relisent_a_l_identique(self, cas: WatcherSignal) -> None:
        parsed = deterministic_parser.parse(formatter.simple_signal(cas))
        assert parsed.symbol == cas.symbol
        assert parsed.direction is cas.direction
        entree = parsed.entry_price if parsed.entry_price is not None else parsed.entry_min
        assert entree == pytest.approx(cas.entry)
        assert parsed.stop_loss == pytest.approx(cas.stop_loss)
        assert parsed.take_profits == pytest.approx(cas.targets)

    @pytest.mark.parametrize(
        "cas",
        [VENTE, ACHAT, OR_VENTE, OR_ACHAT],
        ids=["vente", "achat", "or_vente", "or_achat"],
    )
    def test_le_validateur_accepte(self, cas: WatcherSignal) -> None:
        """Le test qui compte : plus de passage en validation manuelle."""
        parsed = deterministic_parser.parse(formatter.simple_signal(cas))
        resultat = validator.validate(validator.sanitize(parsed))
        assert resultat.ok, resultat.to_dict()

    def test_aucun_rapport_de_risque_n_apparait(self) -> None:
        """La source du bruit : les annotations « (1:2.0) »."""
        texte = formatter.simple_signal(VENTE)
        assert "1:" not in texte
        assert "(" not in texte


class TestFormatDetaille:
    """Le format detaille se relit lui aussi, depuis que le parseur masque les ratios.

    Transmettre le format simple au moteur reste la bonne decision -- on ne
    donne pas a lire a une machine un texte ecrit pour l'oeil. Mais cela ne
    protegeait que les signaux du watcher : un canal exterieur qui annote ses
    objectifs de la meme facon restait mal lu, et c'est ce qui est arrive au
    signal 128 du 14/09/2026. La cause est traitee dans le parseur.
    """

    def test_les_annotations_ne_deviennent_plus_des_objectifs(self) -> None:
        parsed = deterministic_parser.parse(formatter.detailed_signal(VENTE))
        assert parsed.take_profits == pytest.approx(VENTE.targets)

    def test_le_validateur_l_accepte_desormais(self) -> None:
        parsed = deterministic_parser.parse(formatter.detailed_signal(VENTE))
        resultat = validator.validate(validator.sanitize(parsed))
        assert resultat.ok, resultat.to_dict()


class TestCablage:
    def test_le_moteur_recoit_le_format_simple(self) -> None:
        """Verrouille le cablage : un refactor ne doit pas le reperdre."""
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "app" / "watcher" / "engine.py"
        code = source.read_text(encoding="utf-8")
        assert "texte_machine = formatter.simple_signal(signal)" in code
        assert "session,\n            texte_machine,\n            config," in code

    def test_la_publication_garde_le_format_choisi(self) -> None:
        """L'humain continue de recevoir le message complet."""
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "app" / "watcher" / "engine.py"
        code = source.read_text(encoding="utf-8")
        assert "simple=config.simple_format" in code
