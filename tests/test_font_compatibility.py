"""Native checks for font requests that a Unicode engine cannot resolve."""

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
    canonical_font_file,
    prepare_font_files,
    remove_amssymb_loads,
    repair_font_requests,
    unicode_math_active,
)

ACMART_FONT = r"\setmathfont[Scale=MatchUppercase]{libertinusmath-regular.otf}"


async def notify(_):
    pass


def test_font_file_name_is_repaired_for_case_sensitive_lookups(tmp_path):
    (tmp_path / "acmart.cls").write_text(
        "\\ProvidesClass{acmart}\n"
        "\\RequirePackage{unicode-math}\n" + ACMART_FONT + "\n"
    )
    changed = prepare_font_files(tmp_path, "tectonic")
    assert changed == ["acmart.cls"]
    text = (tmp_path / "acmart.cls").read_text()
    assert r"\setmathfont[Scale=MatchUppercase]{LibertinusMath-Regular.otf}" in text
    assert "libertinusmath-regular.otf" not in text
    # The repair is stable and never touches unrelated fonts.
    assert prepare_font_files(tmp_path, "tectonic") == []
    assert prepare_font_files(tmp_path, "pdftex") == []
    assert canonical_font_file("libertinusmath-regular.otf") == (
        "LibertinusMath-Regular.otf"
    )
    assert canonical_font_file("texgyretermes-regular.otf") == ""


def test_project_font_file_is_never_replaced(tmp_path):
    (tmp_path / "acmart.cls").write_text(ACMART_FONT + "\n")
    (tmp_path / "libertinusmath-regular.otf").write_bytes(b"local font")
    assert prepare_font_files(tmp_path, "tectonic") == []
    assert ACMART_FONT in (tmp_path / "acmart.cls").read_text()


def test_font_repair_ignores_comments_and_literal_examples():
    source = (
        "% \\setmathfont{libertinusmath-regular.otf}\n"
        "\\begin{verbatim}\n\\setmathfont{libertinusmath-regular.otf}\n"
        "\\end{verbatim}\n" + ACMART_FONT + "\n"
    )
    output = repair_font_requests(source)
    assert output.count("libertinusmath-regular.otf") == 2
    assert output.count("LibertinusMath-Regular.otf") == 1


def test_amssymb_is_removed_only_when_unicode_math_owns_the_symbols(tmp_path):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage{amsmath}\n"
        "\\usepackage{amssymb}\n"
        "\\usepackage{graphicx}\n"
        "\\begin{document}A $\\eth$.\n\\end{document}\n"
    )
    assert unicode_math_active(tmp_path) is False
    assert remove_amssymb_loads(tmp_path) == []
    assert "\\usepackage{amssymb}" in (tmp_path / "main.tex").read_text()

    (tmp_path / "paper.cls").write_text(
        "\\ProvidesClass{paper}\n\\RequirePackage{unicode-math}\n"
    )
    assert unicode_math_active(tmp_path) is True
    assert remove_amssymb_loads(tmp_path) == ["main.tex"]
    text = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{amssymb}" not in text
    assert "% texglot:" in text
    # Other packages and the paper content stay untouched.
    assert "\\usepackage{amsmath}" in text
    assert "\\usepackage{graphicx}" in text
    assert "A $\\eth$." in text


def test_amssymb_is_kept_alongside_other_packages(tmp_path):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{amsmath,amssymb,bm}\n"
        "\\begin{document}Text.\n\\end{document}\n"
    )
    (tmp_path / "paper.cls").write_text(
        "\\ProvidesClass{paper}\n\\RequirePackage{unicode-math}\n"
    )
    assert remove_amssymb_loads(tmp_path) == ["main.tex"]
    text = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{amsmath,bm}" in text
    assert "amssymb" not in text


def test_recovery_diagnoses_the_amssymb_clash(tmp_path):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{amssymb}\n"
        "\\begin{document}Text.\n\\end{document}\n"
    )
    error = CompilationError(
        "LaTeX 编译未通过",
        "error: amssymb.sty:240: LaTeX Error: Command `\\eth' already defined.\n"
        "(unicode-math.sty (expl3.sty))",
    )
    change = recover_compile_configuration(tmp_path, "main.tex", error)
    assert change
    assert "\\usepackage{amssymb}" not in (tmp_path / "main.tex").read_text()


def test_recovery_keeps_amssymb_without_unicode_math(tmp_path):
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{amssymb}\n"
        "\\begin{document}Text.\n\\end{document}\n"
    )
    error = CompilationError(
        "LaTeX 编译未通过",
        "error: main.tex:9: LaTeX Error: Command `\\eth' already defined.\n"
        "(amssymb.sty (amsfonts.sty))",
    )
    assert recover_compile_configuration(tmp_path, "main.tex", error) == ""
    assert "\\usepackage{amssymb}" in (tmp_path / "main.tex").read_text()


async def test_acmart_style_font_request_compiles_after_recovery(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    (root / "paper.cls").write_text(
        "\\ProvidesClass{paper}\n"
        "\\LoadClass{article}\n"
        "\\RequirePackage{unicode-math}\n" + ACMART_FONT + "\n"
    )
    (root / "main.tex").write_text(
        "\\documentclass{paper}\n"
        "\\usepackage{amssymb}\n"
        "\\begin{document}A $\\eth$ and $\\mathbb{R}$.\n\\end{document}\n"
    )
    prepare_engine_sources(root, "tectonic")
    assert "LibertinusMath-Regular.otf" in (root / "paper.cls").read_text()
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert len(PdfReader(pdf).pages) == 1
    assert not warnings
