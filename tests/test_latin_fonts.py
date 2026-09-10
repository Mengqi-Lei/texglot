"""Explicit legacy Latin families must remain readable under Unicode engines."""

import pytest
from pypdf import PdfReader

from app.compiler import (
    LEGACY_LATIN_FAMILIES,
    compile_pdf,
    find_compiler,
    prepare_engine_sources,
    prepare_legacy_latin_fonts,
)


def test_legacy_selections_keep_size_series_shape_and_are_idempotent(tmp_path):
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\input{body}\n\\begin{document}\nText.\\end{document}\n",
        encoding="utf-8",
    )
    body = tmp_path / "body.tex"
    body.write_text(
        r"\fontsize{10}{12}\usefont{OT1}{phv}{b}{it}"
        "\n"
        r"\fontfamily{ppl}\fontseries{m}\fontshape{n}\selectfont",
        encoding="utf-8",
    )
    prepare_legacy_latin_fonts(tmp_path, "tectonic")
    assert r"\fontsize{10}{12}\usefont{TU}{texglot-phv}{b}{it}" in body.read_text(
        encoding="utf-8"
    )
    assert r"\fontencoding{TU}\fontfamily{texglot-ppl}" in body.read_text(
        encoding="utf-8"
    )
    assert "texgyreheros-regular.otf" in main.read_text(encoding="utf-8")
    assert "texgyrepagella-regular.otf" in main.read_text(encoding="utf-8")
    before = {p.name: p.read_bytes() for p in (main, body)}
    prepare_legacy_latin_fonts(tmp_path, "tectonic")
    assert before == {p.name: p.read_bytes() for p in (main, body)}


def test_comments_examples_and_explicit_unicode_family_are_preserved(tmp_path):
    main = tmp_path / "main.tex"
    source = r"""\documentclass{article}
\usepackage{fontspec}
\newfontfamily\AuthorFont{texgyrepagella-regular.otf}[NFSSFamily=phv]
\setmainfont{texgyrepagella-regular.otf}
\setsansfont{texgyreheros-regular.otf}
\begin{document}
% \usefont{OT1}{phv}{m}{n}
\verb|\usefont{OT1}{phv}{m}{n}|
\begin{verbatim}
\fontfamily{ptm}
\end{verbatim}
{\fontfamily{phv}\selectfont Plzeň}
{\usefont{TU}{phv}{m}{n} Univerzitní}
\end{document}
"""
    main.write_text(source, encoding="utf-8")
    prepare_legacy_latin_fonts(tmp_path, "tectonic")
    assert main.read_text(encoding="utf-8") == source


def test_authors_default_font_commands_are_never_replaced(tmp_path):
    main = tmp_path / "main.tex"
    authored = (
        r"\setmainfont{texgyrepagella-regular.otf}"
        r"\setsansfont{texgyreadventor-regular.otf}"
        r"\setmonofont{texgyrecursor-regular.otf}"
    )
    main.write_text(
        r"\documentclass{article}\usepackage{fontspec}"
        + authored
        + r"\begin{document}{\usefont{T1}{phv}{m}{n} Plzeň}\end{document}",
        encoding="utf-8",
    )
    prepare_legacy_latin_fonts(tmp_path, "tectonic")
    assert authored in main.read_text(encoding="utf-8")
    assert main.read_text(encoding="utf-8").count(r"\setmainfont") == 1
    assert main.read_text(encoding="utf-8").count(r"\setsansfont") == 1
    assert main.read_text(encoding="utf-8").count(r"\setmonofont") == 1


@pytest.mark.skipif(not find_compiler("tectonic"), reason="Tectonic is unavailable")
async def test_native_standard_legacy_families_preserve_unicode_and_authored_default(
    tmp_path,
):
    source = tmp_path / "source"
    source.mkdir()
    main = source / "main.tex"
    rows = []
    for name in LEGACY_LATIN_FAMILIES:
        rows.append(r"{\usefont{OT1}{" + name + r"}{m}{n} Univerzitní Plzeň}\par")
        rows.append(r"{\usefont{T1}{" + name + r"}{b}{it} François}\par")
    main.write_text(
        r"\documentclass{article}\usepackage{fontspec}"
        r"\setmainfont{texgyrepagella-regular.otf}"
        r"\begin{document}\typeout{TEXGLOT-AUTHOR-FONT:\fontname\font}"
        + "\n".join(rows)
        + r"\end{document}",
        encoding="utf-8",
    )
    prepare_engine_sources(source, "tectonic")

    async def notify(message):
        pass

    pdf, warnings = await compile_pdf(
        source, "main.tex", tmp_path / "build", "tectonic", notify
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert text.count("Univerzitní") == len(LEGACY_LATIN_FAMILIES)
    assert text.count("Plzeň") == len(LEGACY_LATIN_FAMILIES)
    assert text.count("François") == len(LEGACY_LATIN_FAMILIES)
    log = (tmp_path / "build/main.log").read_text(errors="replace", encoding="utf-8")
    assert "Missing character:" not in log
    assert "texgyrepagella-regular.otf" in next(
        line for line in log.splitlines() if "TEXGLOT-AUTHOR-FONT:" in line
    )
    assert warnings == []


@pytest.mark.skipif(not find_compiler("tectonic"), reason="Tectonic is unavailable")
async def test_times_compatibility_preserves_explicit_unicode_sans_and_mono(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.tex").write_text(
        r"\documentclass{article}\usepackage{times}\usepackage{fontspec}"
        r"\setsansfont{texgyrepagella-regular.otf}"
        r"\setmonofont{texgyreadventor-regular.otf}"
        r"\begin{document}"
        r"{\sffamily\typeout{TEXGLOT-AUTHOR-SANS:\fontname\font}Plzeň}"
        r"{\ttfamily\typeout{TEXGLOT-AUTHOR-MONO:\fontname\font}Univerzitní}"
        r"\end{document}",
        encoding="utf-8",
    )
    prepare_engine_sources(source, "tectonic")

    async def notify(message):
        pass

    _, warnings = await compile_pdf(
        source, "main.tex", tmp_path / "build", "tectonic", notify
    )
    log = (tmp_path / "build/main.log").read_text(errors="replace", encoding="utf-8")
    assert "texgyrepagella-regular.otf" in next(
        line for line in log.splitlines() if "TEXGLOT-AUTHOR-SANS:" in line
    )
    assert "texgyreadventor-regular.otf" in next(
        line for line in log.splitlines() if "TEXGLOT-AUTHOR-MONO:" in line
    )
    assert "Missing character:" not in log and warnings == []
