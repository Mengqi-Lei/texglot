"""Document entry selection for split preambles, without rewriting sources."""

import pytest

from app.sources import find_main


def project(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    "include",
    [
        r"\input{preambles/preamble.tex}",
        r"\input{preambles/preamble}",
        "\\input preambles/preamble\n",
        r'\input{"preambles/preamble.tex"}',
    ],
)
def test_panonav_split_preamble_is_selected_without_source_edits(tmp_path, include):
    project(
        tmp_path,
        {
            "main.tex": include
            + "\n\\title{PanoNav}\n\\begin{document}A useful paper.\\end{document}",
            "preambles/preamble.tex": r"\documentclass[letterpaper]{article}\usepackage{aaai2026}",
            "irrelevant.tex": r"\documentclass{article}",
        },
    )
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.tex")}
    assert find_main(tmp_path) == ("main.tex", ["main.tex"])
    assert find_main(tmp_path, "main.tex")[0] == "main.tex"
    assert {p: p.read_bytes() for p in before} == before
    with pytest.raises(ValueError, match="不是完整文档"):
        find_main(tmp_path, "preambles/preamble.tex")


def test_nested_preamble_and_main_directory_path_precedence(tmp_path):
    project(
        tmp_path,
        {
            "paper/main.tex": r"\input{preambles/preamble}\begin{document}Paper.\end{document}",
            "paper/preambles/preamble.tex": r"\input{class-config}",
            "paper/class-config.tex": r"\documentclass{article}",
            "paper/preambles/class-config.tex": r"\input{missing}",
        },
    )
    assert find_main(tmp_path)[0] == "paper/main.tex"


def test_nested_preamble_can_use_a_file_relative_include(tmp_path):
    project(
        tmp_path,
        {
            "paper/main.tex": r"\input{preambles/preamble}\begin{document}Paper.\end{document}",
            "paper/preambles/preamble.tex": r"\input{class-config}",
            "paper/preambles/class-config.tex": r"\documentstyle{article}",
        },
    )
    assert find_main(tmp_path)[0] == "paper/main.tex"


@pytest.mark.parametrize(
    "prefix",
    [
        "% \\input{preamble}\n",
        r"\newcommand{\unused}{\input{preamble}}",
        r"\def\unused{\documentclass{article}}",
        r"\begin{verbatim}\input{preamble}\end{verbatim}",
        r"\verb|\documentclass{article}|",
        r"\iffalse\input{preamble}\fi",
        r"\iftrue\relax\else\input{preamble}\fi",
        r"\begin{minted}{latex}\input{preamble}\end{minted}",
        r"\\documentclass{article}",
    ],
)
def test_unexecuted_declarations_and_inputs_do_not_identify_a_main(tmp_path, prefix):
    project(
        tmp_path,
        {
            "main.tex": prefix + "\n\\begin{document}Paper.\\end{document}",
            "preamble.tex": r"\documentclass{article}",
        },
    )
    with pytest.raises(ValueError, match="未找到"):
        find_main(tmp_path)


def test_class_only_reachable_after_begin_document_is_not_a_preamble(tmp_path):
    project(
        tmp_path,
        {
            "main.tex": r"\begin{document}\input{preamble}\end{document}",
            "preamble.tex": r"\documentclass{article}",
        },
    )
    with pytest.raises(ValueError, match="未找到"):
        find_main(tmp_path)


def test_an_included_whole_document_does_not_make_the_outer_file_valid(tmp_path):
    project(
        tmp_path,
        {
            "main.tex": r"\input{paper}\begin{document}Wrong entry.\end{document}",
            "paper.tex": r"\documentclass{article}\begin{document}Actual paper.\end{document}",
        },
    )
    assert find_main(tmp_path) == ("paper.tex", ["paper.tex"])


def test_literal_definitions_in_another_file_protect_document_examples(tmp_path):
    project(
        tmp_path,
        {
            "examples.sty": r"\RequirePackage{fancyvrb}\DefineVerbatimEnvironment{Example}{Verbatim}{}",
            "main.tex": r"\usepackage{examples}\begin{Example}\documentclass{article}\begin{document}Fake.\end{document}\end{Example}",
            "paper.tex": r"\input{preamble}\begin{document}Actual paper.\end{document}",
            "preamble.tex": r"\documentclass{article}",
        },
    )
    assert find_main(tmp_path) == ("paper.tex", ["paper.tex"])


@pytest.mark.parametrize(
    "contents",
    [
        r"\input{b}",
        r"\endinput\documentclass{article}",
        r"\iffalse\documentclass{article}\fi",
    ],
)
def test_cycles_and_terminated_preambles_do_not_supply_a_class(tmp_path, contents):
    project(
        tmp_path,
        {
            "main.tex": r"\input{a}\begin{document}Paper.\end{document}",
            "a.tex": contents,
            "b.tex": r"\input{a}",
        },
    )
    with pytest.raises(ValueError, match="未找到"):
        find_main(tmp_path)


def test_nested_literal_conditionals_and_newif_preserve_active_preamble(tmp_path):
    project(
        tmp_path,
        {
            "main.tex": r"\newif\ifdraft\iffalse\iftrue\input{missing}\fi\else\input{preamble}\fi\begin{document}Paper.\end{document}",
            "preamble.tex": r"\documentclass{article}",
        },
    )
    assert find_main(tmp_path)[0] == "main.tex"


def test_path_escape_and_symlink_do_not_supply_a_class(tmp_path):
    root = tmp_path / "paper"
    project(tmp_path, {"secret.tex": r"\documentclass{article}"})
    project(
        root,
        {
            "main.tex": r"\input{../secret}\input{linked}\begin{document}Paper.\end{document}",
        },
    )
    try:
        (root / "linked.tex").symlink_to(tmp_path / "secret.tex")
    except OSError:
        pass  # Windows can restrict symlink creation; path-escape check still runs.
    with pytest.raises(ValueError, match="未找到"):
        find_main(root)


def test_language_ranking_and_selected_entry_survive_split_preambles(tmp_path):
    project(
        tmp_path,
        {
            "main.tex": r"\input{preamble}\begin{document}这是论文的中文版本，包含完整的中文正文内容和实验分析。\end{document}",
            "english.tex": r"\input{preamble}\begin{document}This is the English source paper.\end{document}",
            "preamble.tex": r"\documentclass{article}",
        },
    )
    assert find_main(tmp_path) == ("english.tex", ["english.tex", "main.tex"])
    assert find_main(tmp_path, "main.tex")[0] == "main.tex"


def test_main_preamble_may_be_style_file(tmp_path):
    project(
        tmp_path,
        {
            "main.tex": r"\input{preamble.sty}\begin{document}Paper.\end{document}",
            "preamble.sty": r"\documentclass{article}",
        },
    )
    assert find_main(tmp_path)[0] == "main.tex"
