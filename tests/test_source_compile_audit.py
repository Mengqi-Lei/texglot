"""Regressions from independently reproduced arXiv input/compiler failures."""

import asyncio
import hashlib
from pathlib import Path

import httpx
import pytest
from pypdf import PdfReader

from app.compiler import (
    compile_pdf,
    find_compiler,
    prepare_chinese,
    prepare_engine_sources,
    validate_sources,
)
from app.graphics import (
    expand_graphic_path,
    find_ghostscript,
    graphics_context,
    prepare_eps,
    referenced_eps,
    rewrite_eps_references,
)
from app.sources import download_arxiv, retry_delay, safe_path, visible_tex

EPS = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 80\nnewpath 0 0 moveto 100 80 lineto stroke showpage\n%%EOF\n"


async def notify(_):
    pass


def test_project_parent_reference_is_valid_but_archive_traversal_is_not(tmp_path):
    (tmp_path / "doc").mkdir()
    main = tmp_path / "doc/main.tex"
    main.write_text(r"\input{../shared/body.tex}", encoding="utf-8")
    validate_sources(tmp_path, "doc/main.tex")
    for value in [r"\input{../../outside.tex}", r"\includegraphics{/etc/passwd}"]:
        main.write_text(value, encoding="utf-8")
        with pytest.raises(ValueError, match="工程目录外"):
            validate_sources(tmp_path, "doc/main.tex")
    with pytest.raises(ValueError, match="不安全"):
        safe_path(tmp_path, "doc/../shared/body.tex")


def test_literal_percent_does_not_hide_subsequent_active_package():
    text = r"\verb|%| \lstinline[columns=fixed]|\usepackage{xeCJK}| \usepackage{graphicx} % \usepackage{color}"
    visible = visible_tex(text)
    assert len(visible) == len(text)
    assert r"\usepackage{graphicx}" in visible
    assert r"\usepackage{xeCJK}" not in visible
    assert r"\usepackage{color}" not in visible
    assert text.index(r"\usepackage{graphicx}") == visible.index(
        r"\usepackage{graphicx}"
    )


def test_legacy_package_normalization_preserves_literal_examples(tmp_path):
    text = (
        r"\ProvidesPackage{custom}\pdfinfo{/Title (Metadata)}"
        + "\n"
        + r"\begin{verbatim}\pdfinfo{example}\pdfoutput=1\usepackage[pdftex]{graphicx}\end{verbatim}"
    )
    path = tmp_path / "custom.sty"
    path.write_text(text, encoding="utf-8")
    prepare_engine_sources(tmp_path, "tectonic")
    fixed = path.read_text(encoding="utf-8")
    assert "/Title" not in fixed
    assert text[text.index(r"\begin{verbatim}") :] in fixed
    assert r"\PassOptionsToPackage" not in fixed


@pytest.mark.parametrize(
    "prefix",
    [
        "% Alternative: \\usepackage{xeCJK}\n",
        r"\begin{verbatim}\usepackage{xeCJK}\end{verbatim}",
        r"\lstinline|\usepackage{xeCJK}|",
    ],
)
def test_font_detection_ignores_comments_and_verbatim(prefix):
    source = (
        r"\documentclass{article}\begin{document}" + prefix + r"Body.\end{document}"
    )
    prepared = prepare_chinese(source, "简体中文", "tectonic")
    assert r"\setCJKmainfont{FandolSong-Regular.otf}" in prepared


def test_path_macro_resolution_is_bounded_and_conservative():
    assert expand_graphic_path(r"\dir{}/plot.eps", {r"\dir": "figs"}) == "figs/plot.eps"
    assert expand_graphic_path(r"\dir plot.eps", {r"\dir": "figs/"}) == "figs/plot.eps"
    for value, definitions in [
        (r"\unknown", {}),
        (r"\cycle", {r"\cycle": r"\cycle"}),
        (r"\parameter", {r"\parameter": "#1.eps"}),
        (r"\dir", {r"\dir": None}),
    ]:
        assert expand_graphic_path(value, definitions) is None


def test_eps_shared_paths_and_macros_are_found_without_model_execution(tmp_path):
    (tmp_path / "figs").mkdir()
    (tmp_path / "figs/plot.eps").write_bytes(EPS)
    main = tmp_path / "main.tex"
    main.write_text(
        r"\documentclass{article}\input{settings}\input{body}", encoding="utf-8"
    )
    settings = tmp_path / "settings.tex"
    settings.write_text(
        r"\graphicspath{{figs/}}\newcommand{\plotfile}{plot.eps}", encoding="utf-8"
    )
    body = tmp_path / "body.tex"
    body.write_text(r"\includegraphics{\plotfile}", encoding="utf-8")
    context = graphics_context(tmp_path, "main.tex", [main, settings, body])
    expected = tmp_path / "figs/plot.eps"
    assert referenced_eps(tmp_path, "main.tex", [main, settings, body], context) == {
        expected
    }
    result = rewrite_eps_references(
        body.read_text(encoding="utf-8"),
        body,
        tmp_path,
        "main.tex",
        {expected: expected.with_suffix(".pdf")},
        context,
    )
    assert result == r"\includegraphics{figs/plot.pdf}"


def test_native_author_pdf_keeps_priority_when_an_explicit_eps_is_converted(tmp_path):
    (tmp_path / "plot.eps").write_bytes(EPS)
    (tmp_path / "plot.pdf").write_bytes(b"author PDF")
    main = tmp_path / "main.tex"
    text = r"\includegraphics{plot} \includegraphics{plot.eps}"
    main.write_text(text, encoding="utf-8")
    result = rewrite_eps_references(
        text,
        main,
        tmp_path,
        "main.tex",
        {tmp_path / "plot.eps": tmp_path / "plot.converted.pdf"},
    )
    assert result == r"\includegraphics{plot} \includegraphics{plot.converted.pdf}"


async def test_retry_after_is_respected_and_partial_download_is_removed(
    tmp_path, monkeypatch
):
    from app import sources

    calls = 0
    delays = []

    def handle(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "31"})
        return httpx.Response(200, content=b"source bytes")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        sources.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(sources.asyncio, "sleep", sleep)
    destination = tmp_path / "upload.bin"
    await download_arxiv("1706.03762", destination, notify)
    assert destination.read_bytes() == b"source bytes"
    assert delays == [31]
    assert not destination.with_suffix(".part").exists()


async def test_cancelled_download_does_not_leave_a_partial_archive(
    tmp_path, monkeypatch
):
    from app import sources

    class CancelledStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"partial bytes"
            raise asyncio.CancelledError()

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        sources.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, stream=CancelledStream())
            ),
            **kwargs,
        ),
    )
    destination = tmp_path / "upload.bin"
    with pytest.raises(asyncio.CancelledError):
        await download_arxiv("1706.03762", destination, notify)
    assert not destination.exists()
    assert not destination.with_suffix(".part").exists()


def test_retry_after_malformed_values_use_bounded_retry_policy():
    assert retry_delay("invalid", 5) == 5
    assert retry_delay("NaN", 5) == 5
    assert retry_delay("-9", 5) == 5
    assert retry_delay("2", 5) == 5


@pytest.mark.parametrize(
    "case", ["relative", "package", "comment_cjk", "macro_eps", "shared_eps"]
)
async def test_real_compiler_preserves_text_and_figures_after_preparation(
    tmp_path, case
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    if "eps" in case and not find_ghostscript():
        pytest.skip("Optional Ghostscript not installed")
    root = tmp_path / "source"
    root.mkdir()
    main = "doc/main.tex" if case == "relative" else "main.tex"
    preamble = r"\documentclass{article}\usepackage{graphicx}"
    body = "A valid academic example."
    reachable = [main]
    if case == "relative":
        (root / "doc").mkdir()
        (root / "shared").mkdir()
        (root / "shared/body.tex").write_text(body, encoding="utf-8")
        body = r"\input{../shared/body.tex}"
    if case == "package":
        (root / "custom.sty").write_text(
            r"\ProvidesPackage{custom}\pdfinfo{/Author (A)}", encoding="utf-8"
        )
        preamble += r"\usepackage{custom}"
    if case == "comment_cjk":
        preamble += "% Alternative: \\usepackage{xeCJK}\n"
        body = "这段中文应该正常显示。"
    if case == "macro_eps":
        (root / "figure.eps").write_bytes(EPS)
        preamble += r"\newcommand{\figfile}{figure.eps}"
        body += r"\includegraphics{\figfile}"
    if case == "shared_eps":
        (root / "figs").mkdir()
        (root / "figs/figure.eps").write_bytes(EPS)
        (root / "settings.tex").write_text(r"\graphicspath{{figs/}}", encoding="utf-8")
        (root / "body.tex").write_text(
            body + r"\includegraphics{figure.eps}", encoding="utf-8"
        )
        preamble += r"\input{settings}"
        body = r"\input{body}"
        reachable += ["settings.tex", "body.tex"]
    (root / main).write_text(
        preamble + r"\begin{document}" + body + r"\end{document}", encoding="utf-8"
    )
    prepare_engine_sources(root, "tectonic")
    await prepare_eps(root, main, notify, source_files=reachable)
    if case == "comment_cjk":
        import shutil

        shutil.copytree(
            Path(__file__).parents[1] / "app/resources/fonts", root / "texglot-fonts"
        )
        (root / main).write_text(
            prepare_chinese(
                (root / main).read_text(encoding="utf-8"), "简体中文", "tectonic"
            ),
            encoding="utf-8",
        )
    pdf, warnings = await compile_pdf(
        root, main, tmp_path / "build", "tectonic", notify, timeout=120
    )
    assert not warnings
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert (
        "这段中文应该正常显示。"
        if case == "comment_cjk"
        else "A valid academic example."
    ) in text
    if "eps" in case:
        assert reader.pages[0]["/Resources"]["/XObject"]
        image = next(root.rglob("figure.pdf"))
        first_hash = hashlib.sha256(image.read_bytes()).hexdigest()
        image.unlink()
        # Restore the original EPS reference to prove repeated recovery produces
        # deterministic figures rather than invalidating the original-PDF cache.
        for document in root.rglob("*.tex"):
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "figure.pdf", "figure.eps"
                ),
                encoding="utf-8",
            )
        await prepare_eps(root, main, notify, source_files=reachable)
        assert hashlib.sha256(image.read_bytes()).hexdigest() == first_hash


def test_invalid_float_position_is_removed_without_touching_literal_source():
    from app.compiler import normalize_engine

    text = (
        r"\begin{figure*}[!ct]Content\end{figure*}"
        + "\n"
        + r"\begin{verbatim}\begin{figure}[!ct]\end{verbatim}"
    )
    fixed = normalize_engine(text, "tectonic")
    assert fixed.startswith(r"\begin{figure*}[!t]")
    assert r"\begin{verbatim}\begin{figure}[!ct]\end{verbatim}" in fixed
    assert (
        normalize_engine(r"\begin{table}[H]Content\end{table}", "tectonic")
        == r"\begin{table}[H]Content\end{table}"
    )
    assert (
        normalize_engine(r"\begin{figure}[c]Content\end{figure}", "tectonic")
        == r"\begin{figure}Content\end{figure}"
    )


def test_pixels_are_changed_only_in_dimension_arguments():
    from app.compiler import normalize_engine

    source = r"\includegraphics[width=400px,alt=400px]{image.pdf} The image is 400px wide. \caption{At 400px resolution} \verb|\hspace{400px}|"
    output = normalize_engine(source, "tectonic")
    assert r"width=400\pdfpxdimen,alt=400px" in output
    assert "The image is 400px wide." in output
    assert r"\caption{At 400px resolution}" in output
    assert r"\verb|\hspace{400px}|" in output


@pytest.mark.parametrize("custom", [False, True])
async def test_native_xetex_pixel_register_preserves_custom_dimensions(
    tmp_path, custom
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.tex").write_text(
        r"\documentclass{article}\newlength{\pixelcheck}\begin{document}\input{body}\end{document}",
        encoding="utf-8",
    )
    setting = r"\pdfpxdimen=4pt\divide\pdfpxdimen by 2" if custom else ""
    expected = "20pt" if custom else "657820sp"
    (root / "body.tex").write_text(
        setting
        + r"\setlength{\pixelcheck}{10px}\ifdim\pixelcheck="
        + expected
        + r"\typeout{PIXEL-CHECK-PASSED}\else\errmessage{Pixel dimension changed}\fi A valid dimension. \rule{10px}{1pt}",
        encoding="utf-8",
    )
    prepare_engine_sources(root, "tectonic")
    _, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify, timeout=120
    )
    assert not warnings
    assert "PIXEL-CHECK-PASSED" in (tmp_path / "build/main.log").read_text(
        encoding="utf-8"
    )


def test_makefile_parser_handles_targets_spaces_windows_paths_and_escapes():
    from app.compiler import makefile_inputs

    content = "build\\ folder/main.pdf build/main.log : source\\ folder/main.tex \\\n source\\ folder/body\\#1.tex cash$$file.tex C:\\source\\body.tex\nignored.tex : other.tex\n"
    assert makefile_inputs(content) == [
        "source folder/main.tex",
        "source folder/body#1.tex",
        "cash$file.tex",
        r"C:\source\body.tex",
    ]
    assert makefile_inputs("# a comment\nnot a rule") is None


def test_recorded_dependencies_reject_outputs_and_project_escape(tmp_path):
    from app.compiler import compiled_dependencies

    root = tmp_path / "source"
    out = tmp_path / "build"
    root.mkdir()
    out.mkdir()
    for name in ["main.tex", "body.tex", "custom.sty"]:
        (root / name).write_text("paper", encoding="utf-8")
    outside = tmp_path / "outside.tex"
    outside.write_text("private", encoding="utf-8")
    (out / "dependencies.mk").write_text(
        f"{out}/artifact.tex : {root}/main.tex {out}/body.tex {out}/custom.sty {outside}\n",
        encoding="utf-8",
    )
    assert compiled_dependencies(root, "main.tex", out, "tectonic") == [
        "body.tex",
        "custom.sty",
        "main.tex",
    ]
    (out / "main.fls").write_text(
        f"PWD {root}\nINPUT main.tex\nINPUT {root}/body.tex\nINPUT {outside}\nOUTPUT {root}/custom.sty\n",
        encoding="utf-8",
    )
    assert compiled_dependencies(root, "main.tex", out, "xelatex") == [
        "body.tex",
        "main.tex",
    ]


async def test_real_compiler_records_dynamic_inputs_and_skips_excluded_files(tmp_path):
    from app.compiler import compiled_dependencies

    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source space"
    root.mkdir()
    (root / "main.tex").write_text(
        r"\documentclass{article}\def\selected{body}\begin{document}\input{\selected}\end{document}",
        encoding="utf-8",
    )
    (root / "body.tex").write_text("The actual paper body.", encoding="utf-8")
    (root / "unused.tex").write_text("This is an unused appendix.", encoding="utf-8")
    out = tmp_path / "build space"
    prepare_engine_sources(root, "tectonic")
    await compile_pdf(root, "main.tex", out, "tectonic", notify, timeout=120)
    assert compiled_dependencies(root, "main.tex", out, "tectonic") == [
        "body.tex",
        "main.tex",
    ]


def test_comment_terminator_trims_tabs_but_keeps_verbatim_examples():
    from app.compiler import normalize_engine

    text = "\\begin{comment}\nignored\n\\end{comment}\t \n\\begin{verbatim}\n\\end{comment}\t\n\\end{verbatim}\n"
    fixed = normalize_engine(text, "tectonic")
    assert fixed.startswith("\\begin{comment}\nignored\n\\end{comment}\n")
    assert "\\begin{verbatim}\n\\end{comment}\t\n\\end{verbatim}" in fixed


async def test_real_comment_environment_with_trailing_tabs_is_compilable(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.tex").write_text(
        "\\documentclass{article}\\usepackage{comment}\n\\begin{document}\n\\begin{comment}\nignored\n\\end{comment}\t \nA valid paper.\\end{document}",
        encoding="utf-8",
    )
    prepare_engine_sources(root, "tectonic")
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify, timeout=120
    )
    assert not warnings
    assert "A valid paper." in PdfReader(pdf).pages[0].extract_text()


def test_main_file_detection_does_not_choose_a_verbatim_document_example(tmp_path):
    from app.sources import find_main

    (tmp_path / "main.tex").write_text(
        r"\begin{verbatim}\documentclass{article}\begin{document}Example\end{document}\end{verbatim}",
        encoding="utf-8",
    )
    (tmp_path / "paper.tex").write_text(
        r"\documentclass{article}\begin{document}Actual paper.\end{document}",
        encoding="utf-8",
    )
    assert find_main(tmp_path) == ("paper.tex", ["paper.tex"])


async def test_no_page_compile_cannot_return_an_old_pdf(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    main = root / "main.tex"
    main.write_text(
        r"\documentclass{article}\begin{document}First PDF.\end{document}",
        encoding="utf-8",
    )
    out = tmp_path / "build"
    await compile_pdf(root, "main.tex", out, "tectonic", notify, timeout=120)
    assert (out / "main.pdf").exists()
    main.write_text(
        r"\documentclass{article}\begin{document}\end{document}", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        await compile_pdf(root, "main.tex", out, "tectonic", notify, timeout=120)
    assert not (out / "main.pdf").exists()


SCOPED_EPS_CASES = [
    r"\def\figfile{a.eps}\includegraphics{\figfile}\def\figfile{b.eps}\includegraphics{\figfile}",
    r"\def\figfile{a.eps}{\def\figfile{b.eps}\includegraphics{\figfile}}\includegraphics{\figfile}",
    r"\def\figfile{a.eps}\def\otherfile{b.eps}\includegraphics{\figfile}\let\figfile\otherfile\includegraphics{\figfile}",
    r"\def\figfile{a.eps}\def\otherfile{b.eps}{\let\figfile\otherfile\includegraphics{\figfile}}\includegraphics{\figfile}",
    r"\graphicspath{{a/}}\includegraphics{plot.eps}\graphicspath{{b/}}\includegraphics{plot.eps}",
    r"\graphicspath{{a/}}{\graphicspath{{b/}}\includegraphics{plot.eps}}\includegraphics{plot.eps}",
]


@pytest.mark.parametrize("body", SCOPED_EPS_CASES)
async def test_ambiguous_eps_scope_fails_before_any_asset_is_changed(
    tmp_path, body, monkeypatch
):
    from app import graphics

    monkeypatch.setattr(graphics, "find_ghostscript", lambda: None)
    for name in ["a.eps", "b.eps", "a/plot.eps", "b/plot.eps"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(EPS)
    original_pdf = tmp_path / "b/plot.pdf"
    original_pdf.write_bytes(b"different author PDF; must not replace its EPS")
    main = tmp_path / "main.tex"
    source = (
        r"\documentclass{article}\usepackage{graphicx}\begin{document}"
        + body
        + r"\end{document}"
    )
    main.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match="无法安全"):
        await prepare_eps(tmp_path, "main.tex", notify)
    assert main.read_text(encoding="utf-8") == source
    assert (
        original_pdf.read_bytes() == b"different author PDF; must not replace its EPS"
    )
    assert list(tmp_path.rglob("*.pdf")) == [original_pdf]


def test_one_ordered_graphicspath_and_extension_order_keep_tex_priority(tmp_path):
    for name in ["a/plot.eps", "b/plot.pdf", "a/plot.png"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test asset")
    main = tmp_path / "main.tex"
    main.write_text(
        r"\graphicspath{{a/}{b/}}\DeclareGraphicsExtensions{.pdf,.eps,.png}\includegraphics{plot}",
        encoding="utf-8",
    )
    assert referenced_eps(tmp_path, "main.tex", [main]) == set()
    (tmp_path / "b/plot.pdf").unlink()
    assert referenced_eps(tmp_path, "main.tex", [main]) == {tmp_path / "a/plot.eps"}


async def test_scoped_pdf_only_macro_does_not_force_conversion_of_unused_eps(
    tmp_path, monkeypatch
):
    from app import graphics

    monkeypatch.setattr(graphics, "find_ghostscript", lambda: None)
    (tmp_path / "unused.eps").write_bytes(EPS)
    source = r"\def\figfile{a.pdf}\let\figfile\otherfile\includegraphics{\figfile}"
    (tmp_path / "main.tex").write_text(source, encoding="utf-8")
    assert await prepare_eps(tmp_path, "main.tex", notify) == 0
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == source


async def test_explicit_paths_render_a_and_b_without_using_the_other_author_pdf(
    tmp_path,
):
    if not find_compiler("tectonic") or not find_ghostscript():
        pytest.skip("Optional native Tectonic and Ghostscript not installed")
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    root = tmp_path / "source"
    root.mkdir()
    for label in ("a", "b"):
        folder = root / label
        folder.mkdir()
        content = f"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 180 80\n/Helvetica findfont 18 scalefont setfont\n10 30 moveto (FIGURE_{label.upper()}) show\nshowpage\n%%EOF\n"
        (folder / "plot.eps").write_text(content, encoding="utf-8")
    writer = PdfWriter()
    page = writer.add_blank_page(180, 80)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 30 Td (UNRELATED_PDF) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    original_pdf = root / "b/plot.pdf"
    writer.write(original_pdf)
    original_hash = hashlib.sha256(original_pdf.read_bytes()).hexdigest()
    main = root / "main.tex"
    main.write_text(
        r"\documentclass{article}\usepackage{graphicx}\begin{document}\graphicspath{{a/}}\includegraphics{a/plot.eps}\graphicspath{{b/}}\includegraphics{b/plot.eps}\end{document}",
        encoding="utf-8",
    )
    prepare_engine_sources(root, "tectonic")
    assert await prepare_eps(root, "main.tex", notify) == 2
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify, timeout=120
    )
    text = "".join(page.extract_text() for page in PdfReader(pdf).pages)
    assert "FIGURE_A" in text and "FIGURE_B" in text
    assert "UNRELATED_PDF" not in text
    assert not warnings
    assert hashlib.sha256(original_pdf.read_bytes()).hexdigest() == original_hash
    assert r"\includegraphics{a/plot.pdf}" in main.read_text(encoding="utf-8")
    assert r"\includegraphics{b/plot.texglot-" in main.read_text(encoding="utf-8")
