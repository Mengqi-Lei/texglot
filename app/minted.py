"""Keep minted sources compatible with restricted compilation."""

import re
from pathlib import Path

from .sources import (
    TEX_SOURCE_SUFFIXES,
    VERBATIM_ENVIRONMENTS,
    _visible_tex,
    collect_literal_environments,
    visible_tex,
)


def remove_unused_minted(root: Path) -> list[str]:
    """Remove explicit loaders only when no project source uses minted's API.

    Called after an actual minted shell-escape failure. Keep used/frozen minted
    documents intact; printed examples and comments are not executable uses.
    Dynamic references, wrappers and aliases mentioning minted veto removal.
    """
    if any(
        p.suffix.lower() in {".pygstyle", ".pygtex", ".pyg"} for p in root.rglob("*")
    ):
        return []
    paths = [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in TEX_SOURCE_SUFFIXES
    ]
    if any(
        p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) for p in paths
    ):
        return []
    texts = {p: p.read_text(encoding="utf-8") for p in paths}
    environments = collect_literal_environments("\n".join(texts.values()))
    loader = re.compile(
        r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\[\]]*\]\s*)?\{([^{}]+)\}"
    )
    plans = {}
    for path, text in texts.items():
        # The ordinary scanner hides minted blocks too. Keep their begin/end
        # visible here so a real code listing can never look like an unused load.
        visible = _visible_tex(
            text, (environments | VERBATIM_ENVIRONMENTS) - {"minted"}
        )
        changes = []
        for match in loader.finditer(visible):
            packages = [part.strip() for part in match[1].split(",")]
            if "minted" not in packages:
                continue
            kept = [part for part in packages if part != "minted"]
            if any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in packages):
                return []
            replacement = (
                text[match.start() : match.start(1)] + ",".join(kept) + "}"
                if kept
                else " " * (match.end() - match.start())
            )
            # Preserve diagnostics' line numbers when removing a whole loader.
            if not kept:
                replacement = "".join("\n" if c == "\n" else " " for c in match[0])
            changes.append((match.start(), match.end(), replacement))
        remainder = visible
        for start, end, _ in reversed(changes):
            remainder = remainder[:start] + " " * (end - start) + remainder[end:]
        if re.search(r"minted|\\mint(?:inline)?(?![A-Za-z@])", remainder, re.I):
            return []
        if changes:
            plans[path] = changes
    for path in plans:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            return []
    for path, changes in plans.items():
        text = texts[path]
        for start, end, replacement in reversed(changes):
            text = text[:start] + replacement + text[end:]
        path.write_text(text, encoding="utf-8")
    return [p.relative_to(root).as_posix() for p in sorted(plans)]


def prepare_minted_cache(root: Path, *, literal_environments=frozenset()) -> int:
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
        visible = visible_tex(text, literal_environments=literal_environments)
        if re.search(r"\\(?:def|gdef|edef|xdef|let)\s*\\PYG(?![A-Za-z@])", visible):
            continue
        prefixes = set(re.findall(r"\\def\s*\\(PYG[A-Za-z]+)\s*#1\s*#2\s*\{", visible))
        if len(prefixes) != 1:
            continue
        prefix = prefixes.pop()
        escapes = set(
            re.findall(
                r"\\def\s*\\(" + re.escape(prefix) + r"Z[A-Za-z]+)\s*\{", visible
            )
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
