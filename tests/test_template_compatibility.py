import pytest

from app.compiler import normalize_engine, prepare_chinese
from app.latex import MARKER, segments


def test_legacy_encoding_metadata_and_math_fonts_keep_paper_content():
    source = r"""% \usepackage[latin9]{inputenc} and \pdfinfo{comment}
\documentclass{amsart}
\usepackage[T1]{fontenc}
\usepackage[latin9]{inputenc}
\usepackage{newpxtext}
\usepackage[notextcomp]{stix}
\pdfinfo{/TemplateVersion (2025.1)}
\begin{document}The genus is $g(d,s)$.\end{document}"""
    output = normalize_engine(source, "tectonic")
    assert output.startswith(r"\PassOptionsToPackage{no-math}{fontspec}")
    assert "% \\usepackage[latin9]{inputenc} and \\pdfinfo{comment}" in output
    assert output.count(r"\usepackage[latin9]{inputenc}") == 1
    assert r"\usepackage[T1]{fontenc}" not in output
    assert "/TemplateVersion" not in output
    assert r"\usepackage[notextcomp]{stix}" in output
    assert r"The genus is $g(d,s)$." in output
    assert normalize_engine(output, "tectonic") == output


def test_pdftex_capabilities_do_not_rewrite_prose_or_supported_engine():
    source = r"""% \pdfcompresslevel=0 \DisableLigatures[f]{family=sf*}
\RequirePackage[tracking=smallcaps,protrusion=true,expansion=true]{microtype}
\DisableLigatures[f]{family=sf*}
\microtypesetup{spacing=true,kerning=true,protrusion=true}
\pdfcompresslevel=0
\pdfoptionpdfminorversion=6
\input{glyphtounicode}
\pdfgentounicode=1
\verb|\pdfcompresslevel=0|
The value remains 6 and the equation is $x=1$."""
    output = normalize_engine(source, "tectonic")
    assert "[tracking=false,protrusion=true,expansion=false]" in output
    assert "{spacing=false,kerning=false,protrusion=true}" in output
    assert output.count(r"\DisableLigatures") == 1  # Only the comment.
    assert output.count(r"\pdfcompresslevel=0") == 2  # Comment and literal example.
    assert r"\input{glyphtounicode}" not in output
    assert output.splitlines()[-1] == source.splitlines()[-1]
    assert output.count("\n") == source.count("\n")
    assert normalize_engine(output, "tectonic") == output
    assert normalize_engine(source, "lualatex") == source


@pytest.mark.asyncio
async def test_real_compiler_preserves_threepart_table_and_notes(tmp_path):
    from pypdf import PdfReader

    from app.compiler import compile_pdf, find_compiler, fit_tables

    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    source = r"""\documentclass{article}
\usepackage{threeparttable,booktabs,adjustbox}
\begin{document}
\begin{table}\begin{threeparttable}
\caption{A measured table}\begin{tabular}{ll}
\toprule Method & Result\\\midrule Baseline\tnote{a} & 42\\\bottomrule
\end{tabular}
\begin{tablenotes}\item[a] Notes survive the table measurement.\end{tablenotes}
\end{threeparttable}\end{table}
\begin{verbatim}\begin{table}\begin{tabular}{l}Example\end{tabular}\end{table}\end{verbatim}
\end{document}"""
    fixed, count = fit_tables(source)
    assert count == 1
    assert r"\begin{adjustbox}{max width=\linewidth}\begin{threeparttable}" in fixed
    assert fit_tables(fixed) == (fixed, 0)
    (root / "main.tex").write_text(fixed, encoding="utf-8")

    async def notify(_):
        pass

    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert not warnings
    rendered = "".join(p.extract_text() for p in PdfReader(pdf).pages)
    import re

    rendered = re.sub(r"-\s*\n\s*", "", rendered)
    rendered = " ".join(rendered.split())
    assert all(
        s in rendered for s in ("A measured table", "Baseline", "42", "Notes survive")
    )


@pytest.mark.asyncio
async def test_real_native_font_microtype_keeps_quotes_and_math(tmp_path):
    from pypdf import PdfReader

    from app.compiler import compile_pdf, find_compiler

    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root = tmp_path / "source"
    root.mkdir()
    source = r"""\documentclass{article}
\usepackage[tracking=smallcaps,expansion=true]{microtype}
\DisableLigatures[f]{family=sf*}
\usepackage{fontspec,textcomp}
\begin{document}
Native text and legacy symbols: \textquotedbl. Math stays $E=mc^2$.
\begin{verbatim}"Literal quotes stay visible."\end{verbatim}
\end{document}"""
    (root / "main.tex").write_text(
        normalize_engine(source, "tectonic"), encoding="utf-8"
    )

    async def notify(_):
        pass

    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert not warnings
    rendered = "".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert "Native text" in rendered and "Literal quotes stay visible." in rendered


@pytest.mark.asyncio
async def test_generated_unicode_math_is_visible_without_rewriting_source_math(
    tmp_path,
):
    from pypdf import PdfReader

    from app.compiler import compile_pdf, find_compiler

    if not find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    item = segments(
        r"The comparison uses $x+y=1$ and conventional scientific symbols."
    )[0]
    output = item.restore("The symbols σ δ ζ α ≤ ≥ ∞ coexist with ⟪P0000⟫.")
    assert "$x+y=1$" in output
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.tex").write_text(
        r"\documentclass{article}\begin{document}" + output + r"\end{document}",
        encoding="utf-8",
    )

    async def notify(_):
        pass

    pdf, warnings = await compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    assert not warnings
    text = "".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert all(symbol in text for symbol in "σδζα≤≥∞")


def test_legacy_cjk_wrappers_become_groups_and_expose_english_prose():
    source = r"""\documentclass{article}
\usepackage{CJKutf8,booktabs}
\begin{document}\begin{CJK*}{UTF8}{gbsn}
\section{Example}中文正文。 English text stays accessible.
\end{CJK*}\end{document}"""
    output = normalize_engine(source, "tectonic")
    assert r"\usepackage{booktabs}" in output
    assert r"\begin{CJK" not in output
    assert r"\usepackage{xeCJK}" in output
    assert "中文正文。" in output
    exposed = " ".join(MARKER.sub("", item.masked) for item in segments(output))
    assert "English text stays accessible." in exposed
    chinese = prepare_chinese(output, "简体中文", "tectonic")
    assert "setCJKfallbackfamilyfont" in chinese


def test_theorem_aliases_do_not_hide_mathematical_claims():
    text = r"""\documentclass{article}
\newcommand{\bt}{\begin{thm}}\newcommand{\et}{\end{thm}}
\newcommand{\be}{\begin{equation}}\newcommand{\ee}{\end{equation}}
\begin{document}
\bt The curve is smooth and has degree $d$.\et
We obtain \be g(d,s)=d+s \ee by induction.
\end{document}"""
    items = segments(text)
    exposed = " ".join(MARKER.sub("", item.masked) for item in items)
    assert "The curve is smooth and has degree" in exposed
    assert "by induction." in exposed
    assert "g(d,s)" not in exposed
    assert all(item.restore(item.masked) == item.source for item in items)


def test_noindent_label_and_accented_letters_are_not_mistranslated():
    text = r"\noindent{KeyWords:} K\"oppen function."
    item = segments(text)[0]
    assert "KeyWords:" in item.masked
    assert r"K\"oppen" in item.protected
    assert item.literal_value(r"K\"oppen") == "Köppen"
    assert r"\"" not in item.protected
    output = item.masked.replace("KeyWords:", "关键词：").replace("function.", "函数。")
    assert item.restore(output) == r"\noindent{关键词：} K\"oppen 函数。"


@pytest.mark.asyncio
async def test_eps_conversion_keeps_original_and_uses_pdf_reference(tmp_path):
    from pypdf import PdfReader

    from app.graphics import find_ghostscript, prepare_eps

    if not find_ghostscript():
        pytest.skip("Optional Ghostscript not installed")
    source = tmp_path / "figure.eps"
    original = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 80\nnewpath 0 0 moveto 100 80 lineto stroke showpage\n%%EOF\n"
    source.write_bytes(original)
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\usepackage{graphicx}\begin{document}\includegraphics{figure.eps}\end{document}"
    )

    async def notify(_):
        pass

    assert await prepare_eps(tmp_path, "main.tex", notify) == 1
    assert source.read_bytes() == original
    assert r"\includegraphics{figure.pdf}" in (tmp_path / "main.tex").read_text()
    pdf = PdfReader(tmp_path / "figure.pdf")
    assert len(pdf.pages) == 1
    assert float(pdf.pages[0].mediabox.width) == 100
    assert float(pdf.pages[0].mediabox.height) == 80
    assert not list(tmp_path.glob("*.part.pdf"))


def test_eps_paths_and_comments_preserve_existing_pdf(tmp_path):
    from app.graphics import rewrite_eps_references

    figures = tmp_path / "figures"
    figures.mkdir()
    main = tmp_path / "main.tex"
    text = r"""\graphicspath{{figures/}}
% \includegraphics{plot.eps}
\includegraphics[width=4cm]{plot.eps}
\DeclareGraphicsExtensions{.eps,.png}"""
    main.write_text(text)
    result = rewrite_eps_references(
        text,
        main,
        tmp_path,
        "main.tex",
        {(figures / "plot.eps").resolve(): figures / "plot.texglot-abc.pdf"},
    )
    assert r"% \includegraphics{plot.eps}" in result
    assert r"\includegraphics[width=4cm]{figures/plot.texglot-abc.pdf}" in result
    assert r"\DeclareGraphicsExtensions{.eps,.png}" in result


def test_model_cannot_insert_prose_between_format_command_and_argument():
    item = segments(r"\textbf{Important}: Text remains.")[0]
    assert (
        item.restore("⟪P0000⟫⟪P0001⟫重要⟪P0002⟫：文本保留。")
        == r"\textbf{重要}：文本保留。"
    )
    with pytest.raises(ValueError, match="参数之间"):
        item.restore("⟪P0000⟫重要⟪P0001⟫：文本保留。⟪P0002⟫")


def test_normalization_does_not_rewrite_literal_latex_examples():
    source = r"""\documentclass{article}
\begin{document}
\begin{verbatim}
\usepackage[latin9]{inputenc}
\usepackage{CJKutf8}
\pdfinfo{/Author (example)}
\begin{CJK}{UTF8}{gbsn}example\end{CJK}
\end{verbatim}
\end{document}"""
    output = normalize_engine(source, "tectonic")
    assert source in output


def test_short_title_does_not_hide_preamble_title():
    text = r"\documentclass{article}\title[Short]{Long title for translation}\begin{document}Body\end{document}"
    items = segments(text)
    assert items[0].role == "title"
    assert items[0].source == "Long title for translation"


def test_icml_title_inside_two_column_header_is_translated_but_authors_are_not():
    text = r"""\documentclass{article}\icmltitlerunning{Short title}
\begin{document}\twocolumn[
\icmltitle{A long paper title}
\begin{icmlauthorlist}\icmlauthor{Alice Smith}{uni}\end{icmlauthorlist}
\icmlaffiliation{uni}{University Name}\icmlkeywords{Machine Learning}
]\begin{abstract}The method improves learning.\end{abstract}\end{document}"""
    items = segments(text)
    exposed = " ".join(MARKER.sub("", item.masked) for item in items)
    assert "A long paper title" in exposed and "Short title" in exposed
    assert "Machine Learning" in exposed and "The method improves learning." in exposed
    assert "Alice Smith" not in exposed and "University Name" not in exposed
    assert any(
        item.role == "title" and "A long paper title" in item.source for item in items
    )
    assert all(item.restore(item.masked) == item.source for item in items)


def test_first_attempt_keeps_command_and_opening_brace_in_one_token():
    item = segments(r"\textbf{Accuracy}: 82.4 with $n=3$.")[0]
    bound, expansion = item.compact(arguments_only=True)
    assert r"\textbf{" in bound.protected
    assert "82.4" in bound.protected and "$n=3$" in bound.protected
    translated = bound.masked.replace("Accuracy", "准确率").replace(" with ", "，其中")
    expanded = MARKER.sub(lambda match: expansion[match[0]], translated)
    assert item.restore(expanded) == r"\textbf{准确率}: 82.4，其中$n=3$."


def test_exact_copied_math_can_be_recovered_without_guessing_identity():
    from app.llm import recover_copied_tokens

    item = segments(r"Graphs of $s$ versus $r$.")[0]
    result = recover_copied_tokens("$s$ 与 $r$ 的关系图。", item)
    assert item.restore(result) == "$s$ 与 $r$ 的关系图。"
    for source, output in [
        ("We use $s$ and $s$.", "$s$ 与 $s$。"),
        ("We use $s$.", "$t$。"),
        ("We use $s$.", "$$s$$。"),
        ("We use $s$.", "$s$ 和 $s$。"),
    ]:
        original = segments(source)[0]
        unchanged = recover_copied_tokens(output, original)
        assert unchanged == output
        with pytest.raises(ValueError):
            original.restore(unchanged)


def test_exposed_header_keeps_tex_lengths_and_glue_out_of_translation():
    text = r"""\twocolumn[\icmltitle{A title}\vskip 0.3in]
\noindent Body text. \hskip 2pt plus 1fil minus .5pt More text.
\kern-.2em \parskip=1.5\baselineskip Text.
\hskip\dimexpr\linewidth-1cm\relax End."""
    items = segments(text)
    exposed = " ".join(MARKER.sub("", item.masked) for item in items)
    assert "A title" in exposed and "Body text." in exposed
    assert "0.3in" not in exposed and "1fil" not in exposed and ".5pt" not in exposed
    assert "baselineskip" not in exposed and "dimexpr" not in exposed
    assert all(item.restore(item.masked) == item.source for item in items)


def test_copied_formatting_and_references_only_recover_exact_source_tokens():
    from app.llm import recover_copied_tokens

    item = segments(r"\paragraph{Ensuring \eqref{bound} on the domain.}")[0]
    bound, _ = item.compact(arguments_only=True)
    output = r"\paragraph{在定义域上确保\eqref{bound}成立。}"
    restored = recover_copied_tokens(output, bound)
    assert bound.restore(restored) == output
    for literal in ["10", "-1", "+1", "1.5"]:
        number = segments("The dimension is 1.")[0]
        unchanged = recover_copied_tokens("维度为" + literal + "。", number)
        with pytest.raises(ValueError):
            number.restore(unchanged)


async def test_dense_proof_repair_keeps_complete_clauses_and_all_math(monkeypatch):
    import json

    from app.config import Settings
    from app.llm import Translator

    source = "".join(f"On $I_{i}$ we bound $f_{i}$ by $a_{i}$.\n" for i in range(10))
    item = segments(source)[0]
    translator = Translator(Settings())
    seen = []

    async def complete(messages, **_):
        payload = json.loads(messages[-1]["content"])
        assert "slots" not in payload
        text = payload["paragraph"]
        seen.append(text)
        return (
            text.replace("On ", "在")
            .replace(" we bound ", " 上，将")
            .replace(" by ", "约束为")
        )

    monkeypatch.setattr(translator, "complete", complete)
    try:
        result = item.restore(await translator.translate_slots(item))
        assert len(seen) == 10
        for i in range(10):
            assert f"在$I_{i}$ 上，将$f_{i}$约束为$a_{i}$." in result.replace(
                "在 ", "在"
            )
    finally:
        await translator.close()


async def test_unused_eps_does_not_require_ghostscript(tmp_path, monkeypatch):
    from app import graphics

    monkeypatch.setattr(graphics, "find_ghostscript", lambda: None)
    (tmp_path / "unused.eps").write_text("not executed")
    (tmp_path / "plot.eps").write_text("not executed")
    (tmp_path / "plot.pdf").write_bytes(b"preferred author PDF")
    (tmp_path / "main.tex").write_text(r"\includegraphics{plot}")

    async def notify(_):
        pass

    assert await graphics.prepare_eps(tmp_path, "main.tex", notify) == 0
    (tmp_path / "main.tex").write_text(r"\includegraphics{plot.eps}")
    with pytest.raises(ValueError, match="Ghostscript"):
        await graphics.prepare_eps(tmp_path, "main.tex", notify)


def test_copied_escape_cannot_match_prefix_of_a_different_quantity():
    from app.llm import recover_copied_tokens

    item = segments(r"See \#2 for details.")[0]
    original = r"参见\#20。"
    assert recover_copied_tokens(original, item) == original
    with pytest.raises(ValueError):
        item.restore(recover_copied_tokens(original, item))
