"""Native checks for source configuration and compiler recovery boundaries."""

import pytest
from pypdf import PdfReader

from app.compiler import (
    CompilationError,
    compile_pdf,
    find_compiler,
    normalize_engine,
    rebase_project_paths,
    recover_compile_configuration,
    validate_sources,
)


async def notify(_):
    pass


async def test_new_compile_does_not_execute_stale_template_auxiliary_files(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root, out = tmp_path / "source", tmp_path / "build"
    root.mkdir()
    out.mkdir()
    (root / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\tableofcontents\section{Current template}Current text.\end{document}"
    )
    for name in ("main.aux", "main.toc", "main.out"):
        (out / name).write_text(r"\UndefinedCommandFromOldTemplate")
    unrelated = out / "user-notes.txt"
    unrelated.write_text("retain")
    pdf, warnings = await compile_pdf(root, "main.tex", out, "tectonic", notify)
    assert len(PdfReader(pdf).pages) == 1 and not warnings
    assert unrelated.read_text() == "retain"


@pytest.mark.parametrize("draw", [False, True])
async def test_postscript_operations_cannot_silently_disappear(tmp_path, draw):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    (root / "pstricks.sty").write_text(
        r"\ProvidesPackage{pstricks}\def\pst@object#1{\relax}\def\testdrawing{\pst@object{dot}}"
    )
    source = r"\documentclass{article}\usepackage{pstricks}\begin{document}A document."
    if draw:
        source += r"\testdrawing"
    source += r"\end{document}"
    (root / "main.tex").write_text(normalize_engine(source, "tectonic"))
    if draw:
        with pytest.raises(ValueError, match="不支持内嵌 PSTricks"):
            await compile_pdf(root, "main.tex", tmp_path / "build", "tectonic", notify)
    else:
        pdf, warnings = await compile_pdf(
            root, "main.tex", tmp_path / "build", "tectonic", notify
        )
        assert pdf.exists() and not warnings


@pytest.mark.parametrize("resolved", [True, False])
async def test_classic_engine_reports_only_final_reference_warnings(tmp_path, resolved):
    if not find_compiler("xelatex"):
        pytest.skip("Optional native XeLaTeX not installed")
    root = tmp_path / "source"
    root.mkdir()
    source = r"\documentclass{article}\begin{document}Reference \ref{later}."
    if resolved:
        source += r"\section{Later}\label{later}"
    (root / "main.tex").write_text(source + r"\end{document}")
    _, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "xelatex", notify
    )
    assert any("未解析的引用" in warning for warning in warnings) is not resolved
    assert "undefined references" in (tmp_path / "build/compile.log").read_text()


def test_driver_replacement_preserves_multiline_comments():
    source = (
        "\\usepackage[\n pdftex,\n % preserve this comment\n colorlinks=true]{hyperref}"
    )
    assert normalize_engine(source, "tectonic") == source.replace("pdftex", "xetex")
    native = source.replace(" pdftex,\n", "")
    assert normalize_engine(native, "tectonic") == native


def test_rebase_uses_exact_archive_path_and_never_a_similar_filename(tmp_path):
    (tmp_path / "pics").mkdir()
    (tmp_path / "pics/figure.pdf").write_bytes(b"included asset")
    main = tmp_path / "main.tex"
    main.write_text(r"\includegraphics{../pics/figure.pdf}")
    assert rebase_project_paths(tmp_path, "main.tex")
    assert main.read_text() == r"\includegraphics{pics/figure.pdf}"
    validate_sources(tmp_path, "main.tex")
    main.write_text(r"\includegraphics{../different/figure.pdf}")
    assert rebase_project_paths(tmp_path, "main.tex") == []
    with pytest.raises(ValueError, match="工程目录外"):
        validate_sources(tmp_path, "main.tex")


@pytest.mark.parametrize(
    "feature", [r"\setmathfont{Latin Modern Math}", "$α$", r"\symbf{x}"]
)
def test_recovery_preserves_explicit_unicode_mathematics(tmp_path, feature):
    source = r"\ifPDFTeX\else\usepackage{unicode-math}\fi" + feature
    (tmp_path / "main.tex").write_text(source, encoding="utf-8")
    error = CompilationError("test", "Extended mathchar used as mathchar")
    assert recover_compile_configuration(tmp_path, "main.tex", error) == ""
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == source


@pytest.mark.parametrize(
    "body, expected",
    [
        (
            r"\usepackage{xcolor}\usepackage[table]{xcolor}\begin{document}\begin{tabular}{ll}\rowcolor{gray}A&B\\\end{tabular}",
            r"\PassOptionsToPackage{table}{xcolor}",
        ),
        (
            r"\usepackage{natbib}\begin{document}\citep{x}\begin{thebibliography}{1}\bibitem{x}Author. Paper. 2020.\end{thebibliography}",
            r"\PassOptionsToPackage{numbers}{natbib}",
        ),
        (
            r"\usepackage{amsmath,amssymb,iftex,bm}\ifPDFTeX\usepackage[T1]{fontenc}\else\usepackage{unicode-math}\fi\newcommand{\FictionalField}{\mathbb{Q}}\begin{document}$x_\FictionalField+x_\mathcal{H}$",
            r"\usepackage{fontspec}",
        ),
        (
            r"\usepackage{bbm}\begin{document}$\mathbbm{1}+\mathbbmss{A}+\mathbbmtt{R}+x_{\mathbbm{1}}$",
            r"\mathbbm{1}",
        ),
    ],
)
async def test_native_configuration_recovery(tmp_path, body, expected):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    main = root / "main.tex"
    text = r"\documentclass{article}" + body + r"\end{document}"
    main.write_text(normalize_engine(text, "tectonic"), encoding="utf-8")
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert len(PdfReader(pdf).pages) == 1 and not warnings
    assert expected in main.read_text()


def test_unknown_compiler_failure_has_no_automatic_source_edit(tmp_path):
    source = r"\documentclass{article}\begin{document}A paper.\end{document}"
    main = tmp_path / "main.tex"
    main.write_text(source)
    assert (
        recover_compile_configuration(
            tmp_path,
            "main.tex",
            CompilationError("failure", "Undefined control sequence"),
        )
        == ""
    )
    assert main.read_text() == source
