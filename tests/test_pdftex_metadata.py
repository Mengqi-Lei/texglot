"""PDF-only engine settings must not block or consume paper content."""

import pytest
from pypdf import PdfReader

from app import compiler


@pytest.mark.parametrize("engine", ["tectonic", "xelatex"])
@pytest.mark.parametrize("assignment", [" 1", "=+1", "\n% a setting\n = -1"])
def test_metadata_arguments_are_removed_without_changing_content(engine, assignment):
    source = (
        "% \\pdfinfoomitdate 1 and \\pdftrailerid{example}\n"
        + "\\global\\pdfinfoomitdate"
        + assignment
        + "\n"
        + r"""\pdftrailerid{seed{nested}\}value% a literal closing brace }
continued}
\pdfinfo{/Title (Example) {\pdfinfoomitdate=1} \microtypesetup{expansion=true}}
\verb|\pdftrailerid{literal}|
\begin{verbatim}\pdfinfoomitdate 1\end{verbatim}
Scientific content $E=mc^2$ and \pdfScientificEquation{retain}."""
    )
    result = compiler.normalize_engine(source, engine)
    visible = compiler.visible_tex(result)
    assert r"\pdfinfoomitdate" not in visible
    assert r"\pdftrailerid" not in visible
    assert "/Title" not in result and "continued}" not in result
    assert result.splitlines()[0] == source.splitlines()[0]
    assert result.splitlines()[-3:] == source.splitlines()[-3:]
    assert result.count("\n") == source.count("\n")
    assert compiler.normalize_engine(result, engine) == result
    assert compiler.normalize_engine(source, "lualatex") == source


@pytest.mark.parametrize(
    "source",
    [
        r"\pdfinfoomitdate=\SomeCounter",
        r"\pdfinfoomitdate=1.5",
        r"\pdfinfoomitdate=1pt",
        r"\pdftrailerid{unclosed {nested} Scientific content",
        r"\pdfinfo{/Title (unclosed) {nested}",
        r"\pdftraileridSuffix{Scientific content}",
    ],
)
def test_unknown_or_incomplete_syntax_is_not_silently_discarded(source):
    assert compiler.normalize_engine(source, "tectonic") == source


@pytest.mark.parametrize(
    ("command", "argument"),
    [("pdfinfoomitdate", "=1"), ("pdftrailerid", "{seed{nested}}")],
)
async def test_external_packages_use_the_same_metadata_policy(
    tmp_path, monkeypatch, command, argument
):
    root, out = tmp_path / "source", tmp_path / "build"
    root.mkdir()
    out.mkdir()
    (root / "main.tex").write_text(r"\documentclass{article}")
    original = (
        "% retain package license\n"
        + "\\"
        + command
        + argument
        + "\n"
        + r"\pdfinfoomitdate 1\pdftrailerid{another seed}"
        + "\n"
        + r"\def\ScientificResult{Retain all content.}"
    ).encode()

    async def cached(*_):
        return original

    monkeypatch.setattr(compiler, "_cached_bundle_file", cached)
    error = compiler.CompilationError(
        "failed",
        "error: unrelated-template.sty:2: Undefined control sequence",
        tex_log=f"! Undefined control sequence.\nl.2 \\{command}\n {argument}",
        bundle="https://example.org/test-bundle",
    )
    assert (
        await compiler.recover_external_package(
            root, "main.tex", out, "tectonic", error
        )
        == "unrelated-template.sty"
    )
    assert (root / "unrelated-template.sty.texglot-original").read_bytes() == original
    adapted = (root / "unrelated-template.sty").read_text()
    assert r"\def\ScientificResult{Retain all content.}" in adapted
    assert r"\pdfinfoomitdate" not in adapted and r"\pdftrailerid" not in adapted


async def test_real_compile_keeps_scientific_content_and_engine_detection(tmp_path):
    if not compiler.find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    (root / "metadata.sty").write_text(
        "\\ProvidesPackage{metadata}\n"
        r"\pdfinfoomitdate 1\pdftrailerid{seed{nested}}"
    )
    (root / "main.tex").write_text(
        r"\documentclass{article}\usepackage{metadata}\begin{document}"
        r"\ifdefined\pdfinfoomitdate Wrong engine.\else Native engine.\fi "
        r"Result 42 remains. $E=mc^2$.\end{document}"
    )
    compiler.prepare_engine_sources(root, "tectonic")

    async def notify(_):
        pass

    pdf, warnings = await compiler.compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    reader = PdfReader(pdf)
    text = reader.pages[0].extract_text()
    assert len(reader.pages) == 1 and not warnings
    assert "Native engine." in text and "Result 42 remains." in text
    assert "Wrong engine" not in text and "seed" not in text
