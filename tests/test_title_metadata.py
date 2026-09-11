"""Display metadata may decode constants without exposing them to translation."""

import json

import pytest

import app.jobs as jobs
from app.latex import collect_title_macros, extract_paper_title, segments


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
        "\\def\\base{Structured% ignored\n Learning}\n"
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
    "source",
    [
        r"\title{\unknown{} Improves Learning}",
        r"\newcommand{\method}[1]{A #1 Method}\title{\method{} Improves Learning}",
        r"\def\method{First}\def\method{Second}\title{\method{} Improves Learning}",
        r"\def\method{First}\let\method\other\title{\method{} Improves Learning}",
        r"\edef\method{Computed}\title{\method{} Improves Learning}",
        r"\def\first{\second}\def\second{\first}\title{\first{} Improves Learning}",
        r"\def\method{\input{private-file}}\title{\method{} Improves Learning}",
        r"\title{An Unclosed Title",
    ],
)
def test_unresolved_titles_fall_back_instead_of_silently_losing_the_prefix(source):
    assert extract_paper_title(source) == ""


def test_display_expansion_has_depth_and_work_limits():
    names = ["method" + chr(97 + index) for index in range(20)]
    deep = (
        "".join(rf"\def\{left}{{\{right}}}" for left, right in zip(names, names[1:]))
        + rf"\def\{names[-1]}{{A Method}}\title{{\{names[0]}}}"
    )
    assert extract_paper_title(deep) == ""
    large = r"\def\base{" + "X" * 4096 + r"}\title{\base\base\base\base}"
    assert extract_paper_title(large) == ""
    assert extract_paper_title(r"\title{" + "A" * 1000 + "}") == "A" * 200


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
        "title_metadata_version": jobs.TITLE_METADATA_VERSION,
    }
    assert manager.get("paper") == expected
    assert json.loads((folder / "job.json").read_text(encoding="utf-8")) == expected
    for name in ["original.pdf", "translated.pdf", "reader.json", "cache.json"]:
        assert (folder / name).read_bytes() == b"private existing data"

    def unexpected(*args, **kwargs):
        raise AssertionError("Versioned metadata must not rescan the source")

    monkeypatch.setattr(jobs, "extract_paper_title", unexpected)
    assert jobs.JobManager().get("paper") == expected


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
