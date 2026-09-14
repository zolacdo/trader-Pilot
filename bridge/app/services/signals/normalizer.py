"""Normalisation d'un message Telegram avant analyse.

Objectif : rendre comparables des messages ecrits avec des emojis, des
majuscules aleatoires, des separateurs exotiques ou des chiffres formates
differemment, sans jamais alterer les valeurs numeriques.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Caracteres decoratifs frequents dans les canaux de signaux.
_DECORATIONS = "•·▪◾◽▫◆◇★☆✅✔️❌⚡🔥💰💵📈📉📊🚀🎯🛑⛔️🟢🔴🔵⭕️➡️⬆️⬇️👇👆‼️❗️❕💎🏆🤑💸🔔"

_ZERO_WIDTH = re.compile(r"[​-‏‪-‮﻿]")
_MULTISPACE = re.compile(r"[ \t ]+")
_MULTINEWLINE = re.compile(r"\n{3,}")
_EMOJI = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f1e6-\U0001f1ff" "\U0000fe00-\U0000fe0f" "]",
    flags=re.UNICODE,
)

# Separateurs textuels autour des valeurs : "SL @ 3300", "TP: 3350", "SL - 3300"
# Les fleches passent AVANT la classe de caracteres : sinon "=>" serait coupe
# par le "=" seul et laisserait un ">" parasite dans le texte normalise.
_LABEL_SEPARATORS = re.compile(r"\s*(?:->|=>|[:=@])\s*")

# Espaces parasites dans les nombres : "3 320.50" -> "3320.50".
# Le groupe de tete ne doit pas suivre une lettre, sinon "TP1 194.800"
# serait recolle en "TP1194.800".
_SPACED_NUMBER = re.compile(r"(?<![A-Za-z0-9])(\d{1,3})[   ](\d{3})(?!\d)")

# Virgule decimale europeenne : "3320,50" -> "3320.50" (mais pas "3320,3310")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d{1,2}\b)")

# Separateur de milliers : "3,320.50" -> "3320.50"
_THOUSAND_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")


def strip_emojis(text: str) -> str:
    cleaned = _EMOJI.sub(" ", text)
    for char in _DECORATIONS:
        cleaned = cleaned.replace(char, " ")
    return cleaned


def normalize_numbers(text: str) -> str:
    """Uniformise l'ecriture des nombres sans changer leur valeur."""
    cleaned = _SPACED_NUMBER.sub(lambda m: m.group(1) + m.group(2), text)
    cleaned = _THOUSAND_COMMA.sub("", cleaned)
    cleaned = _DECIMAL_COMMA.sub(".", cleaned)
    return cleaned


def normalize(text: str) -> str:
    """Version normalisee utilisee par le parser deterministe."""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = _ZERO_WIDTH.sub("", cleaned)
    cleaned = cleaned.replace("–", "-").replace("—", "-").replace("−", "-")
    cleaned = strip_emojis(cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _LABEL_SEPARATORS.sub(" ", cleaned)
    cleaned = normalize_numbers(cleaned)
    cleaned = _MULTISPACE.sub(" ", cleaned)
    cleaned = _MULTINEWLINE.sub("\n\n", cleaned)
    lines = [line.strip() for line in cleaned.split("\n")]
    return "\n".join(line for line in lines if line != "").strip()


def normalize_upper(text: str) -> str:
    return normalize(text).upper()


def collapse_for_matching(text: str) -> str:
    """Forme tres agressive utilisee uniquement pour comparer deux messages."""
    cleaned = normalize_upper(text)
    return re.sub(r"[^A-Z0-9]", "", cleaned)


def content_hash(text: str) -> str:
    """Empreinte stable d'un message, insensible a la mise en forme."""
    return hashlib.sha256(collapse_for_matching(text).encode()).hexdigest()[:32]


def structure_fingerprint(text: str) -> str:
    """Signature de structure : suite des mots-cles rencontres.

    Permet de reconnaitre qu'un canal utilise toujours le meme gabarit
    (CDC section 53) sans stocker le contenu du message.
    """
    keywords = (
        "BUY", "SELL", "LONG", "SHORT", "LIMIT", "STOP", "ENTRY", "ENTER",
        "SL", "STOPLOSS", "TP", "TARGET", "TP1", "TP2", "TP3", "TP4", "BE",
    )
    upper = normalize_upper(text)
    found: list[str] = []
    for token in re.findall(r"[A-Z]+[0-9]*", upper):
        if token in keywords and (not found or found[-1] != token):
            found.append(token)
    return "|".join(found[:12])


def extract_numbers(text: str) -> list[float]:
    """Tous les nombres du texte, dans l'ordre d'apparition."""
    values: list[float] = []
    for raw in re.findall(r"\d+(?:\.\d+)?", normalize_numbers(text)):
        try:
            values.append(float(raw))
        except ValueError:  # pragma: no cover - regex garantit un float valide
            continue
    return values


def looks_like_noise(text: str) -> bool:
    """Detecte un message de convivialite sans intention de trade."""
    cleaned = normalize_upper(text)
    if not cleaned:
        return True
    if len(cleaned) < 3:
        return True
    noise_markers = (
        "GOOD MORNING", "GOOD EVENING", "GOOD NIGHT", "WELCOME", "FAMILY",
        "SUBSCRIBE", "JOIN NOW", "VIP", "CONGRATULATIONS", "WELL DONE",
        "HAPPY", "SEE YOU", "GOOD LUCK", "RESULTS", "TODAY WAS", "PROFIT TODAY",
    )
    has_noise = any(marker in cleaned for marker in noise_markers)
    has_digits = bool(re.search(r"\d", cleaned))
    return has_noise and not has_digits
