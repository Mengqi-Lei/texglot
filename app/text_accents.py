"""Recognize literal Latin words written with TeX's standard text accents.

This is a small lexical recognizer, not a TeX evaluator. Callers are responsible
for excluding math, comments, verbatim code and other non-prose contexts. Every
span refers to the original source; the Unicode value is for display only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ACCENTS = {
    "`": "\u0300",  # grave
    "'": "\u0301",  # acute
    "^": "\u0302",  # circumflex
    '"': "\u0308",  # diaeresis
    "~": "\u0303",  # tilde
    "=": "\u0304",  # macron
    ".": "\u0307",  # dot above
    "u": "\u0306",  # breve
    "v": "\u030c",  # caron
    "H": "\u030b",  # double acute
    "r": "\u030a",  # ring above
    "c": "\u0327",  # cedilla
    "k": "\u0328",  # ogonek
    "b": "\u0331",  # macron below
    "d": "\u0323",  # dot below
    "t": "\u0361",  # tie accent over two letters
}
_CONTROL_WORD = re.compile(r"[A-Za-z@]+")
_MAX_DEPTH = 24


@dataclass(frozen=True)
class _Part:
    end: int
    display: str
    accented: bool = False


def _latin_letter(char: str) -> bool:
    if char.isascii():
        return "A" <= char <= "Z" or "a" <= char <= "z"
    return unicodedata.category(char).startswith("L") and "LATIN" in unicodedata.name(
        char, ""
    )


def _letter(text: str, start: int) -> _Part | None:
    if start >= len(text) or not _latin_letter(text[start]):
        return None
    end = start + 1
    while end < len(text) and unicodedata.category(text[end]).startswith("M"):
        end += 1
    return _Part(end, text[start:end])


def _command(text: str, start: int) -> tuple[str, int] | None:
    if start + 1 >= len(text) or text[start] != "\\":
        return None
    match = _CONTROL_WORD.match(text, start + 1)
    if match:
        return match[0], match.end()
    return text[start + 1], start + 2


def _group(text: str, start: int, depth: int) -> _Part | None:
    if depth > _MAX_DEPTH or start >= len(text) or text[start] != "{":
        return None
    value = _word(text, start + 1, depth + 1)
    if value is None or value.end >= len(text) or text[value.end] != "}":
        return None
    return _Part(value.end + 1, value.display, value.accented)


def _dotless(text: str, start: int) -> _Part | None:
    command = _command(text, start)
    if command is None or command[0] not in {"i", "j"}:
        return None
    name, end = command
    while end < len(text) and text[end].isspace():
        end += 1
    return _Part(end, "ı" if name == "i" else "ȷ")


def _accent(text: str, start: int, depth: int) -> _Part | None:
    if depth > _MAX_DEPTH:
        return None
    command = _command(text, start)
    if command is None or command[0] not in _ACCENTS:
        return None
    name, argument = command
    while argument < len(text) and text[argument].isspace():
        argument += 1
    if argument >= len(text):
        return None
    if text[argument] == "{":
        base = _group(text, argument, depth + 1)
    else:
        base = _letter(text, argument) or _dotless(text, argument)
    if base is None:
        return None
    decomposed = unicodedata.normalize("NFD", base.display)
    letters = [index for index, char in enumerate(decomposed) if _latin_letter(char)]
    # An accent over an arbitrary TeX box cannot be reduced to a literal word.
    if len(letters) != (2 if name == "t" else 1):
        return None
    # TeX uses dotless i/j beneath the accent; Unicode's ordinary accented
    # letters use i/j as their normalization base.
    decomposed = decomposed.replace("ı", "i").replace("ȷ", "j")
    insertion = letters[1] if name == "t" else len(decomposed)
    display = decomposed[:insertion] + _ACCENTS[name] + decomposed[insertion:]
    return _Part(base.end, unicodedata.normalize("NFC", display), True)


def _word(text: str, start: int, depth: int = 0) -> _Part | None:
    if depth > _MAX_DEPTH:
        return None
    pieces = []
    accented = False
    end = start
    while end < len(text):
        part = _letter(text, end)
        if part is None and text[end] == "{":
            part = _group(text, end, depth + 1)
        elif part is None and text[end] == "\\":
            part = _accent(text, end, depth + 1) or _dotless(text, end)
        if part is None:
            break
        pieces.append(part.display)
        accented |= part.accented
        end = part.end
    if not pieces:
        return None
    return _Part(end, unicodedata.normalize("NFC", "".join(pieces)), accented)


def accented_word_spans(text: str) -> list[tuple[int, int, str]]:
    """Return complete Latin runs containing at least one literal TeX accent.

    Brace groups made entirely of word fragments are included in the span.
    An unknown control word is a boundary: its name and argument delimiters
    are never mistaken for part of the word. Escaped backslashes are skipped
    as one control symbol, so ``\\\\'e`` is not mistaken for ``\\'e``.
    """
    spans = []
    position = 0
    while position < len(text):
        word = _word(text, position)
        if word is not None:
            if word.accented:
                spans.append((position, word.end, word.display))
            position = word.end
            continue
        command = _command(text, position)
        if command is not None:
            name, position = command
            # Keep a formatting command's argument braces outside its content
            # word. The caller owns the command and these structural braces.
            if _CONTROL_WORD.fullmatch(name):
                opener = position
                while opener < len(text) and text[opener].isspace():
                    opener += 1
                if opener < len(text) and text[opener] == "{":
                    position = opener + 1
        else:
            position += 1
    return spans


def accented_word_text(value: str) -> str | None:
    """Return an NFC display value only when the entire slice is one such word."""
    spans = accented_word_spans(value)
    if len(spans) == 1 and spans[0][0] == 0 and spans[0][1] == len(value):
        return spans[0][2]
    return None
