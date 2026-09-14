"""Regroupement des actualites identiques (CDC2 sections 31 et 32).

La meme information peut etre reprise par vingt medias. Elle ne doit pas
apparaitre vingt fois : elle apparait une fois, et les dix-neuf reprises
deviennent des confirmations, ce qui fait monter le statut de verification.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.models.intelligence import NewsEvent, VerificationStatus
from app.services.news.taxonomy import normalize

# Mots trop frequents pour distinguer deux titres.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "of", "in", "on", "for", "to", "and", "or", "at", "by",
        "with", "from", "as", "is", "are", "was", "were", "be", "been", "it",
        "its", "that", "this", "after", "over", "amid", "says", "said", "new",
        "le", "la", "les", "des", "du", "de", "un", "une", "et", "en", "au",
        "aux", "pour", "sur", "dans", "par", "avec", "plus", "selon", "apres",
    }
)

# Au-dela de ce seuil, deux titres racontent la meme chose.
DEFAULT_THRESHOLD = 0.72

# Nombre de sources independantes exige pour chaque statut (CDC2 section 32).
PARTIAL_CONFIRMATION_SOURCES = 2
FULL_CONFIRMATION_SOURCES = 3


def significant_tokens(title: str) -> frozenset[str]:
    """Mots porteurs de sens d'un titre, une fois normalise.

    Les mots courts porteurs d'information sont conserves : un chiffre et un
    sigle de pays distinguent souvent deux faits differents. Ecarter tout ce
    qui fait deux lettres ou moins donnait la meme empreinte a
    « Fed raises rates by 25 bp » et « Fed raises rates by 50 bp », qui
    etaient alors regroupes comme un doublon.
    """
    words = normalize(title).split()
    kept = [
        word
        for word in words
        if word not in STOPWORDS and (len(word) > 2 or any(c.isdigit() for c in word))
    ]
    return frozenset(kept or words)


def title_fingerprint(title: str) -> str:
    """Empreinte stable d'un titre : meme information, meme empreinte.

    Les mots significatifs sont tries : l'ordre des mots, la ponctuation et
    les accents ne changent plus rien.
    """
    tokens = sorted(significant_tokens(title))
    payload = " ".join(tokens) if tokens else normalize(title)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def raw_hash(source_key: str, title: str, url: str | None) -> str:
    """Identite d'une depeche precise, pour ne pas la collecter deux fois.

    Deux articles du meme flux portant le meme titre et la meme adresse sont
    la meme depeche. Le champ est unique en base.
    """
    parts = [source_key.strip().lower(), (url or "").strip().lower(), normalize(title)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def similarity(left: str, right: str) -> float:
    """Similarite de Sorensen-Dice entre deux titres, entre 0.0 et 1.0.

    Dice plutot que Jaccard : deux redactions de la meme depeche different
    surtout par des mots ajoutes d'un cote (« Federal Reserve » contre
    « Fed », une incise en fin de titre). Jaccard punit ces ajouts deux fois,
    Dice une seule, ce qui colle mieux a la reprise mediatique.
    """
    tokens_left = significant_tokens(left)
    tokens_right = significant_tokens(right)
    total = len(tokens_left) + len(tokens_right)
    if not total:
        return 0.0
    return 2 * len(tokens_left & tokens_right) / total


@dataclass(slots=True)
class DuplicateMatch:
    """Actualite deja connue que la nouvelle depeche vient confirmer."""

    original: NewsEvent
    score: float
    reason: str


class NewsDeduplicator:
    """Regroupe les reprises d'une meme information."""

    def __init__(self, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold

    def find_duplicate(
        self, title: str, candidates: list[NewsEvent], *, url: str | None = None
    ) -> DuplicateMatch | None:
        """Cherche l'actualite deja enregistree que ce titre reprend.

        Deux chemins : l'adresse exacte (reprise a l'identique) puis la
        similarite des titres. Retourne ``None`` si rien ne correspond.
        """
        normalized_url = (url or "").strip().lower()
        fingerprint = title_fingerprint(title)

        best: DuplicateMatch | None = None
        for candidate in candidates:
            if candidate.id is None:
                continue
            original = self._root_of(candidate, candidates)
            if normalized_url and (candidate.url or "").strip().lower() == normalized_url:
                return DuplicateMatch(original, 1.0, "adresse identique")
            if title_fingerprint(candidate.title) == fingerprint:
                return DuplicateMatch(original, 1.0, "titre identique apres normalisation")
            score = similarity(title, candidate.title)
            if score >= self.threshold and (best is None or score > best.score):
                best = DuplicateMatch(original, score, f"titres similaires a {score:.0%}")
        return best

    @staticmethod
    def _root_of(event: NewsEvent, pool: list[NewsEvent]) -> NewsEvent:
        """Remonte au representant du groupe : on ne chaine pas les doublons."""
        if event.duplicate_of is None:
            return event
        for candidate in pool:
            if candidate.id == event.duplicate_of:
                return candidate
        return event


def verification_for(sources: set[str], *, official_sources: set[str] | None = None) -> VerificationStatus:
    """Statut de verification selon les sources independantes (CDC2 section 32).

    Une source primaire (banque centrale, institut statistique, regulateur)
    qui publie elle-meme l'information vaut deja une confirmation partielle :
    elle est l'emetteur, pas un relais. Il faut malgre tout un second point de
    vue pour atteindre CONFIRMED.
    """
    official = official_sources or set()
    count = len(sources)
    if count >= FULL_CONFIRMATION_SOURCES:
        return VerificationStatus.CONFIRMED
    if count >= PARTIAL_CONFIRMATION_SOURCES:
        return VerificationStatus.CONFIRMED if official else VerificationStatus.PARTIALLY_CONFIRMED
    if official:
        return VerificationStatus.PARTIALLY_CONFIRMED
    return VerificationStatus.UNCONFIRMED


__all__ = [
    "DEFAULT_THRESHOLD",
    "FULL_CONFIRMATION_SOURCES",
    "PARTIAL_CONFIRMATION_SOURCES",
    "STOPWORDS",
    "DuplicateMatch",
    "NewsDeduplicator",
    "raw_hash",
    "significant_tokens",
    "similarity",
    "title_fingerprint",
    "verification_for",
]
