"""Break opportunities preserve literal API spelling and avoid page overflow."""

import re

import pytest
from pypdf import PdfReader

from app.compiler import break_long_code_identifiers, compile_pdf, find_compiler


@pytest.mark.parametrize("underscore", [r"\_", r"\textunderscore "])
def test_literal_long_code_adds_only_invisible_breaks(underscore):
    source = r"A \texttt{scipy.optimize.differential" + underscore + "evolution} call."
    output = break_long_code_identifiers(source)
    assert r"scipy.{\allowbreak}optimize.{\allowbreak}" in output
    assert output.replace(r"{\allowbreak}", "") == source
    assert break_long_code_identifiers(output) == output


@pytest.mark.parametrize(
    "source",
    [
        r"\texttt{short.name}",
        r"\texttt{123456789012345678901234.5}",
        r"\texttt{scipy.optimize.\authorMacro{value}}",
        r"\texttt{scipy.{\allowbreak}optimize.differential\_evolution}",
        r"\texttt{scipy.optimize.differential\_evolution(arg=1)}",
        r"\texttt*{scipy.optimize.differential\_evolution}",
        r"% \texttt{scipy.optimize.differential\_evolution}",
        r"\verb|\texttt{scipy.optimize.differential\_evolution}|",
        r"\begin{lstlisting}\texttt{scipy.optimize.differential\_evolution}\end{lstlisting}",
        r"\begin{code}\texttt{scipy.optimize.differential\_evolution}\end{code}",
        r"$\texttt{scipy.optimize.differential\_evolution}$",
        r"\begin{equation}\texttt{scipy.optimize.differential\_evolution}\end{equation}",
        r"\newcommand{\example}{\texttt{scipy.optimize.differential\_evolution}}",
        r"\unknown{\texttt{scipy.optimize.differential\_evolution}}",
        r"\documentclass{article}\title{\texttt{scipy.optimize.differential\_evolution}}\begin{document}Body.\end{document}",
    ],
)
def test_complex_code_math_and_metadata_are_unchanged(source):
    assert break_long_code_identifiers(source) == source


def test_math_alias_context_keeps_literal_code_untouched():
    source = r"\be\texttt{scipy.optimize.differential\_evolution}\ee"
    aliases = {"be": r"\begin{equation}", "ee": r"\end{equation}"}
    assert break_long_code_identifiers(source, math_aliases=aliases) == source


async def test_native_narrow_column_preserves_exact_scipy_identifier(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    main = root / "main.tex"
    source = (
        r"\documentclass{article}\begin{document}"
        r"\parbox{90pt}{\texttt{scipy.optimize.differential\textunderscore evolution}}"
        r"\end{document}"
    )

    async def notify(_):
        pass

    main.write_text(source, encoding="utf-8")
    await compile_pdf(root, "main.tex", tmp_path / "before", "tectonic", notify)
    assert r"Overfull \hbox" in (tmp_path / "before/main.log").read_text(
        encoding="utf-8"
    )
    main.write_text(break_long_code_identifiers(source), encoding="utf-8")
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "after", "tectonic", notify
    )
    log = (tmp_path / "after/main.log").read_text(encoding="utf-8")
    assert r"Overfull \hbox" not in log
    assert not warnings
    text = "".join(page.extract_text() for page in PdfReader(pdf).pages)
    assert "scipy.optimize.differential_evolution" in re.sub(r"\s+", "", text)
    assert "differential__evolution" not in text
