"""Fit the actual measurement owner, including containers hidden in classes."""

import pytest
from pypdf import PdfReader

from app.compiler import (
    TABLE_FITTING,
    compile_pdf,
    find_compiler,
    fit_tables,
    inject_preamble,
)


async def notify(_):
    pass


@pytest.mark.parametrize("owner", ["plain", "explicit", "class"])
async def test_wide_table_keeps_caption_notes_and_references_inside_page(
    tmp_path, owner
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    measured = owner != "plain"
    if owner == "class":
        # No measurement environment appears in the document. The class adds it
        # indirectly through another environment, as journal templates can do.
        (root / "fixture.cls").write_text(
            r"""\ProvidesClass{fixture}
\LoadClass{article}
\RequirePackage{threeparttable}
\let\savedtable\table\let\endsavedtable\endtable
\newenvironment{TableShell}{\begin{threeparttable}}{\end{threeparttable}}
\renewenvironment{table}[1][]{\begin{savedtable}[#1]\begin{TableShell}}
{\end{TableShell}\end{savedtable}}
""",
            encoding="utf-8",
        )
    documentclass = "fixture" if owner == "class" else "article"
    source = (
        r"\documentclass{"
        + documentclass
        + "}\n"
        + (r"\usepackage{threeparttable}" if measured else "")
        + r"""
\usepackage{booktabs}
\begin{document}
See Table~\ref{measured}.
\begin{table}[p]
\centering
"""
        + (r"\begin{threeparttable}" if owner == "explicit" else "")
        + r"""
\caption{CaptionToken: A complete measured table.}\label{measured}
\begin{tabular}{lll}
\toprule LeftToken & \rule{480pt}{1pt} & RightToken \\
ValueToken & $E=mc^2$ & 42 \\
\bottomrule
\end{tabular}
"""
        + (
            r"\begin{tablenotes}\item NoteToken: The measured notes survive.\end{tablenotes}"
            if measured
            else r"\par NoteToken: The notes survive."
        )
        + (r"\end{threeparttable}" if owner == "explicit" else "")
        + r"""
\end{table}
\begin{table}[p]\centering
\caption{SmallCaption}\begin{tabular}{ll}SmallToken & 7\end{tabular}
\end{table}
\end{document}
"""
    )
    fixed, count = fit_tables(source)
    assert count == 2
    assert fit_tables(fixed) == (fixed, 0)
    (root / "main.tex").write_text(
        inject_preamble(fixed, TABLE_FITTING), encoding="utf-8"
    )
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert not warnings
    tokens = [
        "CaptionToken",
        "LeftToken",
        "RightToken",
        "ValueToken",
        "NoteToken",
        "SmallCaption",
        "SmallToken",
    ]
    positions = {token: [] for token in tokens}
    texts = []
    for page in PdfReader(pdf).pages:

        def visit(value, cm, tm, _font, _size):
            for token in tokens:
                if token in value:
                    x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                    y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                    positions[token].append((x, y))
                    assert 0 < x < float(page.mediabox.width), (token, x)
                    assert 0 < y < float(page.mediabox.height), (token, y)

        texts.append(page.extract_text(visitor_text=visit))
    text = " ".join(" ".join(texts).split())
    assert "See Table 1." in text
    for token in tokens:
        assert text.count(token) == 1
        assert len(positions[token]) == 1
    assert "42" in text


async def test_already_fitting_table_retains_text_positions(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    source = r"""\documentclass{article}
\begin{document}\begin{table}[p]\centering
\caption{CaptionToken}\begin{tabular}{ll}LeftToken & RightToken\end{tabular}
\end{table}\end{document}"""
    results = []
    for name, text in [
        ("before", source),
        ("after", inject_preamble(fit_tables(source)[0], TABLE_FITTING)),
    ]:
        (root / "main.tex").write_text(text, encoding="utf-8")
        pdf, warnings = await compile_pdf(
            root, "main.tex", tmp_path / name, "tectonic", notify
        )
        assert not warnings
        points = []

        def visit(value, cm, tm, _font, _size):
            if "Token" in value:
                points.extend(
                    [
                        tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                        tm[4] * cm[1] + tm[5] * cm[3] + cm[5],
                    ]
                )

        for page in PdfReader(pdf).pages:
            page.extract_text(visitor_text=visit)
        results.append(points)
    assert results[0]
    assert results[1] == pytest.approx(results[0], abs=0.02)
