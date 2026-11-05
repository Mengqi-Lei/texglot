"""Conservative font-file compatibility and diagnosed Unicode math recovery."""

from __future__ import annotations

import re
from pathlib import Path

from .latex import MACRO_DEFINITIONS, definition_end, group_end, skip_tex_space
from .sources import TEX_SOURCE_SUFFIXES, collect_literal_environments, visible_tex

# The bundled file is case-sensitive; some acmart versions request lower case.
CANONICAL_FONT_FILES = {
    "libertinusmath-regular.otf": "LibertinusMath-Regular.otf",
}
FONT_COMMANDS = re.compile(
    r"\\(setmathfont|setmainfont|setsansfont|setmonofont|newfontfamily|"
    r"newfontface|fontspec)(?![A-Za-z@])\*?"
)
PACKAGE_LOAD = re.compile(
    r"\\(?:usepackage|RequirePackage)(?![A-Za-z@])\s*"
    r"(?:\[[^\[\]]*\]\s*)?\{([^{}]*)\}"
)
AMSSYMB_NOTE = "% texglot: skip amssymb only when unicode-math is already loaded"


def canonical_font_file(name: str) -> str:
    key = name.strip().casefold()
    if not key.endswith(".otf"):
        key += ".otf"
    return CANONICAL_FONT_FILES.get(key, "")


def _project_sources(root: Path) -> dict[Path, str]:
    paths = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in TEX_SOURCE_SUFFIXES
    ]
    if any(
        path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
        for path in paths
    ):
        return {}
    try:
        return {path.resolve(): path.read_text(encoding="utf-8") for path in paths}
    except (OSError, UnicodeError):
        return {}


def _font_argument(text: str, command) -> tuple[int, int, str] | None:
    """Read the font argument, without consuming subsequent braced prose."""
    pos = skip_tex_space(text, command.end())
    try:
        if command[1] in {"newfontfamily", "newfontface"}:
            if text.startswith("{", pos):
                pos = group_end(text, pos, strict=True)
            else:
                name = re.match(r"\\[A-Za-z@]+", text[pos:])
                if name is None:
                    return None
                pos += name.end()
            pos = skip_tex_space(text, pos)
        options = ""
        if text.startswith("[", pos):
            end = group_end(text, pos, strict=True)
            options = text[pos + 1 : end - 1]
            pos = skip_tex_space(text, end)
        if not text.startswith("{", pos):
            return None
        end = group_end(text, pos, strict=True)
        after = skip_tex_space(text, end)
        if text.startswith("[", after):
            finish = group_end(text, after, strict=True)
            options += "," + text[after + 1 : finish - 1]
        return pos + 1, end - 1, options
    except ValueError:
        return None


def repair_font_requests(
    text: str, *, literal_environments=frozenset(), provided=frozenset()
) -> str:
    visible = visible_tex(text, literal_environments=literal_environments)
    edits = []
    for command in FONT_COMMANDS.finditer(visible):
        argument = _font_argument(visible, command)
        if argument is None:
            continue
        start, end, options = argument
        # Respect authored lookup rules, including features supplied by macros.
        if "\\" in options or re.search(r"\b(?:Path|Extension)\s*=", options):
            continue
        name = re.fullmatch(r"\s*(\S+)\s*", visible[start:end])
        if name is None:
            continue
        requested = name[1]
        canonical = canonical_font_file(requested)
        if not canonical or requested == canonical:
            continue
        key = requested.casefold()
        if key in provided or (not key.endswith(".otf") and key + ".otf" in provided):
            continue
        # Change only the name token; keep surrounding comments and newlines.
        edits.append((start + name.start(1), start + name.end(1), canonical))
    for start, end, value in reversed(edits):
        text = text[:start] + value + text[end:]
    return text


def prepare_font_files(
    root: Path, engine: str, *, literal_environments=frozenset()
) -> list[str]:
    if engine not in {"tectonic", "xelatex", "lualatex"}:
        return []
    sources = _project_sources(root)
    literals = literal_environments | collect_literal_environments(
        "\n".join(sources.values())
    )
    provided = {path.name.casefold() for path in root.rglob("*") if path.is_file()}
    changed = []
    for path, text in sorted(sources.items()):
        updated = repair_font_requests(
            text, literal_environments=literals, provided=provided
        )
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(path.relative_to(root.resolve()).as_posix())
    return changed


def _package_loads(visible: str):
    cursor = 0
    for command in re.finditer(r"\\([A-Za-z@]+)\*?", visible):
        if command.start() < cursor:
            continue
        if command[1] in MACRO_DEFINITIONS:
            cursor = definition_end(visible, command.end(), command[1])
            continue
        match = PACKAGE_LOAD.match(visible, command.start())
        if match:
            cursor = match.end()
            yield match


def _guarded_load(text: str, match, parts, index: int) -> str:
    """Keep package order/options and preserve the non-Unicode-math branch."""
    prefix, suffix = (
        text[match.start() : match.start(1)],
        text[match.end(1) : match.end()],
    )
    start = match.start(1) + parts[index].start()
    end = match.start(1) + parts[index].end()
    loads = []
    if index:
        loads.append(prefix + text[match.start(1) : start - 1] + suffix)
    original = prefix + text[start:end] + suffix
    loads.append(r"\IfPackageLoadedTF{unicode-math}{}{" + original + "}")
    if index + 1 < len(parts):
        loads.append(prefix + text[end + 1 : match.end(1)] + suffix)
    return "\n".join(loads)


def guard_amssymb_load(root: Path, loaded_paths: set[Path]) -> list[str]:
    """Guard one unambiguous literal load after a confirmed compiler clash.

    The caller verifies the failing package and actual unicode-math load record.
    Global literal definitions protect examples in other files. A runtime guard
    also keeps the original load available when an authored branch uses it alone.
    """
    if any(root.rglob("amssymb.sty")):
        return []
    sources = _project_sources(root)
    literals = collect_literal_environments("\n".join(sources.values()))
    candidates = []
    for path in sorted(loaded_paths):
        if path not in sources:
            continue
        text = sources[path]
        if AMSSYMB_NOTE in text:
            return []
        visible = visible_tex(text, literal_environments=literals)
        for match in _package_loads(visible):
            parts = list(re.finditer(r"[^,]+", match[1]))
            names = [part[0].strip() for part in parts]
            if "amssymb" not in names:
                continue
            if names.count("amssymb") != 1 or any(
                not re.fullmatch(r"[A-Za-z0-9_.-]+", name) for name in names
            ):
                return []
            candidates.append((path, match, parts, names.index("amssymb")))
    if len(candidates) != 1:
        return []
    path, match, parts, index = candidates[0]
    text = sources[path]
    replacement = _guarded_load(text, match, parts, index)
    path.write_text(
        AMSSYMB_NOTE + "\n" + text[: match.start()] + replacement + text[match.end() :],
        encoding="utf-8",
    )
    return [path.relative_to(root.resolve()).as_posix()]
