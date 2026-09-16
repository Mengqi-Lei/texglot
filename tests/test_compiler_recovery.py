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


@pytest.mark.parametrize("prefix", ["error: ", ""])
@pytest.mark.parametrize(
    ("filename", "relative"),
    [
        ("preamble", "paper/preamble.tex"),
        ("preamble.tex", "paper/preamble.tex"),
        ("settings.v1", "paper/settings.v1.tex"),
        ("nested/preamble", "paper/nested/preamble.tex"),
        ("../common/preamble", "common/preamble.tex"),
    ],
)
def test_package_recovery_resolves_the_compilers_input_spelling(
    tmp_path, prefix, filename, relative
):
    main = tmp_path / "paper/main.tex"
    main.parent.mkdir()
    source = r"\documentclass{article}\begin{document}Paper.\end{document}"
    main.write_text(source)
    preamble = tmp_path / relative
    preamble.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "% \\usepackage[monochrome]{xcolor}\n"
        r"\usepackage[table]{xcolor}\usepackage[table]{xcolor}"
    )
    preamble.write_text(content)
    (tmp_path / "unrelated.tex").write_text(r"\usepackage[unknown]{xcolor}")
    error = CompilationError(
        "failure",
        f"{prefix}{filename}:10: LaTeX Error: Option clash for package xcolor.",
    )
    assert (
        recover_compile_configuration(tmp_path, "paper/main.tex", error)
        == "xcolor 宏包选项"
    )
    repaired = main.read_text()
    assert repaired.endswith(source)
    assert repaired.count(r"\PassOptionsToPackage{table}{xcolor}") == 1
    assert "monochrome" not in repaired and "unknown" not in repaired
    assert preamble.read_text() == content
    assert recover_compile_configuration(tmp_path, "paper/main.tex", error) == ""
    assert main.read_text() == repaired


def test_package_recovery_accepts_a_local_absolute_diagnostic_for_other_packages(
    tmp_path,
):
    main = tmp_path / "main.tex"
    main.write_text(r"\documentclass{article}")
    package = tmp_path / "local.sty"
    package.write_text(r"\RequirePackage[draft]{graphicx}")
    error = CompilationError(
        "failure", f"{package}:1: LaTeX Error: Option clash for package graphicx."
    )
    assert (
        recover_compile_configuration(tmp_path, "main.tex", error)
        == "graphicx 宏包选项"
    )
    assert r"\PassOptionsToPackage{draft}{graphicx}" in main.read_text()


def test_package_clash_at_include_eof_uses_the_recorded_input_trace(tmp_path):
    main = tmp_path / "main.tex"
    main.write_text(r"\documentclass{article}\usepackage{xcolor}\input{preamble}")
    preamble = tmp_path / "preamble.tex"
    preamble.write_text(r"\usepackage[table]{xcolor}")
    (tmp_path / "unused.tex").write_text(r"\usepackage[monochrome]{xcolor}")
    message = "LaTeX Error: Option clash for package xcolor."
    error = CompilationError(
        "failure",
        "error: main.tex:3: " + message,
        tex_log="(main.tex (preamble)\n! " + message + "\n(unused.tex)\n",
    )
    assert (
        recover_compile_configuration(tmp_path, "main.tex", error) == "xcolor 宏包选项"
    )
    assert r"\PassOptionsToPackage{table}{xcolor}" in main.read_text()
    assert "monochrome" not in main.read_text()
    assert preamble.read_text() == r"\usepackage[table]{xcolor}"


def test_only_a_post_error_file_mention_cannot_trigger_package_recovery(tmp_path):
    main = tmp_path / "main.tex"
    source = r"\documentclass{article}\usepackage{xcolor}"
    main.write_text(source)
    (tmp_path / "unused.tex").write_text(r"\usepackage[table]{xcolor}")
    message = "LaTeX Error: Option clash for package xcolor."
    error = CompilationError(
        "failure",
        "error: main.tex:3: " + message,
        tex_log="(main.tex\n! " + message + "\n(unused.tex)\n",
    )
    assert recover_compile_configuration(tmp_path, "main.tex", error) == ""
    assert main.read_text() == source


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "outside",
        "symlink",
        "ambiguous",
        "other_diagnostic",
        "non_text",
        "computed_option",
        "empty_options",
    ],
)
def test_unreliable_diagnostic_locations_never_change_source(tmp_path, case):
    root = tmp_path / "project"
    root.mkdir()
    main = root / "main.tex"
    source = r"\documentclass{article}\begin{document}Paper.\end{document}"
    main.write_text(source)
    preamble = root / "preamble.tex"
    content = r"\usepackage[table]{xcolor}"
    preamble.write_text(content)
    filename = "preamble"
    if case == "missing":
        filename = "unknown/preamble"
    elif case == "outside":
        (tmp_path / "preamble.tex").write_text(content)
        filename = "../preamble"
    elif case == "symlink":
        preamble.unlink()
        outside = tmp_path / "external.tex"
        outside.write_text(content)
        try:
            preamble.symlink_to(outside)
        except OSError:
            pytest.skip("This host does not allow creating file symlinks")
    elif case == "ambiguous":
        (root / "preamble").write_text(r"\usepackage[monochrome]{xcolor}")
    elif case == "non_text":
        preamble.write_bytes(b"\xff\xff")
    elif case == "computed_option":
        preamble.write_text(r"\usepackage[\unknownoptions]{xcolor}")
    elif case == "empty_options":
        preamble.write_text(r"\usepackage[ , , ]{xcolor}")
    log = f"error: {filename}:10: LaTeX Error: Option clash for package xcolor."
    if case == "other_diagnostic":
        log = "error: preamble:10: Undefined control sequence\n! LaTeX Error: Option clash for package xcolor."
    assert (
        recover_compile_configuration(
            root, "main.tex", CompilationError("failure", log)
        )
        == ""
    )
    assert main.read_text() == source


async def test_native_recovery_preserves_table_options_in_an_included_preamble(
    tmp_path,
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    source = (
        r"\documentclass{article}\usepackage{xcolor}\input{preamble}"
        r"\begin{document}\begin{tabular}{ll}\rowcolor{gray}"
        r"A&B\\C&D\end{tabular}\end{document}"
    )
    (root / "main.tex").write_text(source)
    options = r"\usepackage[table]{xcolor}\usepackage[table]{xcolor}"
    (root / "preamble.tex").write_text(options)
    repairs = []

    async def record(message):
        repairs.append(message)

    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", record
    )
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1 and not warnings
    assert all(c in reader.pages[0].extract_text() for c in "ABCD")
    assert any(
        operator in (b"g", b"rg")
        for _, operator in reader.pages[0].get_contents().operations
    )
    assert sum("xcolor" in message for message in repairs) == 1
    assert (root / "preamble.tex").read_text() == options
    assert (root / "main.tex").read_text().endswith(source)
