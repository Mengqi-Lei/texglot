"""Legacy minted caches must remain usable without running Pygments."""

from app.minted import prepare_minted_cache

OLD_STYLE = r"""\makeatletter
\def\PYGdefault@reset{\let\PYGdefault@it=\relax}
\def\PYGdefault#1#2{\PYGdefault@reset #2}
\def\PYGdefaultZus{\char`\_}
\def\PYGdefaultZsq{\char`\'}
\makeatother
"""


def test_legacy_frozen_style_keeps_definitions_and_supports_both_listing_prefixes(tmp_path):
    style = tmp_path / "default.pygstyle"
    style.write_text(OLD_STYLE)
    listing = tmp_path / "listing1.pygtex"
    code = r"\PYG{k}{print}\PYGZus \PYGdefault{k}{value}\PYGdefaultZus"
    listing.write_text(code)
    assert prepare_minted_cache(tmp_path) == 1
    result = style.read_text()
    assert result.startswith(OLD_STYLE)
    assert r"\let\PYG\PYGdefault" in result
    assert r"\let\PYGZus\PYGdefaultZus" in result
    assert r"\let\PYGZsq\PYGdefaultZsq" in result
    assert listing.read_text() == code
    assert prepare_minted_cache(tmp_path) == 0
    assert style.read_text() == result


def test_current_ambiguous_and_comment_only_styles_remain_untouched(tmp_path):
    examples = [
        r"\def\PYG#1#2{#2}" + OLD_STYLE,
        OLD_STYLE + OLD_STYLE.replace("PYGdefault", "PYGother"),
        "% " + OLD_STYLE.replace("\n", "\n% "),
    ]
    for index, text in enumerate(examples):
        (tmp_path / f"{index}.pygstyle").write_text(text)
    assert prepare_minted_cache(tmp_path) == 0
    for index, text in enumerate(examples):
        assert (tmp_path / f"{index}.pygstyle").read_text() == text


def test_author_generic_escape_definition_is_not_overwritten(tmp_path):
    style = tmp_path / "default.pygstyle"
    style.write_text(OLD_STYLE + r"\def\PYGZus{custom underscore}")
    assert prepare_minted_cache(tmp_path) == 1
    assert r"\let\PYGZus" not in style.read_text()
    assert r"\def\PYGZus{custom underscore}" in style.read_text()
