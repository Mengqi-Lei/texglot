import json

import httpx
import pytest

from app.config import Settings
from app.latex import segments
from app.llm import Translator
from app.paper_context import (
    MAX_PAPER_CONTEXT_CHARS,
    extract_paper_context,
    limit_context,
)


@pytest.mark.parametrize(
    "abstract",
    [
        r"\begin{abstract}We improve \emph{accuracy} to 92.5\% with $n=8$.\end{abstract}",
        r"\abstract{We improve \emph{accuracy} to 92.5\% with $n=8$.}",
        r"\abstract We improve \emph{accuracy} to 92.5\% with $n=8$.\endabstract",
        r"\begin{abstract*}We improve \emph{accuracy} to 92.5\% with $n=8$.\end{abstract*}",
    ],
)
def test_explicit_abstract_keeps_numbers_math_and_nested_formatting(tmp_path, abstract):
    path = tmp_path / "main.tex"
    path.write_text(
        r"\documentclass{article}\title{Not the abstract}\begin{document}"
        + abstract
        + r"\section{Introduction}Not the abstract either.\end{document}",
        encoding="utf-8",
    )
    before = path.read_bytes()
    assert (
        extract_paper_context(tmp_path, "main.tex")
        == r"We improve \emph{accuracy} to 92.5\% with $n=8$."
    )
    assert path.read_bytes() == before


def test_abstract_input_follows_document_order_not_filenames(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\input{z-summary}\input{a-appendix}\end{document}",
        encoding="utf-8",
    )
    (tmp_path / "z-summary.tex").write_text(
        r"\begin{abstract}\input{summary-text}\end{abstract}", encoding="utf-8"
    )
    (tmp_path / "summary-text.tex").write_text(
        "The actual abstract has 2026 samples.", encoding="utf-8"
    )
    (tmp_path / "a-appendix.tex").write_text(
        r"\begin{abstract}Wrong appendix summary.\end{abstract}", encoding="utf-8"
    )
    (tmp_path / "000-unused.tex").write_text(
        r"\abstract{Wrong unused file.}", encoding="utf-8"
    )
    assert (
        extract_paper_context(tmp_path, "main.tex")
        == "The actual abstract has 2026 samples."
    )


def test_comments_macro_definitions_and_verbatim_are_not_abstracts(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"""
% \abstract{A commented-out draft.}
\newcommand{\example}{\abstract{An unused macro.}}
\newenvironment{sample}{\begin{abstract}An example.}{\end{abstract}}
\def\exampletwo#1{\abstract{Another unused macro.}}
\begin{verbatim}\abstract{Verbatim example.}\end{verbatim}
\begin{comment}\abstract{Comment environment.}\end{comment}
\verb|\abstract{Inline verbatim.}|
\abstract{The real abstract. % remove this comment
Results are promising.}
""",
        encoding="utf-8",
    )
    assert (
        extract_paper_context(tmp_path, "main.tex")
        == "The real abstract. Results are promising."
    )


@pytest.mark.parametrize(
    "source",
    [
        r"\title{A paper}\begin{document}These are the first four paragraphs.\end{document}",
        r"\begin{document}Some body.\end{document}\abstract{Outside the document.}",
        r"\begin{abstract}A broken environment with no closing marker.",
        r"\abstract{A broken command with no closing brace.",
        r"\abstract{A broken command with \emph{nested braces}",
        r"\newcommand{\summarytext}{A dynamically generated summary.}\abstract{\summarytext}",
    ],
)
def test_missing_or_unclosed_abstract_has_no_arbitrary_prose_fallback(tmp_path, source):
    (tmp_path / "main.tex").write_text(source, encoding="utf-8")
    assert extract_paper_context(tmp_path, "main.tex") == ""


def test_nested_inputs_cycles_and_external_paths(tmp_path):
    root = tmp_path / "paper"
    root.mkdir()
    (root / "parts").mkdir()
    (tmp_path / "secret.tex").write_text(r"\abstract{PRIVATE}", encoding="utf-8")
    (root / "main.tex").write_text(
        r"\input{../secret}\input{parts/front}", encoding="utf-8"
    )
    (root / "parts/front.tex").write_text(
        r"\input{../main}\input{abstract}", encoding="utf-8"
    )
    (root / "parts/abstract.tex").write_text(
        r"\abstract{An included abstract.}", encoding="utf-8"
    )
    assert extract_paper_context(root, "main.tex") == "An included abstract."


@pytest.mark.parametrize(
    "text",
    ["word " * 4000, "摘要内容。" * 2000, "x" * 20000],
    ids=["long-words", "long-chinese", "long-token"],
)
def test_oversized_abstract_and_request_limit_are_bounded(tmp_path, text):
    (tmp_path / "main.tex").write_text(r"\abstract{" + text + "}", encoding="utf-8")
    context = extract_paper_context(tmp_path, "main.tex")
    assert len(context) <= MAX_PAPER_CONTEXT_CHARS
    assert context.endswith("…")
    assert limit_context(context) == context


def test_truncation_prefers_a_complete_sentence():
    complete = "This is a complete sentence. " * 190
    context = limit_context(
        complete + "An exceptionally long unfinished sentence " * 100
    )
    assert context == complete.strip() + "…"
    chinese = limit_context("这是一段完整的摘要句子。" * 800)
    assert chinese.endswith("。…") and len(chinese) <= MAX_PAPER_CONTEXT_CHARS


async def test_api_payload_keeps_abstract_on_repair_and_enforces_limit():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "准确的译文。"}}]}
        )

    translator = Translator(Settings())
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        item = segments("A paragraph to translate.")[0]
        context = "An abstract with 42 samples and $x+y$. " * 300
        await translator.translate(item, context)
        await translator.translate(item, context, "Previous output was incomplete.")
    finally:
        await translator.close()
    first, retry = [json.loads(call["messages"][1]["content"]) for call in calls]
    assert first["paper_context"] == retry["paper_context"] == limit_context(context)
    assert len(first["paper_context"]) > 1800  # the old limit must not silently survive
    assert len(first["paper_context"]) <= MAX_PAPER_CONTEXT_CHARS
    assert "42" in first["paper_context"] and "$x+y$" in first["paper_context"]
    assert retry["previous_validation_error"] == "Previous output was incomplete."
    assert first["paragraph"] == retry["paragraph"] == "A paragraph to translate."
    assert "source-language abstract" in calls[0]["messages"][0]["content"]


async def test_changing_abstract_invalidates_body_cache_without_deleting_old_cache(
    tmp_path, monkeypatch
):
    from pypdf import PdfWriter

    import app.jobs as jobs_module

    folder = tmp_path / "abstract-cache-test"
    source = folder / "source"
    source.mkdir(parents=True)
    (folder / "source-ready").touch()
    main = source / "main.tex"

    def write_paper(abstract):
        main.write_text(
            r"\documentclass{article}\begin{document}\begin{abstract}"
            + abstract
            + r"\end{abstract}A shared body paragraph.\end{document}",
            encoding="utf-8",
        )

    calls = []

    class FakeTranslator:
        tokens = 0

        def __init__(self, settings):
            pass

        async def translate(self, segment, context, feedback):
            calls.append((segment.source, context))
            return segment.masked

        async def close(self):
            pass

    async def fake_compile(work, main, out, engine, log):
        out.mkdir(parents=True, exist_ok=True)
        pdf = out / "main.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=600, height=800)
        writer.write(pdf)
        return pdf, []

    monkeypatch.setattr(jobs_module, "JOBS", tmp_path)
    monkeypatch.setattr(jobs_module, "Translator", FakeTranslator)
    monkeypatch.setattr(jobs_module, "compile_pdf", fake_compile)
    monkeypatch.setattr(jobs_module, "choose_compiler", lambda _: "xelatex")
    manager = jobs_module.JobManager()
    job = {
        "id": folder.name,
        "main": "main.tex",
        "kind": "file",
        "name": "paper.tex",
        "logs": [],
    }
    settings = Settings(target_language="English")
    write_paper("We study optimization methods.")
    await manager.pipeline(job, settings)
    assert ("A shared body paragraph.", "We study optimization methods.") in calls
    old_cache = {p.name: p.read_bytes() for p in folder.glob("cache-*.json")}
    calls.clear()
    await manager.pipeline(job, settings)
    assert calls == []
    write_paper("We study language understanding.")
    await manager.pipeline(job, settings)
    assert ("A shared body paragraph.", "We study language understanding.") in calls
    assert len(list(folder.glob("cache-*.json"))) == 2
    main.write_text(
        r"\documentclass{article}\begin{document}A shared body paragraph.\end{document}",
        encoding="utf-8",
    )
    settings.context_guidance = False
    extract = jobs_module.extract_paper_context

    def must_not_extract(*args):
        raise AssertionError("Disabled guidance must not extract background")

    monkeypatch.setattr(jobs_module, "extract_paper_context", must_not_extract)
    calls.clear()
    await manager.pipeline(job, settings)
    assert calls == [("A shared body paragraph.", "")]
    calls.clear()
    await manager.pipeline(job, settings)
    assert calls == []
    settings.context_guidance = True
    monkeypatch.setattr(jobs_module, "extract_paper_context", extract)
    await manager.pipeline(job, settings)
    # Even when no abstract exists, on/off modes must not share cached outputs.
    assert calls == [("A shared body paragraph.", "")]
    assert len(list(folder.glob("cache-*.json"))) == 4
    for name, content in old_cache.items():
        assert (folder / name).read_bytes() == content
