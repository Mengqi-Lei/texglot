"""Oversized floats keep all content; already fitting floats stay untouched."""

import re

import pytest
from pypdf import PdfReader

from app.compiler import FLOAT_SIZING, compile_pdf, find_compiler, prepare_float_sizing
from app.i18n import MESSAGES


def test_float_hook_is_idempotent_and_preserves_body_and_includes(tmp_path):
    main = tmp_path / "main.tex"
    source = (
        r"\documentclass{article}\makeatletter"
        "\n"
        r"\begin{document}\input{figures}\end{document}"
    )
    main.write_text(source, encoding="utf-8")
    child = tmp_path / "figures.tex"
    body = r"\begin{figure*}\rule{3cm}{2cm}\caption{A panel}\label{fig:a}\end{figure*}"
    child.write_text(body, encoding="utf-8")
    prepare_float_sizing(tmp_path)
    fitted = main.read_text(encoding="utf-8")
    assert FLOAT_SIZING.strip() in fitted
    assert fitted[fitted.index(r"\begin{document}") :] == source[
        source.index(r"\begin{document}") :
    ]
    assert child.read_text(encoding="utf-8") == body
    prepare_float_sizing(tmp_path)
    assert main.read_text(encoding="utf-8") == fitted


@pytest.mark.parametrize(
    "body",
    [
        "A paper without floats.",
        "% \\begin{figure}\nText.",
        r"\verb|\begin{figure*}|",
        "\\begin{verbatim}\n\\begin{table}\n\\end{verbatim}",
        "\\begin{lstlisting}\n\\begin{figure}\n\\end{lstlisting}",
        r"\begin{sidewaysfigure}An author-defined float.\end{sidewaysfigure}",
    ],
)
def test_comments_code_and_custom_float_examples_do_not_trigger_injection(tmp_path, body):
    main = tmp_path / "main.tex"
    source = r"\documentclass{article}\begin{document}" + body + r"\end{document}"
    main.write_text(source, encoding="utf-8")
    prepare_float_sizing(tmp_path)
    assert main.read_text(encoding="utf-8") == source


async def notify(_):
    pass


@pytest.mark.parametrize("environment", ["figure", "figure*", "table", "table*"])
async def test_native_oversized_float_keeps_every_row_caption_and_reference(
    tmp_path, environment
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    main = root / "main.tex"
    # Each line is a distinguishable panel: the last rows and caption are outside
    # the physical page before fitting, as in the SUNRISE twelve-panel figure.
    rows = "\n".join(
        rf"\noindent\rule{{1pt}}{{0.095\textheight}} Panel-{i:02d}\par"
        for i in range(1, 13)
    )
    source = (
        r"\documentclass{article}\usepackage{graphicx}\begin{document}"
        r"Reference \ref{group}.\begin{"
        + environment
        + "}[p]\n"
        + rows
        + r"\caption{Complete group caption}\label{group}\end{"
        + environment
        + r"}\end{document}"
    )
    main.write_text(source, encoding="utf-8")
    _, before_warnings = await compile_pdf(
        root, "main.tex", tmp_path / "before", "tectonic", notify
    )
    assert any("可能被裁切" in item for item in before_warnings)
    prepare_float_sizing(root)
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "after", "tectonic", notify
    )
    assert len(warnings) == 1 and "已整体缩放" in warnings[0]
    assert "scaled together" in MESSAGES[warnings[0]]
    log = (tmp_path / "after/main.log").read_text(encoding="utf-8")
    assert "Float too large for page" not in log
    assert "TeXGlot-Float-Fit:" in log
    pages = PdfReader(pdf).pages
    text = "\n".join(page.extract_text() for page in pages)
    assert "Reference 1." in text
    for i in range(1, 13):
        assert text.count(f"Panel-{i:02d}") == 1
    assert text.count("Complete group caption") == 1
    assert r"\newlabel{group}{{1}{2}}" in (tmp_path / "after/main.aux").read_text(
        encoding="utf-8"
    )
    # A text extractor can return off-page text. Check the real transformed
    # coordinates too, including the scaling matrix applied to the whole box.
    panel_positions = []

    def visit(value, cm, tm, _font, _size):
        if "Panel-" in value or "Complete group caption" in value:
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            panel_positions.append((x, y))

    pages[-1].extract_text(visitor_text=visit)
    assert len(panel_positions) >= 13
    assert all(
        0 < x < float(pages[-1].mediabox.width)
        and 0 < y < float(pages[-1].mediabox.height)
        for x, y in panel_positions
    )


async def test_native_fitting_floats_keep_exact_pdf_content_streams_and_at_catcode(
    tmp_path,
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    main = root / "main.tex"
    body = "\n".join(
        r"\begin{"
        + kind
        + r"}[p]\centering\rule{30pt}{20pt}\caption{Small "
        + kind.replace("*", " star")
        + r"}\end{"
        + kind
        + "}"
        for kind in ("figure", "figure*", "table", "table*")
    )
    source = (
        r"\documentclass{article}\usepackage{graphicx}\makeatletter"
        r"\begin{document}\def\author@macro{Author catcode preserved}"
        r"\author@macro\makeatother"
        + body
        + r"\end{document}"
    )
    main.write_text(source, encoding="utf-8")
    before, old_warnings = await compile_pdf(
        root, "main.tex", tmp_path / "before", "tectonic", notify
    )
    prepare_float_sizing(root)
    after, new_warnings = await compile_pdf(
        root, "main.tex", tmp_path / "after", "tectonic", notify
    )
    assert old_warnings == new_warnings == []
    old_pages, new_pages = PdfReader(before).pages, PdfReader(after).pages
    assert len(old_pages) == len(new_pages)
    assert [page.get_contents().get_data() for page in old_pages] == [
        page.get_contents().get_data() for page in new_pages
    ]
    assert "Author catcode preserved" in new_pages[0].extract_text()
    log = (tmp_path / "after/main.log").read_text(encoding="utf-8")
    assert not re.search(r"TeXGlot-Float-Fit:|Float too large for page", log)
