"""A deferred float must not leave negative glue between translated paragraphs."""

import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.compiler import (
    compile_pdf,
    find_compiler,
    normalize_float_spacing,
    prepare_chinese,
)


def test_only_external_literal_spacers_are_neutralized():
    source = r"""\documentclass{article}
\newcommand{\example}{\vspace{-4mm}\begin{figure}X\end{figure}\vspace{-5mm}}
\begin{document}
\vspace{-1mm}Unrelated paragraph spacing.
\vspace*{-4mm}
% Keep this explanation and paragraph boundaries.
\vspace{2pt}\vspace{-.5cm}
\begin{figure*}[tb]
\vspace{-3mm}\includegraphics{panel}\caption{Caption}\vspace{-2mm}
\end{figure*}
\vspace{- % Keep an argument comment too.
5mm}

Next paragraph.
\vspace{-4mm}\begin{table}[H]Fixed box.\end{table}\vspace{-5mm}
\vspace{-\baselineskip}\begin{figure}[p]Unknown length.\end{figure}
\end{document}
"""
    fixed, count = normalize_float_spacing(source)
    assert count == 3
    assert r"\vspace*{0pt}" in fixed
    assert r"\vspace{2pt}\vspace{0pt}" in fixed
    assert "0pt % Keep an argument comment too.\n" in fixed
    for preserved in (
        source.splitlines()[1],
        r"\vspace{-1mm}Unrelated paragraph spacing.",
        r"\vspace{-3mm}\includegraphics{panel}\caption{Caption}\vspace{-2mm}",
        r"\vspace{-4mm}\begin{table}[H]Fixed box.\end{table}\vspace{-5mm}",
        r"\vspace{-\baselineskip}\begin{figure}[p]Unknown length.\end{figure}",
    ):
        assert preserved in fixed
    assert fixed.count("\n") == source.count("\n")
    assert "\n\nNext paragraph." in fixed
    assert normalize_float_spacing(fixed) == (fixed, 0)


@pytest.mark.parametrize(
    "wrapper",
    [
        "% {}\n",
        r"\verb|{}|",
        "\\begin{{verbatim}}\n{}\n\\end{{verbatim}}",
        "\\begin{{lstlisting}}\n{}\n\\end{{lstlisting}}",
        r"\newcommand{{\demo}}{{{}}}",
        r"\def\demo#1{{{}}}",
        r"\newenvironment{{demo}}{{{}}}{{}}",
        r"$\text{{{}}}$",
    ],
)
def test_examples_math_and_definitions_are_untouched(wrapper):
    source = wrapper.format(r"\vspace{-4mm}\begin{figure}X\end{figure}\vspace{-5mm}")
    assert normalize_float_spacing(source) == (source, 0)


@pytest.mark.parametrize(
    "barrier",
    [r"\verb|example|", r"\begin{verbatim}example\end{verbatim}", r"\label{x}", "Text"],
)
def test_adjacency_does_not_jump_over_other_content(barrier):
    source = r"\vspace{-4mm}" + barrier + r"\begin{figure}X\end{figure}"
    source += barrier + r"\vspace{-5mm}"
    assert normalize_float_spacing(source) == (source, 0)


def test_linebreaks_and_optional_spacing_are_not_math_or_spacing_commands():
    source = (
        r"\documentclass{article}\newcommand{\heading}{Title\\[0.5em]Subtitle}"
        r"\begin{document}First line\\[2pt]Second line."
        r"\vspace{-4mm}\begin{figure}X\end{figure}\vspace{-5mm}"
        r"\end{document}"
    )
    fixed, count = normalize_float_spacing(source)
    assert count == 2
    assert (
        source.replace(r"\vspace{-4mm}", r"\vspace{0pt}").replace(
            r"\vspace{-5mm}", r"\vspace{0pt}"
        )
        == fixed
    )
    literal = r"\\vspace{-4mm}\begin{figure}X\end{figure}\\vspace{-5mm}"
    assert normalize_float_spacing(literal) == (literal, 0)
    definition = r"\def\openmath{\[}"
    body = r"\vspace{-4mm}\begin{figure}X\end{figure}\vspace{-5mm}"
    assert normalize_float_spacing(definition + body) == (
        definition + body.replace("-4mm", "0pt").replace("-5mm", "0pt"),
        2,
    )


def test_math_ranges_follow_control_sequences_and_escaped_dollars():
    from app.latex import math_regions

    source = (
        r"A\\[2pt]B \$5 \\$x$ \(y\) \[z\] $$a$$ "
        r"\begin{align}b&=c\\[1pt]d&=e\end{align}"
    )
    assert [source[a:b] for a, b in math_regions(source)] == [
        r"$x$",
        r"\(y\)",
        r"\[z\]",
        r"$$a$$",
        r"\begin{align}b&=c\\[1pt]d&=e\end{align}",
    ]


def token_positions(pdf):
    positions = {}
    for number, page in enumerate(PdfReader(pdf).pages):

        def visit(text, cm, tm, _font, _size):
            for token in (
                "BeforeOne",
                "BeforeTwo",
                "BeforeThree",
                "AfterOne",
                "AfterTwo",
                "FloatToken",
            ):
                if token in text:
                    assert token not in positions
                    positions[token] = (number, tm[4] * cm[1] + tm[5] * cm[3] + cm[5])

        page.extract_text(visitor_text=visit)
    assert len(positions) == 6
    return positions


@pytest.mark.parametrize(
    "environment,columns,language",
    [
        ("figure", "", "English"),
        ("table", "", "简体中文"),
        ("figure*", "twocolumn", "English"),
        ("table*", "twocolumn", "English"),
    ],
)
async def test_deferred_float_keeps_paragraphs_separate_in_real_pdf(
    tmp_path, environment, columns, language
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    content = (
        "正文翻译后的段落。" if language != "English" else "A translated paragraph."
    )
    source = (
        rf"\documentclass[{columns}]{{article}}"
        + r"\begin{document}"
        + "\n"
        + rf"\noindent BeforeOne {content}\\BeforeTwo {content}\\BeforeThree {content}\par"
        + "\n"
        + r"\vspace{-4mm}"
        + rf"\begin{{{environment}}}[p]\centering\rule{{20pt}}{{20pt}}\caption{{FloatToken}}\end{{{environment}}}"
        + r"\vspace{-5mm}"
        + "\n\n"
        + rf"\noindent AfterOne {content}\\AfterTwo {content}\par"
        + r"\end{document}"
    )
    if language != "English":
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "app/resources/fonts",
            root / "texglot-fonts",
        )
    fixed, count = normalize_float_spacing(source)
    assert count == 2
    positions = []

    async def notify(_):
        pass

    for name, text in (("before", source), ("after", fixed)):
        (root / "main.tex").write_text(
            prepare_chinese(text, language, "tectonic"), encoding="utf-8"
        )
        pdf, warnings = await compile_pdf(
            root, "main.tex", tmp_path / name, "tectonic", notify
        )
        assert not warnings  # The original bug compiled successfully too.
        points = token_positions(pdf)
        assert all(points[token][0] == 0 for token in points if token != "FloatToken")
        assert points["FloatToken"][0] > 0
        positions.append(points)
    # Before the fix, the second paragraph starts above the preceding last line.
    assert positions[0]["BeforeThree"][1] < positions[0]["AfterOne"][1]
    assert positions[1]["BeforeThree"][1] - positions[1]["AfterOne"][1] >= 11.5
    # Earlier paragraphs retain their coordinates exactly; only the gap changes.
    for token in ("BeforeOne", "BeforeTwo", "BeforeThree"):
        assert positions[0][token] == pytest.approx(positions[1][token], abs=0.02)
