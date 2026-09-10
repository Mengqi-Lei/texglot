import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.config import Settings, public_settings
from app.latex import MARKER, apply_translations, segments
from app.sources import extract_source, find_main, parse_arxiv


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://arxiv.org/abs/1706.03762", "1706.03762"),
        ("https://arxiv.org/pdf/1706.03762v7.pdf?download=1", "1706.03762v7"),
        ("arXiv:1412.6980", "1412.6980"),
        ("https://arxiv.org/abs/hep-ph/0310102v2", "hep-ph/0310102v2"),
        ("https://export.arxiv.org/src/2501.14787", "2501.14787"),
    ],
)
def test_arxiv_formats(value, expected):
    assert parse_arxiv(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.test/abs/1706.03762",
        "https://arxiv.org.evil.test/abs/1706.03762",
        "http://user@arxiv.org/abs/1706.03762",
        "1706.03762/../../etc/passwd",
        "not a paper",
    ],
)
def test_arxiv_rejects_bad_input(value):
    with pytest.raises(ValueError):
        parse_arxiv(value)


def test_lossless_protection():
    text = Path("examples/academic-demo.tex").read_text(encoding="utf-8")
    items = segments(text)
    assert len(items) >= 10
    assert all(item.restore(item.masked) == item.source for item in items)
    assert (
        apply_translations(text, items, {i.key: i.restore(i.masked) for i in items})
        == text
    )
    exposed = " ".join(MARKER.sub("", i.masked) for i in items)
    assert "softmax" not in exposed
    assert "vaswani2017attention" not in exposed
    assert "TeXGlot Research Notes" not in exposed
    assert "Accuracy" in exposed
    assert "Here " in exposed


def test_marker_corruption_rejected():
    item = segments(r"Where $x$ is the unknown, see \ref{eq:one}.")[0]
    with pytest.raises(ValueError):
        item.restore(item.masked.replace("⟪P0000⟫", ""))
    with pytest.raises(ValueError):
        item.restore(item.masked.replace("⟪P0000⟫", "⟪P0001⟫"))
    result = item.restore("其中 ⟪P0000⟫ 为未知数，参见 ⟪P0001⟫。")
    assert "$x$" in result and r"\ref{eq:one}" in result


def test_generated_specials_are_escaped():
    item = segments("The accuracy increases.")[0]
    assert item.restore("准确率提升 20% & 30_40。") == r"准确率提升 20\% \& 30\_40。"


def test_generated_commands_rejected_and_literal_newlines_normalized():
    item = segments("A small example.")[0]
    with pytest.raises(ValueError):
        item.restore(r"一段 \input{evil} 文字")
    assert item.restore(r"一个\n简短示例。") == "一个\n简短示例。"


def test_restoring_protected_macro_cannot_merge_it_with_model_name():
    from app.latex import join_tex

    item = segments(r"We compare with our baseline, \ie YOLOv8.")[0]
    assert (
        item.restore("我们与基线（⟪P0000⟫⟪P0001⟫）比较。")
        == r"我们与基线（\ie YOLOv8）比较。"
    )
    assert item.restore(item.masked) == item.source
    assert join_tex([r"\model", "", "Name"]) == r"\model Name"
    assert join_tex([r"\item", "我们提出一种方法。"]) == r"\item 我们提出一种方法。"
    assert join_tex([r"\\", "Name"]) == r"\\Name"
    assert join_tex([r"\textbf{", "Name", "}"]) == r"\textbf{Name}"


def test_semantic_units_do_not_create_false_format_boundaries():
    from app.latex import movable_token

    item = segments(r"With 5.3\% less latency, see \#2 and baseline~\cite{yolo}.")[0]
    assert item.protected == [r"5.3\%", r"\#2", r"~\cite{yolo}"]
    assert all(movable_token(v) for v in item.protected)
    assert (
        item.restore("参见⟪P0001⟫和基线⟪P0002⟫，延迟降低⟪P0000⟫。")
        == r"参见\#2和基线~\cite{yolo}，延迟降低5.3\%。"
    )
    assert item.restore(item.masked) == item.source
    assert movable_token(r"\ie") and movable_token("~")
    assert movable_token(r"\&") and movable_token(r"\%")
    assert not movable_token("&") and not movable_token("{")
    with pytest.raises(ValueError):
        item.restore("⟪P0000⟫⟪P0001⟫⟪P0002⟫⟪P0003⟫")


def test_inline_scopes_allow_root_reordering_but_protect_emphasis_and_cells():
    item = segments(r"Our model uses \emph{fewer} filters than VGG \cite{vgg}.")[0]
    assert (
        item.restore("相比VGG⟪P0003⟫，模型使用⟪P0000⟫⟪P0001⟫更少⟪P0002⟫的滤波器。")
        == r"相比VGG\cite{vgg}，模型使用\emph{更少}的滤波器。"
    )
    item = segments(r"It improves by \textbf{5\%} with 2 layers.")[0]
    with pytest.raises(ValueError, match="格式边界"):
        item.restore("提升⟪P0002⟫，使用⟪P0000⟫⟪P0001⟫⟪P0004⟫⟪P0003⟫层。")
    item = segments(r"We use 2 layers. \small With 5 filters.")[0]
    with pytest.raises(ValueError, match="格式边界"):
        item.restore("使用⟪P0002⟫层。⟪P0001⟫含⟪P0000⟫个滤波器。")


def test_numerical_results_are_protected():
    item = segments("Accuracy is 82.4 and the model has 120 parameters.")[0]
    assert "82.4" not in item.masked and "120" not in item.masked
    assert item.restore(item.masked) == item.source


def test_magnitude_and_grouped_numbers_are_atomic_and_invalidate_old_cache():
    import hashlib

    from app.latex import movable_token

    source = (
        "GPT-3 has 175 billion parameters, or 175B; we test 12,288 and 3.6 million."
    )
    item = segments(source)[0]
    assert item.protected == ["GPT-3", "175 billion", "175B", "12,288", "3.6 million"]
    assert all(movable_token(v) for v in item.protected)
    assert item.restore(item.masked) == source
    assert item.key != hashlib.sha256(source.encode()).hexdigest()


def test_font_declarations_do_not_hide_caption_prose():
    source = r"\caption{\small{Generated samples on CIFAR10 and $x$.}}"
    item = segments(source)[0]
    assert "Generated samples" in MARKER.sub("", item.masked)
    assert item.restore(item.masked) == source
    result = item.restore(
        item.masked.replace("Generated samples on ", "在").replace(" and ", "与")
    )
    assert r"\small{在CIFAR10与" in result


def test_literal_name_macros_can_move_without_swapping_model_and_dataset():
    from app.latex import collect_literal_macros

    definitions = r"\newcommand{\model}{ViT\xspace}\newcommand{\dataset}{ImageNet\xspace}\newcommand{\danger}{\input{secret}}\newcommand{\wrap}[1]{#1}"
    literals = collect_literal_macros(definitions)
    assert literals == {"model": "ViT", "dataset": "ImageNet"}
    source = r"BiT outperforms \model{} on \dataset."
    item = segments(source, literal_macros=literals)[0]
    assert (
        item.restore("BiT在⟪P0001⟫上优于⟪P0000⟫。") == r"BiT在\dataset 上优于\model{}。"
    )
    assert item.key != segments(source)[0].key
    assert item.literal_value(item.protected[0]) == "ViT"
    assert item.compact()[0].literal_macros == literals
    item = segments(
        r"We compare \textbf{\model{}} on \dataset.", literal_macros=literals
    )[0]
    with pytest.raises(ValueError, match="格式边界"):
        item.restore("⟪P0002⟫在⟪P0000⟫⟪P0001⟫⟪P0004⟫⟪P0003⟫上的比较。")


def test_custom_heading_with_font_and_spacing_commands_exposes_prose():
    from app.latex import collect_text_macros

    definition = r"\newcommand{\parhead}[1]{\medskip \noindent {\bfseries\boldmath\ignorespaces #1.}\hskip 0.9em plus 0.3em minus 0.3em}"
    wrappers = collect_text_macros(definition)
    assert wrappers == {"parhead"}
    item = segments(
        r"\parhead{No Additional Inference Latency} We compare models.",
        text_macros=wrappers,
    )[0]
    assert "No Additional Inference Latency" in item.masked
    assert item.restore(item.masked) == item.source


def test_precompiled_bibliography_is_used_only_when_database_is_missing(tmp_path):
    from app.compiler import use_bundled_bibliography

    path = tmp_path / "paper.tex"
    source = "% commented \\bibliography{missing}\n" + r"\bibliography{references}"
    assert use_bundled_bibliography(source, path) == source
    path.with_suffix(".bbl").write_text(
        r"\begin{thebibliography}{1}\bibitem{x} A.\end{thebibliography}",
        encoding="utf-8",
    )
    fixed = use_bundled_bibliography(source, path)
    assert fixed.endswith(r"\input{paper.bbl}")
    assert fixed.startswith("% commented \\bibliography{missing}")
    (tmp_path / "references.bib").write_text("@article{x,title={A}}", encoding="utf-8")
    assert use_bundled_bibliography(source, path) == source


def test_structural_arguments_stay_opaque():
    text = r"\captionof{figure}{A useful caption.} \multicolumn{2}{c}{Experimental results} \textcolor{red}{A red heading} \href{https://example.com}{Project website}"
    items = segments(text)
    exposed = " ".join(MARKER.sub("", i.masked) for i in items)
    assert (
        "A useful caption" in exposed
        and "Experimental results" in exposed
        and "Project website" in exposed
    )
    assert "figure" not in exposed and "https://" not in exposed
    assert all(i.restore(i.masked) == i.source for i in items)


def test_atomic_placeholders_can_follow_target_grammar():
    item = segments("Our model achieves 28.4 BLEU on the WMT 2014 task.")[0]
    assert (
        item.restore("在 WMT ⟪P0001⟫ 任务中，模型达到 ⟪P0000⟫ BLEU。")
        == "在 WMT 2014 任务中，模型达到 28.4 BLEU。"
    )


def test_formatting_cannot_be_reordered():
    item = segments(r"\textbf{A bold statement}.")[0]
    with pytest.raises(ValueError):
        item.restore("⟪P0001⟫粗体⟪P0000⟫⟪P0002⟫。")


def test_table_width_and_pdftex_compatibility():
    from app.compiler import fit_tables, normalize_engine

    source = "\\pdfoutput=1\n" + r"\usepackage[pdftex,colorlinks]{hyperref}"
    fixed = normalize_engine(source, "tectonic")
    assert r"\pdfoutput=1" not in fixed and "[xetex,colorlinks]" in fixed
    source = r"\begin{table}\begin{tabular}{lr}Name & 82.4\\\end{tabular}\end{table}"
    fixed, n = fit_tables(source)
    assert n == 1 and r"max width=\linewidth" in fixed
    assert r"Name & 82.4" in fixed
    assert fit_tables(fixed) == (fixed, 0)


def test_main_selection_does_not_prefer_multibyte_language_edition(tmp_path):
    from app.sources import find_main

    for filename, prose in [
        ("english.tex", "The scientific result is useful. " * 10),
        ("russian.tex", "Научный результат полезен. " * 20),
    ]:
        (tmp_path / filename).write_text(
            r"\documentclass{article}\begin{document}" + prose + r"\end{document}",
            encoding="utf-8",
        )
    assert find_main(tmp_path)[0] == "english.tex"
    assert find_main(tmp_path, "russian.tex")[0] == "russian.tex"


def test_author_names_stay_but_contribution_note_is_translated():
    source = r"\documentclass{article}\title{A Paper}\author{Alice\thanks{A research contribution.}}\begin{document}Some text.\end{document}"
    items = segments(source)
    exposed = " ".join(s.masked for s in items)
    assert "Alice" not in exposed and "A research contribution" in exposed
    assert items[0].role == "title"


def test_commented_document_marker_does_not_receive_injected_packages():
    from app.compiler import inject_preamble

    text = "% A commented \\begin{document}\n\\documentclass{article}\n\\begin{document}Body\\end{document}"
    fixed = inject_preamble(text, "PACKAGE\n")
    assert fixed.startswith("% A commented \\begin{document}\n")
    assert "\\documentclass{article}\nPACKAGE\n\\begin{document}" in fixed


def test_numbers_cannot_move_between_table_cells():
    item = segments("Method & 82.4 & 1.2")[0]
    with pytest.raises(ValueError, match="表格单元格"):
        item.restore("方法 ⟪P0000⟫ ⟪P0003⟫ ⟪P0002⟫ ⟪P0001⟫")


def test_safe_custom_prose_macros():
    from app.latex import collect_text_macros

    pre = r"\newcommand{\myparagraph}[1]{\smallskip\indent{\it{#1}}}\newcommand{\norm}[1]{\|#1\|}"
    macros = collect_text_macros(pre)
    assert macros == {"myparagraph"}
    items = segments(r"\myparagraph{A custom heading}\norm{x}", text_macros=macros)
    assert "A custom heading" in items[0].masked
    assert "norm" not in items[0].masked


def test_keys_are_bound_to_their_endpoint():
    from app.config import merge_settings

    config = Settings(api_key="private-key")
    assert (
        merge_settings(config, {"model": "another-model", "api_key": ""}).api_key
        == "private-key"
    )
    assert (
        merge_settings(
            config, {"base_url": "http://localhost:11434/v1", "api_key": ""}
        ).api_key
        == ""
    )
    assert (
        merge_settings(
            config,
            {"base_url": "https://another-provider.test/v1", "api_key": "new-key"},
        ).api_key
        == "new-key"
    )


def test_comments_and_verbatim_are_opaque():
    text = (
        "A short paragraph. % do not translate this comment\n"
        + r"\begin{verbatim}do not translate code\end{verbatim}"
        + "\n\n"
        + r"Another $x+y$ paragraph."
    )
    exposed = " ".join(MARKER.sub("", i.masked) for i in segments(text))
    assert "comment" not in exposed and "translate code" not in exposed


def test_math_aliases_are_protected():
    text = r"""\documentclass{article}
\newcommand{\be}{\begin{equation}}
\newcommand{\ee}{\end{equation}}
\begin{document}
Here is a formula: \be x = y + z \ee which is useful.
\end{document}"""
    exposed = " ".join(MARKER.sub("", i.masked) for i in segments(text))
    assert "x = y" not in exposed
    assert "which is useful" in exposed


def test_archive_traversal_blocked(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("../escaped.tex", "bad")
    with pytest.raises(ValueError):
        extract_source(stream.getvalue(), "source.zip", tmp_path / "source")
    assert not (tmp_path / "escaped.tex").exists()


def test_archive_symlink_blocked(tmp_path):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as z:
        item = tarfile.TarInfo("link")
        item.type = tarfile.SYMTYPE
        item.linkname = "/etc/passwd"
        z.addfile(item)
    with pytest.raises(ValueError):
        extract_source(stream.getvalue(), "a.tar", tmp_path / "source")


def test_zip_multifile_main(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr(
            "paper/main.tex",
            r"\documentclass{article}\begin{document}\input{intro}\end{document}",
        )
        z.writestr("paper/intro.tex", "Introduction to a research paper.")
    root = tmp_path / "source"
    extract_source(stream.getvalue(), "paper.zip", root)
    assert find_main(root)[0] == "paper/main.tex"
    from app.jobs import JobManager

    assert JobManager.reachable_files(root, "paper/main.tex") == [
        "paper/intro.tex",
        "paper/main.tex",
    ]


def test_pdf_input_not_misrepresented(tmp_path):
    with pytest.raises(ValueError, match="未提供可用 LaTeX"):
        extract_source(b"%PDF-1.7 fake", "paper.gz", tmp_path / "source")


def test_settings_never_returns_secret():
    config = Settings(api_key="secret")
    public = public_settings(config)
    assert public["has_api_key"] is True
    assert "api_key" not in public
    assert "secret" not in str(public)


def test_endpoint_normalization():
    assert (
        Settings(base_url="https://api.deepseek.com/v1/chat/completions/").base_url
        == "https://api.deepseek.com/v1"
    )
    with pytest.raises(ValueError):
        Settings(base_url="http://example.org/v1")


def test_included_file_comment_and_shared_math_aliases():
    from app.latex import collect_math_aliases

    aliases = collect_math_aliases(
        r"\newcommand{\be}{\begin{equation}}\newcommand{\ee}{\end{equation}}"
    )
    text = "% See \\begin{document} in main file.\nThe equation is \\be x=y \\ee and it is useful."
    items = segments(text, math_aliases=aliases)
    assert len(items) == 1
    assert "The equation is" in items[0].masked
    assert "x=y" not in items[0].masked


def test_compact_repair_expands_back_to_original_markers():
    item = segments(r"The change occurred in \textbf{2018} and \textbf{2019}.")[0]
    compact, mapping = item.compact()
    assert len(compact.protected) < len(item.protected)
    expanded = MARKER.sub(lambda m: mapping[m.group()], compact.masked)
    assert item.restore(expanded) == item.source


def test_language_normalization_preserves_markers():
    from app.llm import normalize_language

    assert normalize_language("強化學習 ⟪P0000⟫", "简体中文") == "强化学习 ⟪P0000⟫"


def test_english_prose_cannot_silently_pass_as_chinese():
    from app.llm import validate_translation_language

    item = segments("The model is based on attention and was designed for this task.")[
        0
    ]
    with pytest.raises(ValueError, match="未将正文翻译"):
        validate_translation_language(item, item.masked, "简体中文")
    validate_translation_language(
        item, "该模型基于注意力机制，并为这项任务而设计。", "简体中文"
    )
