"""Parser deterministe de signaux de trading.

Analyse ligne par ligne, car les canaux de signaux ecrivent presque toujours
un element par ligne. Priorite absolue sur l'IA : rapide, predictible,
testable, et il ne consomme aucun quota OpenRouter (CDC sections 16 et 20).

Regle fondamentale : ce qui n'est pas ecrit dans le message reste ``None``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.models.enums import Direction, OrderType, ParserSource
from app.services.signals.models import ParsedSignal
from app.services.signals.normalizer import (
    looks_like_noise,
    normalize_upper,
    structure_fingerprint,
)
from app.services.signals.symbols import canonical_symbol, extract_symbol

NUMBER = r"\d+(?:\.\d+)?"
_NUMBER_RE = re.compile(NUMBER)

# --- direction et type d'ordre ---
# Les canaux francophones ecrivent « ACHAT » et « VENTE ». Sans ces formes, le
# message etait lu jusqu'au bout puis ecarte pour « direction absente » : le
# meme angle mort que l'etiquette « Entree », corrigee le 12/09/2026.
_SENS = r"BUY|SELL|LONG|SHORT|ACHAT|ACHETER|VENTE|VENDRE"
_ORDER_RE = re.compile(
    rf"\b({_SENS})\b"
    r"(?:\s*(STOP\s*LIMIT|LIMIT|STOP(?!\s*LOSS)))?"
)
_REVERSE_ORDER_RE = re.compile(rf"\b(STOP\s*LIMIT|LIMIT|STOP)\s+({_SENS})\b")
_MARKET_HINTS = ("NOW", "MARKET", "INSTANT", "CMP", "ASAP", "RUNNING", "OPEN NOW")

_DIRECTION_MAP = {
    "BUY": Direction.BUY,
    "LONG": Direction.BUY,
    "ACHAT": Direction.BUY,
    "ACHETER": Direction.BUY,
    "SELL": Direction.SELL,
    "SHORT": Direction.SELL,
    "VENTE": Direction.SELL,
    "VENDRE": Direction.SELL,
}

_ORDER_TYPE_MAP: dict[tuple[Direction, str], OrderType] = {
    (Direction.BUY, "LIMIT"): OrderType.BUY_LIMIT,
    (Direction.SELL, "LIMIT"): OrderType.SELL_LIMIT,
    (Direction.BUY, "STOP"): OrderType.BUY_STOP,
    (Direction.SELL, "STOP"): OrderType.SELL_STOP,
    (Direction.BUY, "STOPLIMIT"): OrderType.BUY_STOP_LIMIT,
    (Direction.SELL, "STOPLIMIT"): OrderType.SELL_STOP_LIMIT,
}

# --- etiquettes ---
_SL_LABEL = re.compile(r"\b(?:SL|S/L|STOP\s?LOSS|STOPLOSS|STOPP?|CUT\s?LOSS)\b")
# Le numero d'objectif ("TP1") ne doit jamais avaler la partie entiere d'un
# prix decimal : dans "TP 1.0840", le "1" appartient au prix, pas a l'index.
_TP_LABEL = re.compile(
    r"\b(?:TP|T/P|TAKE\s?PROFITS?|TARGETS?|TGTS?|OBJECTIFS?)\s*(\d{1,2}(?![.,]?\d))?\b"
)
# Etiquettes qui donnent VRAIMENT le prix d'entree, par opposition a « ZONE »
# ou « AROUND » qui decrivent un contexte. Une ligne explicite prime donc sur
# une zone lue plus haut dans le message.
#
# Les formes francaises figurent avec ET sans accent : le normaliseur met en
# majuscules mais conserve les accents, donc « Entrée » devient « ENTRÉE ».
# Sans elles, un signal redige en francais perdait son prix d'entree alors que
# son stop et ses objectifs etaient parfaitement lus -- « Stop loss » et
# « TP » sont identiques dans les deux langues, « Entry » ne l'est pas.
_EXPLICIT_ENTRY_RE = re.compile(
    r"\b(?:ENTRY|ENTRIES|ENTER|OPEN|ENTREES?|ENTRÉES?)\b"
)

_ENTRY_LABEL = re.compile(
    r"\b(?:"
    r"ENTRY(?:\s*(?:PRICE|POINT|ZONE))?|ENTRIES|ENTER|OPEN|PRICE|ZONE|AROUND|@"
    r"|ENTREES?|ENTRÉES?|PRIX\s+D[’']\s*ENTREE|PRIX\s+D[’']\s*ENTRÉE"
    r")\b"
)
# Separateurs de zone d'entree rencontres chez les canaux : « 4640-4635 »,
# « 4640_4635 », « 4307//4304 », « 4640 ~ 4635 », « 4640..4635 ». Un seul
# caractere etait accepte, ce qui faisait perdre la seconde borne des formats
# a souligne ou a double barre.
#
# Le POINT en est volontairement exclu : c'est un separateur decimal. L'avoir
# inclus faisait lire \u00ab Entry: 154.387 \u00bb comme une zone allant de 154 a 387,
# et \u00ab 1.38104 \u00bb comme une zone de 1 a 38104.
_RANGE_SEPARATOR = r"[-\u2013\u2014_/\\|~]{1,2}"
_RANGE_RE = re.compile(rf"({NUMBER})\s*{_RANGE_SEPARATOR}\s*({NUMBER})")

# Marque laissee a la place des mots-cles de type d'ordre pour ne pas les
# confondre avec un stop loss.
_ORDER_PLACEHOLDER = "\x00ORDER\x00"


@dataclass(slots=True)
class _Extraction:
    stop_loss: float | None = None
    take_profits: list[float] = field(default_factory=list)
    entry_price: float | None = None
    entry_min: float | None = None
    entry_max: float | None = None
    warnings: list[str] = field(default_factory=list)


# Horaires « 12:05 », « 9h30 » : ce sont des heures, jamais des prix. Le
# masque s'applique sur le texte D'ORIGINE, car la normalisation remplace le
# deux-points par une espace et « 12:05 » devient alors deux nombres.
_TIME_RE = re.compile(r"\b\d{1,2}\s*[:Hh]\s*[0-5]\d\b")

# Annotations de rendement/risque : « (1:1.0) », « (1 : 2) », « R:R 1:3 ».
#
# Les deux formes sont volontairement etroites. Une regle generale « nombre
# deux-points nombre » avalerait « TP1 : 1.15396 », c'est-a-dire l'objectif
# lui-meme : la parenthese et le marqueur R:R sont ce qui distingue une
# notation de ratio d'un simple separateur.
_RATIO_RE = re.compile(
    r"\(\s*\d+(?:[.,]\d+)?\s*:\s*\d+(?:[.,]\d+)?\s*\)"
    r"|\bR\s*[:/]?\s*R\b\s*[:=]?\s*\d+(?:[.,]\d+)?\s*:\s*\d+(?:[.,]\d+)?"
)

# Au-dela de ce nombre de mots, un message sans stop ni objectif n'est plus un
# ordre : c'est un article ou une publication pedagogique. Un vrai signal, meme
# reduit a « BUY GOLD NOW », tient en quelques mots.
_PROSE_WORD_LIMIT = 60


def _mask_times(text: str) -> str:
    """Efface horaires et ratios avant toute lecture de prix.

    Sans cela, « 12:05 - EUR/USD - Sell » donnait une entree a 12,0 sur une
    paire qui cote 1,16.

    Meme raison pour les ratios : « TP1 : 1.15396  (1:1.0) » livrait
    ``[1.0, 2.0, 3.0, 1.15396, ...]``. Le filtre d'ordre de grandeur
    (``_plausible``) ne pouvait rien voir -- sur une paire a 1,155, les
    nombres 1, 2 et 3 sont exactement du bon ordre de grandeur. Le premier
    objectif retenu tombait donc a 1,0, soit 1355 pips hors d'atteinte.
    """
    return _RATIO_RE.sub(" ", _TIME_RE.sub(" ", text))


def _numbers_in(text: str) -> list[float]:
    return [float(value) for value in _NUMBER_RE.findall(text)]


def _plausible(value: float, reference: float | None) -> bool:
    """Ecarte les faux positifs du type "TARGET 1" interprete comme prix 1.0."""
    if value <= 0:
        return False
    if reference is None or reference <= 0:
        return True
    ratio = value / reference
    return 0.3 <= ratio <= 3.0


# Formulations qui SUBORDONNENT l'ordre a une cassure encore a venir.
#
# La distinction est tout le sujet : « SI cassure confirmee » pose une
# condition, « Breakout confirme » constate un fait deja survenu. Un message
# reel du 12/09/2026 portait « Breakout confirme » dans sa section d'analyse
# technique, et une premiere version de cette expression -- qui acceptait le
# mot BREAKOUT seul -- en faisait un ordre en attente a 77 205 alors que le
# marche cotait 77 290 : un stop d'achat SOUS le marche, incoherent.
#
# On exige donc un mot subordonnant (si, sur, apres, des, on, upon, if, once).
# Sans lui, le message decrit, il n'ordonne pas.
#
# Le sens de l'erreur a ete choisi : manquer une condition fait partir un
# ordre au marche, que le RiskManager verifiera ; inventer une condition pose
# un ordre qui ne se declenchera jamais. Aucun des deux n'est bon, mais seul
# le premier engage de l'argent sans qu'on l'ait demande.
_BREAKOUT_RE = re.compile(
    r"(?:"
    # Subordination explicite en francais : « si », « sur », « apres », « des ».
    r"SI\s+(?:LA\s+|LE\s+)?(?:CASSURE|CASSE|FRANCHI|CLOTURE|COURS|PRIX|BTC|BITCOIN)"
    r"|(?:SUR|APRES|DES)\s+(?:LA\s+)?CASSURE"
    r"|(?:SUR|APRES)\s+(?:LE\s+)?FRANCHISSEMENT"
    # Subordination explicite en anglais.
    r"|ON\s+(?:A\s+)?BREAK|UPON\s+BREAK|IF\s+(?:IT\s+)?BROKE[NS]?"
    r"|IF\s+(?:IT\s+)?(?:BREAK|CLOSE)[SD]?|ONCE\s+(?:IT\s+)?(?:BREAK|CLOSE)[SD]?"
    r")"
)


# Marqueurs propres aux options binaires. Aucun n'existe dans un signal CFD.
#
# Message reellement recu le 13/09/2026 sur le canal « Forex Signals Trading » :
#
#     SIGNAL
#     EUR/GBP  OTC
#     Timeframe: M5
#     Expiration: 5 minutes
#     Entry: 09:50
#     Direction: BUY
#     Martingale: 09:55 / 10:00 / 10:05
#
# Une option binaire n'a ni prix d'entree, ni stop, ni objectif : on parie sur
# un sens pendant cinq minutes. « Entry » y designe une HEURE. Le systeme, lui,
# passe des ordres CFD sur MetaTrader -- il n'y a rien a executer ici.
#
# Ces messages etaient refuses par hasard, sur le plancher de confiance (0.50
# contre 0.75 exige). Le jour ou l'un d'eux serait lu avec plus d'assurance, il
# atteindrait l'execution avec une entree nulle : le RiskManager se rabattrait
# sur le prix du marche et ouvrirait une position SANS STOP. D'ou ce refus par
# nature, qui ne depend d'aucun seuil.
_MARTINGALE_RE = re.compile(r"\bMARTINGALES?\b")
# « OTC » designe les paires synthetiques des courtiers d'options binaires :
# elles cotent le week-end, quand le vrai marche est ferme.
_OTC_RE = re.compile(r"(?<![A-Z0-9])OTC(?![A-Z0-9])")
# Une expiration chiffree en minutes est la duree de vie de l'option.
_EXPIRATION_RE = re.compile(r"\bEXPIR\w*\s*:?\s*\d+\s*(?:MIN|MINUTE|M\b)")


def _is_binary_option(text: str) -> bool:
    """Le message decrit-il une option binaire plutot qu'un ordre CFD ?

    Un seul marqueur suffit : ils ne se rencontrent pas ailleurs, et se tromper
    dans ce sens ne coute qu'un signal ecarte, alors que l'inverse ouvre une
    position sans protection.
    """
    majuscules = _sans_accents(text).upper()
    return bool(
        _MARTINGALE_RE.search(majuscules)
        or _OTC_RE.search(majuscules)
        or _EXPIRATION_RE.search(majuscules)
    )


def _sans_accents(text: str) -> str:
    """Replie les accents avant comparaison.

    Le normaliseur met en majuscules mais garde les accents : « Apres » reste
    accentue, « confirmee » aussi. Enumerer chaque variante dans l'expression
    serait interminable et se casserait au premier canal qui ecrit autrement.
    """
    decompose = unicodedata.normalize("NFD", text)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


#  Puces, fleches et ponctuation qui decorent un debut de ligne sans en
#  changer la nature.
_DECORATIONS = " \t-*•●▪➡>#.:"


def _is_conditional_breakout(text: str) -> bool:
    """Le message subordonne-t-il l'ordre a une cassure de niveau ?

    La marque doit OUVRIR une ligne. Une condition introduit l'ordre -- « Si
    cassure confirmee : » suivi du BUY -- tandis qu'une description l'evoque au
    fil d'une phrase : « Higher Low detecte apres cassure de la moyenne ».
    Sans cet ancrage, cette seconde tournure posait un ordre en attente.
    """
    return any(
        _BREAKOUT_RE.match(ligne.lstrip(_DECORATIONS))
        for ligne in _sans_accents(text).splitlines()
    )


def _detect_order(text: str) -> tuple[Direction | None, str | None, tuple[int, int] | None]:
    """Retourne (direction, modificateur, span du mot-cle)."""
    match = _ORDER_RE.search(text)
    if match:
        direction = _DIRECTION_MAP.get(match.group(1))
        modifier = match.group(2)
        return direction, _clean_modifier(modifier), match.span()
    match = _REVERSE_ORDER_RE.search(text)
    if match:
        direction = _DIRECTION_MAP.get(match.group(2))
        return direction, _clean_modifier(match.group(1)), match.span()
    return None, None, None


def _clean_modifier(modifier: str | None) -> str | None:
    if not modifier:
        return None
    compact = re.sub(r"\s+", "", modifier)
    if compact == "STOPLIMIT":
        return "STOPLIMIT"
    if compact in {"LIMIT", "STOP"}:
        return compact
    return None


def _mask_order_keywords(text: str) -> str:
    """Neutralise "BUY STOP"/"SELL LIMIT" pour ne pas les lire comme un SL."""
    masked = _ORDER_RE.sub(lambda m: _ORDER_PLACEHOLDER if m.group(2) else m.group(0), text)
    masked = _REVERSE_ORDER_RE.sub(_ORDER_PLACEHOLDER, masked)
    return masked


def _split_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        # Une ligne peut contenir plusieurs elements separes par | ou ;
        for part in re.split(r"[|;]", raw_line):
            cleaned = part.strip()
            if cleaned:
                lines.append(cleaned)
    return lines


def _next_line_numbers(lines: list[str], index: int) -> list[float]:
    """Valeurs de la ligne suivante lorsqu'elle ne contient que des nombres."""
    if index + 1 >= len(lines):
        return []
    candidate = lines[index + 1]
    if re.fullmatch(rf"[\s,\-/]*{NUMBER}(?:\s*[,/]\s*{NUMBER})*[\s,\-/]*", candidate):
        return _numbers_in(candidate)
    return []


def _extract_values(lines: list[str], reference_hint: float | None) -> _Extraction:
    """Parcourt les lignes et affecte chaque nombre a son etiquette."""
    result = _Extraction()
    tp_by_index: dict[int, float] = {}
    tp_sequence: list[float] = []
    consumed_lines: set[int] = set()

    for index, raw_line in enumerate(lines):
        line = _mask_order_keywords(raw_line)

        # --- stop loss ---
        sl_match = _SL_LABEL.search(line)
        if sl_match and result.stop_loss is None:
            tail = line[sl_match.end():]
            values = _numbers_in(tail) or _next_line_numbers(lines, index)
            if values:
                result.stop_loss = values[0]
                consumed_lines.add(index)
                continue

        # --- take profits ---
        tp_match = _TP_LABEL.search(line)
        if tp_match:
            tail = line[tp_match.end():]
            values = _numbers_in(tail)
            if not values:
                values = _next_line_numbers(lines, index)
            if values:
                explicit_index = tp_match.group(1)
                if explicit_index and len(values) == 1:
                    tp_by_index[int(explicit_index)] = values[0]
                else:
                    tp_sequence.extend(values)
                consumed_lines.add(index)
                continue

        # --- entree ---
        # « Zone cle : 77335 - 77345 » puis « Entry 77345 » : les deux portent
        # l'etiquette ZONE, mais seule la seconde donne l'ordre. Le premier
        # rencontre gagnait, et c'etait le contexte, pas l'instruction.
        entry_match = _ENTRY_LABEL.search(line)
        explicite = _EXPLICIT_ENTRY_RE.search(line) is not None
        deja_lue = result.entry_price is not None or result.entry_min is not None
        if entry_match and (not deja_lue or (explicite and result.entry_price is None)):
            tail = line[entry_match.end():]
            range_match = _RANGE_RE.search(tail)
            if range_match:
                low, high = sorted((float(range_match.group(1)), float(range_match.group(2))))
                result.entry_min, result.entry_max = low, high
                consumed_lines.add(index)
                continue
            values = _numbers_in(tail) or _next_line_numbers(lines, index)
            if len(values) >= 2 and _plausible(values[1], values[0]):
                low, high = sorted((values[0], values[1]))
                result.entry_min, result.entry_max = low, high
            elif values:
                result.entry_price = values[0]
            if values:
                consumed_lines.add(index)

    # TP indexes explicites puis sequence libre
    ordered = [tp_by_index[key] for key in sorted(tp_by_index)]
    for value in tp_sequence:
        if value not in ordered:
            ordered.append(value)
    reference = result.entry_price or result.entry_min or reference_hint or result.stop_loss
    result.take_profits = [value for value in ordered if _plausible(value, reference)]
    if len(result.take_profits) != len(ordered):
        result.warnings.append("take_profit_implausible_ignored")

    if result.stop_loss is not None and not _plausible(result.stop_loss, reference):
        result.warnings.append("stop_loss_implausible_ignored")
        result.stop_loss = None

    return result


def _extract_inline_entry(
    lines: list[str],
    direction_line_index: int | None,
    extraction: _Extraction,
    symbol_raw: str | None = None,
) -> None:
    """Format compact "SELL GOLD 3350" ou "BUY GOLD 3350-3345"."""
    if extraction.entry_price is not None or extraction.entry_min is not None:
        return
    if direction_line_index is None:
        return
    line = _mask_order_keywords(lines[direction_line_index])
    # Les chiffres du nom de l'instrument (US30, NAS100, GER40) ne sont pas des prix.
    if symbol_raw:
        line = line.replace(symbol_raw.upper(), " ")
    if _SL_LABEL.search(line) or _TP_LABEL.search(line):
        return
    range_match = _RANGE_RE.search(line)
    if range_match:
        low, high = sorted((float(range_match.group(1)), float(range_match.group(2))))
        extraction.entry_min, extraction.entry_max = low, high
        return
    values = _numbers_in(line)
    if values:
        extraction.entry_price = values[0]


def _compute_confidence(signal: ParsedSignal) -> float:
    score = 0.0
    if signal.direction is not None and signal.symbol is not None:
        score += 0.50
    if signal.has_entry:
        score += 0.15
    if signal.stop_loss is not None:
        score += 0.20
    if signal.take_profits:
        score += 0.15
    score -= 0.05 * len(signal.warnings)
    return max(0.0, min(1.0, round(score, 3)))


def parse(text: str, extra_aliases: dict[str, str] | None = None) -> ParsedSignal:
    """Analyse un message et retourne un ``ParsedSignal``.

    ``is_signal`` reste False lorsque le message ne contient pas une intention
    de trade explicite (direction + instrument).
    """
    signal = ParsedSignal(source=ParserSource.DETERMINISTIC)
    if not text or not text.strip():
        return signal

    normalized = normalize_upper(_mask_times(text))
    signal.format_signature = structure_fingerprint(text)

    if looks_like_noise(normalized):
        signal.add_warning("message_sans_intention_de_trade")
        return signal

    # Le texte BRUT est examine : le normaliseur efface la ponctuation qui
    # porte justement les marqueurs (« Expiration: 5 minutes »).
    if _is_binary_option(text):
        signal.add_warning("option_binaire_non_executable")
        return signal

    lines = _split_lines(normalized)
    if not lines:
        return signal

    # 1) direction et type d'ordre
    direction: Direction | None = None
    modifier: str | None = None
    direction_line_index: int | None = None
    directions_vues: set[Direction] = set()
    for index, line in enumerate(lines):
        found_direction, found_modifier, _ = _detect_order(line)
        if found_direction is None:
            continue
        directions_vues.add(found_direction)
        if direction is None:
            direction, modifier = found_direction, found_modifier
            direction_line_index = index

    # Un message qui enumere des ordres de sens OPPOSES est un bilan de
    # journee ou une liste de resultats, pas un ordre a executer. Retenir le
    # premier reviendrait a trader un trade deja passe.
    if len(directions_vues) > 1:
        signal.add_warning("recapitulatif_plusieurs_directions")
        return signal

    # Une cassure annoncee sans type d'ordre explicite reste un ordre en
    # attente : entrer au marche executerait un trade que personne n'a demande.
    conditionnel = direction is not None and modifier is None and _is_conditional_breakout(
        normalized
    )
    if conditionnel:
        modifier = "STOP"

    # 2) instrument
    symbol_raw, symbol = extract_symbol(normalized, extra_aliases)
    if symbol is None and direction_line_index is not None:
        symbol_raw, symbol = extract_symbol(lines[direction_line_index], extra_aliases)

    signal.direction = direction
    signal.symbol_raw = symbol_raw
    signal.symbol = symbol

    if direction is None or symbol is None:
        if direction is not None and symbol is None:
            signal.add_warning("instrument_absent")
        if symbol is not None and direction is None:
            signal.add_warning("direction_absente")
        return signal

    # 3) valeurs numeriques
    extraction = _extract_values(lines, reference_hint=None)
    _extract_inline_entry(lines, direction_line_index, extraction, symbol_raw)

    signal.entry_price = extraction.entry_price
    signal.entry_min = extraction.entry_min
    signal.entry_max = extraction.entry_max
    signal.stop_loss = extraction.stop_loss
    signal.take_profits = extraction.take_profits
    for warning in extraction.warnings:
        signal.add_warning(warning)

    # 4) type d'ordre
    if modifier:
        signal.order_type = _ORDER_TYPE_MAP.get((direction, modifier))
    elif any(hint in normalized for hint in _MARKET_HINTS) or not signal.has_entry:
        signal.order_type = OrderType.MARKET
    else:
        # Prix fourni sans mot-cle : le planificateur d'execution tranchera en
        # comparant au cours reel (market si proche, sinon limit/stop).
        signal.order_type = None
        signal.add_warning("type_ordre_non_precise")

    # Un texte long qui ne porte ni stop ni objectif est un commentaire, pas un
    # ordre. Constate en production : un article sur Bitcoin est devenu
    # « BTCUSD SELL », et un message intitule « HOW I LAYER MY ENTRIES » est
    # devenu « XAUUSD BUY a 60,0 ». Seule l'exigence de stop loss les arretait,
    # par chance et non par regle.
    if (
        signal.stop_loss is None
        and not signal.take_profits
        and len(text.split()) > _PROSE_WORD_LIMIT
    ):
        signal.add_warning("texte_explicatif_sans_ordre")
        return signal

    signal.is_signal = True
    signal.confidence = _compute_confidence(signal)
    return signal


def parse_symbol_only(text: str, extra_aliases: dict[str, str] | None = None) -> str | None:
    """Utilitaire : instrument mentionne dans un message de suivi."""
    _, symbol = extract_symbol(normalize_upper(text), extra_aliases)
    if symbol is None:
        return canonical_symbol(text, extra_aliases)
    return symbol
