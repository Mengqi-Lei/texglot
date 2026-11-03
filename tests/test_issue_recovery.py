import re

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from app.compiler import CompilationError, compile_pdf, find_compiler
from app.i18n import english
from app.minted import remove_unused_minted
from app.pdf_graphics import graphic_failure, page_signature, recover_pdf_graphic


def write_pdf(path, *, broken=False):
    writer = PdfWriter()
    page = writer.add_blank_page(120, 80)
    stream = DecodedStreamObject()
    stream.set_data(b"0 0 1 rg 10 10 50 30 re f")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    if broken:
        blob = path.read_bytes()
        blob = re.sub(
            rb"startxref\s+(\d+)",
            lambda m: b"startxref\n" + str(int(m[1]) - 21).encode(),
            blob,
        )
        path.write_bytes(blob)
    return path.read_bytes()


def test_unused_minted_removal_preserves_other_packages_comments_and_code(tmp_path):
    source = (
        "% \\usepackage{minted}\n"
        + r"\usepackage{listings,minted,xcolor}"
        + "\n"
        + r"\verb|\begin{minted}|"
    )
    p = tmp_path / "main.tex"
    p.write_text(source)
    assert remove_unused_minted(tmp_path) == ["main.tex"]
    assert p.read_text() == source.replace(
        "{listings,minted,xcolor}", "{listings,xcolor}"
    )
    assert remove_unused_minted(tmp_path) == []


@pytest.mark.parametrize(
    "usage",
    [
        r"\begin{minted}{python}print(1)\end{minted}",
        r"\mintinline{python}{print(1)}",
        r"\mint{python}|print(1)|",
        r"\inputminted{python}{file.py}",
        r"\newminted{python}{}",
        r"\let\inline\mint",
        r"\def\codeenv{minted}",
        r"\usemintedstyle{colorful}",
        r"\setminted{breaklines}",
    ],
)
def test_minted_uses_in_an_included_file_veto_removal(tmp_path, usage):
    p = tmp_path / "main.tex"
    p.write_text(r"\usepackage{minted}\input{body}")
    (tmp_path / "body.tex").write_text(usage)
    assert remove_unused_minted(tmp_path) == []
    assert p.read_text() == r"\usepackage{minted}\input{body}"


def test_frozen_minted_and_literal_package_examples_remain_untouched(tmp_path):
    p = tmp_path / "main.tex"
    p.write_text(r"\usepackage{minted}")
    (tmp_path / "default.pygstyle").write_text("style")
    assert remove_unused_minted(tmp_path) == []

    (tmp_path / "default.pygstyle").unlink()
    p.write_text(
        r"\newtcblisting{example}{listing only}"
        + "\n"
        + r"\begin{example}\usepackage{minted}\end{example}"
    )
    assert remove_unused_minted(tmp_path) == []


def test_minted_inference_does_not_read_symlinked_sources(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    main = root / "main.tex"
    main.write_text(r"\usepackage{minted}")
    outside = tmp_path / "outside.tex"
    outside.write_bytes(b"\xff\xfe")
    try:
        (root / "body.tex").symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks unavailable")
    assert remove_unused_minted(root) == []
    assert main.read_text() == r"\usepackage{minted}"


def test_pdf_index_repair_preserves_page_and_original(tmp_path):
    p = tmp_path / "figure.pdf"
    original = write_pdf(p, broken=True)
    before = page_signature(PdfReader(p))
    fixed, message = recover_pdf_graphic(tmp_path, "main.tex", "figure.pdf")
    assert fixed and "已修复" in message
    assert page_signature(PdfReader(p, strict=True)) == before
    assert (tmp_path / "figure.pdf.texglot-original").read_bytes() == original
    after = p.read_bytes()
    assert not recover_pdf_graphic(tmp_path, "main.tex", "figure.pdf")[0]
    assert p.read_bytes() == after


@pytest.mark.parametrize("kind", ["valid", "garbage", "empty", "encrypted", "backup"])
def test_pdf_recovery_refuses_unrelated_or_unsafe_rewrites(tmp_path, kind):
    p = tmp_path / "figure.pdf"
    if kind in {"valid", "backup"}:
        write_pdf(p, broken=kind == "backup")
    elif kind == "encrypted":
        w = PdfWriter()
        w.add_blank_page(120, 80)
        w.encrypt("password")
        w.write(p)
    else:
        p.write_bytes(b"garbage" if kind == "garbage" else b"")
    if kind == "backup":
        (tmp_path / "figure.pdf.texglot-original").write_bytes(b"keep existing backup")
    before = p.read_bytes()
    assert not recover_pdf_graphic(tmp_path, "main.tex", "figure.pdf")[0]
    assert p.read_bytes() == before


def test_graphic_diagnostics_distinguish_missing_and_unreadable(tmp_path):
    log = "error: main.tex:12: Unable to load picture or PDF file 'fig_13.pdf'"
    assert graphic_failure(log) == "fig_13.pdf"
    missing = recover_pdf_graphic(tmp_path, "main.tex", "fig_13.pdf")[1]
    assert "找不到" in missing and "fig_13.pdf" in missing
    (tmp_path / "fig_13.pdf").write_bytes(b"%PDF-broken")
    corrupt = recover_pdf_graphic(tmp_path, "main.tex", "fig_13.pdf")[1]
    assert "损坏" in corrupt
    assert not re.search("[\u4e00-\u9fff]", english(missing + "\n" + corrupt))
    assert graphic_failure("File `missing.sty' not found") == ""


def test_pdf_repair_does_not_follow_outside_or_symlink_targets(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    p = tmp_path / "outside.pdf"
    original = write_pdf(p, broken=True)
    assert not recover_pdf_graphic(root, "main.tex", "../outside.pdf")[0]
    try:
        (root / "figure.pdf").symlink_to(p)
    except OSError:
        pytest.skip("Symlinks unavailable")
    assert not recover_pdf_graphic(root, "main.tex", "figure.pdf")[0]
    assert p.read_bytes() == original


async def test_native_unused_minted_and_three_bad_figures_recover_together(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional Tectonic")
    root = tmp_path / "source"
    root.mkdir()
    for name in ("one", "two", "three"):
        write_pdf(root / (name + ".pdf"), broken=True)
    (root / "main.tex").write_text(
        r"\documentclass{article}\usepackage{graphicx,minted}\begin{document}Original text.\includegraphics{one.pdf}\includegraphics{two.pdf}\includegraphics{three.pdf}\end{document}"
    )
    messages = []

    async def notify(msg):
        messages.append(msg)

    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert not warnings
    assert len(PdfReader(pdf).pages) == 1
    assert len(PdfReader(pdf).pages[0]["/Resources"]["/XObject"]) == 3
    assert sum("已修复 PDF 插图索引" in m for m in messages) == 3
    assert sum("已移除未使用" in m for m in messages) == 1
    assert all(not re.search("[\u4e00-\u9fff]", english(m)) for m in messages)


async def test_native_used_minted_fails_with_actionable_message(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional Tectonic")
    root = tmp_path / "source"
    root.mkdir()
    p = root / "main.tex"
    source = (
        r"\documentclass{article}\usepackage{minted}\begin{document}"
        + "\n"
        + r"\begin{minted}{python}"
        + "\nprint(1)\n"
        + r"\end{minted}\end{document}"
    )
    p.write_text(source)

    async def notify(_):
        pass

    with pytest.raises(CompilationError, match="冻结缓存"):
        await compile_pdf(root, "main.tex", tmp_path / "build", "tectonic", notify)
    assert p.read_text() == source


def test_failed_pdf_rewrite_keeps_original_without_partial_backup(
    tmp_path, monkeypatch
):
    p = tmp_path / "figure.pdf"
    before = write_pdf(p, broken=True)

    def fail(*args, **kwargs):
        raise OSError("Simulated write failure")

    monkeypatch.setattr(PdfWriter, "write", fail)
    assert not recover_pdf_graphic(tmp_path, "main.tex", "figure.pdf")[0]
    assert p.read_bytes() == before
    assert not (tmp_path / "figure.pdf.texglot-original").exists()
    assert not list(tmp_path.glob(".texglot-pdf-*"))


async def test_minted_repair_preserves_existing_configuration_retry_budget(
    tmp_path, monkeypatch
):
    import app.compiler as compiler

    (tmp_path / "main.tex").write_text(r"\usepackage{minted}")
    errors = iter(
        [
            "Package minted Error: You must invoke LaTeX with the -shell-escape flag.",
            "Option clash for package xcolor",
            "Option clash for package natbib",
            None,
        ]
    )

    async def compile_once(*args, **kwargs):
        message = next(errors)
        if message:
            raise CompilationError(message, message)
        return tmp_path / "main.pdf", []

    async def notify(message):
        pass

    monkeypatch.setattr(compiler, "_compile_document", compile_once)
    monkeypatch.setattr(
        compiler, "recover_compile_configuration", lambda *args: "package options"
    )
    assert (
        await compiler.compile_pdf(
            tmp_path, "main.tex", tmp_path / "build", "tectonic", notify
        )
    )[0].name == "main.pdf"


def test_pdf_access_error_is_actionable(tmp_path, monkeypatch):
    from pathlib import Path

    p = tmp_path / "figure.pdf"
    write_pdf(p)

    def denied(self):
        raise PermissionError("test")

    monkeypatch.setattr(Path, "read_bytes", denied)
    changed, message = recover_pdf_graphic(tmp_path, "main.tex", "figure.pdf")
    assert not changed and "无法访问" in message
    assert not re.search("[\u4e00-\u9fff]", english(message))


async def test_native_missing_figure_reports_path_without_creating_placeholder(
    tmp_path,
):
    if not find_compiler("tectonic"):
        pytest.skip("Optional Tectonic")
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.tex").write_text(
        r"\documentclass{article}\usepackage{graphicx}\begin{document}\includegraphics{missing.pdf}\end{document}"
    )

    async def notify(_):
        pass

    with pytest.raises(CompilationError, match="找不到插图文件：missing.pdf"):
        await compile_pdf(root, "main.tex", tmp_path / "build", "tectonic", notify)
    assert not (root / "missing.pdf").exists()
