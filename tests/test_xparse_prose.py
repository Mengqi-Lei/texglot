"""Infer prose roles from fixed xparse signatures, never from macro names."""

import pytest

from app.latex import (
    MARKER,
    apply_translations,
    collect_prose_arguments,
    collect_text_macros,
    input_references,
    segments,
)
from app.sources import collect_literal_environments, find_main

BOX = r"\newtcolorbox{reviewpanel}[2][]{title=#1,colback=white,#2}"
BODY = r"\begin{reviewpanel}[\IfBlankTF{#2}{#1}{#1: \emph{#2}}]{}#3\end{reviewpanel}"


@pytest.mark.parametrize(
    "kind",
    [
        "NewDocumentCommand",
        "RenewDocumentCommand",
        "DeclareDocumentCommand",
        "ProvideDocumentCommand",
    ],
)
@pytest.mark.parametrize("signature", ["mm+m", "m m +m"])
def test_fixed_xparse_box_payload_is_prose_and_configuration_stays_opaque(
    kind, signature
):
    definitions = BOX + "\\" + kind + r"{\Panel}{" + signature + "}{" + BODY + "}"
    roles = collect_prose_arguments(definitions)
    assert roles["Panel"] == (3, frozenset({3}))
    source = (
        definitions
        + r"\begin{document}\Panel{Title}{mode}{Important body with $x=2$ and \cite{a}.}\end{document}"
    )
    items = segments(source)
    exposed = "\n".join(MARKER.sub("", s.masked) for s in items)
    assert (
        "Important body" in exposed and "mode" not in exposed and "Title" not in exposed
    )
    outputs = {s.key: s.target_probe("简体中文") for s in items}
    result = apply_translations(source, items, outputs)
    assert definitions in result and r"\Panel{Title}{mode}" in result
    assert (
        "$x=2$" in result and r"\cite{a}" in result and "Important body" not in result
    )
    for s in items:
        s.validate_source_map()


def test_simple_xparse_formatting_alias_remains_translatable():
    definition = r"\NewDocumentCommand{\plainwrap}{+m}{\textbf{#1}}"
    assert "plainwrap" in collect_text_macros(definition)
    items = segments(
        definition + r"\begin{document}\plainwrap{Ordinary prose}\end{document}"
    )
    assert any("Ordinary prose" in s.masked for s in items)


@pytest.mark.parametrize(
    "signature", ["O{}m+m", "m v m", r"m >{\TrimSpaces}m +m", "s m +m", "m r() m"]
)
def test_optional_verbatim_and_processed_signatures_remain_opaque(signature):
    definitions = BOX + r"\NewDocumentCommand{\Panel}{" + signature + "}{" + BODY + "}"
    assert "Panel" not in collect_prose_arguments(definitions)


@pytest.mark.parametrize(
    "body",
    [
        r"\begin{minted}{python}#3\end{minted}",
        r"$#3$",
        r"\unknown#3",
        r"\begin{reviewpanel}[#3]{}#3\end{reviewpanel}",
    ],
)
def test_code_math_unknown_operands_and_mixed_uses_are_not_opened(body):
    definitions = BOX + r"\NewDocumentCommand{\Panel}{m m m}{" + body + "}"
    assert (
        3 not in collect_prose_arguments(definitions).get("Panel", (3, frozenset()))[1]
    )


def test_redefinitions_and_nested_definitions_disable_inference():
    first = BOX + r"\NewDocumentCommand{\Panel}{mmm}{" + BODY + "}"
    replacement = r"\RenewDocumentCommand{\Panel}{O{}mm}{#1#2#3}"
    assert "Panel" not in collect_prose_arguments(first + replacement)
    nested = r"\NewDocumentCommand{\Outer}{O{}m}{" + first + "}"
    assert "Panel" not in collect_prose_arguments(nested)
    assert "Panel" not in collect_prose_arguments(
        first + r"\renewenvironment{reviewpanel}{\begin{verbatim}}{\end{verbatim}}"
    )


def test_xparse_definition_examples_do_not_become_file_dependencies_or_main(tmp_path):
    text = r"\NewDocumentCommand{\Example}{O{}}{\documentclass{book}\input{not-executed}\newtcblisting{fake}{listing only}}"
    assert input_references(text) == []
    assert collect_literal_environments(text) == set()
    (tmp_path / "example.tex").write_text(text, encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}Text\end{document}", encoding="utf-8"
    )
    assert find_main(tmp_path)[0] == "main.tex"
