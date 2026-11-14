"""Small independent regressions extracted from the five-paper report."""

import pytest

from app.compiler import (
    CompilationError,
    compile_pdf,
    find_compiler,
    prepare_engine_sources,
    recover_compile_configuration,
    use_bundled_bibliography,
)
from app.latex import MARKER, segments
from app.sources import _visible_tex


def test_authored_prompt_fences_are_immutable_but_new_model_fences_are_rejected():
    text = 'Explain this example: ```json\\\\ {"value": 42} ``` and ⟪P0000⟫ here.'
    items = segments(text)
    assert items
    for item in items:
        assert item.validate_source_map() == item.source
        assert "```" not in item.masked
        assert item.target_probe("简体中文").count("```") == item.source.count("```")
        with pytest.raises(ValueError, match="无效格式"):
            item.restore(item.masked + " ```injected```")
    assert any("Explain" in MARKER.sub("", s.masked) for s in items)


def test_emergency_stretch_is_glue_not_translatable_text():
    text = (
        r"\begingroup\emergencystretch=2em plus 1pt\textbf{Readable text.}\par\endgroup"
    )
    for item in segments(text):
        item.validate_source_map()
        probe = item.target_probe("简体中文")
        if "emergencystretch" in item.source:
            assert r"\emergencystretch=2em plus 1pt" in probe
        assert "Readable" not in probe


def test_book_visibility_keeps_offsets_without_quadratic_suffix_copies():
    class Measured(str):
        copied = 0

        def __getitem__(self, key):
            value = super().__getitem__(key)
            if isinstance(key, slice):
                self.copied += len(value)
            return value

    source = Measured((r"\textbf{Visible} \verb|%literal| % comment" + "\n") * 12000)
    result = _visible_tex(source, frozenset())
    assert len(result) == len(source) and result.count("\n") == 12000
    assert result.count(r"\textbf{Visible}") == 12000
    assert "%literal" not in result and "% comment" not in result
    assert source.copied < len(source) * 3


def test_chapter_bibliography_uses_document_base_and_preserves_examples(tmp_path):
    chapter = tmp_path / "chapters" / "one.tex"
    chapter.parent.mkdir()
    chapter.with_suffix(".bbl").write_text(
        r"\begin{thebibliography}{1}\bibitem{x} Author.\end{thebibliography}",
        encoding="utf-8",
    )
    text = r"\bibliography{refs}"
    assert (
        use_bundled_bibliography(text, chapter, base_dir=tmp_path)
        == r"\input{chapters/one.bbl}"
    )
    example = r"\begin{verbatim}\bibliography{refs}\end{verbatim}"
    assert use_bundled_bibliography(example, chapter, base_dir=tmp_path) == example
    (tmp_path / "refs.bib").write_text("@book{x,title={A}}", encoding="utf-8")
    assert use_bundled_bibliography(text, chapter, base_dir=tmp_path) == text


def test_index_repair_requires_diagnosis_and_retains_every_entry(tmp_path):
    (tmp_path / "main.tex").write_text(r"\documentclass{book}", encoding="utf-8")
    index = tmp_path / "main.ind"
    original = b"\\begin{theindex}\r\n\\item \\makefirstuc {$k$-NN}, \\hyperpage{76}\r\n\\item Unchanged, 99\r\n\\end{theindex}"
    index.write_bytes(original)
    log = "error: main.ind:2: Extra }, or forgotten $"
    assert not recover_compile_configuration(
        tmp_path, "main.tex", CompilationError("", log)
    )
    error = CompilationError("", log, tex_log="Package: mfirstuc 2021 v2.07\n")
    assert recover_compile_configuration(tmp_path, "main.tex", error)
    assert index.with_name("main.ind.texglot-original").read_bytes() == original
    assert index.read_bytes() == original.replace(b"{$k$-NN}", b"{{$k$}-NN}")
    assert not recover_compile_configuration(tmp_path, "main.tex", error)


@pytest.mark.asyncio
async def test_native_standalone_and_nested_bibliography(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    (root / "figs").mkdir()
    (root / "chapters").mkdir()
    (root / "main.tex").write_text(
        r"\documentclass{article}\usepackage{standalone}\begin{document}\input{chapters/chapter}\includestandalone{figs/figure}\end{document}",
        encoding="utf-8",
    )
    (root / "figs/figure.tex").write_text(
        r"\documentclass{standalone}\begin{document}Visible diagram\end{document}",
        encoding="utf-8",
    )
    chapter = root / "chapters/chapter.tex"
    chapter.write_text(r"Text \cite{x}.\bibliography{missing}", encoding="utf-8")
    chapter.with_suffix(".bbl").write_text(
        r"\begin{thebibliography}{1}\bibitem{x} Retained reference.\end{thebibliography}",
        encoding="utf-8",
    )
    prepare_engine_sources(root, "tectonic", main="main.tex")
    assert (
        (root / "figs/figure.tex")
        .read_text(encoding="utf-8")
        .startswith(r"\documentclass")
    )
    chapter.write_text(
        use_bundled_bibliography(
            chapter.read_text(encoding="utf-8"), chapter, base_dir=root
        ),
        encoding="utf-8",
    )

    async def notify(_):
        pass

    pdf, _ = await compile_pdf(root, "main.tex", tmp_path / "build", "tectonic", notify)
    from pypdf import PdfReader

    rendered = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert "Visible diagram" in rendered and "Retained reference" in rendered


@pytest.mark.asyncio
async def test_unsupported_packages_fail_without_discarding_content(
    tmp_path, monkeypatch
):
    import app.compiler as compiler

    root = tmp_path / "source"
    root.mkdir()
    main = root / "main.tex"
    original = r"\documentclass{book}\begin{document}Important code\end{document}"
    main.write_text(original, encoding="utf-8")

    async def notify(_):
        pass

    async def missing(*args, **kwargs):
        raise CompilationError(
            "missing", "error: main.tex:2: LaTeX Error: File `pstricks.sty' not found."
        )

    monkeypatch.setattr(compiler, "_compile_document", missing)
    with pytest.raises(CompilationError, match="PSTricks"):
        await compile_pdf(root, "main.tex", tmp_path / "build", "tectonic", notify)
    (root / "default.style.minted").write_text("style", encoding="utf-8")
    (root / "hash.highlight.minted").write_text("code", encoding="utf-8")

    async def incompatible(*args, **kwargs):
        raise CompilationError(
            "cache",
            "Package minted Error: Missing style definition for default with frozencache.",
            tex_log="Package: minted 2021 v2.6\n",
        )

    monkeypatch.setattr(compiler, "_compile_document", incompatible)
    with pytest.raises(CompilationError, match="minted 3"):
        await compile_pdf(root, "main.tex", tmp_path / "build", "tectonic", notify)
    assert main.read_text(encoding="utf-8") == original
    assert (root / "hash.highlight.minted").read_text(encoding="utf-8") == "code"


@pytest.mark.asyncio
async def test_native_index_math_repair_after_a_long_log(tmp_path):
    if not find_compiler("tectonic"):
        pytest.skip("Optional Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    spam = "\\typeout{" + "A" * 900 + "}\n"
    (root / "main.tex").write_text(
        r"\documentclass{article}\usepackage{makeidx,mfirstuc,hyperref}\begin{document}"
        + spam * 160
        + r"Original text.\input{main.ind}\end{document}",
        encoding="utf-8",
    )
    original = r"\begin{theindex}\item \makefirstuc {$k$-NN}, \hyperpage{1}\item Preserved entry, 1\end{theindex}"
    (root / "main.ind").write_text(original, encoding="utf-8")
    notices = []

    async def notify(s):
        notices.append(s)

    pdf, _ = await compile_pdf(root, "main.tex", tmp_path / "build", "tectonic", notify)
    from pypdf import PdfReader

    rendered = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert "Preserved entry" in rendered and "NN" in rendered
    assert (root / "main.ind.texglot-original").read_text(encoding="utf-8") == original
    assert any("索引词条" in n for n in notices)
