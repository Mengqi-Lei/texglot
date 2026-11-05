"""Font lookup, diagnosed recovery and content-preservation regressions."""

import pytest
from pypdf import PdfReader

from app.compiler import (
    CompilationError,
    compile_pdf,
    find_compiler,
    prepare_engine_sources,
    recover_compile_configuration,
)
from app.fonts import (
    AMSSYMB_NOTE,
    canonical_font_file,
    prepare_font_files,
    repair_font_requests,
)
from app.i18n import english

ACMART_FONT = r"\setmathfont[Scale=MatchUppercase]{libertinusmath-regular.otf}"
UNICODE_TRACE = "(main.tex\n(unicode-math.sty\nPackage: unicode-math 2020/01/31\n)"
CLASH = "error: amssymb.sty:240: LaTeX Error: Command `\\eth' already defined."


async def notify(_):
    pass


def recover(root, *, log=CLASH, trace=UNICODE_TRACE, main="main.tex"):
    return recover_compile_configuration(
        root, main, CompilationError("test", log, tex_log=trace)
    )


@pytest.mark.parametrize("engine", ["tectonic", "xelatex", "lualatex"])
def test_font_file_name_is_repaired_for_unicode_engines(tmp_path, engine):
    path = tmp_path / "acmart.cls"
    path.write_text(ACMART_FONT)
    assert prepare_font_files(tmp_path, engine) == ["acmart.cls"]
    assert "LibertinusMath-Regular.otf" in path.read_text()
    assert prepare_font_files(tmp_path, engine) == []
    path.write_text(ACMART_FONT)
    assert prepare_font_files(tmp_path, "pdftex") == []
    assert canonical_font_file("texgyretermes-regular.otf") == ""


@pytest.mark.parametrize(
    "name", ["libertinusmath-regular", "libertinusmath-regular.otf"]
)
@pytest.mark.parametrize("location", ["", "fonts/"])
def test_project_font_file_is_never_replaced(tmp_path, name, location):
    source = rf"\setmathfont{{{name}}}"
    (tmp_path / "paper.cls").write_text(source)
    font = tmp_path / location / "libertinusmath-regular.otf"
    font.parent.mkdir(exist_ok=True)
    font.write_bytes(b"authored font")
    assert prepare_font_files(tmp_path, "tectonic") == []
    assert (tmp_path / "paper.cls").read_text() == source
    assert font.read_bytes() == b"authored font"


@pytest.mark.parametrize(
    "source",
    [
        r"\setmathfont[Path=fonts/]{libertinusmath-regular}",
        r"\setmathfont{libertinusmath-regular}[Extension=.otf]",
        r"\setmathfont[\authorfeatures]{libertinusmath-regular}",
        r"\setmathfont{\authorfont}",
        r"\setmathfontface{\mathup}{libertinusmath-regular.otf}",
        r"\fontspec{Latin Modern Roman}{libertinusmath-regular.otf}",
        r"\setmathfont[Scale={bad]{libertinusmath-regular.otf}",
    ],
)
def test_font_lookup_rules_and_unrelated_arguments_are_preserved(source):
    assert repair_font_requests(source) == source


@pytest.mark.parametrize(
    "command",
    [
        r"\setmathfont",
        r"\newfontfamily\myfont",
        r"\newfontfamily{\myfont}",
        r"\newfontface\myfont",
    ],
)
def test_font_parser_preserves_comments_and_nested_feature_groups(command):
    source = (
        command
        + "[Scale={1.2},StylisticSet={1,2}]{\n% retained\nlibertinusmath-regular\n}"
    )
    assert repair_font_requests(source) == source.replace(
        "libertinusmath-regular", "LibertinusMath-Regular.otf"
    )


def test_font_repair_preserves_inherited_literal_environments(tmp_path):
    block = "\\begin{ExampleCode}\n" + ACMART_FONT + "\n\\end{ExampleCode}"
    (tmp_path / "settings.sty").write_text(
        r"\DefineVerbatimEnvironment{ExampleCode}{Verbatim}{}"
    )
    source = "% " + ACMART_FONT + "\n" + block + "\n" + ACMART_FONT
    (tmp_path / "main.tex").write_text(source)
    prepare_font_files(tmp_path, "tectonic")
    assert (tmp_path / "main.tex").read_text() == source[: -len(ACMART_FONT)] + (
        ACMART_FONT.replace("libertinusmath-regular.otf", "LibertinusMath-Regular.otf")
    )


@pytest.mark.parametrize(
    "log, trace",
    [
        (CLASH, ""),
        (CLASH, "(unused-unicode-math-example.tex)"),
        (CLASH, "Example: Package: unicode-math is not a load record"),
        (
            "error: other.sty:2: LaTeX Error: Command `\\eth' already defined.",
            UNICODE_TRACE,
        ),
        (
            "error: main.tex:4: LaTeX Error: Command `\\foo' already defined.",
            UNICODE_TRACE,
        ),
        ("error: amssymb.sty:240: Undefined control sequence", UNICODE_TRACE),
    ],
)
def test_unconfirmed_conflict_keeps_every_source(tmp_path, log, trace):
    source = r"\documentclass{article}\usepackage{amssymb}"
    (tmp_path / "main.tex").write_text(source)
    (tmp_path / "unused.cls").write_text(r"\RequirePackage{unicode-math}")
    assert recover(tmp_path, log=log, trace=trace) == ""
    assert (tmp_path / "main.tex").read_text() == source


def test_recovery_uses_loaded_files_and_preserves_cross_file_examples(tmp_path):
    (tmp_path / "settings.sty").write_text(
        r"\DefineVerbatimEnvironment{ExampleCode}{Verbatim}{}"
    )
    example = "\\begin{ExampleCode}\n\\usepackage{amssymb}\n\\end{ExampleCode}"
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\input{preamble}\begin{document}" + example
    )
    preamble = r"\usepackage{unicode-math,amssymb,graphicx}"
    (tmp_path / "preamble.tex").write_text(preamble)
    unused = r"\usepackage{amssymb}"
    (tmp_path / "unused.tex").write_text(unused)
    trace = UNICODE_TRACE + "\n(./preamble\n(amssymb.sty\n"
    assert recover(tmp_path, trace=trace)
    assert example in (tmp_path / "main.tex").read_text()
    assert (tmp_path / "unused.tex").read_text() == unused
    updated = (tmp_path / "preamble.tex").read_text()
    assert updated.index(r"\usepackage{unicode-math}") < updated.index(
        r"\IfPackageLoadedTF"
    )
    assert updated.index(r"\IfPackageLoadedTF") < updated.index(
        r"\usepackage{graphicx}"
    )
    assert r"\IfPackageLoadedTF{unicode-math}{}{\usepackage{amssymb}}" in updated
    assert recover(tmp_path, trace=trace) == ""


def test_recovery_preserves_options_inline_text_and_comments(tmp_path):
    source = (
        r"\documentclass{article}" + "\n"
        r"\usepackage[psamsfonts]{amssymb}\def\retained{yes}% retained" + "\n"
    )
    (tmp_path / "main.tex").write_text(source)
    assert recover(tmp_path)
    result = (tmp_path / "main.tex").read_text()
    assert (
        r"\IfPackageLoadedTF{unicode-math}{}{\usepackage[psamsfonts]{amssymb}}"
        in result
    )
    assert r"\def\retained{yes}% retained" in result


@pytest.mark.parametrize(
    "source",
    [
        r"\newcommand{\unused}{\usepackage{amssymb}}",
        r"\usepackage{\dynamic,amssymb}",
        r"\usepackage{amssymb}\usepackage{amssymb}",
    ],
)
def test_ambiguous_or_dynamic_loads_are_not_rewritten(tmp_path, source):
    (tmp_path / "main.tex").write_text(source)
    assert recover(tmp_path) == ""
    assert (tmp_path / "main.tex").read_text() == source


def test_authored_amssymb_package_is_kept(tmp_path):
    source = r"\usepackage{amssymb}"
    (tmp_path / "main.tex").write_text(source)
    (tmp_path / "amssymb.sty").write_text(r"\def\authoredfeature{retained}")
    assert recover(tmp_path) == ""
    assert (tmp_path / "main.tex").read_text() == source


def test_symlinked_source_is_not_modified(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside.tex"
    outside.write_text(ACMART_FONT + r"\usepackage{amssymb}")
    (root / "main.tex").symlink_to(outside)
    assert prepare_font_files(root, "tectonic") == []
    assert recover(root) == ""
    assert outside.read_text() == ACMART_FONT + r"\usepackage{amssymb}"


def test_recovery_messages_have_english_translations():
    for message in [
        "已修正无法解析的字体文件名：acmart.cls",
        "已按编译诊断调整 amssymb 与 unicode-math 的符号冲突，正在重试",
    ]:
        assert not any("\u4e00" <= char <= "\u9fff" for char in english(message))


async def test_native_recovery_keeps_printed_code_and_non_unicode_branch(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    (root / "settings.sty").write_text(
        "\\RequirePackage{fancyvrb}\n"
        "\\DefineVerbatimEnvironment{ExampleCode}{Verbatim}{}\n"
    )
    (root / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage{amsmath,unicode-math,amssymb,graphicx}\n"
        "\\usepackage{settings}\n"
        "\\begin{document}\n"
        "\\begin{ExampleCode}\n\\usepackage{amssymb}\n\\end{ExampleCode}\n"
        "A $\\eth$ and $\\mathbb{R}$.\n\\end{document}\n"
    )
    prepare_engine_sources(root, "tectonic")
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert not warnings
    content = PdfReader(pdf).pages[0].extract_text()
    assert r"\usepackage{amssymb}" in content
    assert "texglot:" not in content
    updated = (root / "main.tex").read_text()
    assert AMSSYMB_NOTE in updated
    # The original amssymb load remains usable if an author disables Unicode math.
    updated = updated.replace(
        r"\usepackage{amsmath,unicode-math}", r"\usepackage{amsmath}"
    )
    (root / "main.tex").write_text(updated)
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "classic", "tectonic", notify
    )
    assert not warnings and len(PdfReader(pdf).pages) == 1


async def test_native_unused_unicode_class_does_not_trigger_recovery(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    (tmp_path / "unused.cls").write_text(r"\RequirePackage{unicode-math}")
    source = (
        "\\documentclass{article}\n\\newcommand{\\eth}{custom}\n"
        "\\usepackage{amssymb}\n\\begin{document}$\\square$\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(source)
    with pytest.raises(CompilationError, match="already defined"):
        await compile_pdf(tmp_path, "main.tex", tmp_path / "build", "tectonic", notify)
    assert (tmp_path / "main.tex").read_text() == source


async def test_acmart_style_font_request_compiles_after_recovery(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    (tmp_path / "paper.cls").write_text(
        "\\ProvidesClass{paper}\n\\LoadClass{article}\n"
        "\\RequirePackage{unicode-math}\n" + ACMART_FONT + "\n"
    )
    (tmp_path / "main.tex").write_text(
        "\\documentclass{paper}\n\\usepackage{amssymb}\n"
        "\\begin{document}A $\\eth$ and $\\mathbb{R}$.\\end{document}"
    )
    assert prepare_engine_sources(tmp_path, "tectonic")
    pdf, warnings = await compile_pdf(
        tmp_path, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert len(PdfReader(pdf).pages) == 1 and not warnings
