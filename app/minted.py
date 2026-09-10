"""Reuse authors' frozen Pygments styles across minted prefix conventions."""

import re
from pathlib import Path

from .sources import visible_tex


def prepare_minted_cache(root: Path) -> int:
    """Add aliases for legacy style names without regenerating or executing code.

    Older minted caches define a style-specific ``PYGdefault`` command, while
    newer minted expects ``PYG``. Keep every original definition so cached
    listings using either naming convention render with the author's styles.
    """
    changed = 0
    for path in root.rglob("*.pygstyle"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        visible = visible_tex(text)
        if re.search(r"\\(?:def|gdef|edef|xdef|let)\s*\\PYG(?![A-Za-z@])", visible):
            continue
        prefixes = set(
            re.findall(r"\\def\s*\\(PYG[A-Za-z]+)\s*#1\s*#2\s*\{", visible)
        )
        if len(prefixes) != 1:
            continue
        prefix = prefixes.pop()
        escapes = set(
            re.findall(r"\\def\s*\\(" + re.escape(prefix) + r"Z[A-Za-z]+)\s*\{", visible)
        )
        aliases = [prefix, *sorted(escapes)]
        block = "\n% texglot: legacy minted style aliases\n\\makeatletter\n"
        for name in aliases:
            target = "PYG" + name[len(prefix) :]
            # A style may already supply some generic escape commands.
            if re.search(
                r"\\(?:def|gdef|edef|xdef|let)\s*\\" + target + r"(?![A-Za-z@])",
                visible,
            ):
                continue
            block += "\\let\\" + target + "\\" + name + "\n"
        block += "\\makeatother\n"
        path.write_text(text + block, encoding="utf-8")
        changed += 1
    return changed
