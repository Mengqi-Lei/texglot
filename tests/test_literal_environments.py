"""Printed code remains literal across source discovery and translation/layout."""

import pytest

from app.compiler import (
    break_long_code_identifiers,
    fit_tables,
    normalize_engine,
    normalize_float_spacing,
    prepare_engine_sources,
)
from app.latex import MARKER, apply_translations, input_references, segments
from app.paper_context import extract_paper_context
from app.sources import collect_literal_environments, visible_tex


@pytest.mark.parametrize(
    "declaration",
    [
        r"\newtcblisting{examplebox}[2]{listing only,title={#2}}",
        r"\renewtcblisting[auto counter]{examplebox}[1][default]{listing only}",
        r"\NewTCBListing{examplebox}{O{default} m}{listing only}",
        r"\lstnewenvironment{examplebox}[1][]{\lstset{#1}}{}",
        r"\DefineVerbatimEnvironment{examplebox}{Verbatim}{fontsize=\small}",
    ],
)
def test_explicit_listing_declarations_preserve_literal_bodies(declaration):
    block = "\\begin{examplebox}{label}{Title}\n```choice\n# Keep 100% and {unbalanced\n\\input{printed-only}\n% \\end{examplebox}\n"
    source = (
        declaration
        + "\n\\begin{document}\nScientific prose before.\n"
        + block
        + "Scientific prose after.\n\\end{document}"
    )
    assert collect_literal_environments(source) == {"examplebox"}
    items = segments(source)
    for item in items:
        item.validate_source_map()
    assert (
        apply_translations(source, items, {s.key: s.restore(s.masked) for s in items})
        == source
    )
    exposed = "\n".join(MARKER.sub("", s.masked) for s in items)
    assert "before" in exposed and "after" in exposed
    assert "choice" not in exposed and "printed-only" not in exposed
    shown = visible_tex(source)
    assert len(shown) == len(source)
    assert [i for i, c in enumerate(shown) if c == "\n"] == [
        i for i, c in enumerate(source) if c == "\n"
    ]
    assert "printed-only" not in shown


def test_listing_discovery_ignores_printed_commented_and_nested_declarations():
    printed = r"\newtcblisting{fakebox}{listing only}"
    real = r"\newtcblisting{realbox}{listing only}"
    example = "\\begin{realbox}\n" + printed + "\n\\end{realbox}\n"
    noise = (
        "% "
        + printed
        + "\n\\verb|"
        + printed
        + "|\n"
        + r"\newcommand{\example}{"
        + printed
        + "}\n"
    )
    for context in (real + example + noise, example + noise + real):
        assert collect_literal_environments(context) == {"realbox"}
    assert collect_literal_environments(r"\newtcblisting{broken}{unterminated") == set()


def test_ordinary_boxes_still_translate_and_generated_fences_still_fail():
    source = r"\newtcolorbox{promptbox}[1]{title={#1}}\begin{document}\begin{promptbox}{Title}Translate this prose.\end{promptbox}\end{document}"
    assert collect_literal_environments(source) == set()
    item = next(s for s in segments(source) if "Translate this prose" in s.source)
    assert "Translate this prose" in item.masked
    with pytest.raises(ValueError, match="无效格式"):
        item.restore("```An unsolicited fenced answer.```")


def test_inherited_listing_context_preserves_preparation_and_layout(tmp_path):
    declaration = r"\newtcblisting{promptbox}[2]{listing only,title={#2}}"
    block = r"""\begin{promptbox}{id}{Printed example}
```choice
% \input{false}
\pdfinfo{/Title (Printed metadata)}
\usefont{OT1}{phv}{m}{n}
\vspace{-12pt}
\begin{table}[Q]\begin{tabular}{ll}example & 2\\\end{tabular}\end{table}
\texttt{a\_very\_long\_printed\_identifier\_here}
\usepackage{fontenc}
\end{promptbox}
"""
    body = "Prose before.\n" + block + "Prose after.\n"
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\input{defs}\begin{document}\input{body}\end{document}"
    )
    (tmp_path / "defs.tex").write_text(declaration)
    (tmp_path / "body.tex").write_text(body)
    known = collect_literal_environments(declaration)
    assert input_references(body, literal_environments=known) == []
    assert normalize_engine(body, "tectonic", literal_environments=known) == body
    assert fit_tables(body, literal_environments=known) == (body, 0)
    assert normalize_float_spacing(body, literal_environments=known) == (body, 0)
    assert break_long_code_identifiers(body, literal_environments=known) == body
    prepare_engine_sources(tmp_path, "tectonic")
    assert block in (tmp_path / "body.tex").read_text()
    items = segments(body, literal_environments=known)
    output = apply_translations(
        body, items, {s.key: s.target_probe("简体中文") for s in items}
    )
    assert block in output and "Prose" not in output.replace(block, "")


def test_printed_abstract_cannot_override_real_paper_context(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\input{body}\end{document}"
    )
    (tmp_path / "body.tex").write_text(
        r"\begin{promptbox}\begin{abstract}Fabricated abstract.\end{abstract}\end{promptbox}\begin{abstract}Actual scientific abstract.\end{abstract}"
    )
    context = extract_paper_context(
        tmp_path, "main.tex", literal_environments=frozenset({"promptbox"})
    )
    assert "Actual scientific abstract" in context and "Fabricated" not in context
