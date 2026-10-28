import pytest

from app.latex import (
    MARKER,
    apply_translations,
    collect_prose_arguments,
    collect_text_macros,
    segments,
)


@pytest.mark.parametrize(
    "declaration",
    [
        r"\DeclareRobustCommand{\review}[1]{{\color{black}#1}}",
        r"\DeclareRobustCommand*\review[1]{\textbf{#1}}",
        r"\newcommand{\review}[1]{#1}",
        r"\def\review#1{\textbf{#1}}",
        r"\gdef\review#1{\emph{#1}}",
    ],
)
def test_explicit_single_argument_prose_wrappers(declaration):
    wrappers = collect_text_macros(declaration)
    assert "review" in wrappers
    source = r"Before. \review{Visible text with $x^2$ and \cite{paper}.} After."
    items = segments(source, text_macros=wrappers)
    assert "Visible text with" in "\n".join(MARKER.sub("", s.masked) for s in items)
    result = apply_translations(
        source,
        items,
        {
            s.key: s.restore(s.masked.replace("Visible text with", "可见文字包含"))
            for s in items
        },
    )
    assert result == source.replace("Visible text with", "可见文字包含")
    assert [s.key for s in items] != [s.key for s in segments(source)]


@pytest.mark.parametrize(
    "body",
    [
        r"\color{#1}word",
        r"\textcolor{#1}{#1}",
        r"\hspace{#1}",
        r"\textbf[#1]{word}",
        r"\texttt{#1}",
        r"\ttfamily #1",
        r"$#1$",
        r"\includegraphics{#1}",
        r"\unknown{#1}",
        r"prefix#1",
    ],
)
def test_nonprose_parameters_are_never_opened(body):
    assert "review" not in collect_text_macros(
        r"\DeclareRobustCommand{\review}[1]{" + body + "}"
    )


@pytest.mark.parametrize(
    "replacement",
    [
        r"\renewcommand{\review}[1]{\texttt{#1}}",
        r"\def\review#1{$#1$}",
        r"\let\review=X",
        r"\renewcommand{\review}[2][blue]{\textcolor{#1}{#2}}",
    ],
)
def test_redefinitions_disable_wrapper_and_alias_inference(replacement):
    source = r"\DeclareRobustCommand{\review}[1]{\textbf{#1}}\let\alias=\review"
    assert not {"review", "alias"} & collect_text_macros(source + replacement)


def test_cross_file_title_abstract_alias_and_nested_description():
    declarations = r"""\DeclareRobustCommand{\review}[1]{{\color{black}#1}}
\let\alias\review
\newcommand{\outer}[1]{\alias{#1}}
\DeclareRobustCommand{\summarybox}[2]{\begin{notice}\textbf{#1}\quad #2\end{notice}}"""
    wrappers = collect_text_macros(declarations)
    assert {"review", "alias", "outer"} <= wrappers
    roles = collect_prose_arguments(declarations)
    assert roles["summarybox"] == (2, frozenset({1, 2}))
    source = r"\title{\review{Visible title}}\begin{document}\alias{Visible abstract}\summarybox{Visible heading}{\outer{Visible conclusion with $x$.}}\end{document}"
    items = segments(source, text_macros=wrappers, prose_arguments=roles)
    exposed = "\n".join(MARKER.sub("", s.masked) for s in items)
    for word in ("title", "abstract", "heading", "conclusion"):
        assert "Visible " + word in exposed
    result = apply_translations(
        source,
        items,
        {s.key: s.restore(s.masked.replace("Visible", "可见")) for s in items},
    )
    assert result == source.replace("Visible", "可见")


def test_nested_definitions_and_literal_examples_do_not_define_wrappers():
    source = r"""\newcommand{\factory}{\DeclareRobustCommand{\review}[1]{\textbf{#1}}}
\begin{verbatim}
\DeclareRobustCommand{\example}[1]{#1}
\end{verbatim}
\let\cycleA\cycleB\let\cycleB\cycleA"""
    assert not {"review", "example", "cycleA", "cycleB"} & collect_text_macros(source)


def test_custom_icon_label_translates_description_without_changing_identifier():
    definitions = r"\newcommand{\icon}[1]{\csname icon@#1\endcsname}\newcommand{\key}[2]{\icon{#1}\,=\,#2}"
    roles = collect_prose_arguments(definitions)
    assert roles["key"] == (2, frozenset({2}))
    source = r"\key{UFF}{Unchecked first frame.}"
    items = segments(source, prose_arguments=roles)
    assert "Unchecked first frame." in items[0].masked
    assert "UFF" not in items[0].masked
    assert (
        apply_translations(
            source,
            items,
            {
                s.key: s.restore(
                    s.masked.replace("Unchecked first frame.", "未经检查的首帧。")
                )
                for s in items
            },
        )
        == r"\key{UFF}{未经检查的首帧。}"
    )
    assert "key" not in collect_prose_arguments(
        definitions + r"\renewcommand{\icon}[2]{#1#2}"
    )


@pytest.mark.parametrize("spacing", [r"\kern0.04em", r"\hskip2pt", r"\vskip1cm"])
def test_unit_touching_prose_remains_protected(spacing):
    source = spacing + "Visible title"
    item = segments(source)[0]
    assert spacing in item.protected
    assert "Visible title" in item.masked
    assert (
        item.restore(item.masked.replace("Visible title", "可见标题"))
        == spacing + "可见标题"
    )
