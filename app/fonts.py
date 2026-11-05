"""Resolve font requests that a Unicode engine cannot satisfy as written."""

from __future__ import annotations

import re
from pathlib import Path

from .sources import TEX_SOURCE_SUFFIXES, visible_tex

# TeX Live ships the Libertinus math font as LibertinusMath-Regular.otf. The
# acmart class asks for the same font in lower case, and a case-sensitive
# lookup - the Tectonic bundle, or a TeX Live tree on a case-sensitive file
# system - cannot resolve that spelling.
CANONICAL_FONT_FILES = {
    "libertinusmath-regular.otf": "LibertinusMath-Regular.otf",
}

# Font commands that name a font. \newfontfamily takes the new command
# between the macro and its arguments, so the arguments are read separately.
FONT_COMMANDS = re.compile(
    r"\\(?:setmathfont|setmainfont|setsansfont|setmonofont|newfontfamily|"
    r"newfontfamilyb|fontspec)\*?"
)

PACKAGE_LOAD = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}"
)

AMSSYMB_NOTE = (
    "% texglot: amssymb redeclares the AMS symbols that unicode-math already "
    "provides, so this load was removed"
)


def canonical_font_file(name: str) -> str:
    """Return the canonical file name of a requested font, or an empty string."""
    value = name.strip()
    if not value:
        return ""
    key = value.lower()
    if not key.endswith(".otf"):
        key += ".otf"
    return CANONICAL_FONT_FILES.get(key, "")


def _font_arguments(text: str, start: int) -> list[tuple[int, int]]:
    """Return the braced arguments that follow a font command."""
    from .latex import group_end

    pos = start
    while pos < len(text) and text[pos].isspace():
        pos += 1
    # \newfontfamily names the command it defines before the font itself.
    if text.startswith("\\", pos):
        token = re.match(r"\\[A-Za-z@]+", text[pos:])
        if token is None:
            return []
        pos += token.end()
    while pos < len(text) and text[pos].isspace():
        pos += 1
    # Font features may precede the font name.
    if text.startswith("[", pos):
        end = text.find("]", pos)
        if end < 0:
            return []
        pos = end + 1
    ranges = []
    while pos < len(text):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if not text.startswith("{", pos):
            break
        try:
            end = group_end(text, pos)
        except ValueError:
            break
        ranges.append((pos + 1, end - 1))
        pos = end
    return ranges


def repair_font_requests(
    text: str, *, literal_environments=frozenset(), provided=frozenset()
) -> str:
    """Point font requests at the canonical file name of the same font.

    Only requests for a known font file are rewritten, and only when the
    project does not ship that file itself.
    """
    visible = visible_tex(text, literal_environments=literal_environments)
    edits = []
    for match in FONT_COMMANDS.finditer(visible):
        for start, end in _font_arguments(visible, match.end()):
            requested = visible[start:end].strip()
            canonical = canonical_font_file(requested)
            if not canonical or canonical == requested:
                continue
            if requested.lower() in provided:
                continue
            edits.append((start, end, canonical))
    for start, end, value in reversed(edits):
        text = text[:start] + value + text[end:]
    return text


def prepare_font_files(
    root: Path, engine: str, *, literal_environments=frozenset()
) -> list[str]:
    """Repair font file names that a case-sensitive lookup cannot resolve."""
    if engine not in {"tectonic", "xelatex", "lualatex"}:
        return []
    provided = {path.name.lower() for path in root.rglob("*") if path.is_file()}
    changed = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEX_SOURCE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        updated = repair_font_requests(
            text, literal_environments=literal_environments, provided=provided
        )
        if updated == text:
            continue
        path.write_text(updated, encoding="utf-8")
        changed.append(path.relative_to(root).as_posix())
    return changed


def unicode_math_active(root: Path, log: str = "") -> bool:
    """Report whether the document loads unicode-math, which owns AMS symbols."""
    if "unicode-math" in log:
        return True
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEX_SOURCE_SUFFIXES:
            continue
        try:
            text = visible_tex(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
        for match in PACKAGE_LOAD.finditer(text):
            if "unicode-math" in [name.strip() for name in match.group(1).split(",")]:
                return True
    return False


def remove_amssymb_loads(root: Path, log: str = "") -> list[str]:
    """Remove amssymb loads that clash with an already loaded unicode-math.

    unicode-math declares the AMS symbols itself and does so before the
    document body runs. amssymb declares the same commands again, and LaTeX
    stops at the first command that is already defined. Without unicode-math
    the load stays, because amssymb then provides symbols of its own.
    """
    if not unicode_math_active(root, log):
        return []
    changed = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".tex", ".sty", ".cls"}:
            continue
        text = path.read_text(encoding="utf-8")
        visible = visible_tex(text)
        edits = []
        for match in PACKAGE_LOAD.finditer(visible):
            names = [name.strip() for name in match.group(1).split(",")]
            if "amssymb" not in names:
                continue
            if len(names) == 1:
                edits.append((match.start(), match.end(), None))
            else:
                remaining = ",".join(name for name in names if name != "amssymb")
                edits.append((match.start(1), match.end(1), remaining))
        if not edits:
            continue
        for start, end, value in reversed(edits):
            if value is not None:
                text = text[:start] + value + text[end:]
                continue
            # Keep the note on its own line so that it cannot swallow code
            # that follows the load on the same line.
            line_start = text.rfind("\n", 0, start) + 1
            line_end = text.find("\n", end)
            line_end = len(text) if line_end < 0 else line_end
            alone = (
                not text[line_start:start].strip() and not text[end:line_end].strip()
            )
            replacement = AMSSYMB_NOTE if alone else ""
            text = text[:start] + replacement + text[end:]
        path.write_text(text, encoding="utf-8")
        changed.append(path.relative_to(root).as_posix())
    return changed
