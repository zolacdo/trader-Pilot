"""Second avis d'une IA sur « ce message est-il vraiment un ordre ? ».

Le parser deterministe est litteral : il voit un sens, un instrument et des
nombres, et il conclut. Cela lui a fait lire comme des ordres un bilan de
journee, un article de presse sur Bitcoin, et un cours intitule « HOW I LAYER
MY ENTRIES ». Chaque fois, un garde-fou de hasard l'a arrete -- la confiance
trop basse, l'absence de stop loss -- jamais une regle.

Ce module ajoute la regle manquante. Une IA relit le message et dit s'il
demande vraiment d'executer quelque chose maintenant.

LE POINT ESSENTIEL : cette verification n'a qu'un DROIT DE VETO. Elle peut
transformer un signal en non-signal, jamais l'inverse. Une IA ne peut donc pas
faire naitre un ordre que le parser deterministe n'avait pas vu, ce qui
respecte la regle du cahier des charges selon laquelle aucune sortie d'IA ne
contourne les controles locaux.

En cas de panne ou de doute de l'IA, on garde la lecture deterministe : un
verificateur indisponible ne doit jamais bloquer le trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config.logging_config import get_logger
from app.models.intelligence import AITaskKind
from app.services.ai.base import MIN_JSON_MAX_TOKENS
from app.services.ai.service import ai_service
from app.services.signals.models import ParsedSignal

logger = get_logger(__name__)

SYSTEM_PROMPT = (
    "Tu verifies des messages de canaux Telegram de trading. Ta seule tache est "
    "de dire si le message demande d'EXECUTER une operation MAINTENANT. "
    "Tu ne juges ni la qualite ni la rentabilite du trade. Reponds en JSON strict."
)

INSTRUCTION = """Reponds UNIQUEMENT avec cet objet JSON :

{"est_un_ordre": true/false, "nature": "...", "raison": "..."}

"nature" doit valoir exactement l'une de ces valeurs :
  ordre        : demande d'ouvrir une position maintenant (avec ou sans prix)
  suivi        : gestion d'une position existante (deplacer le stop, cloturer)
  recapitulatif: liste de trades deja passes, bilan, tableau de resultats
  article      : actualite, analyse de marche, commentaire
  publicite    : promotion, recrutement, lien, offre d'abonnement
  cours        : explication pedagogique, methode, conseil general
  autre        : rien de ce qui precede

Mets "est_un_ordre" a true UNIQUEMENT pour "ordre" et "suivi".

Attention aux pieges observes :
  - un bilan qui enumere « 12:05 EUR/USD Sell, 12:20 AUD/CHF Buy » n'est PAS un ordre ;
  - un article qui dit « analysts expect bitcoin to sell off » n'est PAS un ordre ;
  - un cours qui dit « quand je dis GOLD BUY NOW, cela signifie... » n'est PAS un ordre.

Message a examiner :
"""

NATURES_SANS_ORDRE = {"recapitulatif", "article", "publicite", "cours"}


@dataclass(frozen=True, slots=True)
class Verdict:
    """Ce que l'IA a repondu, et ce qu'on en fait."""

    veto: bool
    nature: str | None = None
    raison: str | None = None
    disponible: bool = True

    @property
    def detail(self) -> str:
        if not self.disponible:
            return "verificateur indisponible"
        if self.veto:
            return f"{self.nature or 'non-ordre'} : {self.raison or 'aucun ordre a executer'}"
        return "ordre confirme"


_AFFIRMATIONS = {"true", "oui", "yes", "1"}
_NEGATIONS = {"false", "non", "no", "0"}


def _lire(payload: Any) -> tuple[bool | None, str | None, str | None]:
    """Extrait le verdict, sans jamais faire confiance a la forme recue."""
    if not isinstance(payload, dict):
        return None, None, None
    brut = payload.get("est_un_ordre")
    if isinstance(brut, str):
        # Une reponse evasive n'est PAS un refus. Convertir « peut-etre » en
        # False transformerait une hesitation du modele en veto ferme.
        mot = brut.strip().lower()
        brut = True if mot in _AFFIRMATIONS else False if mot in _NEGATIONS else None
    if not isinstance(brut, bool):
        brut = None
    nature = payload.get("nature")
    nature = nature.strip().lower() if isinstance(nature, str) else None
    raison = payload.get("raison")
    raison = raison.strip()[:200] if isinstance(raison, str) else None
    return brut, nature, raison


async def verifier(signal: ParsedSignal, text: str) -> Verdict:
    """Demande un second avis. Ne renvoie un veto que sur un refus explicite.

    Le veto exige DEUX conditions concordantes : l'IA repond ``false`` ET elle
    nomme une nature qui exclut l'execution. Une reponse incomplete, evasive ou
    malformee laisse passer la lecture deterministe.
    """
    if not signal.is_signal:
        # Rien a vetoer : cette verification ne cree jamais de signal.
        return Verdict(veto=False)

    try:
        routed = await ai_service.complete_json(
            f"{INSTRUCTION}{text[:2000]}",
            system=SYSTEM_PROMPT,
            task=AITaskKind.SIGNAL_PARSE,
            max_tokens=MIN_JSON_MAX_TOKENS,
        )
    except Exception as exc:
        logger.info("Verification IA impossible : %s", type(exc).__name__)
        return Verdict(veto=False, disponible=False)

    if routed is None or routed.response.payload is None:
        return Verdict(veto=False, disponible=False)

    est_un_ordre, nature, raison = _lire(routed.response.payload)
    if est_un_ordre is None or nature is None:
        logger.info("Verification IA illisible : reponse ignoree")
        return Verdict(veto=False, disponible=False)

    if est_un_ordre is False and nature in NATURES_SANS_ORDRE:
        return Verdict(veto=True, nature=nature, raison=raison)

    return Verdict(veto=False, nature=nature, raison=raison)
