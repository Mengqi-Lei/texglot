from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .config import CONFIG, DATA
from .platforms import process_options, terminate_process_tree
from .runtime import bundled_tools, child_environment
from .sources import decode_tex, visible_tex, without_comments


def available_compilers():
    return {
        name: bool(find_compiler(name)) for name in ("tectonic", "xelatex", "lualatex")
    }


def find_compiler(name: str):
    tools = bundled_tools()
    if tools is not None:
        bundled = tools / (name + (".exe" if sys.platform == "win32" else ""))
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return str(bundled)
    found = shutil.which(name)
    if found and not (
        sys.platform == "win32" and Path(found).suffix.lower() in (".cmd", ".bat")
    ):
        return found
    filename = name + (".exe" if sys.platform == "win32" else "")
    candidates = [DATA / "tools" / filename]
    if sys.platform == "darwin":
        candidates += [
            Path("/Library/TeX/texbin") / name,
            Path("/opt/homebrew/bin") / name,
            Path("/usr/local/bin") / name,
        ]
    return next(
        (str(p) for p in candidates if p.is_file() and os.access(p, os.X_OK)), None
    )


def inject_preamble(text: str, block: str) -> str:
    marker = re.search(r"\\begin\s*\{document\}", visible_tex(text))
    if not marker:
        return text
    return text[: marker.start()] + block + text[marker.start() :]


PIXEL_COMPATIBILITY = r"""% texglot: pdfTeX pixel dimensions for XeTeX
\ifdefined\pdfpxdimen\else\newdimen\pdfpxdimen\pdfpxdimen=65782sp\fi
"""


FLOAT_SIZING = r"""% texglot: fit complete oversized float boxes v1
\usepackage{graphicx}
\begingroup
\makeatletter
\AtBeginDocument{%
\let\texglot@endfloatbox\@endfloatbox
\def\@endfloatbox{%
\texglot@endfloatbox
\def\texglot@figure{figure}%
\def\texglot@figurestar{figure*}%
\def\texglot@table{table}%
\def\texglot@tablestar{table*}%
\let\texglot@floatscope\@empty
\ifx\@currenvir\texglot@figure\def\texglot@floatscope{1}\fi
\ifx\@currenvir\texglot@figurestar\def\texglot@floatscope{1}\fi
\ifx\@currenvir\texglot@table\def\texglot@floatscope{1}\fi
\ifx\@currenvir\texglot@tablestar\def\texglot@floatscope{1}\fi
\ifx\texglot@floatscope\@empty\else
\ifdim\dimexpr\ht\@currbox+\dp\@currbox\relax>\textheight
\edef\texglot@floatwidth{\the\wd\@currbox}%
\edef\texglot@floatheight{\the\dimexpr\textheight-\baselineskip\relax}%
\ifdim\texglot@floatheight>0pt
\typeout{TeXGlot-Float-Fit: \@captype\space \csname the\@captype\endcsname; height \the\dimexpr\ht\@currbox+\dp\@currbox\relax; limit \texglot@floatheight}%
\global\setbox\@currbox=\vbox{\hbox to\texglot@floatwidth{\hfil\resizebox*{!}{\texglot@floatheight}{\box\@currbox}\hfil}}%
\fi\fi\fi}%
}
\endgroup
"""


def prepare_float_sizing(root: Path) -> None:
    """Keep complete oversized standard figures and tables within a usable page."""
    sources = {
        path: path.read_text(encoding="utf-8")
        for path in root.rglob("*.tex")
        if path.is_file()
    }
    visible = {path: visible_tex(text) for path, text in sources.items()}
    if not any(
        re.search(r"\\begin\s*\{(?:figure|table)\*?\}", text) for text in visible.values()
    ):
        return
    for path, text in sources.items():
        if FLOAT_SIZING.strip() in text:
            continue
        if re.search(
            r"\\(?:documentclass|documentstyle)\b", visible[path]
        ) and re.search(r"\\begin\s*\{document\}", visible[path]):
            path.write_text(inject_preamble(text, FLOAT_SIZING), encoding="utf-8")


LEGACY_LATIN_FAMILIES = {
    "ptm": "texgyretermes",
    "phv": "texgyreheros",
    "pcr": "texgyrecursor",
    "ppl": "texgyrepagella",
    "pbk": "texgyrebonum",
    "pnc": "texgyreschola",
    "pag": "texgyreadventor",
}


def prepare_legacy_latin_fonts(root: Path, engine: str) -> None:
    """Adapt explicit standard Type1 text selections to Unicode equivalents.

    Keep font sizes, series and shapes, along with the author's default fonts.
    Unicode selections and custom NFSS families are never replaced.
    """
    if engine not in {"tectonic", "xelatex", "lualatex"}:
        return
    from .latex import group_end

    sources = {
        path: path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".tex", ".sty", ".cls"}
    }
    visible = {path: visible_tex(text) for path, text in sources.items()}
    documents = {
        path
        for path, text in visible.items()
        if re.search(r"\\documentclass\b", text)
        and re.search(r"\\begin\s*\{document\}", text)
    }
    if not documents:
        return
    context = "\n".join(visible.values())
    custom_families = set(
        re.findall(r"NFSSFamily\s*=\s*\{?([A-Za-z0-9-]+)", context)
    ) | set(re.findall(r"\\DeclareFontFamily\s*\{TU\}\s*\{([^{}]+)\}", context))
    names = "|".join(LEGACY_LATIN_FAMILIES)
    usefont = re.compile(rf"\\usefont\s*\{{(OT1|T1|LY1)\}}\s*\{{({names})\}}")
    family = re.compile(rf"\\fontfamily\s*\{{({names})\}}")
    needed = set()
    for path, text in sources.items():
        edits = []
        for match in usefont.finditer(visible[path]):
            name = match[2]
            needed.add(name)
            edits.extend(
                [
                    (*match.span(1), "TU"),
                    (*match.span(2), "texglot-" + name),
                ]
            )
        for match in family.finditer(visible[path]):
            name = match[1]
            if name in custom_families:
                continue
            needed.add(name)
            edits.extend(
                [
                    (*match.span(1), "texglot-" + name),
                    (match.start(), match.start(), r"\fontencoding{TU}"),
                ]
            )
        for start, end, replacement in sorted(edits, reverse=True):
            text = text[:start] + replacement + text[end:]
        sources[path] = text
    if not needed:
        return
    definitions = []
    for name in sorted(needed):
        font = LEGACY_LATIN_FAMILIES[name]
        definitions.append(
            rf"\newfontfamily\TeXGlotLatin{name}{{{font}-regular.otf}}"
            + rf"[NFSSFamily=texglot-{name},BoldFont={font}-bold.otf,"
            + rf"ItalicFont={font}-italic.otf,BoldItalicFont={font}-bolditalic.otf,"
            + rf"SlantedFont={font}-italic.otf,BoldSlantedFont={font}-bolditalic.otf]"
        )
    block = (
        "\n% texglot: Unicode equivalents for explicit legacy Latin families\n"
        r"\let\TeXGlotSavedRmDefault\rmdefault" + "\n"
        r"\let\TeXGlotSavedSfDefault\sfdefault" + "\n"
        r"\let\TeXGlotSavedTtDefault\ttdefault" + "\n"
        r"\RequirePackage[no-math]{fontspec}" + "\n" + "\n".join(definitions) + "\n"
        r"\let\rmdefault\TeXGlotSavedRmDefault" + "\n"
        r"\let\sfdefault\TeXGlotSavedSfDefault" + "\n"
        r"\let\ttdefault\TeXGlotSavedTtDefault" + "\n"
        "% texglot: end legacy Latin families\n"
    )
    for path in documents:
        text = sources[path]
        match = re.search(r"\\documentclass\s*(?:\[[^]]*\]\s*)?\{", visible_tex(text))
        if match:
            end = group_end(text, match.end() - 1)
            sources[path] = text[:end] + block + text[end:]
    for path, text in sources.items():
        if text != path.read_text(encoding="utf-8"):
            path.write_text(text, encoding="utf-8")


def normalize_float_positions(text: str) -> str:
    visible = visible_tex(text)
    for match in reversed(
        list(
            re.finditer(
                r"\\begin\s*\{(?:figure|table)\*?\}\s*(\[([A-Za-z!\s]+)\])", visible
            )
        )
    ):
        positions = "".join(c for c in match[2] if c in "htbpH!" or c.isspace())
        if positions == match[2]:
            continue
        replacement = (
            "[" + positions + "]" if any(c in "htbpH" for c in positions) else ""
        )
        text = text[: match.start(1)] + replacement + text[match.end(1) :]
    return text


def normalize_comment_terminators(text: str) -> str:
    # comment.sty compares whole input lines. Trailing tabs accepted by TeX's
    # ordinary scanner otherwise make it consume through end-of-file.
    visible = visible_tex(text, mask_comment_environments=False)
    for match in reversed(
        list(re.finditer(r"(?m)^[ \t]*(\\end\s*\{comment\})[ \t]+(?=\r?$)", visible))
    ):
        text = text[: match.start()] + r"\end{comment}" + text[match.end() :]
    return text


def normalize_pixel_dimensions(text: str) -> str:
    """Preserve pdfTeX's configurable pixel unit only in dimension arguments."""
    visible = visible_tex(text)
    ranges = []
    for match in re.finditer(r"\\includegraphics\*?\s*\[([^]]*)\]", visible):
        for option in re.finditer(
            r"(?:width|height|totalheight)\s*=\s*([^,]+)", match[1]
        ):
            ranges.append(
                (match.start(1) + option.start(1), match.start(1) + option.end(1))
            )
    patterns = [
        r"\\(?:setlength|addtolength)\s*\{[^{}]+\}\s*\{([^{}]+)\}",
        r"\\(?:hspace|vspace)\*?\s*\{([^{}]+)\}",
        r"\\rule\s*(?:\[([^]]*)\])?\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
        r"\\(?:hskip|vskip|kern|hsize|vsize|textwidth|textheight|linewidth|columnwidth|parindent|parskip)\s*=?\s*([+-]?\s*(?:\d+(?:\.\d*)?|\.\d+)\s*px)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, visible):
            ranges.extend(
                match.span(index)
                for index in range(1, len(match.groups()) + 1)
                if match[index] is not None
            )
    edits = {}
    for start, end in ranges:
        for match in re.finditer(
            r"(?<![A-Za-z\\])([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*px\b", visible[start:end]
        ):
            edits[(start + match.start(), start + match.end())] = (
                match[1] + r"\pdfpxdimen"
            )
    for (start, end), value in sorted(edits.items(), reverse=True):
        text = text[:start] + value + text[end:]
    return text


def normalize_engine(text: str, engine: str) -> str:
    text = normalize_comment_terminators(text)
    text = normalize_float_positions(text)
    if engine in ("tectonic", "xelatex"):
        text = normalize_pixel_dimensions(text)
        visible = visible_tex(text)
        if (
            r"\pdfpxdimen" in visible
            and re.search(r"\\begin\s*\{document\}", visible)
            and PIXEL_COMPATIBILITY not in text
        ):
            text = PIXEL_COMPATIBILITY + text
            visible = visible_tex(text)
        if (
            re.search(r"\\begin\s*\{document\}", visible)
            and r"\PassOptionsToPackage{no-math}{fontspec}" not in visible
        ):
            text = "\\PassOptionsToPackage{no-math}{fontspec}\n" + text
        # The importer has already decoded every TeX file to UTF-8. Legacy
        # input/font encodings conflict with XeTeX's native Unicode fonts.
        visible = visible_tex(text)
        removals = []
        for match in re.finditer(
            r"\\(?:usepackage|RequirePackage)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}", visible
        ):
            names = [v.strip() for v in match[1].split(",")]
            kept = [v for v in names if v not in {"inputenc", "fontenc"}]
            if kept != names:
                value = (
                    text[match.start() : match.start(1)] + ",".join(kept) + "}"
                    if kept
                    else "\n"
                )
                removals.append((match.start(), match.end(), value))
        # pdfinfo is PDF metadata, not paper content; XeTeX has no such primitive.
        from .latex import group_end

        for match in re.finditer(r"\\pdfinfo\s*\{", visible):
            removals.append((match.start(), group_end(visible, match.end() - 1), "\n"))
        for start, end, value in sorted(removals, reverse=True):
            text = text[:start] + value + text[end:]
        # A pdfTeX-only switch misleads old hyperref templates under XeTeX.
        for match in reversed(
            list(re.finditer(r"\\pdfoutput\s*=?\s*1\b", visible_tex(text)))
        ):
            text = text[: match.start()] + " " + text[match.end() :]

        def driver(match):
            options = [
                "xetex" if v.strip() == "pdftex" else v
                for v in match.group(2).split(",")
            ]
            return match.group(1) + "[" + ",".join(options) + "]" + match.group(3)

        for match in reversed(
            list(
                re.finditer(
                    r"(\\(?:usepackage|RequirePackage)\s*)\[([^]]+)\](\s*\{(?:hyperref|graphicx|graphics|color|xcolor)\})",
                    visible_tex(text),
                )
            )
        ):
            text = text[: match.start()] + driver(match) + text[match.end() :]
        visible = visible_tex(text)
        if (
            r"\usepackage{microtype}" in visible
            and r"\begin{verbatim}" in without_comments(text)
        ):
            # The bundled microtype's TS1 quote protrusion data cannot be used
            # with native XeTeX fonts. Set options before font hooks register.
            for match in reversed(
                list(re.finditer(r"\\usepackage\{microtype\}", visible))
            ):
                text = (
                    text[: match.start()]
                    + r"\usepackage[protrusion=false,expansion=false]{microtype}"
                    + text[match.end() :]
                )
        visible = visible_tex(text)
        if (
            re.search(r"\\usepackage(?:\[[^]]*\])?\{(?:times|mathptmx)\}", visible)
            and "% texglot: Unicode-capable Times-compatible fonts" not in text
        ):
            text = inject_preamble(
                text,
                r"""% texglot: Unicode-capable Times-compatible fonts
\edef\TeXGlotTimesRm{\rmdefault}
\edef\TeXGlotTimesSf{\sfdefault}
\edef\TeXGlotTimesTt{\ttdefault}
\def\TeXGlotLegacyTimes{ptm}
\def\TeXGlotLegacyHelvetica{phv}
\def\TeXGlotLegacyCourier{pcr}
\usepackage{fontspec}
\ifx\TeXGlotTimesRm\TeXGlotLegacyTimes
\setmainfont{texgyretermes-regular.otf}[BoldFont=texgyretermes-bold.otf,ItalicFont=texgyretermes-italic.otf,BoldItalicFont=texgyretermes-bolditalic.otf]
\fi
\ifx\TeXGlotTimesSf\TeXGlotLegacyHelvetica
\setsansfont{texgyreheros-regular.otf}[BoldFont=texgyreheros-bold.otf,ItalicFont=texgyreheros-italic.otf]
\fi
\ifx\TeXGlotTimesTt\TeXGlotLegacyCourier
\setmonofont{texgyrecursor-regular.otf}
\fi
""",
            )
    if engine in ("tectonic", "xelatex", "lualatex"):
        text = normalize_legacy_cjk(text, engine)
    return text


def prepare_engine_sources(root: Path, engine: str) -> None:
    """Adapt author-supplied TeX packages as well as the document entry points."""
    normalized = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".tex", ".sty", ".cls"}:
            original = path.read_bytes()
            text = normalize_engine(decode_tex(original), engine)
            normalized[path] = (original, text)
    needs_pixels = engine in ("tectonic", "xelatex") and any(
        r"\pdfpxdimen" in visible_tex(text) for _, text in normalized.values()
    )
    for path, (original, text) in normalized.items():
        if (
            needs_pixels
            and re.search(r"\\begin\s*\{document\}", visible_tex(text))
            and PIXEL_COMPATIBILITY not in text
        ):
            text = PIXEL_COMPATIBILITY + text
        output = text.encode("utf-8")
        if output != original:
            path.write_bytes(output)
    from .minted import prepare_minted_cache

    prepare_legacy_latin_fonts(root, engine)
    prepare_minted_cache(root)
    prepare_float_sizing(root)


def normalize_legacy_cjk(text: str, engine: str) -> str:
    """Use Unicode CJK fonts for legacy pdfTeX CJK packages and environments."""
    visible = visible_tex(text)
    changes = []
    package = "luatexja-fontspec" if engine == "lualatex" else "xeCJK"
    command = "setmainjfont" if engine == "lualatex" else "setCJKmainfont"
    loader = (
        "usepackage"
        if re.search(r"\\begin\s*\{document\}", visible)
        else "RequirePackage"
    )
    native = (
        "\n% texglot: adapted legacy CJK\n\\"
        + loader
        + "{"
        + package
        + "}\n"
        + "\\"
        + command
        + "{FandolSong-Regular.otf}[BoldFont=FandolSong-Bold.otf,ItalicFont=FandolKai-Regular.otf]\n"
        + (
            "\\setCJKsansfont{FandolHei-Regular.otf}[BoldFont=FandolHei-Bold.otf]\n\\setCJKmonofont{FandolFang-Regular.otf}\n"
            if engine != "lualatex"
            else ""
        )
    )
    for match in re.finditer(
        r"\\(?:usepackage|RequirePackage)\s*(?:\[[^]]*\])?\s*\{([^}]+)\}", visible
    ):
        names = [name.strip() for name in match[1].split(",")]
        kept = [name for name in names if name not in {"CJK", "CJKutf8"}]
        if len(kept) != len(names):
            replacement = (
                text[match.start() : match.start(1)] + ",".join(kept) + "}"
                if kept
                else ""
            )
            changes.append((match.start(), match.end(), replacement + native))
    # Keep the original environment's grouping, but not its 8-bit font encoding.
    for match in re.finditer(
        r"\\begin\s*\{CJK\*?\}\s*\{[^{}]*\}\s*\{[^{}]*\}|\\end\s*\{CJK\*?\}", visible
    ):
        changes.append(
            (match.start(), match.end(), "{" if match[0].startswith(r"\begin") else "}")
        )
    for start, end, value in sorted(changes, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def fit_tables(text: str) -> tuple[str, int]:
    """Shrink only oversized tabulars within floats; never enlarge a table."""
    count = 0

    def table(match):
        nonlocal count
        body = match.group()
        if r"\resizebox" in body or r"\begin{adjustbox}" in body:
            return body
        pairs = []
        start = None
        depth = 0
        for token in re.finditer(r"(?<!%)\\(begin|end)\{tabular\*?\}", body):
            # Ignore commented-out environment tokens.
            line = body[body.rfind("\n", 0, token.start()) + 1 : token.start()]
            if re.search(r"(?<!\\)%", line):
                continue
            if token.group(1) == "begin":
                if depth == 0:
                    start = token.start()
                depth += 1
            else:
                depth -= 1
                if depth == 0 and start is not None:
                    pairs.append((start, token.end()))
        for a, b in reversed(pairs):
            body = (
                body[:a]
                + r"\begin{adjustbox}{max width=\linewidth}"
                + body[a:b]
                + r"\end{adjustbox}"
                + body[b:]
            )
        count += len(pairs)
        return body

    text = re.sub(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", table, text, flags=re.S)
    return text, count


def break_long_code_identifiers(
    text: str, *, math_aliases: dict[str, str] | None = None
) -> str:
    """Permit wraps at existing separators in long, literal texttt identifiers.

    The original characters and escapes remain intact. Complex arguments,
    macro definitions, math, and code environments are deliberately untouched.
    """
    from .latex import (
        CODE_ARGUMENT_COMMANDS,
        COMMAND,
        FONT_SWITCHES,
        OPAQUE_COMMAND,
        OPAQUE_ENV,
        TEXT_COMMAND,
        TEXT_DECLARATIONS,
        args_end,
        collect_math_aliases,
        definition_end,
        group_end,
        math_end,
        opaque_environment_end,
        skip_tex_space,
    )

    visible = visible_tex(text)
    aliases = collect_math_aliases(text) | (math_aliases or {})
    in_body = not re.search(r"\\begin\s*\{document\}", visible)
    definitions = {
        "def",
        "gdef",
        "edef",
        "xdef",
        "newcommand",
        "renewcommand",
        "providecommand",
        "DeclareRobustCommand",
        "newenvironment",
        "renewenvironment",
    }
    opaque = OPAQUE_ENV | {
        "alltt",
        "code",
        "program",
        "algorithm",
        "algorithm*",
        "algorithmic",
    }
    token = re.compile(
        r"\\textunderscore(?![A-Za-z@])[ \t]*(?:\r?\n[ \t]*)?|\\_|[A-Za-z0-9_.]"
    )
    changes = []
    position = 0
    while position < len(text):
        if visible[position] == "$":
            opening = "$$" if visible.startswith("$$", position) else "$"
            position = math_end(visible, position + len(opening), opening, aliases)
            continue
        match = COMMAND.match(visible, position)
        if not match:
            position += 1
            continue
        name = match[0][1:].rstrip("*")
        position = match.end()
        value = aliases.get(name, match[0])
        if value in (r"\(", r"\["):
            position = math_end(visible, position, value, aliases)
            continue
        if alias_env := re.fullmatch(r"\\begin\{([^{}]+)\}", value):
            if alias_env[1] in opaque:
                position = opaque_environment_end(
                    visible, position, alias_env[1], aliases
                )
                continue
        if name in {"begin", "end"}:
            start = skip_tex_space(visible, position)
            end = group_end(visible, start)
            if start < len(text) and visible[start] == "{":
                environment = visible[start + 1 : end - 1]
                if environment == "document":
                    in_body = name == "begin"
                elif name == "begin" and environment in opaque:
                    end = opaque_environment_end(visible, end, environment, aliases)
                position = end
            continue
        if name in definitions:
            position = definition_end(visible, position, name)
            continue
        if not in_body:
            continue
        if match[0] == r"\texttt":
            start = skip_tex_space(visible, position)
            end = group_end(visible, start)
            if start >= len(text) or visible[start] != "{":
                continue
            body = text[start + 1 : end - 1]
            parts = []
            cursor = 0
            while part := token.match(body, cursor):
                raw = part[0]
                parts.append((raw, "_" if raw.startswith("\\") else raw))
                cursor = part.end()
            display = "".join(value for _, value in parts)
            if (
                cursor == len(body)
                and len(display) >= 24
                and any(char in display for char in "._")
                and re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", display
                )
            ):
                rewritten = "".join(
                    raw
                    + (
                        r"{\allowbreak}"
                        if index < len(parts) - 1 and value in "._"
                        else ""
                    )
                    for index, (raw, value) in enumerate(parts)
                )
                if rewritten != body:
                    changes.append((start + 1, end - 1, rewritten))
            position = end
        elif (
            name in OPAQUE_COMMAND | CODE_ARGUMENT_COMMANDS
            or name not in TEXT_COMMAND | FONT_SWITCHES | TEXT_DECLARATIONS
        ):
            position = args_end(visible, position)
    for start, end, value in reversed(changes):
        text = text[:start] + value + text[end:]
    return text


def use_bundled_bibliography(text: str, path: Path) -> str:
    """Use arXiv's ready .bbl when its BibTeX databases were not included."""
    bbl = path.with_suffix(".bbl")
    if not bbl.is_file() or r"\begin{thebibliography}" not in bbl.read_text(
        errors="replace", encoding="utf-8"
    ):
        return text
    for match in reversed(
        list(re.finditer(r"\\bibliography\s*\{([^}]+)\}", without_comments(text)))
    ):
        databases = [
            path.parent
            / (v.strip() if v.strip().endswith(".bib") else v.strip() + ".bib")
            for v in match.group(1).split(",")
        ]
        if any(not p.is_file() for p in databases):
            text = (
                text[: match.start()]
                + r"\input{"
                + bbl.name
                + "}"
                + text[match.end() :]
            )
    return text


def prepare_chinese(text: str, language: str, engine: str) -> str:
    if language == "English":
        return text
    # Font-only CJK support avoids changing section names, dates and template geometry.
    if "% texglot: adapted legacy CJK" not in text:
        for match in re.finditer(
            r"\\(?:usepackage|RequirePackage|documentclass)\s*(?:\[[^\]]*\]\s*)?\{([^}]+)\}",
            visible_tex(text),
        ):
            if any(
                re.fullmatch(r"ctex\w*|xeCJK|luatexja[^,]*", name.strip())
                for name in match[1].split(",")
            ):
                return text
    if language in ("日本語", "한국어"):
        font = "Hiragino Mincho ProN" if language == "日本語" else "AppleMyungjo"
        block = "\n\\usepackage{xeCJK}\n\\setCJKmainfont{" + font + "}\n"
    elif engine == "lualatex":
        block = r"""
\usepackage{luatexja-fontspec}
\setmainjfont{FandolSong-Regular.otf}[BoldFont=FandolSong-Bold.otf,ItalicFont=FandolKai-Regular.otf]
"""
    else:
        block = r"""
\usepackage{xeCJK}
\setCJKmainfont{FandolSong-Regular.otf}[BoldFont=FandolSong-Bold.otf,ItalicFont=FandolKai-Regular.otf]
\setCJKsansfont{FandolHei-Regular.otf}[BoldFont=FandolHei-Bold.otf]
\setCJKmonofont{FandolFang-Regular.otf}
\xeCJKsetup{AutoFallBack=true}
\setCJKfallbackfamilyfont{\CJKrmdefault}[Path=texglot-fonts/]{NotoSerifCJKsc-Regular.otf}
\setCJKfallbackfamilyfont{\CJKsfdefault}[Path=texglot-fonts/]{NotoSerifCJKsc-Regular.otf}
\setCJKfallbackfamilyfont{\CJKttdefault}[Path=texglot-fonts/]{NotoSerifCJKsc-Regular.otf}
"""
    # Add before document, after the author's packages; do not rewrite their preamble.
    block += "\\emergencystretch=2em\n"
    if language in ("简体中文", "繁體中文"):
        names = {
            "abstractname": "摘要",
            "refname": "参考文献" if language == "简体中文" else "參考文獻",
            "bibname": "参考文献" if language == "简体中文" else "參考文獻",
            "figurename": "图" if language == "简体中文" else "圖",
            "tablename": "表",
            "contentsname": "目录" if language == "简体中文" else "目錄",
        }
        block += (
            "\\AtBeginDocument{"
            + "".join(
                "\\def\\" + key + "{" + value + "}" for key, value in names.items()
            )
            + "}\n"
        )
    block += "\\AtBeginDocument{\\ifdefined\\hypersetup\\hypersetup{hidelinks}\\fi}\n"
    return inject_preamble(text, block)


def choose_compiler(preferred: str):
    found = available_compilers()
    if preferred != "auto":
        if not found.get(preferred):
            raise ValueError(f"未安装 {preferred}，请安装后重试或切换编译器")
        return preferred
    for name in ("tectonic", "xelatex", "lualatex"):
        if found[name]:
            return name
    raise ValueError(
        "未安装 LaTeX 编译器。请运行项目安装脚本，或安装 Tectonic / TeX Live 后重试"
    )


def validate_sources(root: Path, main: str | None = None):
    root = root.resolve()
    cwd = (root / main).parent if main else root
    for p in root.rglob("*"):
        if p.suffix.lower() not in (".tex", ".sty", ".cls", ".bib", ".bst"):
            continue
        text = visible_tex(p.read_text(errors="replace", encoding="utf-8"))
        # The compiler itself additionally runs in untrusted/no-shell-escape mode.
        for match in re.finditer(
            r"\\(?:input|include|includegraphics|openin|openout)(?![A-Za-z@])\s*(?:\[[^]]*\])?\s*(?:\{([^{}]*)\}|([^\s{}%]+))",
            text,
        ):
            name = (match[1] if match[1] is not None else match[2]).strip()
            absolute = re.match(r"/|~|[A-Za-z]:", name)
            # TeX input paths are resolved from the main document's working
            # directory. A parent segment is valid if it stays in the project.
            outside = ".." in Path(name).parts and not (
                cwd / name
            ).resolve().is_relative_to(root)
            if absolute or outside:
                raise ValueError(
                    f"{p.name} 引用了工程目录外的路径，请将依赖文件放入源码包并使用相对路径"
                )
        if re.search(r"\\(?:input|include)\s*\{?\s*\|", text):
            raise ValueError("源码包含外部命令输入，当前本地编译不支持")


def sandbox_command(cmd: list[str], root: Path, out: Path) -> list[str]:
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        return cmd
    cache = Path.home() / "Library/Caches/TectonicProject.Tectonic"
    cache.mkdir(parents=True, exist_ok=True)
    # Allow compiler resources and this job only. In particular settings.json,
    # browser profiles, SSH keys and other user documents are not readable.
    read = [
        str(root),
        str(out),
        str(cache),
        str(DATA / "tools"),
        str(Path.home() / "Library/Fonts"),
        tempfile.gettempdir(),
    ]
    write = [str(out), str(cache), tempfile.gettempdir(), "/dev"]
    tools = bundled_tools()
    if tools is not None:
        read.append(str(tools))
    profile = (
        "(version 1)\n(allow default)\n(deny file-read* (subpath "
        + json.dumps(str(Path.home()), ensure_ascii=False)
        + "))\n(deny file-write*)\n"
    )
    profile += (
        "(allow file-read* "
        + " ".join("(subpath " + json.dumps(p, ensure_ascii=False) + ")" for p in read)
        + ")\n"
    )
    profile += (
        "(allow file-write* "
        + " ".join("(subpath " + json.dumps(p, ensure_ascii=False) + ")" for p in write)
        + ")\n"
    )
    return ["/usr/bin/sandbox-exec", "-p", profile, *cmd]


def makefile_inputs(text: str) -> list[str] | None:
    """Read the first dependency rule, including Make's escaped filenames."""
    text = re.sub(r"\\\r?\n", " ", text)
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        separator = None
        i = 0
        while i < len(line):
            if line[i] == "\\" and i + 1 < len(line) and line[i + 1] in " \\#:\t":
                i += 2
                continue
            if line[i] == ":" and (i + 1 == len(line) or line[i + 1].isspace()):
                separator = i
                break
            i += 1
        if separator is None:
            return None
        values, current = [], []
        i = separator + 1
        while i < len(line):
            char = line[i]
            if char == "\\" and i + 1 < len(line) and line[i + 1] in " \\#:\t":
                current.append(line[i + 1])
                i += 2
                continue
            if char == "#":
                break
            if char.isspace():
                if current:
                    values.append("".join(current).replace("$$", "$"))
                    current = []
            else:
                current.append(char)
            i += 1
        if current:
            values.append("".join(current).replace("$$", "$"))
        return values
    return None


def tectonic_unescaped_inputs(text: str) -> list[str]:
    """Tectonic also emits unescaped names, one prerequisite per physical line."""
    values = []
    started = False
    for line in text.splitlines():
        if not started:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            separator = re.search(r"(?<!\\):(?=\s|$)", line)
            if separator is None:
                return []
            line = line[separator.end() :]
            started = True
        continued = line.endswith("\\")
        value = (line[:-1] if continued else line).strip()
        if value:
            values.append(value)
        if not continued:
            break
    return values


def compiled_dependencies(
    root: Path, main: str, out: Path, engine: str, *, include_eps: bool = False
) -> list[str] | None:
    """Return actual local TeX/package inputs, excluding outputs and bundle files."""
    root = root.resolve()
    cwd = (root / main).parent
    out = out.resolve()
    if engine == "tectonic":
        record = out / "dependencies.mk"
        if not record.is_file():
            return None
        content = record.read_text(encoding="utf-8", errors="replace")
        names = makefile_inputs(content)
        if names is None:
            return None
        names += tectonic_unescaped_inputs(content)
    else:
        record = out / (Path(main).stem + ".fls")
        if not record.is_file():
            return None
        lines = record.read_text(encoding="utf-8", errors="replace").splitlines()
        names = [line[6:] for line in lines if line.startswith("INPUT ")]
        if not names:
            return None
    files = set()
    extensions = {".tex", ".sty", ".cls"} | ({".eps"} if include_eps else set())
    for name in names:
        path = Path(name)
        candidates = [path] if path.is_absolute() else [cwd / path]
        # Tectonic writes relative input names under outdir in its Make rules,
        # even though those inputs were read relative to the main document.
        if engine == "tectonic":
            for value in (path, path.resolve()):
                if value.is_relative_to(out):
                    candidates.append(cwd / value.relative_to(out))
        for candidate in candidates:
            candidate = candidate.resolve()
            if (
                candidate.is_relative_to(root)
                and candidate.is_file()
                and candidate.suffix.lower() in extensions
            ):
                files.add(candidate.relative_to(root).as_posix())
                break
    if Path(main).as_posix() not in files:
        return None
    return sorted(files)


async def compile_pdf(
    root: Path, main: str, out: Path, engine: str, notify, timeout=420
) -> tuple[Path, list[str]]:
    return await _compile_document(root, main, out, engine, notify, timeout=timeout)


async def probe_source_dependencies(
    root: Path, main: str, out: Path, notify, timeout=420
) -> tuple[list[str], list[str]]:
    """Run TeX without its PDF driver to discover macro-selected EPS sources."""
    await _compile_document(
        root, main, out, "tectonic", notify, timeout=timeout, output_format="xdv"
    )
    inputs = compiled_dependencies(root, main, out, "tectonic", include_eps=True)
    if inputs is None:
        raise ValueError("编译依赖探测未生成有效记录，请检查源码工程")
    documents = [value for value in inputs if Path(value).suffix.lower() != ".eps"]
    images = [value for value in inputs if Path(value).suffix.lower() == ".eps"]
    return documents, images


async def _compile_document(
    root: Path,
    main: str,
    out: Path,
    engine: str,
    notify,
    timeout=420,
    output_format="pdf",
) -> tuple[Path, list[str]]:
    out.mkdir(parents=True, exist_ok=True)
    path = root / main
    validate_sources(root, main)
    # A successful no-page compile must not accidentally return an old PDF or
    # an old dependency graph left by an earlier attempt with the same basename.
    for stale in (
        out / (path.stem + ".pdf"),
        out / (path.stem + ".xdv"),
        out / (path.stem + ".fls"),
        out / "dependencies.mk",
    ):
        stale.unlink(missing_ok=True)
    if engine == "tectonic":
        bundle = os.environ.get(
            "TEXGLOT_TEX_BUNDLE",
            os.environ.get(
                "MOYI_TEX_BUNDLE",
                "https://data1b.fullyjustified.net/tlextras-2022.0r0.tar",
            ),
        )
        cmd = [
            find_compiler("tectonic"),
            "-X",
            "compile",
            "--untrusted",
            "--bundle",
            bundle,
            "--keep-logs",
            "--keep-intermediates",
            "--outfmt",
            output_format,
            "--makefile-rules",
            str(out / "dependencies.mk"),
            "--outdir",
            str(out),
            "--hide",
            str(CONFIG),
            "--hide",
            str(CONFIG.with_name("connections.json")),
            str(path),
        ]
    else:
        cmd = [
            find_compiler(engine),
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-recorder",
            f"-output-directory={out}",
            str(path),
        ]
    env = {
        k: v
        for k, v in child_environment().items()
        if not any(t in k.upper() for t in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    env.update(
        {
            "TECTONIC_UNTRUSTED_MODE": "1",
            "openin_any": "p",
            "openout_any": "p",
            "shell_escape": "f",
        }
    )
    # Classic engines resolve included files relative to the main document.
    cwd = path.parent
    logs = []
    for run in range(1 if engine == "tectonic" else 3):
        proc = await asyncio.create_subprocess_exec(
            *sandbox_command(cmd, root, out),
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **process_options(),
        )

        async def collect():
            chunks = []
            size = 0
            packages = 0
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                packages += chunk.count(b"note: downloading")
                if size < 8 * 1024 * 1024:
                    chunks.append(chunk)
                    size += len(chunk)
                if b"note: downloading" in chunk and packages % 10 == 1:
                    await notify(f"首次使用的宏包正在缓存到本机 · 已下载 {packages} 项")
            await proc.wait()
            return b"".join(chunks)

        try:
            output = await asyncio.wait_for(collect(), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await terminate_process_tree(proc)
            if asyncio.current_task().cancelling():
                raise
            raise ValueError(
                "编译超时，任务和译文已保存；可重试以复用已下载的宏包"
            ) from None
        log = output.decode(errors="replace")
        logs.append(log)
        (out / "compile.log").write_text("\n".join(logs), encoding="utf-8")
        if proc.returncode:
            hints = []
            for line in log.splitlines():
                if re.search(
                    r"error:|^!|not found|Emergency stop|Undefined control|Fatal",
                    line,
                    re.I,
                ):
                    hints.append(line)
            detail = "\n".join(hints[-5:])[:1000] or log[-800:]
            raise ValueError("LaTeX 编译未通过：" + detail)
        if (
            engine != "tectonic"
            and run == 0
            and (out / (path.stem + ".aux")).exists()
            and find_compiler("bibtex")
        ):
            aux = (out / (path.stem + ".aux")).read_text(
                errors="replace", encoding="utf-8"
            )
            if r"\bibdata" in aux:
                bibenv = env | {
                    "BIBINPUTS": str(cwd) + os.pathsep,
                    "BSTINPUTS": str(cwd) + os.pathsep,
                }
                bib = await asyncio.create_subprocess_exec(
                    *sandbox_command([find_compiler("bibtex"), path.stem], root, out),
                    cwd=out,
                    env=bibenv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    **process_options(),
                )
                try:
                    bout, _ = await asyncio.wait_for(bib.communicate(), 90)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    await terminate_process_tree(bib)
                    if asyncio.current_task().cancelling():
                        raise
                    raise ValueError("参考文献编译超时") from None
                logs.append(bout.decode(errors="replace"))
                if bib.returncode:
                    raise ValueError("参考文献编译失败，请检查 .bib 和 .bst 文件")
    if output_format == "xdv":
        xdv = out / (path.stem + ".xdv")
        if not xdv.is_file():
            raise ValueError("编译依赖探测未生成有效记录，请检查源码工程")
        return xdv, []
    pdf = out / (path.stem + ".pdf")
    if not pdf.exists() or pdf.stat().st_size < 100:
        raise ValueError("编译器未生成有效 PDF")
    from .pdf import embed_cjk_mappings

    embed_cjk_mappings(pdf)
    warnings = []
    # Tectonic's console omits citation details; its final TeX log is authoritative.
    tex_log = out / (path.stem + ".log")
    all_logs = "\n".join(logs) + (
        tex_log.read_text(errors="replace", encoding="utf-8")
        if tex_log.exists()
        else ""
    )
    if "Missing character:" in all_logs:
        warnings.append("编译日志报告缺失字形，请检查 PDF 中的特殊字符")
    if re.search(r"undefined references|Citation .+ undefined", all_logs, re.I):
        warnings.append("存在未解析的引用，请检查参考文献文件")
    if "TeXGlot-Float-Fit:" in all_logs:
        warnings.append("部分图表超出页高，已整体缩放以保留全部内容、标签和图表说明")
    if "Float too large for page" in all_logs:
        warnings.append("存在超出页高的浮动体，内容可能被裁切；请检查图表及编译日志")
    return pdf, warnings
