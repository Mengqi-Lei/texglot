"""Compatibility of subcaption with an existing subfigure counter owner."""

import re

import pytest
from pypdf import PdfReader

from app.compiler import CompilationError, compile_pdf, find_compiler
from app.i18n import english
from app.tex_runtime import RuntimeOverlay


def conflict(legacy="subfigure", *, location="subcaption.sty", version="1.5"):
    first = "Package subcaption Error: This package can't be used in cooperation"
    return CompilationError(
        "compile failed",
        f"error: {location}:87: {first}\n",
        tex_log=(
            f"Package: {legacy} 2002/03/15 v2.1.5\n"
            f"Package: subcaption 2022/01/07 v{version} Sub-captions (AR)\n"
            f"! {first}\n(subcaption)                with the {legacy} package.\n"
        ),
    )


@pytest.mark.parametrize("legacy", ["subfigure", "subfig"])
def test_recovery_installs_once_next_to_nested_main_and_keeps_author_files(
    tmp_path, legacy
):
    book = tmp_path / "book"
    book.mkdir()
    paper = book / "paper.tex"
    paper.write_bytes(b"Original document\r\n")
    runtime = RuntimeOverlay(tmp_path, "book/paper.tex")
    error = conflict(legacy)
    assert runtime.recover(error) == "subcaption 1.6b"
    assert b"v1.6b" in (book / "subcaption.sty").read_bytes()
    assert (book / "texglot-runtime/subcaption/provenance.json").is_file()
    assert not runtime.recover(error)
    assert paper.read_bytes() == b"Original document\r\n"


@pytest.mark.parametrize(
    "error",
    [
        conflict(location="paper.tex"),  # begin-document check: reverse load order
        conflict(version="1.6b"),
        conflict(legacy="unrelated"),
        CompilationError(
            "unrelated", "error: main.tex:7: Missing number", tex_log=conflict().tex_log
        ),
    ],
)
def test_only_the_diagnosed_legacy_load_is_repaired(tmp_path, error):
    assert not RuntimeOverlay(tmp_path, "paper.tex").recover(error)
    assert not list(tmp_path.iterdir())


async def test_pinned_project_package_preserved_and_full_conflict_reported(
    tmp_path, monkeypatch
):
    root = tmp_path / "source"
    root.mkdir()
    sty = root / "subcaption.sty"
    sty.write_bytes(b"% project package\r\n")
    (root / "paper.tex").write_text(r"\documentclass{article}", encoding="utf-8")
    error = conflict("subfig")

    async def fail(*_, **__):
        raise error

    async def notify(_):
        pytest.fail("An author-supplied package should not be replaced")

    monkeypatch.setattr("app.compiler._compile_document", fail)
    with pytest.raises(CompilationError, match="subcaption 与 subfig 冲突") as raised:
        await compile_pdf(root, "paper.tex", tmp_path / "build", "tectonic", notify)
    assert "subcaption and subfig" in english(str(raised.value))
    assert raised.value.tex_log == error.tex_log
    assert sty.read_bytes() == b"% project package\r\n"
    assert not (root / "texglot-runtime").exists()


@pytest.mark.skipif(not find_compiler("tectonic"), reason="Optional native Tectonic")
@pytest.mark.parametrize(
    ("legacy", "panel", "expected_refs"),
    [
        (
            "subfigure",
            r"\subfigure[{caption}\label{key}]{{{content}}}",
            ("1(a)", "1(b)"),
        ),
        ("subfig", r"\subfloat[{caption}]{{{content}\label{key}}}", ("1a", "1b")),
    ],
)
async def test_native_template_preserves_panels_captions_and_references(
    tmp_path, legacy, panel, expected_refs
):
    root = tmp_path / "source"
    root.mkdir()
    template = root / "paper-style.sty"
    template.write_bytes(b"\\RequirePackage{caption,subcaption}\n")
    panels = [
        panel.format(
            caption=caption,
            key="{" + key + "}",
            content=r"\fbox{\makebox[28mm]{" + content + "}}",
        )
        for caption, key, content in [
            ("First caption", "panel:left", "Left content"),
            ("Second caption", "panel:right", "Right content"),
        ]
    ]
    author_tex = (
        r"\documentclass{article}\usepackage{" + legacy + r"}\usepackage{paper-style}"
        r"\begin{document}\begin{figure}\centering"
        + "\n".join(panels)
        + r"\caption{Both panels}\label{fig:pair}\end{figure}"
        r"Figure~\ref{fig:pair}, left~\ref{panel:left}, right~\ref{panel:right}."
        r"\end{document}"
    ).encode()
    (root / "paper.tex").write_bytes(author_tex)
    notices = []

    async def record(message):
        notices.append(message)

    pdf, warnings = await compile_pdf(
        root, "paper.tex", tmp_path / "build", "tectonic", record
    )
    text = " ".join(PdfReader(pdf).pages[0].extract_text().split())
    for item in (
        "Left content",
        "Right content",
        "(a) First caption",
        "(b) Second caption",
        "Both panels",
    ):
        assert text.count(item) == 1
    assert f"Figure 1, left {expected_refs[0]}, right {expected_refs[1]}." in text
    assert warnings == []
    assert sum("subcaption 1.6b" in msg for msg in notices) == 1
    assert not re.search(
        r"[\u4e00-\u9fff]", english(next(m for m in notices if "subcaption" in m))
    )
    assert (root / "paper.tex").read_bytes() == author_tex
    assert template.read_bytes() == b"\\RequirePackage{caption,subcaption}\n"


@pytest.mark.skipif(not find_compiler("tectonic"), reason="Optional native Tectonic")
async def test_incompatible_commands_are_not_silently_dropped(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    text = (
        r"\documentclass{article}\usepackage{subfigure,subcaption}\begin{document}"
        r"\begin{figure}\subcaptionbox{First\label{a}}{Panel}\caption{Both}\end{figure}"
        r"Reference~\ref{a}.\end{document}"
    )
    (root / "main.tex").write_text(text, encoding="utf-8")

    async def record(_):
        pass

    with pytest.raises(CompilationError, match="subfigure") as raised:
        await compile_pdf(root, "main.tex", tmp_path / "build", "tectonic", record)
    assert (
        "Undefined subtype" in raised.value.tex_log
        or "was defined by" in raised.value.tex_log
    )
    assert (root / "main.tex").read_text(encoding="utf-8") == text
    assert not (tmp_path / "build/main.pdf").exists()
