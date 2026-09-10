"""Regression cases from structural source review, independent of any model."""

import pytest

from app.latex import MARKER, Segment, apply_translations, segments
from app.paper_context import extract_paper_context


def exposed(source):
    return " ".join(MARKER.sub("", item.masked) for item in segments(source))


def rewritten(source, old, new):
    items = segments(source)
    return apply_translations(
        source,
        items,
        {item.key: item.restore(item.masked.replace(old, new)) for item in items},
    )


@pytest.mark.parametrize(
    "separator", ["\n", "\r\n", "% author note\n", " \t% note\n  "]
)
@pytest.mark.parametrize("name", ["input", "includegraphics", "label", "cite", "ref"])
def test_opaque_arguments_after_tex_whitespace_never_become_prose(separator, name):
    source = "A result. \\" + name + separator + "{important-file} Follow-up text."
    assert "important-file" not in exposed(source)
    assert "Follow-up text" in exposed(source)
    assert rewritten(source, "important-file", "broken-reference") == source


@pytest.mark.parametrize(
    "definition,formula",
    [
        (
            r"\newcommand{\be}{\begin{equation}}\newcommand{\en}{\end{equation}}",
            r"\be\ensuremath{x}=y\en",
        ),
        (
            r"\newcommand{\be}{\begin{equation}}\newcommand{\ee}{\end{equation}}",
            "\\be x % ignored \\ee\n+value=y\\ee",
        ),
        (
            r"\newcommand{\be}{\[}\newcommand{\ee}{\]}",
            r"\be\eegroup +value\ee",
        ),
    ],
)
def test_math_aliases_match_complete_control_tokens_and_ignore_comments(
    definition, formula
):
    source = (
        definition
        + r"\begin{document}Before. "
        + formula
        + r" After formula.\end{document}"
    )
    items = segments(source)
    assert "value" not in exposed(source)
    assert "After formula" in exposed(source)
    assert (
        apply_translations(source, items, {s.key: s.restore(s.masked) for s in items})
        == source
    )
    assert formula in rewritten(source, "After formula", "Translated tail")


@pytest.mark.parametrize(
    "formula",
    [
        "\\begin{equation}x % ignored \\end{equation}\n+value=y\\end{equation}",
        r"\begin{equation}value=x\end {equation}",
        "\\begin{equation}value=x\\end% author note\n{equation}",
        "$x % ignored $\n+value=y$",
        "$$x % ignored $$\n+value=y$$",
        "\\(x % ignored \\)\n+value=y\\)",
        "\\[x % ignored \\]\n+value=y\\]",
    ],
)
def test_math_comments_and_end_whitespace_preserve_formula_and_following_prose(formula):
    source = "Before formula. " + formula + " After formula."
    assert "value" not in exposed(source)
    assert "After formula." in exposed(source)
    assert formula in rewritten(source, "After formula", "Translated tail")


@pytest.mark.parametrize("environment", ["abstract", "center", "proof", "itemize"])
def test_initial_group_in_text_environment_remains_translatable(environment):
    source = (
        "\\begin{"
        + environment
        + "}{Important prose.}\\end{"
        + environment
        + "}{Following prose.}"
    )
    assert "Important prose." in exposed(source)
    assert "Following prose." in exposed(source)
    assert "Translated prose." in rewritten(
        source, "Important prose.", "Translated prose."
    )


def test_environment_parameters_stay_opaque_but_grouped_table_cells_do_not():
    source = r"\begin{tabular}{lr}{Method} & Accuracy\\\end{tabular}"
    assert "lr" not in exposed(source)
    assert "Method" in exposed(source)
    assert "Accuracy" in exposed(source)


@pytest.mark.parametrize(
    "code",
    [
        r"\lstinline[columns=fixed]|print(42)|",
        r"\lstinline{print(42)}",
        r"\verb|literal % text|",
    ],
)
def test_inline_literal_options_preserve_code_and_following_paragraph(code):
    source = "Before. " + code + " Important explanatory prose."
    assert "print" not in exposed(source) and "literal" not in exposed(source)
    assert "Important explanatory prose." in exposed(source)
    assert code in rewritten(
        source, "Important explanatory prose.", "Translated prose."
    )


@pytest.mark.parametrize(
    "primitive",
    [
        r"\char65",
        r'\char"41',
        r"\char'101",
        r"\char`A",
        r"\char`\%",
        r"\penalty10000",
        "\\penalty% note\n-1000",
        r"\widowpenalty=10000",
    ],
)
def test_integer_primitives_are_indivisible_syntax(primitive):
    source = "Before " + primitive + " after."
    item = segments(source)[0]
    assert primitive in item.protected
    assert item.restore(item.masked) == source


@pytest.mark.parametrize(
    "definition",
    [
        r"\newcommand\example[1]{#1 and literal words}",
        "\\newcommand% note\n{\\example}[1]%note\n{#1 and literal words}",
        r"\newenvironment{custom}{literal opening}{literal closing}",
        "\\def\\example#1% note with {\n{#1 and literal words}",
    ],
)
def test_document_body_macro_definitions_do_not_expose_implementation_text(definition):
    source = "Body before. " + definition + " Body after."
    assert "literal" not in exposed(source)
    assert "Body after." in exposed(source)
    assert definition in rewritten(source, "Body after.", "Translated body.")


@pytest.mark.parametrize(
    "source",
    [
        r"\title{An important title}",
        r"\textbf{An important statement}",
        "\\textbf% comment\n{An important statement}",
    ],
)
def test_model_blank_lines_cannot_inject_paragraphs_inside_short_arguments(source):
    item = segments(source)[0]
    output = item.masked.replace("An important", "A translated\n\nimportant")
    restored = item.restore(output)
    assert "\n\n" not in restored
    assert "translated important" in restored


def test_comments_and_optional_arguments_cannot_detach_text_commands():
    for source in [
        "\\textbf% comment\n{Important prose}",
        r"\section[Short prose]{Long prose}",
    ]:
        item = segments(source)[0]
        for boundary in item.argument_boundaries():
            token = f"⟪P{boundary:04d}⟫"
            with pytest.raises(ValueError, match="参数之间"):
                item.restore(item.masked.replace(token, token + "Inserted prose"))


def test_cache_key_binds_protected_token_layout():
    one = Segment(0, 4, "same", "⟪P0000⟫ prose", [r"\macro"])
    two = Segment(0, 4, "same", "⟪P0000⟫ prose", [r"\macro{argument}"])
    three = Segment(0, 4, "same", "prose ⟪P0000⟫", [r"\macro"])
    assert len({one.key, two.key, three.key}) == 3


def test_context_skips_inline_listings_with_options_and_literal_percent(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\lstinline[columns=fixed]|\abstract{Fake abstract}|"
        + r"\verb|% \abstract{Another fake abstract}|"
        + "\n\\abstract{The actual abstract is here.}",
        encoding="utf-8",
    )
    assert extract_paper_context(tmp_path, "main.tex") == "The actual abstract is here."


def test_comment_newline_and_indented_paragraph_boundaries_are_not_duplicated():
    source = "First paragraph. % A literal comment\n \n  Second paragraph. % End\n"
    items = segments(source)
    assert len(items) == 2
    assert (
        apply_translations(source, items, {s.key: s.restore(s.masked) for s in items})
        == source
    )
    actual = rewritten(source, "paragraph", "translated")
    assert actual == source.replace("paragraph", "translated")


@pytest.mark.parametrize("filename", ["intro.tex", "parts/body.tex", "intro"])
def test_unbraced_tex_input_filename_stays_opaque(filename):
    source = "Before. \\input% comment\n" + filename + " After input."
    assert filename not in exposed(source)
    assert "After input." in exposed(source)
    assert rewritten(source, filename, "changed") == source


@pytest.mark.parametrize("environment", ["IEEEeqnarray", "dmath", "mathpar"])
def test_template_specific_math_environments_are_opaque(environment):
    source = (
        "Before. \\begin{" + environment + "}value=x\\end{" + environment + "} After."
    )
    assert "value" not in exposed(source)
    assert "After." in exposed(source)


def test_environment_alias_whitespace_and_literal_definitions():
    source = r"""\newcommand{\be}{\begin {equation}}\newcommand{\ee}{\end {equation}}
\begin{verbatim}\newcommand{\be}{\begin{center}}\end{verbatim}
\be value=x\ee After formula."""
    assert "value" not in exposed(source)
    assert "After formula." in exposed(source)


@pytest.mark.parametrize(
    "command",
    [
        r"\cite{author}",
        r"\ref{section}",
        r"\label{section}",
        r"\maketitle",
        r"\newpage",
    ],
)
def test_completed_commands_do_not_capture_following_grouped_paragraphs(command):
    source = "Before. " + command + "\n\n{Important scientific paragraph.} After."
    assert "Important scientific paragraph." in exposed(source)
    assert command in rewritten(
        source, "Important scientific paragraph.", "Translated paragraph."
    )


def test_literal_math_opening_can_close_with_an_alias():
    source = r"\newcommand{\ee}{\end{equation}}\begin{document}Before. \begin{equation}value=x\ee After formula.\end{document}"
    assert "value" not in exposed(source)
    assert "After formula." in exposed(source)


def test_numexpr_primitive_keeps_nested_expressions_and_comments_opaque():
    value = "\\penalty\\numexpr 100+\\numexpr20+30\\relax% fake \\relax\n+40\\relax"
    item = segments("Before " + value + " after.")[0]
    assert value in item.protected
    assert item.restore(item.masked) == item.source


def test_declared_numeric_registers_in_included_definitions_stay_opaque():
    from app.latex import collect_numeric_registers

    declarations = r"\newdimen\pIR\newlength{\customlen}\newcount\customcount"
    assignments = r"\pIR= -131072sp \customlen=2.5pt \customcount=200"
    registers = collect_numeric_registers(declarations)
    assert len(registers) == 3
    assert segments(declarations + assignments) == []
    source = "Before. " + assignments + " After."
    item = segments(source, numeric_registers=registers)[0]
    assert not any(unit in MARKER.sub("", item.masked) for unit in ("sp", "pt", "200"))
    assert item.restore(item.masked) == source


def test_scientific_reports_abstract_before_document_is_translated_in_place():
    source = r"""\documentclass{wlscirep}
\title{Paper title}
\begin{abstract}Important abstract. Math is $x+y$.\end{abstract}
\begin{document}\maketitle Body prose.\end{document}"""
    assert "Important abstract." in exposed(source)
    translated = rewritten(source, "Important abstract.", "Translated abstract.")
    assert translated == source.replace("Important abstract.", "Translated abstract.")


def test_acm_ccs_xml_metadata_is_not_prose():
    xml = r"\begin{CCSXML}<ccs2012><conceptdesc>Computer science</conceptdesc></ccs2012>\end{CCSXML}"
    source = "Before. " + xml + " After."
    assert "Computer science" not in exposed(source)
    assert "After." in exposed(source)
    assert rewritten(source, "Computer science", "Translated metadata") == source


def test_aa_structured_abstract_context_uses_all_five_fields(tmp_path):
    source = r"""\documentclass{aa}\begin{document}
\abstract{Context field.}{Aims field.}{Methods field.}{Results field.}{Conclusions field.}
\section{Introduction}Not part of abstract.\end{document}"""
    (tmp_path / "main.tex").write_text(source, encoding="utf-8")
    assert extract_paper_context(tmp_path, "main.tex") == (
        "Context field. Aims field. Methods field. Results field. Conclusions field."
    )
    assert all(
        field in exposed(source)
        for field in ("Context", "Aims", "Methods", "Results", "Conclusions")
    )


@pytest.mark.parametrize("in_preamble", [False, True])
def test_ieee_abstract_and_index_wrapper_exposes_the_complete_abstract(in_preamble):
    wrapper = r"\IEEEtitleabstractindextext{\begin{abstract}The complete abstract is here.\end{abstract}\begin{IEEEkeywords}Graph neural networks\end{IEEEkeywords}}"
    source = (
        r"\documentclass{IEEEtran}"
        + (wrapper if in_preamble else "")
        + r"\begin{document}"
        + ("" if in_preamble else wrapper)
        + r"\maketitle Body text.\end{document}"
    )
    assert "The complete abstract is here." in exposed(source)
    assert "Graph neural networks" in exposed(source)
    assert rewritten(
        source, "The complete abstract is here.", "Translated abstract."
    ) == source.replace("The complete abstract is here.", "Translated abstract.")


def test_aastex_table_caption_and_headings_are_prose():
    source = r"\tablecaption{Measured stellar properties}\tablehead{\colhead{Star name} & \colhead{Mass}}"
    assert "Measured stellar properties" in exposed(source)
    assert "Star name" in exposed(source) and "Mass" in exposed(source)


def test_context_respects_the_compilers_actual_source_dependencies(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\input{unused}\input{active}", encoding="utf-8"
    )
    (tmp_path / "unused.tex").write_text(
        r"\abstract{Inactive draft abstract.}", encoding="utf-8"
    )
    (tmp_path / "active.tex").write_text(
        r"\abstract{The active paper abstract.}", encoding="utf-8"
    )
    assert (
        extract_paper_context(
            tmp_path, "main.tex", source_files=["main.tex", "active.tex"]
        )
        == "The active paper abstract."
    )


def test_input_references_preserve_inherited_math_and_graphic_context():
    from app.latex import input_references

    source = r"""\input{intro}
\newcommand{\example}{\input{unused-definition}}
\newcommand{\be}{\begin{equation}}\newcommand{\ee}{\end{equation}}
\begin{tikzpicture}\input{plot}\end{tikzpicture}
\be\input{formula}\ee
$\input{inline-formula}$
\input{conclusion}
\begin{verbatim}\input{unused-example}\end{verbatim}
% \input{unused-comment}
"""
    assert input_references(source) == [
        ("intro", False),
        ("plot", True),
        ("formula", True),
        ("inline-formula", True),
        ("conclusion", False),
    ]


def test_opaque_input_context_propagates_and_reports_mixed_usage(tmp_path):
    from app.latex import classify_source_contexts

    contents = {
        "main.tex": r"\input{intro}\begin{tikzpicture}\input{plot}\input{shared}\end{tikzpicture}\input{shared}",
        "intro.tex": "Ordinary body prose.",
        "plot.tex": r"\input{nodes}\foreach \x in {1,2,3} {\draw (\x,0)--(\x,1);}",
        "nodes.tex": r"\node at (0,0) {Label};",
        "shared.tex": r"\input{shared-child}Both uses must be preserved.",
        "shared-child.tex": "Content inherited from a mixed parent.",
        "dynamic.tex": "A dynamic macro loaded this body file.",
    }
    for name, text in contents.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    opaque, mixed = classify_source_contexts(tmp_path, "main.tex", list(contents))
    assert opaque == {"plot.tex", "nodes.tex"}
    assert mixed == {"shared.tex", "shared-child.tex"}


def test_opaque_input_graph_resolves_subdirectories_and_external_math_aliases(tmp_path):
    from app.latex import classify_source_contexts

    (tmp_path / "parts").mkdir()
    contents = {
        "main.tex": r"\be\include*{parts/formula}\ee\input{parts/body}",
        "parts/formula.tex": r"\input{nested}",
        "parts/nested.tex": "value=x",
        "parts/body.tex": "A normal paragraph.",
    }
    for name, text in contents.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert classify_source_contexts(
        tmp_path,
        "main.tex",
        list(contents),
        math_aliases={"be": r"\begin{equation}", "ee": r"\end{equation}"},
    ) == ({"parts/formula.tex", "parts/nested.tex"}, set())


def test_quoted_unbraced_input_keeps_a_filename_with_spaces():
    from app.latex import input_references

    source = 'Before. \\input "some file.tex" After.'
    assert "some file.tex" not in exposed(source)
    assert input_references(source) == [("some file.tex", False)]
    assert rewritten(source, "some file", "bad filename") == source


@pytest.mark.parametrize(
    "formula",
    [
        r"$x+\text{for $i$ and $j$}$",
        r"\(x+\text{for \(i\) and \(j\)}\)",
        r"$$x+\vbox{for $$i+j$$}$$",
        "$x+\\text{use \\{braces\\} and $i$ % fake } $\n and $j$}$",
        r"$x+\hbox\bgroup for $i$ and $j$\egroup$",
        r"$x+\hbox{for $i$ and $j$\egroup$",
        r"\begin{equation}x+\text{for $i$ and $j$}\end{equation}",
        r"\begin{equation}\begin{split}x&=\text{for $i$ and $j$}\end{split}\end{equation}",
        r"$x+\hbox{\begingroup for $i$\endgroup and $j$}$",
    ],
)
def test_nested_math_in_balanced_text_groups_is_one_protected_formula(formula):
    source = "Before " + formula + " after."
    item = segments(source)[0]
    assert item.protected == [formula]
    assert MARKER.sub("", item.masked) == "Before  after."
    assert item.restore(item.masked.replace("i", "k").replace("j", "l")) == source


def test_nested_text_math_does_not_end_an_outer_math_alias():
    source = r"\newcommand{\mathstart}{\(}\newcommand{\mathstop}{\)}\begin{document}Start \mathstart x+\text{for \(i\) and \(j\)}\mathstop after.\end{document}"
    assert "for" not in exposed(source)
    assert "after." in exposed(source)
    assert rewritten(source, "for", "changed") == source


def test_input_in_text_box_after_nested_math_retains_opaque_context():
    from app.latex import input_references

    source = r"$x+\text{for $i$ \input{formula-label}}$\input{body}"
    assert input_references(source) == [("formula-label", True), ("body", False)]


@pytest.mark.parametrize(
    "separator",
    [
        r"\\ \hline",
        r"\\ \cline{2-3}",
        r"\\ \cmidrule{1-2}",
        r"\hline \hline",
        "& &",
        r"& \\",
        r"\\ &",
        r"\multicolumn{1}{c}{}",
    ],
)
def test_table_structure_and_empty_cells_cannot_receive_generated_words(separator):
    item = segments("A cell " + separator + " following prose.")[0]
    boundaries = list(item.whitespace_boundaries())
    assert boundaries
    for index in boundaries:
        with pytest.raises(ValueError, match="不能插入正文"):
            item.restore(
                item.masked.replace(f"⟪P{index:04d}⟫", f"⟪P{index:04d}⟫Invented")
            )
    bound, expansion = item.compact(arguments_only=True)
    for index in boundaries:
        left, right = f"⟪P{index:04d}⟫", f"⟪P{index + 1:04d}⟫"
        assert any(
            left in original and right in original for original in expansion.values()
        )
    assert item.restore(item.masked) == item.source


def test_pure_data_cells_stay_literal_while_prose_math_remains_flexible():
    item = segments(r"Method & 12 & $x$ & \cite{paper} \\ Next row.")[0]
    for index in item.whitespace_boundaries():
        with pytest.raises(ValueError):
            item.restore(
                item.masked.replace(f"⟪P{index:04d}⟫", f"⟪P{index:04d}⟫New label")
            )
    prose = segments("For $x$ and $y$ we use 12 samples.")[0]
    assert list(prose.whitespace_boundaries()) == []
    assert (
        prose.restore("对于⟪P0000⟫和⟪P0001⟫，使用⟪P0002⟫个样本。")
        == "对于$x$和$y$，使用12个样本。"
    )


def test_empty_group_is_bound_with_its_formatting_command_in_first_request():
    item = segments(r"\multicolumn{1}{c}{} & Method & Value")[0]
    bound, _ = item.compact(arguments_only=True)
    assert r"\multicolumn{1}{c}{}" in bound.protected[0]


def test_multiargument_macro_roles_follow_usage_not_macro_names():
    from app.latex import collect_prose_arguments

    definitions = r"""\newcommand{\code}[1]{{\sffamily #1}}
\newcommand{\entrya}[3]{{\item \code{#1} \texttt{#2}: #3}}
\newcommand{\entryb}[4]{{\item \code{#1} \code{#2}\begin{list}{}{\setlength{\leftmargin}{1em}}\item #3\end{list}\indent#4}}"""
    roles = collect_prose_arguments(definitions)
    assert roles == {"entrya": (3, frozenset({3})), "entryb": (4, frozenset({3, 4}))}
    source = (
        definitions
        + r"\begin{document}\entrya{lnpostfn}{numpy.ndarray}{Return the posterior \code{lnprobfn(p)}.}\entryb{sample}{pos, args=[]}{A method description.}{\entrya{pos}{tuple}{The current position.}}\end{document}"
    )
    text = exposed(source)
    assert "Return the posterior" in text and "The current position." in text
    assert (
        "lnpostfn" not in text
        and "numpy.ndarray" not in text
        and "lnprobfn(p)" not in text
    )
    result = rewritten(source, "The current position.", "当前位置。")
    assert result == source.replace("The current position.", "当前位置。")
    items = segments(source)
    assert (
        apply_translations(source, items, {s.key: s.restore(s.masked) for s in items})
        == source
    )


@pytest.mark.parametrize(
    "definition",
    [
        r"\newcommand{\entry}[2]{\texttt{#1}\emph{#1}#2}",
        r"\newcommand{\entry}[2]{\textbf{#1}\label{#1}#2}",
        r"\newcommand{\entry}[2]{\textbf{#1} $#1$ #2}",
        r"\newcommand{\entry}[2]{\kern#1pt\item#2}",
        r"\newcommand{\entry}[2]{\item prefix#1\item#2}",
        r"\newcommand{\entry}[2]{\item#1suffix\item#2}",
        r"\newcommand{\entry}[2]{\item\unknown#1\item#2}",
        r"\newcommand{\entry}[2]{\node at (#1,#2) {\textbf{Label}}}",
    ],
)
def test_mixed_or_nonprose_macro_parameters_remain_opaque(definition):
    from app.latex import collect_prose_arguments

    schema = collect_prose_arguments(definition).get("entry", (2, frozenset()))
    assert 1 not in schema[1]


@pytest.mark.parametrize(
    "replacement",
    [
        r"\renewcommand{\entry}[1]{\texttt{#1}}",
        r"\renewcommand{\entry}[2]{#1+#2}",
        r"\def\entry#1{#1}",
        r"\renewcommand{\entry}[2][default]{\item#2}",
    ],
)
def test_conflicting_or_unsupported_macro_redefinitions_disable_inference(replacement):
    from app.latex import collect_prose_arguments

    first = r"\newcommand{\entry}[2]{\item\texttt{#1}:#2}"
    assert "entry" not in collect_prose_arguments(first + replacement)


def test_api_description_keeps_explicit_code_identifiers_literal():
    source = r"\newcommand{\entry}[2]{\item\texttt{#1}:#2}\entry{random_state}{Use \texttt{get_state()} to read \code{numpy.random.RandomState}.}"
    text = exposed(source)
    assert "Use" in text and "to read" in text
    assert (
        "random_state" not in text
        and "get_state" not in text
        and "numpy.random" not in text
    )
    assert rewritten(source, "Use", "调用") == source.replace("Use", "调用")


def test_custom_parameter_inference_does_not_override_author_metadata():
    from app.latex import collect_prose_arguments

    source = r"\renewcommand{\author}[2]{\noindent\textbf{#1} #2}\begin{document}\author{Alice Smith}{Research University}\end{document}"
    assert "author" not in collect_prose_arguments(source)
    assert "Alice Smith" not in exposed(source)


@pytest.mark.parametrize(
    "rule",
    [
        r"\cmidrule(lr){2-8}",
        r"\cmidrule[0.4pt](lr){2-8}",
        r"\cmidrule[.3pt](l{.2em}r{.3em}){1-3}",
        "\\cmidrule% comment\n[.3pt](l{\\dimexpr 1em-2pt\\relax}r{.3em})% more\n{1-3}",
        r"\cmidrule{1-3}",
    ],
)
def test_booktabs_cmidrule_protects_width_trim_and_ascii_column_range(rule):
    item = segments("Before " + rule + " after (ordinary prose).")[0]
    assert rule in item.protected
    assert "ordinary prose" in MARKER.sub("", item.masked)
    assert item.restore(item.masked.replace("-", "–")) == item.source


def test_setlength_with_unbraced_register_does_not_expose_units():
    source = r"\setlength\itemsep{0.01em}"
    assert segments(source) == []
    assert rewritten(source + " Body text.", "em", "invalid") == source + " Body text."


@pytest.mark.parametrize(
    "body", [r"\texttt{#1}: #2", r"{\texttt{#1}: {#2}}", r"\code{#1}: #2"]
)
def test_literal_code_label_with_plain_description_infers_only_description(body):
    from app.latex import collect_prose_arguments

    definition = r"\newcommand{\NativeDoc}[2]{" + body + "}"
    assert collect_prose_arguments(definition) == {"NativeDoc": (2, frozenset({2}))}
    source = (
        definition
        + r"\begin{document}\NativeDoc{api\_name}{Native description.}\end{document}"
    )
    assert "Native description." in exposed(source)
    assert "api" not in exposed(source)
    assert rewritten(source, "Native description.", "本地说明。") == source.replace(
        "Native description.", "本地说明。"
    )


@pytest.mark.parametrize(
    "body",
    [
        r"#1: #2",
        r"\texttt{#1}: \texttt{#2}",
        r"\texttt{#1}: $#2$",
        r"\texttt{#1}: \hskip#2pt",
        r"\texttt{#1}: #2pt",
        r"\texttt{#1}: #2+#3",
        r"\texttt{#1}: \unknown{#2}",
    ],
)
def test_literal_label_does_not_open_code_math_dimensions_or_bare_tuples(body):
    from app.latex import collect_prose_arguments

    count = 3 if "#3" in body else 2
    definition = r"\newcommand{\NativeDoc}[" + str(count) + "]{" + body + "}"
    assert collect_prose_arguments(definition) == {}


def test_plain_formatted_heading_keeps_existing_prose_parameter_behavior():
    from app.latex import collect_prose_arguments

    definition = r"\newcommand{\NativeDoc}[2]{\textbf{#1}: #2}"
    assert collect_prose_arguments(definition) == {"NativeDoc": (2, frozenset({1, 2}))}


@pytest.mark.parametrize(
    "identifier",
    [
        r"scipy.optimize.differential\textunderscore evolution",
        r"module.function\_name",
        r"path/to/data\%20file",
        r"value\textunderscore{}name",
    ],
)
def test_explicit_monospace_code_preserves_whole_identifiers_and_tex_escapes(
    identifier,
):
    source = r"We use \texttt{" + identifier + "} for optimization."
    item = segments(source)[0]
    assert item.protected == [r"\texttt{" + identifier + "}"]
    assert (
        item.restore("我们使用⟪P0000⟫进行优化。")
        == r"我们使用\texttt{" + identifier + "}进行优化。"
    )
    assert identifier not in MARKER.sub("", item.masked)


def test_alias_explicitly_wrapping_monospace_code_is_not_a_prose_macro():
    from app.latex import collect_text_macros

    definition = r"\newcommand{\Identifier}[1]{\texttt{#1}}"
    assert "Identifier" not in collect_text_macros(definition)
    source = (
        definition
        + r"\begin{document}Use \Identifier{module.foo\textunderscore bar}.\end{document}"
    )
    assert "module.foo" not in exposed(source)
    assert rewritten(source, "Use", "调用") == source.replace("Use", "调用")


def test_monospace_code_boundary_leaves_surrounding_prose_and_emphasis_translatable():
    source = r"We use \texttt{api\_name} with \emph{important settings}."
    assert "We use" in exposed(source) and "important settings" in exposed(source)
    assert rewritten(source, "important settings", "重要设置") == source.replace(
        "important settings", "重要设置"
    )


@pytest.mark.parametrize(
    "entry", ["title", "icmltitle", "subtitle", "icmltitlerunning"]
)
@pytest.mark.parametrize(
    "definition",
    [r"\def\papername", r"\newcommand{\papername}", r"\newcommand*\papername"],
)
def test_literal_macro_at_explicit_title_entry_is_translated_once(entry, definition):
    from app.latex import collect_title_macros

    title = "A Unified Framework for Learning"
    source = (
        definition
        + "{"
        + title
        + "}\n"
        + "\\"
        + entry
        + "{\\papername}"
        + r"\begin{document}\maketitle\begin{center}\papername\end{center}\end{document}"
    )
    assert collect_title_macros(source) == {"papername": title}
    items = segments(source)
    titles = [s for s in items if s.role == "title"]
    assert len(titles) == 1 and titles[0].source == title
    output = apply_translations(
        source,
        items,
        {s.key: s.restore(s.masked.replace(title, "统一学习框架")) for s in items},
    )
    assert output == source.replace(title, "统一学习框架")
    assert (
        apply_translations(source, items, {s.key: s.restore(s.masked) for s in items})
        == source
    )


def test_title_macro_definition_and_usage_in_separate_files_keep_references():
    from app.latex import collect_title_macros, extract_paper_title

    definitions = "\\def% comment\n\\papername% ignored\n{A Unified% author note\n Framework for Learning}\n"
    main = r"\input{definitions}\title[Short]{\papername}\begin{document}\maketitle\end{document}"
    macros = collect_title_macros(definitions + "\n" + main)
    assert set(macros) == {"papername"}
    assert (
        extract_paper_title(main, title_macros=macros)
        == "A Unified Framework for Learning"
    )
    items = segments(definitions, title_macros=macros)
    assert len(items) == 1 and items[0].role == "title"
    assert "author note" not in MARKER.sub("", items[0].masked)
    result = apply_translations(
        definitions,
        items,
        {s.key: s.restore(s.masked.replace("A Unified", "统一")) for s in items},
    )
    assert result == definitions.replace("A Unified", "统一")
    assert segments(main, title_macros=macros) == []


@pytest.mark.parametrize(
    "source",
    [
        r"\def\brand{Open Research}\title{A Study of \brand}",
        r"\def\brand{SUNRISE}\title{\brand}",
        r"\def\formula{x+y}\title{\formula}",
        r"\def\papername{A Study of $x+y$}\title{\papername}",
        r"\def\papername#1{A Study of #1}\title{\papername}",
        r"\newcommand{\papername}[1]{A Study of #1}\title{\papername}",
        r"\newcommand{\papername}[1][Default]{A Study of #1}\title{\papername}",
        r"\def\papername{A Plain Title}\def\papername{Another Title}\title{\papername}",
        r"\def\papername{A Plain Title}\let\papername\other\title{\papername}",
        r"\def\papername{A Plain Title}\newcommand{\wrapper}{\title{\papername}}",
        r"\def\papername{A Plain Title}\verb|\title{\papername}|",
        r"\def\papername{A Plain Title}\begin{verbatim}\title{\papername}\end{verbatim}",
        r"\def\papername{A Plain Title}$\text{\title{\papername}}$",
        r"\edef\papername{A Plain Title}\title{\papername}",
        r"\def\papername{A Plain Title}\section{\papername}",
    ],
)
def test_nonliteral_or_ambiguous_title_macros_remain_opaque(source):
    from app.latex import collect_title_macros

    assert collect_title_macros(source) == {}
    items = segments(source)
    assert not any(
        s.role == "title"
        and s.source in {"A Plain Title", "Another Title", "Open Research"}
        for s in items
    )
    assert (
        apply_translations(source, items, {s.key: s.restore(s.masked) for s in items})
        == source
    )


def test_extract_paper_title_ignores_macro_definition_examples():
    from app.latex import extract_paper_title

    source = (
        r"\newcommand{\template}{\title{Fake Title}}\title{Actual \textbf{Paper} Title}"
    )
    assert extract_paper_title(source) == "Actual Paper Title"


@pytest.mark.parametrize("body", ["A Study", "Learning Framework", "统一学习框架"])
def test_plain_title_macro_can_be_short_without_exposing_unrelated_macros(body):
    from app.latex import collect_title_macros

    source = (
        r"\def\brand{Open Research}\def\mathvalue{alpha beta}\def\papername{"
        + body
        + r"}\title{\papername}"
    )
    assert collect_title_macros(source) == {"papername": body}
    assert [s.source for s in segments(source) if s.role == "title"] == [body]


def test_title_command_inside_math_alias_is_not_a_prose_entry():
    from app.latex import collect_title_macros

    source = r"\newcommand{\be}{\begin{equation}}\newcommand{\ee}{\end{equation}}\def\papername{A Plain Title}\be\text{\title{\papername}}\ee"
    assert collect_title_macros(source) == {}


@pytest.mark.parametrize(
    "name",
    [
        "ResNet-101-FPN",
        "GPT-4o",
        "GPT-3.5",
        "COCO2017",
        "word2vec",
        "float32",
        "H2O",
        "L2",
        "A-10",
        "VGG-16",
    ],
)
def test_compact_named_identifiers_keep_their_digits_as_one_literal(name):
    source = f"The model {name} takes 44 hours."
    item = segments(source)[0]
    assert item.protected == [name, "44"]
    assert item.literal_value(name) == name
    assert item.is_movable(name)
    assert name not in item.masked
    assert (
        item.restore("耗时 ⟪P0001⟫ 小时，模型为 ⟪P0000⟫。")
        == f"耗时 44 小时，模型为 {name}。"
    )
    assert (
        apply_translations(source, [item], {item.key: item.restore(item.masked)})
        == source
    )


@pytest.mark.parametrize(
    "modifier",
    [
        "top-5",
        "Top-5",
        "step-1",
        "Section-3",
        "10-fold",
        "32 hours",
        "64GB",
        "3D",
        "first 20 samples",
        "3.6 million",
    ],
)
def test_regular_quantities_and_natural_language_modifiers_are_not_named_literals(
    modifier,
):
    from app.latex import named_identifier

    assert not named_identifier(modifier)
    item = segments(f"We evaluate {modifier} on data.")[0]
    assert not any(named_identifier(value) for value in item.protected)
    if "top" in modifier.lower():
        assert modifier.split("-")[0] in item.masked
    assert item.restore(item.masked) == item.source


def test_named_identifier_does_not_freeze_following_english_modifier():
    item = segments("The ResNet-101-FPN-based method uses COCO2017-trained weights.")[0]
    assert item.protected == ["ResNet-101-FPN", "COCO2017"]
    assert "-based method" in item.masked and "-trained weights" in item.masked
    assert (
        item.restore("该方法基于 ⟪P0000⟫，权重在 ⟪P0001⟫ 上训练。")
        == "该方法基于 ResNet-101-FPN，权重在 COCO2017 上训练。"
    )


def test_named_identifiers_remain_opaque_in_math_code_and_command_arguments():
    source = r"Before $\text{ResNet-101-FPN}$ and \texttt{COCO2017} and \cite{GPT-4o}. After."
    item = segments(source)[0]
    assert r"$\text{ResNet-101-FPN}$" in item.protected
    assert r"\texttt{COCO2017}" in item.protected
    assert r"\cite{GPT-4o}" in item.protected
    assert item.restore(item.masked) == source


def test_model_depths_can_no_longer_exchange_with_training_hours():
    source = "Training ResNet-50-FPN takes 32 hours and ResNet-101-FPN takes 44 hours."
    item = segments(source)[0]
    assert item.protected == ["ResNet-50-FPN", "32", "ResNet-101-FPN", "44"]
    assert "101" not in item.protected and "50" not in item.protected
    assert (
        item.restore("⟪P0000⟫ 需 ⟪P0001⟫ 小时，⟪P0002⟫ 需 ⟪P0003⟫ 小时。")
        == "ResNet-50-FPN 需 32 小时，ResNet-101-FPN 需 44 小时。"
    )


@pytest.mark.parametrize(
    "name", ["EfficientNet-B7", "ResNet-v2", "FA9550-18-1-0490", "N66001-15-C-4066"]
)
def test_numbered_hyphen_components_stay_inside_high_confidence_name(name):
    item = segments(f"The identifier {name} appears with 44 samples.")[0]
    assert item.protected == [name, "44"]
    assert item.literal_value(name) == name
    assert item.restore(item.masked) == item.source


def test_capitalized_natural_modifier_is_not_promoted_by_letter_before_number():
    from app.latex import named_identifier

    assert not named_identifier("Top-K5")
    assert not named_identifier("phase-v2")


@pytest.mark.parametrize(
    "translation",
    [
        "ResNet-⟪P0000⟫ 使用 ⟪P0001⟫ 个样本。",
        "⟪P0000⟫-FPN 使用 ⟪P0001⟫ 个样本。",
        "⟪P0000⟫101 使用 ⟪P0001⟫ 个样本。",
    ],
)
def test_named_literal_cannot_be_spliced_into_a_different_model_name(translation):
    item = segments("The model ResNet-101-FPN uses 44 samples.")[0]
    with pytest.raises(ValueError, match="命名标识符"):
        item.restore(translation)


def test_named_literal_boundary_allows_original_nonbreaking_space_and_word_suffix():
    item = segments("Our~GPT-4o-based method uses 44 samples.")[0]
    assert item.restore(item.masked) == item.source
    assert (
        item.restore("我们的⟪P0000⟫方法使用⟪P0001⟫个样本。")
        == "我们的~GPT-4o方法使用44个样本。"
    )


def test_named_literal_after_line_break_is_not_glued_to_previous_word():
    source = "We thank the developers of\nPylearn2 and others."
    item = segments(source)[0]
    assert item.restore(item.masked) == source
