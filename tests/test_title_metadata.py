"""Display metadata may decode constants without exposing them to translation."""

import asyncio
import json

import pytest

import app.jobs as jobs
from app.latex import (
    collect_title_macros,
    display_paper_title,
    extract_paper_title,
    extract_title_metadata,
    segments,
)


def test_embedded_method_macro_keeps_the_complete_title_and_translation_boundaries():
    source = (
        r"\newcommand{\method}{Structured Adversarial Training}"
        r"\title{\method{} Improves Recognition Performance}"
    )
    assert extract_paper_title(source) == (
        "Structured Adversarial Training Improves Recognition Performance"
    )
    assert collect_title_macros(source) == {}
    assert all(
        "Structured Adversarial Training" not in item.source
        for item in segments(source)
    )


def test_display_constants_can_be_nested_formatted_and_defined_in_another_file():
    main = r"\title[Short]{\method{}: Learning at Scale}"
    definitions = (
        "\\def\\base{Structured % ignored\n Learning}\n"
        r"\newcommand{\method}{\textbf{\base} \emph{Models}}"
    )
    assert extract_paper_title(main, macro_context=definitions + main) == (
        "Structured Learning Models: Learning at Scale"
    )
    assert collect_title_macros(definitions + main) == {}


def test_display_decoding_keeps_text_and_symbols_without_typesetting_adornments():
    source = (
        r"\def\engine{\LaTeX}"
        r"\title{\includegraphics[width=2cm][viewport=0 0 1 1]{logo.pdf}"
        r"{\color{red}\textbf{Learning}} \href{https://example.com}{with} "
        r"\engine{}: G\"{o}del \& $\alpha$\thanks{A grant acknowledgement}}"
    )
    assert extract_paper_title(source) == "Learning with LaTeX: Gödel & α"


@pytest.mark.parametrize(
    ("title", "definitions", "expected"),
    [
        (
            r"\LARGE \bf Learning with Point Clouds",
            r"\def\LARGE{\@setfontsize{\LARGE}{14}{17pt}}"
            r"\def\LARGE{\@setfontsize{\LARGE}{16}{20pt}}",
            "Learning with Point Clouds",
        ),
        (
            r"\Huge\bfseries Learning with Point Clouds",
            r"\def\Huge{\@setfontsize{\Huge}{24}{28pt}}"
            r"\DeclareRobustCommand{\bfseries}{\fontseries{b}\selectfont}",
            "Learning with Point Clouds",
        ),
        (
            r"\method{}: Learning with Point Clouds",
            r"\def\method{{\large\bf A New Method}}"
            r"\def\large{\@setfontsize{\large}{14}{17pt}}"
            r"\def\bf{\normalfont\bfseries}",
            "A New Method: Learning with Point Clouds",
        ),
        (
            r"\LARGE\H{} Learning with $\alpha$",
            r"\def\H{Hypergraph}\def\LARGE{\@setfontsize{\LARGE}{16}{20pt}}",
            "Hypergraph Learning with α",
        ),
    ],
)
def test_template_typesetting_definitions_do_not_override_display_semantics(
    title, definitions, expected
):
    main = rf"\title{{{title}}}"
    assert extract_paper_title(main, macro_context=definitions + main) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (r"\title{\unknown{} Improves Learning}", r"\unknown{} Improves Learning"),
        (
            r"\newcommand{\method}[1]{A #1 Method}\title{\method{} Improves Learning}",
            r"\method{} Improves Learning",
        ),
        (
            r"\def\method{First}\def\method{Second}\title{\method{} Improves Learning}",
            r"\method{} Improves Learning",
        ),
        (
            r"\def\method{First}\let\method\other\title{\method{} Improves Learning}",
            r"\method{} Improves Learning",
        ),
        (
            r"\edef\method{Computed}\title{\method{} Improves Learning}",
            r"\method{} Improves Learning",
        ),
        (
            r"\def\first{\second}\def\second{\first}\title{\first{} Improves Learning}",
            r"\first{} Improves Learning",
        ),
        (
            r"\def\method{\input{private-file}}\title{\method{} Improves Learning}",
            r"{\input{private-file}}{} Improves Learning",
        ),
        (r"\title{An Unclosed Title", ""),
    ],
)
def test_unresolved_titles_preserve_the_expression_instead_of_losing_content(
    source, expected
):
    assert extract_paper_title(source) == expected


def test_display_expansion_has_depth_and_work_limits():
    names = ["method" + chr(97 + index) for index in range(20)]
    deep = (
        "".join(rf"\def\{left}{{\{right}}}" for left, right in zip(names, names[1:]))
        + rf"\def\{names[-1]}{{A Method}}\title{{\{names[0]}}}"
    )
    assert extract_paper_title(deep) == r"\methoda"
    large = r"\def\base{" + "X" * 4096 + r"}\title{\base\base\base\base}"
    assert extract_paper_title(large) == r"\base\base\base\base"
    assert extract_paper_title(r"\title{" + "A" * 1000 + "}") == "A" * 1000


@pytest.mark.parametrize(
    ("raw", "display"),
    [
        (r"VGGT-$\omega$", "VGGT-ω"),
        (r"VGGT-$\unknownsymbol$", r"VGGT-$\unknownsymbol$"),
        (
            r"\unknownmodel{}: Learning with $\omega$",
            r"\unknownmodel{}: Learning with $\omega$",
        ),
        ("Learning at 50% of the Cost", "Learning at 50% of the Cost"),
        (
            r"Learning with \kern\customlength Space",
            r"Learning with \kern\customlength Space",
        ),
    ],
)
def test_title_display_keeps_unknown_math_and_literal_content(raw, display):
    assert display_paper_title(raw) == display


@pytest.mark.parametrize(
    ("raw", "display"),
    [
        ("A & B: Why {geometry} matters", "A & B: Why {geometry} matters"),
        ("C# and A_B at 50% of the Cost", "C# and A_B at 50% of the Cost"),
        (r"VGGT-$\omega$ & 3D", "VGGT-ω & 3D"),
        (r"VGGT-$\customsymbol$ & 3D", r"VGGT-$\customsymbol$ & 3D"),
        (r"$\omega$ & $\customsymbol$", r"ω & $\customsymbol$"),
        ("Learning for $100 and $200", "Learning for $100 and $200"),
    ],
)
def test_citation_prose_is_not_interpreted_as_tex_syntax(raw, display):
    assert display_paper_title(raw, literal=True) == display


def test_wordmark_title_preserves_content_and_raw_source_without_translating_macros():
    source = r"""
\newcommand{\wordmark}{%
  \mbox{%
    {\fontfamily{cmr}\fontseries{bx}\fontshape{it}\selectfont X}%
    \kern0.4pt%
    {\fontfamily{cmr}\fontseries{m}\fontshape{it}\selectfont -Model:}%
  }%
}
\newcommand{\subject}{{\bfseries Self-supervised Reconstruction}}
\title{\wordmark\ \subject\ with $\omega$}
"""
    result = extract_title_metadata(source)
    assert result.raw == r"\wordmark\ \subject\ with $\omega$"
    assert result.display == "X-Model: Self-supervised Reconstruction with ω"
    assert collect_title_macros(source) == {}
    assert all(
        "Self-supervised Reconstruction" not in item.source for item in segments(source)
    )


def write_old_job(root, *, main="main.tex", dependencies=None):
    folder = root / "paper"
    source = folder / "prepared-source"
    source.mkdir(parents=True)
    (source / "main.tex").write_text(
        r"\input{definitions}\title{\method{} Improves Learning}", encoding="utf-8"
    )
    (source / "definitions.tex").write_text(
        r"\newcommand{\method}{Structured Training}", encoding="utf-8"
    )
    record = {
        "id": "paper",
        "kind": "arxiv",
        "name": "Improves Learning",
        "main": main,
        "source_dependencies": dependencies or ["main.tex", "definitions.tex"],
        "status": "completed",
        "updated_at": 1234.5,
        "tokens": 123456,
        "cached": 23,
    }
    (folder / "job.json").write_text(json.dumps(record), encoding="utf-8")
    for name in ["original.pdf", "translated.pdf", "reader.json", "cache.json"]:
        (folder / name).write_bytes(b"private existing data")
    return folder, record


def test_startup_repairs_old_cross_file_title_once_without_rerunning_or_reordering(
    tmp_path, monkeypatch
):
    folder, old = write_old_job(tmp_path)
    monkeypatch.setattr(jobs, "JOBS", tmp_path)
    manager = jobs.JobManager()
    expected = {
        **old,
        "name": "Structured Training Improves Learning",
        "title": {"raw": r"\method{} Improves Learning", "source": "latex"},
        "title_metadata_version": jobs.TITLE_METADATA_VERSION,
    }
    assert manager.get("paper") == expected
    assert json.loads((folder / "job.json").read_text(encoding="utf-8")) == expected
    for name in ["original.pdf", "translated.pdf", "reader.json", "cache.json"]:
        assert (folder / name).read_bytes() == b"private existing data"

    def unexpected(*args, **kwargs):
        raise AssertionError("Versioned metadata must not rescan the source")

    monkeypatch.setattr(jobs, "extract_title_metadata", unexpected)
    assert jobs.JobManager().get("paper") == expected


def test_startup_refreshes_previous_version_fallback_with_template_dependencies(
    tmp_path, monkeypatch
):
    folder, old = write_old_job(tmp_path)
    source = folder / "prepared-source"
    (source / "main.tex").write_text(
        r"\documentclass{conference}\title{\LARGE\bf Learning with Point Clouds}",
        encoding="utf-8",
    )
    (source / "conference.cls").write_text(
        r"\def\LARGE{\@setfontsize{\LARGE}{14}{17pt}}"
        r"\def\LARGE{\@setfontsize{\LARGE}{16}{20pt}}",
        encoding="utf-8",
    )
    old.update(
        name="arXiv 2409.12345",
        title_metadata_version=1,
        source_dependencies=["main.tex", "conference.cls"],
    )
    (folder / "job.json").write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(jobs, "JOBS", tmp_path)
    manager = jobs.JobManager()
    assert manager.get("paper") == {
        **old,
        "name": "Learning with Point Clouds",
        "title": {"raw": r"\LARGE\bf Learning with Point Clouds", "source": "latex"},
        "title_metadata_version": jobs.TITLE_METADATA_VERSION,
    }
    for name in ["original.pdf", "translated.pdf", "reader.json", "cache.json"]:
        assert (folder / name).read_bytes() == b"private existing data"


@pytest.mark.parametrize(
    "damage", ["missing", "malformed", "oversized", "escape", "invalid_dependencies"]
)
def test_unreadable_title_sources_do_not_hide_existing_jobs(
    tmp_path, monkeypatch, damage
):
    folder, old = write_old_job(tmp_path)
    source = folder / "prepared-source"
    if damage == "missing":
        (source / "definitions.tex").unlink()
    elif damage == "malformed":
        (source / "main.tex").write_bytes(b"\xff")
    elif damage == "oversized":
        (source / "definitions.tex").write_bytes(b"X" * (4 * 1024 * 1024 + 1))
    elif damage == "escape":
        old["source_dependencies"].append("../../outside.tex")
    else:
        old["source_dependencies"] = [None, {}]
    (folder / "job.json").write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(jobs, "JOBS", tmp_path)
    record = jobs.JobManager().get("paper")
    assert record == {**old, "title_metadata_version": jobs.TITLE_METADATA_VERSION}


def test_cached_official_title_survives_startup_without_local_sources(
    tmp_path, monkeypatch
):
    folder, old = write_old_job(tmp_path, main="missing.tex")
    raw = r"VGGT-$\omega$: " + "A long title " * 30
    old.update(
        name="arXiv 2512.12345",
        title={"raw": raw, "source": "arxiv"},
        title_metadata_version=2,
    )
    (folder / "job.json").write_text(json.dumps(old))
    monkeypatch.setattr(jobs, "JOBS", tmp_path)
    record = jobs.JobManager().get("paper")
    assert record["name"] == ("VGGT-ω: " + "A long title " * 30).strip()
    assert record["title"]["raw"] == raw
    assert record["updated_at"] == old["updated_at"]


async def test_background_title_repair_does_not_block_or_overwrite_newer_job_state(
    tmp_path, monkeypatch
):
    folder, old = write_old_job(tmp_path)
    old.update(name="arXiv 2512.12345", arxiv_id="2512.12345")
    (folder / "job.json").write_text(json.dumps(old))
    monkeypatch.setattr(jobs, "JOBS", tmp_path)
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def fetch(identifier):
        calls.append(identifier)
        entered.set()
        await finish.wait()
        return r"Official Title with $\omega$"

    monkeypatch.setattr(jobs, "fetch_arxiv_title", fetch)
    manager = jobs.JobManager()
    manager.start_title_refresh()
    await entered.wait()
    record = manager.get("paper")
    assert record["name"] == "Structured Training Improves Learning"
    # Simulate progress arriving while a metadata request is pending.
    record.update(done=7, tokens=123999, status="compiling")
    finish.set()
    await manager._title_refresh
    assert record["name"] == "Official Title with ω"
    assert record["title"] == {
        "raw": r"Official Title with $\omega$",
        "source": "arxiv",
    }
    assert record["done"] == 7 and record["tokens"] == 123999
    assert record["status"] == "compiling" and record["updated_at"] == old["updated_at"]
    assert json.loads((folder / "job.json").read_text()) == record
    for name in ["original.pdf", "translated.pdf", "reader.json", "cache.json"]:
        assert (folder / name).read_bytes() == b"private existing data"
    await manager.resolve_arxiv_title(record)
    assert calls == ["2512.12345"]


async def test_shutdown_cancels_pending_title_lookup_and_keeps_local_title(
    tmp_path, monkeypatch
):
    folder, old = write_old_job(tmp_path)
    old.update(name="arXiv 2512.12345", arxiv_id="2512.12345")
    (folder / "job.json").write_text(json.dumps(old))
    monkeypatch.setattr(jobs, "JOBS", tmp_path)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def fetch(_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(jobs, "fetch_arxiv_title", fetch)
    manager = jobs.JobManager()
    manager.start_title_refresh()
    await entered.wait()
    await manager.close()
    assert cancelled.is_set() and manager._title_refresh.cancelled()
    assert manager.get("paper")["name"] == "Structured Training Improves Learning"


async def test_background_offline_failure_preserves_a_previous_version_literal_title(
    tmp_path, monkeypatch
):
    folder, old = write_old_job(tmp_path)
    (folder / "prepared-source/main.tex").write_text(r"\title{VGGT-$\customsymbol$}")
    old.update(name="arXiv 2512.12345", arxiv_id="2512.12345", title_metadata_version=2)
    (folder / "job.json").write_text(json.dumps(old))
    monkeypatch.setattr(jobs, "JOBS", tmp_path)

    async def unavailable(_):
        return ""

    monkeypatch.setattr(jobs, "fetch_arxiv_title", unavailable)
    manager = jobs.JobManager()
    manager.start_title_refresh()
    await manager._title_refresh
    assert manager.get("paper")["name"] == r"VGGT-$\customsymbol$"
    assert manager.get("paper")["updated_at"] == old["updated_at"]
