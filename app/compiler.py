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
from .sources import TEX_SOURCE_SUFFIXES, decode_tex, visible_tex, without_comments


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


XETEX_COMPATIBILITY = r"""% texglot: native XeTeX font and PDF-driver capabilities
\AddToHook{package/microtype/after}{%
\DeclareMicrotypeSet{texglot-native}{encoding={TU,EU1,EU2}}%
\UseMicrotypeSet[protrusion]{texglot-native}%
}
% breakurl already has a native-PDF branch; limit its PDF-mode override to loading.
\AddToHook{package/breakurl/before}{%
\RequirePackage{xkeyval,ifpdf}%
\let\TeXGlotSavedIfpdf\ifpdf\let\ifpdf\iftrue
}
\AddToHook{package/breakurl/after}{\let\ifpdf\TeXGlotSavedIfpdf}
% This class's optional arXiv check assumes every non-pdfTeX engine writes DVI.
\PassOptionsToClass{nopdfoutputerror,allowfontchageintitle}{quantumarticle}
% Embedded PostScript can silently disappear with restricted XeTeX drivers.
% Record actual drawing operations; merely loading an unused package is harmless.
\AddToHook{package/pstricks/after}{%
\ifcsname pst@object\endcsname
\expandafter\let\expandafter\TeXGlotPstObject\csname pst@object\endcsname
\expandafter\def\csname pst@object\endcsname#1{%
\typeout{TeXGlot-PostScript-object: #1}\TeXGlotPstObject{#1}}%
\fi
}
"""


TECTONIC_FONT_COMPATIBILITY = r"""% texglot: vector double-stroke fonts; Tectonic cannot generate PK fonts
\AddToHook{package/bbm/after}{%
\SetMathAlphabet{\mathbbm}{normal}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbm}{bold}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbmss}{normal}{U}{dsss}{m}{n}%
\SetMathAlphabet{\mathbbmss}{bold}{U}{dsss}{m}{n}%
\SetMathAlphabet{\mathbbmtt}{normal}{U}{dsrom}{m}{n}%
\SetMathAlphabet{\mathbbmtt}{bold}{U}{dsrom}{m}{n}%
}
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
        re.search(r"\\begin\s*\{(?:figure|table)\*?\}", text)
        for text in visible.values()
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
        if path.is_file() and path.suffix.lower() in TEX_SOURCE_SUFFIXES
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
        text = normalize_pdftex_features(text, engine)
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
            and XETEX_COMPATIBILITY not in text
        ):
            text = XETEX_COMPATIBILITY + text
        if (
            engine == "tectonic"
            and re.search(r"\\begin\s*\{document\}", visible)
            and TECTONIC_FONT_COMPATIBILITY not in text
        ):
            text = TECTONIC_FONT_COMPATIBILITY + text
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

        for match in reversed(
            list(
                re.finditer(
                    r"(\\(?:usepackage|RequirePackage)\s*)\[([^]]+)\](\s*\{(?:hyperref|graphicx|graphics|color|xcolor)\})",
                    visible_tex(text),
                )
            )
        ):
            # A masked view locates tokens; copying it back would turn comment
            # lines into blank lines and break multiline package arguments.
            for option in reversed(
                list(re.finditer(r"(?:^|,)\s*(pdftex)\s*(?=,|$)", match[2]))
            ):
                start = match.start(2) + option.start(1)
                end = match.start(2) + option.end(1)
                text = text[:start] + "xetex" + text[end:]
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


def normalize_pdftex_features(text: str, engine: str) -> str:
    """Drop unsupported output/typography controls, retaining document content.

    XeTeX writes through xdvipdfmx; pdfTeX compression and glyph-map settings
    cannot configure that backend. Microtype's ligature control likewise has no
    XeTeX implementation. The bundled 2022 microtype also lacks XeTeX tracking.
    Apply the same capability policy in documents and author-supplied packages.
    """
    from .latex import group_end

    visible = visible_tex(text)
    edits = []
    for match in re.finditer(
        r"(?:\\global\s*)?\\pdf(?:compresslevel|objcompresslevel|minorversion|majorversion|optionpdfminorversion|gentounicode)\s*=?\s*\d+\b"
        r"|\\input\s*(?:\{glyphtounicode(?:\.tex)?\}|glyphtounicode(?:\.tex)?\b)",
        visible,
    ):
        edits.append((match.start(), match.end(), ""))
    for match in re.finditer(r"\\DisableLigatures\s*(?:\[[^]]*\]\s*)?\{", visible):
        end = group_end(text, match.end() - 1)
        edits.append((match.start(), end, ""))
    unsupported = {"expansion", "spacing", "kerning"}
    if engine == "tectonic":
        unsupported.add("tracking")
    for pattern in (
        r"\\(?:usepackage|RequirePackage)\s*\[([^]]*)\]\s*\{microtype\}",
        r"\\PassOptionsToPackage\s*\{([^{}]*)\}\s*\{microtype\}",
        r"\\microtypesetup\s*\{([^{}]*)\}",
    ):
        for match in re.finditer(pattern, visible):
            options = text[match.start(1) : match.end(1)]
            for option in re.finditer(
                r"(?:^|,)\s*([A-Za-z]+)(?:\s*=\s*([^,]*))?", options
            ):
                if option[1] in unsupported and (option[2] or "").strip() != "false":
                    start = match.start(1) + option.start(1)
                    end = match.start(1) + option.end()
                    edits.append((start, end, option[1] + "=false"))
    for start, end, replacement in sorted(edits, reverse=True):
        # Keep source line numbers stable for diagnostics and content mapping.
        replacement += "\n" * (text[start:end].count("\n") - replacement.count("\n"))
        text = text[:start] + replacement + text[end:]
    return text


def prepare_engine_sources(root: Path, engine: str) -> None:
    """Adapt author-supplied TeX packages as well as the document entry points."""
    if engine == "tectonic":
        # Prefer the author's classes. Supply complete, pinned upstream runtime
        # classes only where the fixed Tectonic bundle ships an obsolete alias.
        for resource in (Path(__file__).parent / "resources/tex").glob("*.cls"):
            if any(root.rglob(resource.name)):
                continue
            for document in root.rglob("*.tex"):
                if re.search(
                    rf"\\documentclass\s*(?:\[[^]]*\]\s*)?\{{{re.escape(resource.stem)}\}}",
                    visible_tex(document.read_text(encoding="utf-8")),
                ):
                    (document.parent / resource.name).write_bytes(resource.read_bytes())
    normalized = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEX_SOURCE_SUFFIXES:
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
    """Fit complete table boxes, preserving caption/notes measurement scopes."""
    count = 0
    visible = visible_tex(text)
    for match in reversed(
        list(re.finditer(r"\\begin\s*\{(table\*?)\}.*?\\end\s*\{\1\}", visible, re.S))
    ):
        body = text[match.start() : match.end()]
        shown = visible[match.start() : match.end()]
        if re.search(r"\\resizebox\b|\\begin\s*\{adjustbox\}", shown):
            continue
        pairs = []
        start = None
        stack = []
        for token in re.finditer(
            r"\\(begin|end)\s*\{(tabular\*?|threeparttable)\}", shown
        ):
            if token.group(1) == "begin":
                if not stack:
                    start = token.start()
                stack.append(token.group(2))
            elif stack and stack[-1] == token.group(2):
                stack.pop()
                if (
                    not stack
                    and start is not None
                    and re.search(
                        r"\\begin\s*\{tabular\*?\}", shown[start : token.end()]
                    )
                ):
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
        text = text[: match.start()] + body + text[match.end() :]
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
        math_opening,
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
        opening = math_opening(value)
        if opening in (r"\(", r"\[", "$", "$$"):
            position = math_end(visible, position, value, aliases)
            continue
        if alias_env := re.fullmatch(r"\\begin\{([^{}]+)\}", opening):
            if alias_env[1] in opaque:
                position = math_end(visible, position, value, aliases)
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
    block += "\\AtBeginDocument{\\ifdefined\\hypersetup\\hypersetup{colorlinks=false,pdfborder={0 0 0}}\\fi}\n"
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
    for path, _, message in source_path_violations(root, main):
        raise ValueError(f"{path.name} {message}")


def rebase_project_paths(root: Path, main: str) -> list[str]:
    """Recover misplaced parent prefixes only when the exact asset is in the archive."""
    root = root.resolve()
    cwd = (root / main).parent
    changes = {}
    for path, match, _ in source_path_violations(root, main):
        if not match[0].startswith((r"\input", r"\include")):
            continue
        group = 1 if match[1] is not None else 2
        name = match[group].strip()
        if not name.startswith("../") or re.search(r"[\\#{}~]", name):
            continue
        while name.startswith("../"):
            name = name[3:]
        candidate = (root / name).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            relative = Path(os.path.relpath(candidate, cwd)).as_posix()
            changes.setdefault(path, []).append((*match.span(group), relative))
    locations = []
    for path, edits in changes.items():
        text = path.read_text(encoding="utf-8")
        for start, end, relative in reversed(edits):
            locations.append(
                f"{path.relative_to(root)}:{text.count(chr(10), 0, start) + 1}"
            )
            text = text[:start] + relative + text[end:]
        path.write_text(text, encoding="utf-8")
    return sorted(locations)


def source_path_violations(root: Path, main: str | None = None):
    root = root.resolve()
    cwd = (root / main).parent if main else root
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEX_SOURCE_SUFFIXES | {
            ".bib",
            ".bst",
            ".bbl",
        }:
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
            if absolute or outside or name.startswith("|"):
                message = (
                    "源码包含外部命令输入，当前本地编译不支持"
                    if name.startswith("|")
                    else "引用了工程目录外的路径，请将依赖文件放入源码包并使用相对路径"
                )
                yield p, match, message


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
    # An explicitly configured data directory may live outside the user's home,
    # including inside system temp. Keep other jobs and credentials private even
    # there, while allowing this compilation and installed compiler resources.
    profile += (
        "(deny file-read* (require-all (subpath "
        + json.dumps(str(DATA), ensure_ascii=False)
        + ") "
        + " ".join(
            "(require-not (subpath " + json.dumps(str(p), ensure_ascii=False) + "))"
            for p in (root, out, DATA / "tools")
        )
        + "))\n"
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
    extensions = TEX_SOURCE_SUFFIXES | ({".eps"} if include_eps else set())
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
    return await _compile_with_recovery(
        root, main, out, engine, notify, timeout=timeout
    )


async def probe_source_dependencies(
    root: Path, main: str, out: Path, notify, timeout=420
) -> tuple[list[str], list[str]]:
    """Run TeX without its PDF driver to discover macro-selected EPS sources."""
    await _compile_with_recovery(
        root, main, out, "tectonic", notify, timeout=timeout, output_format="xdv"
    )
    inputs = compiled_dependencies(root, main, out, "tectonic", include_eps=True)
    if inputs is None:
        raise ValueError("编译依赖探测未生成有效记录，请检查源码工程")
    documents = [value for value in inputs if Path(value).suffix.lower() != ".eps"]
    images = [value for value in inputs if Path(value).suffix.lower() == ".eps"]
    return documents, images


class CompilationError(ValueError):
    def __init__(self, message: str, log: str):
        super().__init__(message)
        self.log = log


def recover_compile_configuration(
    root: Path, main: str, error: CompilationError
) -> str:
    """Use concrete compiler diagnostics to repair a late package configuration."""
    from .latex import math_regions

    document = root / main
    source = document.read_text(encoding="utf-8")
    visible = visible_tex(source)
    # Some dual-engine templates offer classic pdfTeX mathematics but
    # automatically load unicode-math on XeTeX. If the latter fails on legacy
    # math macros, retain the author's classic math route and Unicode text.
    # Explicit Unicode math fonts, commands, and input are never downgraded.
    if (
        "__um_group_begin:" in error.log
        or "Extended mathchar used as mathchar" in error.log
    ):
        branch = re.search(
            r"\\ifPDFTeX\b(?:(?!\\(?:else|fi|if[A-Za-z]*)\b).)*\\else\b"
            r"\s*\\usepackage\s*\{(unicode-math)\}",
            visible,
            re.S,
        )
        context = "\n".join(
            visible_tex(p.read_text(encoding="utf-8"))
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in TEX_SOURCE_SUFFIXES
        )
        explicit = re.search(
            r"\\(?:setmathfont\w*|unimathsetup|sym[A-Za-z]+|Umath[A-Za-z]*)\b", context
        )
        native_symbols = any(
            ord(c) > 127 for a, b in math_regions(context) for c in context[a:b]
        )
        if branch and not explicit and not native_symbols:
            start, end = branch.span(1)
            document.write_text(
                source[:start] + "fontspec" + source[end:], encoding="utf-8"
            )
            return "模板提供的传统数学排版模式"
    package, options = "", ""
    if "Bibliography not compatible with author-year citations" in error.log:
        package, options = "natbib", "numbers"
    elif clash := re.search(r"Option clash for package ([A-Za-z0-9_-]+)", error.log):
        package = clash[1]
        locations = re.findall(r"(?:^|\n)error: (.+?):\d+:", error.log)
        for filename in locations:
            path = ((root / main).parent / filename).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                continue
            original = path.read_text(encoding="utf-8")
            for match in re.finditer(
                rf"\\(?:usepackage|RequirePackage)\s*\[([^]]*)\]\s*\{{{re.escape(package)}\}}",
                visible_tex(original),
            ):
                option = " ".join(match[1].split())
                if option and re.fullmatch(r"[A-Za-z0-9_,=.+ -]+", option):
                    options = ",".join(filter(None, [options, option]))
    if not package or not options:
        return ""
    command = rf"\PassOptionsToPackage{{{options}}}{{{package}}}"
    if command in visible_tex(source):
        return ""
    document.write_text(
        "% texglot: package options resolved from compiler diagnostics\n"
        + command
        + "\n"
        + source,
        encoding="utf-8",
    )
    return f"{package} 宏包选项"


async def _compile_with_recovery(root, main, out, engine, notify, **options):
    for attempt in range(3):
        try:
            return await _compile_document(root, main, out, engine, notify, **options)
        except CompilationError as exc:
            if attempt == 2 or not (
                change := recover_compile_configuration(root, main, exc)
            ):
                raise
            await notify(f"已按编译诊断调整 {change}，正在重试")


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
    # Auxiliary files contain executable TeX tied to a particular template and
    # driver. A new compilation must not load leftovers from a previous run;
    # keep them only between passes of this invocation.
    for generated in out.rglob("*"):
        if generated.is_file() and (
            generated.suffix
            in {
                ".aux",
                ".toc",
                ".lof",
                ".lot",
                ".out",
                ".bbl",
                ".blg",
                ".bcf",
                ".nav",
                ".snm",
            }
            or generated.name.endswith(".run.xml")
        ):
            generated.unlink()
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
            raise CompilationError("LaTeX 编译未通过：" + detail, log)
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
    # Earlier passes normally contain unresolved references. Report only the
    # final pass; keep every pass in compile.log for debugging.
    tex_log = out / (path.stem + ".log")
    final_log = (
        tex_log.read_text(errors="replace", encoding="utf-8")
        if tex_log.exists()
        else logs[-1]
    )
    if engine in {"tectonic", "xelatex"} and "TeXGlot-PostScript-object:" in final_log:
        raise ValueError(
            "当前受限编译器不支持内嵌 PSTricks 绘图，图形可能缺失；请先将图形转换为 PDF 后重新上传源码"
        )
    if "Missing character:" in final_log:
        warnings.append("编译日志报告缺失字形，请检查 PDF 中的特殊字符")
    if re.search(r"undefined references|Citation .+ undefined", final_log, re.I):
        warnings.append("存在未解析的引用，请检查参考文献文件")
    if "TeXGlot-Float-Fit:" in final_log:
        warnings.append("部分图表超出页高，已整体缩放以保留全部内容、标签和图表说明")
    if "Float too large for page" in final_log:
        warnings.append("存在超出页高的浮动体，内容可能被裁切；请检查图表及编译日志")
    return pdf, warnings
