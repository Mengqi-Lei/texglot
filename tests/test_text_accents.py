"""Whole-word recognition for literal TeX text accents, without evaluating TeX."""

import unicodedata

import pytest

from app.text_accents import accented_word_spans, accented_word_text


@pytest.mark.parametrize(
    ("source", "display"),
    [
        (r"Universit\'e", "Université"),
        (r"Montr\'eal", "Montréal"),
        (r"Universit\'{e}", "Université"),
        (r"Universit{\'e}", "Université"),
        (r"Universit{\'{e}}", "Université"),
        (r"{Montr\'eal}", "Montréal"),
        (r"{{Montr\'{e}al}}", "Montréal"),
        (r"G{\"o}del", "Gödel"),
        (r"G{{\"{o}}}del", "Gödel"),
        (r"{\v{S}}imek", "Šimek"),
        (r"{\v S}imek", "Šimek"),
        (r"Fran\c{c}ois", "François"),
        (r"Fran{\c c}ois", "François"),
        (r"{\'{{e}}}", "é"),
        (r"\'{\c{c}}", "ḉ"),
        (r"\'{\i}", "í"),
        (r"\'\i", "í"),
        (r"na{\"{\i}}ve", "naïve"),
        (r"\v{\j}", "ǰ"),
        ("Universit\\'\ne", "Université"),
        (r"\'{A}", "Á"),
        (r"\`a", "à"),
        (r"\^o", "ô"),
        (r"\"u", "ü"),
        (r"\~n", "ñ"),
        (r"\=a", "ā"),
        (r"\.z", "ż"),
        (r"\u g", "ğ"),
        (r"\v s", "š"),
        (r"\H o", "ő"),
        (r"\r a", "å"),
        (r"\c c", "ç"),
        (r"\k a", "ą"),
        (r"\b b", "ḇ"),
        (r"\d d", "ḍ"),
        (r"\t{oo}", "o͡o"),
    ],
)
def test_standard_accent_words_keep_the_entire_original_slice(source, display):
    assert accented_word_spans(source) == [(0, len(source), display)]
    assert accented_word_text(source) == display
    assert unicodedata.normalize("NFC", display) == display
    # Unicode is a display value; the source—including braces and line breaks—
    # is still the exact string a caller can protect and later restore.
    start, end, _ = accented_word_spans(source)[0]
    assert source[start:end].encode("utf-8") == source.encode("utf-8")


@pytest.mark.parametrize(
    "source",
    [
        "ordinary English text",
        "Université",
        "naïve",
        "Universit'e",
        r"Universit\\'e",
        r'G\\"odel',
        r"\Universit",
        r"\vbox{ordinary text}",
        r"\Hbox{ordinary text}",
        r"\cfoo",
        r"\'{ab}",
        r"\t{o}",
        r"\v{中}",
        r"\v{α}",
        r"\v{я}",
        r"\v{1}",
        r"\v{$a$}",
        r"\'{\unknown}",
        r"\'{\textbf{e}}",
        "\\'{e",
        "\\'",
    ],
)
def test_non_words_and_unknown_control_sequences_are_not_accent_words(source):
    assert accented_word_spans(source) == []
    assert accented_word_text(source) is None


def test_multiple_words_have_precise_offsets_and_do_not_capture_commands():
    text = r"From \textbf{Universit\'e} de {Montr\'eal}, G{\"o}del wrote."
    spans = accented_word_spans(text)
    assert [(text[a:b], value) for a, b, value in spans] == [
        (r"Universit\'e", "Université"),
        (r"{Montr\'eal}", "Montréal"),
        (r"G{\"o}del", "Gödel"),
    ]
    assert text[spans[0][0] - 1] == "{"
    assert text[spans[0][1]] == "}"
    assert accented_word_text(r"\textbf{Universit\'e}") is None


def test_whitespace_after_a_formatting_command_does_not_change_span_boundaries():
    text = "\\textbf \n{Universit\\'e}"
    assert [(text[a:b], value) for a, b, value in accented_word_spans(text)] == [
        (r"Universit\'e", "Université")
    ]


def test_a_real_accent_after_escaped_linebreak_does_not_capture_the_prior_word():
    text = r"Universit\\\'e"
    spans = accented_word_spans(text)
    assert [(text[a:b], value) for a, b, value in spans] == [(r"\'e", "é")]
    assert accented_word_text(text) is None


def test_non_latin_arguments_do_not_connect_adjacent_latin_words():
    text = r"before\v{中}after and before\'{ab}after"
    assert accented_word_spans(text) == []


def test_nesting_is_bounded_and_malformed_wrappers_are_not_whole_words():
    text = "{" * 100 + r"Universit\'e" + "}" * 100
    assert accented_word_text(text) is None
    assert accented_word_text(r"Universit{\'e") is None
    assert accented_word_text(r"{Universit\'e") is None


def test_real_segment_moves_university_names_as_whole_source_words():
    from app.latex import segments

    source = r"Researchers from Universit\'e de Montr\'eal proved the result."
    item = segments(source)[0]
    assert item.protected == [r"Universit\'e", r"Montr\'eal"]
    assert [item.literal_value(value) for value in item.protected] == [
        "Université",
        "Montréal",
    ]
    assert all(item.is_movable(value) for value in item.protected)
    assert item.restore(item.masked) == source
    result = item.restore("这一结果由⟪P0001⟫的⟪P0000⟫研究人员证明。")
    assert result == r"这一结果由Montr\'eal的Universit\'e研究人员证明。"


def test_real_segment_moves_braced_accent_word_without_detaching_its_letter():
    from app.latex import segments

    source = r'G{\"o}del and K\"oppen discussed the theorem.'
    item = segments(source)[0]
    assert item.protected == [r'G{\"o}del', r'K\"oppen']
    assert [item.literal_value(value) for value in item.protected] == [
        "Gödel",
        "Köppen",
    ]
    assert item.restore(item.masked) == source
    result = item.restore("⟪P0001⟫与⟪P0000⟫讨论了该定理。")
    assert result == r'K\"oppen与G{\"o}del讨论了该定理。'
