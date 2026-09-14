"""L'IA relit le message et peut REFUSER un faux signal -- jamais en creer un.

Le parser deterministe est litteral. Il a lu comme des ordres un bilan de
journee, un article sur Bitcoin et un cours intitule « HOW I LAYER MY
ENTRIES ». Ces tests verrouillent le second avis, et surtout sa limite : le
verificateur n'a qu'un droit de veto.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.models.enums import Direction
from app.services.signals import verification
from app.services.signals.models import ParsedSignal


def signal_lu(is_signal: bool = True) -> ParsedSignal:
    return ParsedSignal(
        is_signal=is_signal,
        symbol_raw="XAUUSD",
        symbol="XAUUSD",
        direction=Direction.BUY,
        entry_price=4372.0,
        stop_loss=4362.0,
        take_profits=[4375.0],
    )


class ReponseIA:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.model = "test"


class RoutageIA:
    def __init__(self, payload: Any) -> None:
        self.response = ReponseIA(payload)


def brancher(monkeypatch: pytest.MonkeyPatch, resultat: Any) -> list[str]:
    """Remplace l'appel a l'IA, et note les messages qui lui sont soumis."""
    soumis: list[str] = []

    async def faux_appel(prompt: str, **_: Any) -> Any:
        soumis.append(prompt)
        if isinstance(resultat, Exception):
            raise resultat
        return resultat

    monkeypatch.setattr(verification.ai_service, "complete_json", faux_appel)
    return soumis


# ---------------------------------------------------------------------------
# Le veto fonctionne
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "nature",
    ["recapitulatif", "article", "publicite", "cours"],
)
async def test_un_message_qui_n_est_pas_un_ordre_est_ecarte(
    monkeypatch: pytest.MonkeyPatch, nature: str
) -> None:
    brancher(
        monkeypatch,
        RoutageIA({"est_un_ordre": False, "nature": nature, "raison": "aucun ordre"}),
    )

    verdict = await verification.verifier(signal_lu(), "un texte quelconque")

    assert verdict.veto is True
    assert verdict.nature == nature


async def test_un_vrai_ordre_passe(monkeypatch: pytest.MonkeyPatch) -> None:
    brancher(monkeypatch, RoutageIA({"est_un_ordre": True, "nature": "ordre"}))

    verdict = await verification.verifier(signal_lu(), "BUY XAUUSD 4372 SL 4362 TP 4375")

    assert verdict.veto is False
    assert verdict.disponible is True


async def test_un_message_de_suivi_passe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deplacer un stop est une action a executer : ce n'est pas un veto."""
    brancher(monkeypatch, RoutageIA({"est_un_ordre": True, "nature": "suivi"}))

    verdict = await verification.verifier(signal_lu(), "TP1 hit, move SL to BE")

    assert verdict.veto is False


# ---------------------------------------------------------------------------
# La limite : le veto ne peut jamais creer un signal
# ---------------------------------------------------------------------------

async def test_l_ia_ne_peut_jamais_creer_un_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Meme si l'IA affirme qu'il y a un ordre, un non-signal le reste.

    C'est la garantie qui permet a cette verification de ne contourner aucun
    controle local : elle ne sait que retrancher.
    """
    soumis = brancher(monkeypatch, RoutageIA({"est_un_ordre": True, "nature": "ordre"}))

    verdict = await verification.verifier(signal_lu(is_signal=False), "un texte quelconque")

    assert verdict.veto is False
    assert soumis == [], "l'IA a ete interrogee sur un message qui n'est pas un signal"


# ---------------------------------------------------------------------------
# Une IA en panne ne doit jamais bloquer le trading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "panne",
    [
        RuntimeError("serveur local injoignable"),
        None,
        RoutageIA(None),
    ],
    ids=["exception", "aucune_reponse", "charge_utile_vide"],
)
async def test_une_ia_indisponible_laisse_passer(
    monkeypatch: pytest.MonkeyPatch, panne: Any
) -> None:
    brancher(monkeypatch, panne)

    verdict = await verification.verifier(signal_lu(), "BUY XAUUSD 4372")

    assert verdict.veto is False
    assert verdict.disponible is False


@pytest.mark.parametrize(
    "reponse",
    [
        {"est_un_ordre": False},
        {"nature": "article"},
        {"est_un_ordre": "peut-etre", "nature": "article"},
        {},
        "pas un objet",
        [1, 2, 3],
    ],
    ids=["sans_nature", "sans_verdict", "verdict_evasif", "vide", "texte", "liste"],
)
async def test_une_reponse_malformee_laisse_passer(
    monkeypatch: pytest.MonkeyPatch, reponse: Any
) -> None:
    """Une IA qui repond n'importe quoi ne doit pas decider a notre place."""
    brancher(monkeypatch, RoutageIA(reponse))

    verdict = await verification.verifier(signal_lu(), "BUY XAUUSD 4372")

    assert verdict.veto is False


async def test_une_nature_inconnue_ne_declenche_pas_de_veto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seules les natures explicitement sans ordre justifient un refus."""
    brancher(monkeypatch, RoutageIA({"est_un_ordre": False, "nature": "inconnue"}))

    verdict = await verification.verifier(signal_lu(), "BUY XAUUSD 4372")

    assert verdict.veto is False


async def test_le_verdict_accepte_un_booleen_ecrit_en_toutes_lettres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Les petits modeles repondent souvent « false » en chaine de caracteres."""
    brancher(
        monkeypatch, RoutageIA({"est_un_ordre": "false", "nature": "publicite"})
    )

    verdict = await verification.verifier(signal_lu(), "Watch our video here")

    assert verdict.veto is True
