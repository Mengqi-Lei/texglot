"""XDV dependency discovery before safe EPS conversion, without model requests."""

import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.compiler import (
    compile_pdf,
    find_compiler,
    prepare_chinese,
    prepare_engine_sources,
    probe_source_dependencies,
)
from app.graphics import find_ghostscript, prepare_eps
from app.jobs import JobManager

EPS = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 80\nnewpath 0 0 moveto 100 80 lineto stroke showpage\n%%EOF\n"


async def notify(_):
    pass


async def test_cfg_sources_and_input_paths_participate_in_eps_preparation(tmp_path):
    if not find_compiler("tectonic") or not find_ghostscript():
        pytest.skip("Optional native Tectonic and Ghostscript not installed")
    root = tmp_path / "source"
    (root / "figures").mkdir(parents=True)
    (root / "figures/chart.eps").write_bytes(EPS)
    (root / "layout.cfg").write_text(
        r"\makeatletter\def\input@path{{figures/}{}}\makeatother"
        r"\newcommand{\chartname}{chart}"
        r"\AtBeginDocument{\includegraphics{\chartname}}",
        encoding="utf-8",
    )
    (root / "main.tex").write_text(
        r"\input{layout.cfg}\documentclass{article}\usepackage{graphicx}"
        r"\begin{document}The plotted evidence remains.\end{document}",
        encoding="utf-8",
    )
    prepare_engine_sources(root, "tectonic")
    documents, images = await probe_source_dependencies(
        root, "main.tex", tmp_path / "probe", notify
    )
    assert "layout.cfg" in documents and images == ["figures/chart.eps"]
    assert (
        await prepare_eps(
            root,
            "main.tex",
            notify,
            source_files=documents,
            used_images=[root / p for p in images],
        )
        == 1
    )
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "final", "tectonic", notify
    )
    assert not warnings
    page = PdfReader(pdf).pages[0]
    assert "The plotted evidence remains." in page.extract_text()
    assert page["/Resources"]["/XObject"]


async def test_xdv_discovers_dynamic_unicode_input_and_only_the_used_eps(tmp_path):
    if not find_compiler("tectonic") or not find_ghostscript():
        pytest.skip("Optional native Tectonic and Ghostscript not installed")
    root = tmp_path / "用户 研究 & source"
    (root / "sections").mkdir(parents=True)
    main = root / "main.tex"
    main.write_text(
        r"\documentclass{article}\usepackage{graphicx}"
        r"\newcommand{\papersection}{sections/章节 一}"
        r"\begin{document}\input{\papersection}\end{document}",
        encoding="utf-8",
    )
    child = root / "sections/章节 一.tex"
    child.write_text(
        r"An actual academic paragraph. $E=mc^2$. \includegraphics{figure.eps}"
        r"\iffalse\includegraphics{unused.eps}\fi",
        encoding="utf-8",
    )
    (root / "unused.tex").write_text(r"\includegraphics{unused.eps}", encoding="utf-8")
    (root / "figure.eps").write_bytes(EPS)
    (root / "unused.eps").write_bytes(b"unused EPS must never reach Ghostscript")
    assert JobManager.reachable_files(root, "main.tex") == ["main.tex"]
    prepare_engine_sources(root, "tectonic")
    documents, images = await probe_source_dependencies(
        root, "main.tex", tmp_path / "探测 xdv", notify, timeout=120
    )
    assert documents == ["main.tex", "sections/章节 一.tex"]
    assert images == ["figure.eps"]
    assert (tmp_path / "探测 xdv/main.xdv").is_file()
    assert not (tmp_path / "探测 xdv/main.pdf").exists()
    assert (
        await prepare_eps(
            root,
            "main.tex",
            notify,
            source_files=documents,
            used_images=[root / value for value in images],
        )
        == 1
    )
    assert r"\includegraphics{figure.eps}" in child.read_text(encoding="utf-8")
    assert len(list((root / "texglot-eps").glob("*.pdf"))) == 1
    assert r"\includegraphics{unused.eps}" in child.read_text(encoding="utf-8")
    assert not (root / "unused.pdf").exists()
    assert (root / "figure.eps").read_bytes() == EPS
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "original", "tectonic", notify, timeout=120
    )
    reader = PdfReader(pdf)
    assert not warnings
    assert "An actual academic paragraph." in reader.pages[0].extract_text()
    assert reader.pages[0]["/Resources"]["/XObject"]
    child.write_text(
        child.read_text(encoding="utf-8").replace(
            "An actual academic paragraph.", "宏展开引入的真实中文段落。"
        ),
        encoding="utf-8",
    )
    main.write_text(
        prepare_chinese(main.read_text(encoding="utf-8"), "简体中文", "tectonic"),
        encoding="utf-8",
    )
    shutil.copytree(
        Path(__file__).parents[1] / "app/resources/fonts", root / "texglot-fonts"
    )
    translated, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "translated", "tectonic", notify, timeout=120
    )
    assert not warnings
    assert "宏展开引入的真实中文段落。" in PdfReader(translated).pages[0].extract_text()


async def test_unused_eps_engineering_assets_do_not_require_ghostscript(
    tmp_path, monkeypatch
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    from app import graphics

    monkeypatch.setattr(graphics, "find_ghostscript", lambda: None)
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.tex").write_text(
        r"\documentclass{article}\usepackage{graphicx}\begin{document}"
        r"The real paper has no EPS figures.\iffalse\includegraphics{unused.eps}\fi"
        r"\end{document}",
        encoding="utf-8",
    )
    (root / "unused.eps").write_bytes(b"invalid unused author asset")
    documents, images = await probe_source_dependencies(
        root, "main.tex", tmp_path / "probe", notify, timeout=120
    )
    assert images == []
    assert (
        await prepare_eps(
            root, "main.tex", notify, source_files=documents, used_images=[]
        )
        == 0
    )
    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "original", "tectonic", notify, timeout=120
    )
    assert pdf.is_file() and not warnings
    assert not (root / "unused.pdf").exists()


@pytest.mark.parametrize("complete_trace", [True, False])
async def test_compiler_selected_assets_keep_scoped_parameterized_paths(
    tmp_path, complete_trace
):
    if not find_compiler("tectonic") or not find_ghostscript():
        pytest.skip("Optional native Tectonic and Ghostscript not installed")
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        data = (
            EPS
            if name == "a"
            else EPS.replace(b"0 0 moveto 100 80", b"0 80 moveto 100 0")
        )
        (tmp_path / name / "plot.eps").write_bytes(data)
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\usepackage{graphicx}"
        r"\newcommand{\plotasset}[1]{\includegraphics[width=100pt]{#1}}"
        r"\begin{document}Two different plots:"
        r"{\graphicspath{{./a/}}\plotasset{plot.eps}}"
        r"{\graphicspath{{b/}}\plotasset{plot.eps}}\end{document}",
        encoding="utf-8",
    )
    used = [tmp_path / "a/plot.eps"]
    if complete_trace:
        used.append(tmp_path / "b/plot.eps")
    assert await prepare_eps(tmp_path, "main.tex", notify, used_images=used) == len(
        used
    )
    if complete_trace:
        pdf, warnings = await compile_pdf(
            tmp_path, "main.tex", tmp_path / "build", "tectonic", notify
        )
        assert not warnings
        assert len(PdfReader(pdf).pages[0]["/Resources"]["/XObject"]) == 2
    else:
        # An unobserved, different image must never borrow the converted image.
        with pytest.raises(ValueError, match="编译未通过"):
            await compile_pdf(
                tmp_path, "main.tex", tmp_path / "build", "tectonic", notify
            )
    assert r"\plotasset{plot.eps}" in (tmp_path / "main.tex").read_text()
