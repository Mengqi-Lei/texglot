"""Fault-path contracts for jobs, compatible providers, and CLI resumption."""

import asyncio
import json

import httpx
import pytest
from pypdf import PdfReader, PdfWriter

import app.jobs as jobs
from app.cli import Service, parser, run
from app.config import DATA, Settings
from app.llm import ProviderError, Translator


def write_dependency_record(root, out, files):
    def quote(value):
        return (
            value.as_posix().replace("$", "$$").replace("#", r"\#").replace(" ", r"\ ")
        )

    (out / "dependencies.mk").write_text(
        quote(out / "main.pdf")
        + ": "
        + " ".join(quote(root / rel) for rel in files)
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS", tmp_path)
    settings = Settings(
        target_language="English", context_guidance=False, concurrency=1
    )
    monkeypatch.setattr(jobs, "load_settings", lambda: settings.model_copy())
    monkeypatch.setattr(jobs, "choose_compiler", lambda _: "tectonic")
    calls = []

    async def compile_fake(root, main, out, engine, log):
        calls.append(out.name)
        out.mkdir(parents=True, exist_ok=True)
        pdf = out / "main.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=600, height=800)
        writer.add_metadata(
            {
                "/Source": "\n".join(
                    p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.tex"))
                )
            }
        )
        writer.write(pdf)
        write_dependency_record(
            root,
            out,
            [
                p.relative_to(root).as_posix()
                for p in root.rglob("*")
                if p.suffix in {".tex", ".sty", ".cls"}
            ],
        )
        return pdf, []

    monkeypatch.setattr(jobs, "compile_pdf", compile_fake)
    manager = jobs.JobManager()
    folder = tmp_path / "paper"
    source = folder / "source"
    source.mkdir(parents=True)
    (folder / "source-ready").touch()
    (source / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{body}\n\\end{document}\n",
        encoding="utf-8",
    )
    (source / "body.tex").write_text(
        "The first scientific result is correct and useful.\n\n"
        "The second scientific result is correct and important.\n\n"
        "The third scientific result is both significant and reproducible.\n",
        encoding="utf-8",
    )
    job = {
        "id": folder.name,
        "main": "main.tex",
        "kind": "file",
        "name": "paper.zip",
        "language": "English",
        "context_guidance": False,
        "status": "queued",
        "logs": [],
    }
    manager.jobs[job["id"]] = job
    return manager, job, folder, settings, calls


class ControlledTranslator:
    calls = []
    bad = ""
    error = ValueError
    closed = 0

    def __init__(self, settings):
        self.tokens = 0

    async def translate(self, segment, context, feedback=""):
        self.calls.append(segment.source)
        self.tokens += 5
        if self.bad and self.bad in segment.source:
            raise self.error("Injected failure")
        return segment.masked

    translate_slots = translate

    async def close(self):
        type(self).closed += 1


@pytest.fixture
def translator(monkeypatch):
    ControlledTranslator.calls = []
    ControlledTranslator.bad = ""
    ControlledTranslator.error = ValueError
    ControlledTranslator.closed = 0
    monkeypatch.setattr(jobs, "Translator", ControlledTranslator)
    return ControlledTranslator


async def test_settings_failure_is_terminal_and_cancel_recovers_orphaned_active(
    pipeline, monkeypatch
):
    manager, job, _, _, _ = pipeline

    def broken():
        raise ValueError("settings file invalid")

    monkeypatch.setattr(jobs, "load_settings", broken)
    manager.start(job["id"])
    await manager.tasks[job["id"]]
    assert job["status"] == "failed"
    assert "settings file invalid" in job["error"]
    job["status"] = "queued"  # Recover orphaned active state from an older service.
    await manager.cancel(job["id"])
    assert job["status"] == "cancelled"


async def test_inconsistent_source_map_stops_before_paid_requests(
    pipeline, translator, monkeypatch
):
    manager, job, _, _, _ = pipeline
    original = jobs.segments

    def corrupt(text, **kwargs):
        items = original(text, **kwargs)
        if items:
            items[-1].masked += " corrupted source"
        return items

    monkeypatch.setattr(jobs, "segments", corrupt)
    await manager.run(job["id"])
    assert job["status"] == "failed"
    assert "源码分段还原检查失败（body.tex:" in job["error"]
    assert translator.calls == []


async def test_layout_transform_failure_is_caught_before_paid_requests(
    pipeline, translator, monkeypatch
):
    manager, job, _, _, calls = pipeline
    original = jobs.fit_tables

    def broken_layout(text):
        text, count = original(text)
        return text + r"\InvalidLayoutCommand", count

    compile_original = jobs.compile_pdf

    async def compile_with_realistic_failure(root, main, out, engine, log):
        if any(r"\InvalidLayoutCommand" in p.read_text() for p in root.rglob("*.tex")):
            raise ValueError("Layout transformation did not compile")
        return await compile_original(root, main, out, engine, log)

    monkeypatch.setattr(jobs, "fit_tables", broken_layout)
    monkeypatch.setattr(jobs, "compile_pdf", compile_with_realistic_failure)
    await manager.run(job["id"])
    assert job["status"] == "failed"
    assert "Layout transformation did not compile" in job["error"]
    assert calls == ["build-original"]
    assert translator.calls == []


async def test_partial_retries_only_failed_segments_and_keeps_deliverable(
    pipeline, translator
):
    manager, job, folder, settings, calls = pipeline
    translator.bad = "second"
    await manager.pipeline(job, settings)
    assert job["status"] == "partial"
    assert job["done"] == job["total"] == 3
    assert len(translator.calls) == 5  # Two successes and three repair attempts.
    assert (folder / job["artifacts"]["translated"]).is_file()
    assert len(job["warnings"]) == 1
    assert "second" in (folder / "translated/body.tex").read_text(encoding="utf-8")
    translator.bad = ""
    translator.calls.clear()
    await manager.pipeline(job, settings)
    assert job["status"] == "completed" and job["cached"] == 2
    assert len(translator.calls) == 1 and "second" in translator.calls[0]
    assert job["warnings"] == []
    assert calls.count("build-original") == 1


def test_existing_auto_layout_notices_move_to_logs_without_hiding_real_problems(
    pipeline,
):
    manager, job, folder, _, _ = pipeline
    cropped = "存在超出页高的浮动体，内容可能被裁切；请检查图表及编译日志"
    job["warnings"] = [jobs.FLOAT_FIT_NOTICE, cropped]
    job["original_warnings"] = list(job["warnings"])
    manager.persist(job)
    original = (folder / "job.json").read_bytes()
    loaded = jobs.JobManager().get(job["id"])
    assert loaded["warnings"] == loaded["original_warnings"] == [cropped]
    assert (
        len(loaded["logs"]) == 1
        and loaded["logs"][0]["message"] == jobs.FLOAT_FIT_NOTICE
    )
    jobs.separate_layout_notices(loaded)
    assert len(loaded["logs"]) == 1
    assert (folder / "job.json").read_bytes() == original


async def test_auto_layout_log_does_not_replace_the_visible_progress_message(pipeline):
    manager, job, _, _, _ = pipeline
    job["message"] = "检查排版"
    await manager.log(job, jobs.FLOAT_FIT_NOTICE)
    assert job["message"] == "检查排版"
    assert job["logs"][-1]["message"] == jobs.FLOAT_FIT_NOTICE
    await manager.log(job, "开始翻译")
    assert job["message"] == "开始翻译"


async def test_compiler_adapted_original_is_reused_with_its_warnings(
    pipeline, translator, monkeypatch
):
    import zipfile

    manager, job, folder, settings, calls = pipeline
    original = jobs.compile_pdf
    library = b"% adapted package\n\\def\\KeptMacro{Scientific meaning}\n"
    upstream = b"% original package\n\\pdfcompresslevel=0\n"

    async def adapted(root, main, out, engine, log):
        if out.name == "build-original":
            path = root / main
            path.write_text("% compiler configuration repair\n" + path.read_text())
            (root / "external.sty").write_bytes(library)
            (root / "external.sty.texglot-original").write_bytes(upstream)
        else:
            assert (root / "external.sty").read_bytes() == library
            assert (root / "external.sty.texglot-original").read_bytes() == upstream
            assert (
                (root / main).read_text().startswith("% compiler configuration repair")
            )
        pdf, warnings = await original(root, main, out, engine, log)
        return pdf, warnings + (
            ["Original source warning"] if out.name == "build-original" else []
        )

    monkeypatch.setattr(jobs, "compile_pdf", adapted)
    translator.bad = "second"
    await manager.pipeline(job, settings)
    translator.bad = ""
    translator.calls.clear()
    await manager.pipeline(job, settings)
    assert job["status"] == "completed" and job["cached"] == 2
    assert len(translator.calls) == 1 and "second" in translator.calls[0]
    assert calls.count("build-original") == 1
    assert job["warnings"] == ["Original source warning"]
    assert (
        (folder / "prepared-source/main.tex")
        .read_text()
        .startswith("% compiler configuration repair")
    )
    with zipfile.ZipFile(folder / job["artifacts"]["source"]) as archive:
        assert archive.read("external.sty") == library
        assert archive.read("external.sty.texglot-original") == upstream
    assert not (folder / "source/external.sty").exists()
    (folder / "source/body.tex").write_text(
        "A changed scientific result needs fresh source preparation."
    )
    await manager.pipeline(job, settings)
    assert calls.count("build-original") == 2


async def test_probe_adaptation_survives_final_writeback_and_export(
    pipeline, translator, monkeypatch
):
    import zipfile

    manager, job, folder, settings, _ = pipeline
    original = jobs.compile_pdf
    prefix = "\\PassOptionsToPackage{table}{xcolor}\n"

    async def adapted(root, main, out, engine, log):
        if out.name == "build-probe":
            path = root / main
            path.write_text(prefix + path.read_text(encoding="utf-8"), encoding="utf-8")
        return await original(root, main, out, engine, log)

    monkeypatch.setattr(jobs, "compile_pdf", adapted)
    await manager.pipeline(job, settings)
    output = (folder / "translated/main.tex").read_bytes()
    assert (
        (folder / "translated/main.tex").read_text(encoding="utf-8").startswith(prefix)
    )
    with zipfile.ZipFile(folder / job["artifacts"]["source"]) as archive:
        assert archive.read("main.tex") == output


async def test_failed_final_compile_exports_the_last_repaired_source(
    pipeline, translator, monkeypatch
):
    import zipfile

    manager, job, folder, _, _ = pipeline
    original = jobs.compile_pdf

    async def fails_after_edit(root, main, out, engine, log):
        if out.name == "build-translated":
            path = root / main
            path.write_text("% final compiler repair\n" + path.read_text())
            raise ValueError("Still cannot compile")
        return await original(root, main, out, engine, log)

    monkeypatch.setattr(jobs, "compile_pdf", fails_after_edit)
    await manager.run(job["id"])
    assert job["status"] == "failed" and len(translator.calls) == 3
    with zipfile.ZipFile(folder / job["artifacts"]["source"]) as archive:
        assert archive.read("main.tex") == (folder / "translated/main.tex").read_bytes()


async def test_provider_failure_preserves_successful_cache_and_resume(
    pipeline, translator
):
    manager, job, _, _, _ = pipeline
    translator.bad = "second"
    translator.error = ProviderError
    await manager.run(job["id"])
    assert job["status"] == "failed"
    assert job["done"] >= 1  # A sibling can finish before gather observes failure.
    assert translator.closed == 1
    assert job["tokens"] >= 10
    translator.bad = ""
    translator.calls.clear()
    await manager.run(job["id"])
    assert job["status"] == "completed" and job["cached"] >= 1
    assert all("first" not in source for source in translator.calls)
    assert translator.closed == 2


@pytest.mark.parametrize(
    "cache_value", ["{broken json", "[]", "null", "non-string-entry"]
)
async def test_damaged_cache_can_resume_without_losing_other_valid_entries(
    pipeline, translator, cache_value
):
    manager, job, folder, settings, _ = pipeline
    await manager.pipeline(job, settings)
    path = next(folder.glob("cache-*.json"))
    if cache_value == "non-string-entry":
        data = json.loads(path.read_text(encoding="utf-8"))
        data[next(iter(data))] = None
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        path.write_text(cache_value, encoding="utf-8")
    translator.calls.clear()
    await manager.pipeline(job, settings)
    assert job["status"] == "completed"
    assert len(translator.calls) == (1 if cache_value == "non-string-entry" else 3)
    if cache_value != "non-string-entry":
        assert (
            next(folder.glob("cache-*-invalid-*.json")).read_text(encoding="utf-8")
            == cache_value
        )


async def test_original_signature_covers_children_templates_assets_and_engine(
    pipeline, translator
):
    manager, job, folder, settings, calls = pipeline
    await manager.pipeline(job, settings)
    source = folder / "source"
    initial = PdfReader(folder / "original.pdf").metadata["/Source"]
    (source / "body.tex").write_text(
        "An updated scientific result is consistent with the evidence.",
        encoding="utf-8",
    )
    await manager.pipeline(job, settings)
    assert calls.count("build-original") == 2
    assert PdfReader(folder / "original.pdf").metadata["/Source"] != initial
    signature = jobs.project_signature(source, "main.tex", "tectonic")
    (source / "template.sty").write_text("% template version one", encoding="utf-8")
    changed = jobs.project_signature(source, "main.tex", "tectonic")
    assert signature != changed
    (source / "figure.pdf").write_bytes(b"a figure")
    assert changed != jobs.project_signature(source, "main.tex", "tectonic")
    assert jobs.project_signature(
        source, "main.tex", "xelatex"
    ) != jobs.project_signature(source, "main.tex", "tectonic")


async def test_cancel_running_and_waiting_jobs_releases_global_slot(
    pipeline, monkeypatch
):
    manager, job, _, _, _ = pipeline
    entered = asyncio.Event()
    hold = asyncio.Event()

    async def blocked(current, settings):
        entered.set()
        await hold.wait()

    monkeypatch.setattr(manager, "pipeline", blocked)
    manager.start(job["id"])
    await entered.wait()
    second = dict(job, id="queued", logs=[], status="queued")
    manager.jobs[second["id"]] = second
    manager.start(second["id"])
    await asyncio.sleep(0)
    await manager.cancel(second["id"])
    assert second["status"] == "cancelled"
    await manager.cancel(job["id"])
    assert job["status"] == "cancelled"
    assert not manager.slot.locked()


@pytest.mark.parametrize(
    "usage,expected",
    [
        (None, 0),
        ({"total_tokens": None}, 0),
        ({"total_tokens": "17"}, 17),
        ({"total_tokens": -10}, 0),
        ([], 0),
        ({"total_tokens": "bad"}, 0),
    ],
)
async def test_optional_usage_does_not_discard_valid_completion(usage, expected):
    translator = Translator(Settings())
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "准确的译文。"}}],
                    "usage": usage,
                },
            )
        )
    )
    try:
        assert await translator.complete([]) == "准确的译文。"
        assert translator.tokens == expected
    finally:
        await translator.close()


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {},
        {"choices": None},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": None}]},
    ],
)
async def test_malformed_completion_is_diagnosable_provider_error(response):
    translator = Translator(Settings())
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        )
    )
    try:
        with pytest.raises(ProviderError, match="格式不兼容"):
            await translator.complete([])
    finally:
        await translator.close()


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 503])
async def test_transient_provider_responses_retry_with_bounded_backoff(
    status, monkeypatch
):
    calls, sleeps = [], []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(status, headers={"Retry-After": "10"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "译文"}}]})

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("app.llm.asyncio.sleep", sleep)
    translator = Translator(Settings())
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await translator.complete([]) == "译文"
        assert len(calls) == 3 and sleeps == [10, 10]
    finally:
        await translator.close()


@pytest.mark.parametrize("status,expected", [("completed", 0), ("translating", 1)])
def test_cli_resume_main_change_retries_completed_or_rejects_active(
    tmp_path, status, expected
):
    retried = []
    current = {
        "id": "done",
        "name": "paper",
        "main": "wrong.tex",
        "status": status,
        "pages": 1,
        "tokens": 0,
        "artifacts": {},
        "context_guidance": True,
    }

    def handler(request):
        if request.url.path == "/api/health":
            return httpx.Response(
                200, json={"ok": True, "name": "TeXGlot", "data_dir": str(DATA)}
            )
        if request.url.path.endswith("/retry"):
            data = json.loads(request.content)
            retried.append(data)
            current.update(status="completed", **data)
        return httpx.Response(200, json=current)

    service = Service(transport=httpx.MockTransport(handler))
    try:
        args = parser().parse_args(
            ["--resume", "done", "--main", "correct.tex", "--json", "-o", str(tmp_path)]
        )
        assert run(args, service) == expected
        assert retried == ([{"main": "correct.tex"}] if status == "completed" else [])
    finally:
        service.client.close()


@pytest.mark.parametrize("stage", ["build-original", "build-probe", "build-translated"])
async def test_compile_failures_preserve_recovery_state_and_avoid_extra_model_cost(
    pipeline, translator, monkeypatch, stage
):
    manager, job, folder, _, _ = pipeline
    normal_compile = jobs.compile_pdf

    async def fail_stage(root, main, out, engine, log):
        if out.name == stage:
            raise ValueError("Injected compiler failure")
        return await normal_compile(root, main, out, engine, log)

    monkeypatch.setattr(jobs, "compile_pdf", fail_stage)
    await manager.run(job["id"])
    assert job["status"] == "failed" and "compiler failure" in job["error"]
    if stage != "build-translated":
        assert translator.calls == []
    else:
        assert len(translator.calls) == 3
        assert (folder / job["artifacts"]["source"]).is_file()
        assert "translated" not in job["artifacts"]
    translator.calls.clear()
    monkeypatch.setattr(jobs, "compile_pdf", normal_compile)
    await manager.run(job["id"])
    assert job["status"] == "completed"
    assert len(translator.calls) == (0 if stage == "build-translated" else 3)


async def test_cancel_during_translation_closes_client_and_retains_completed_cache(
    pipeline, translator, monkeypatch
):
    manager, job, _, _, _ = pipeline
    entered = asyncio.Event()
    wait = asyncio.Event()
    normal_translate = translator.translate

    async def block_second(self, item, context, feedback=""):
        if "second" in item.source:
            entered.set()
            await wait.wait()
        return await normal_translate(self, item, context, feedback)

    monkeypatch.setattr(translator, "translate", block_second)
    manager.start(job["id"])
    await entered.wait()
    await manager.cancel(job["id"])
    assert job["status"] == "cancelled" and translator.closed == 1
    assert job["done"] == 1
    monkeypatch.setattr(translator, "translate", normal_translate)
    translator.calls.clear()
    await manager.run(job["id"])
    assert job["status"] == "completed" and job["cached"] == 1
    assert len(translator.calls) == 2


def test_damaged_job_record_does_not_prevent_loading_other_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "JOBS", tmp_path)
    for index, data in enumerate(
        [None, [], {"id": [], "status": "queued"}, {"id": "bad", "status": []}]
    ):
        folder = tmp_path / f"broken-{index}"
        folder.mkdir()
        (folder / "job.json").write_text(json.dumps(data), encoding="utf-8")
    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "job.json").write_text(
        json.dumps({"id": "valid", "status": "translating"}), encoding="utf-8"
    )
    manager = jobs.JobManager()
    assert list(manager.jobs) == ["valid"]
    assert manager.jobs["valid"]["status"] == "interrupted"


async def test_arxiv_pipeline_uses_compiled_macro_dependencies_for_display_title(
    pipeline, translator
):
    manager, job, folder, settings, _ = pipeline
    job.update(kind="arxiv", arxiv_id="2111.12345", name="arXiv 2111.12345")
    source = folder / "source"
    (source / "definitions.tex").write_text(
        r"\newcommand{\method}{Structured Training}", encoding="utf-8"
    )
    (source / "main.tex").write_text(
        r"\documentclass{article}\input{definitions}"
        r"\title{\method{} Improves Learning}"
        r"\begin{document}\maketitle\input{body}\end{document}",
        encoding="utf-8",
    )
    await manager.pipeline(job, settings)
    assert job["status"] == "completed"
    assert job["name"] == "Structured Training Improves Learning"
    assert job["title_metadata_version"] == jobs.TITLE_METADATA_VERSION


async def test_long_provider_retry_after_does_not_retry_too_early(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "999"})

    async def no_sleep(seconds):
        raise AssertionError("A long rate limit must not keep the task running")

    monkeypatch.setattr("app.llm.asyncio.sleep", no_sleep)
    translator = Translator(Settings())
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="较长的重试等待"):
            await translator.complete([])
        assert len(calls) == 1
    finally:
        await translator.close()


def test_starred_includes_reach_body_without_control_word_prefix_confusion(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\include*{intro}\include{results}\inputencoding{ignored}\includegraphics{figure}",
        encoding="utf-8",
    )
    for name in ["intro", "results", "encoding", "graphics", "ignored", "figure"]:
        (tmp_path / (name + ".tex")).write_text(
            "Some scientific prose.", encoding="utf-8"
        )
    assert jobs.JobManager.reachable_files(tmp_path, "main.tex") == [
        "intro.tex",
        "main.tex",
        "results.tex",
    ]


async def test_actual_compile_graph_drives_body_and_loaded_style_context(
    pipeline, translator, monkeypatch
):
    manager, job, folder, settings, _ = pipeline
    source = folder / "source"
    (source / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{layout}\n\\begin{document}\n"
        "\\def\\bodyfile{body}\\input{\\bodyfile}\n\\end{document}\n",
        encoding="utf-8",
    )
    (source / "body.tex").write_text(
        "This is the actual scientific paragraph. \\pIR=-131072sp Following prose.",
        encoding="utf-8",
    )
    (source / "layout.sty").write_text(r"\newdimen\pIR", encoding="utf-8")
    (source / "unused.tex").write_text(
        "This unused draft must not be translated.", encoding="utf-8"
    )
    normal_compile = jobs.compile_pdf

    async def record_selected(root, main, out, engine, log):
        result = await normal_compile(root, main, out, engine, log)
        write_dependency_record(root, out, ["main.tex", "body.tex", "layout.sty"])
        return result

    checked = []
    normal_translate = translator.translate

    async def check_register(self, item, context, feedback=""):
        if "actual scientific" in item.source:
            assert r"\pIR=-131072sp" in item.protected
            checked.append(True)
        return await normal_translate(self, item, context, feedback)

    monkeypatch.setattr(jobs, "compile_pdf", record_selected)
    monkeypatch.setattr(translator, "translate", check_register)
    assert jobs.JobManager.reachable_files(source, "main.tex") == ["main.tex"]
    await manager.pipeline(job, settings)
    assert job["source_files"] == ["body.tex", "main.tex"]
    assert job["source_dependencies"] == ["body.tex", "layout.sty", "main.tex"]
    assert checked == [True]
    assert all("unused draft" not in text for text in translator.calls)
    assert (folder / "translated/unused.tex").read_text(encoding="utf-8") == (
        source / "unused.tex"
    ).read_text(encoding="utf-8")


async def test_missing_dependency_record_recompiles_original_before_reusing_cache(
    pipeline, translator
):
    manager, job, folder, settings, calls = pipeline
    await manager.pipeline(job, settings)
    (folder / "build-original/dependencies.mk").unlink()
    translator.calls.clear()
    await manager.pipeline(job, settings)
    assert calls.count("build-original") == 2
    assert translator.calls == [] and job["cached"] == 3


async def test_unavailable_dependency_record_is_explicit_fallback(
    pipeline, translator, monkeypatch
):
    manager, job, _, settings, _ = pipeline
    monkeypatch.setattr(jobs, "compiled_dependencies", lambda *args: None)
    await manager.pipeline(job, settings)
    assert job["status"] == "completed" and job["source_files"] == [
        "body.tex",
        "main.tex",
    ]
    assert any("依赖记录不可用" in warning for warning in job["warnings"])


@pytest.mark.parametrize("mixed", [False, True])
async def test_opaque_graphic_fragments_are_preserved_and_excluded_from_translation(
    pipeline, translator, mixed
):
    manager, job, folder, settings, _ = pipeline
    source = folder / "source"
    (source / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nA scientific result.\n"
        "\\begin{tikzpicture}\\input{diagram}\\end{tikzpicture}\n"
        + ("\\input{diagram}\n" if mixed else "")
        + "\\end{document}\n",
        encoding="utf-8",
    )
    diagram = r"\foreach \x in {A,B} {\node at (\x) {}; }\input{coordinates}"
    (source / "diagram.tex").write_text(diagram, encoding="utf-8")
    (source / "coordinates.tex").write_text(r"\node at (0,0) {A};", encoding="utf-8")
    (source / "body.tex").unlink()
    await manager.pipeline(job, settings)
    assert job["source_files"] == ["coordinates.tex", "diagram.tex", "main.tex"]
    assert job["translation_files"] == ["main.tex"]
    assert (folder / "translated/diagram.tex").read_text(encoding="utf-8") == diagram
    assert len(translator.calls) == 1
    assert ("同时用于正文" in " ".join(job["warnings"])) is mixed
    if mixed:
        assert job["mixed_source_files"] == ["coordinates.tex", "diagram.tex"]
        assert job["opaque_source_files"] == []
    else:
        assert job["opaque_source_files"] == ["coordinates.tex", "diagram.tex"]
        assert job["mixed_source_files"] == []


@pytest.mark.parametrize(
    "invalid,category,english_category",
    [
        (None, "返回了非字符串", "returned a non-string value"),
        (" \n ", "返回了空白正文", "returned empty text"),
        ("PRIVATE_MODEL_OUTPUT ⟪P0000⟫", "包含保护标记", "included a protected token"),
        (
            r"\textbf{PRIVATE_MODEL_OUTPUT}",
            "包含无效的 LaTeX 或格式",
            "included invalid LaTeX or formatting",
        ),
        ("$x$", "包含无效的 LaTeX 或格式", "included invalid LaTeX or formatting"),
        ("```latex", "包含无效的 LaTeX 或格式", "included invalid LaTeX or formatting"),
        (r"\n\t", "返回了空白正文", "returned empty text"),
    ],
)
async def test_repair_diagnostics_identify_slot_and_category_without_response_text(
    invalid, category, english_category
):
    from app.i18n import english
    from app.latex import segments

    item = segments("First words " + "$x$ following words " * 10)[0]
    client = Translator(Settings())
    batches = []

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        values = dict(payload["slots"])
        batches.append(len(values))
        if len(batches) >= 2:
            values[next(iter(values))] = invalid
        return json.dumps(values)

    client.complete = complete
    try:
        with pytest.raises(ValueError) as error:
            await client.translate_slots(item)
        message = str(error.value)
        assert message == f"结构修复片段 9 {category}"
        assert english(message) == f"Structure repair slot 9 {english_category}"
        assert "PRIVATE_MODEL_OUTPUT" not in message and "⟪P0000⟫" not in message
        assert batches == [8, 3, 1]
    finally:
        await client.close()


async def test_final_fallback_log_locates_first_duplicate_source_occurrence(
    pipeline, translator
):
    from app.i18n import english

    manager, job, folder, settings, _ = pipeline
    source = folder / "source"
    (source / "copy.tex").write_text(
        (source / "body.tex").read_text(encoding="utf-8"), encoding="utf-8"
    )
    main = source / "main.tex"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            r"\end{document}", r"\input{copy}\end{document}"
        ),
        encoding="utf-8",
    )
    translator.bad = "second"
    await manager.pipeline(job, settings)
    assert job["status"] == "partial" and job["total"] == 3
    failures = [
        entry["message"]
        for entry in job["logs"]
        if "未通过结构检查" in entry["message"]
    ]
    assert len(failures) == 1
    failed_key = jobs.segments((source / "body.tex").read_text(encoding="utf-8"))[1].key
    assert f"[segment {failed_key[:12]} · body.tex:3]" in failures[0]
    assert "Injected failure" in failures[0]
    assert f"[segment {failed_key[:12]} · body.tex:3]" in english(failures[0])
    assert "body.tex" not in job["message"]
    assert all("body.tex" not in warning for warning in job["warnings"])


@pytest.mark.parametrize(
    "kind",
    ["empty_text", "not_a_string", "protected_token", "missing", "invalid_syntax"],
)
async def test_slot_recovery_requests_only_bad_slots_once_and_keeps_good_text(kind):
    from app.latex import segments

    item = segments("First text $x$ middle text $y$ final text.")[0]
    client = Translator(Settings())
    payloads = []

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        payloads.append(payload)
        if len(payloads) == 1:
            values = {"0": "合格首句", "1": "middle", "2": "合格尾句"}
            if kind == "missing":
                values.pop("1")
            else:
                values["1"] = {
                    "empty_text": " ",
                    "not_a_string": None,
                    "protected_token": "⟪P0000⟫",
                    "invalid_syntax": r"\textbf{middle}",
                }[kind]
            return json.dumps(values)
        assert set(payload["slots"]) == {"1"}
        assert payload["slots"]["1"] == payloads[0]["slots"]["1"]
        assert payload["paragraph"] == payloads[0]["paragraph"]
        assert payload["protected_tokens"] == payloads[0]["protected_tokens"]
        assert payload["slot_validation_failures"] == {"1": kind}
        return json.dumps({"1": "修复中句"})

    client.complete = complete
    try:
        output = await client.translate_slots(item, "Original abstract")
        restored = item.restore(output)
        assert (
            "合格首句" in restored and "合格尾句" in restored and "修复中句" in restored
        )
        assert restored.count("$x$") == restored.count("$y$") == 1
        assert len(payloads) == 2
    finally:
        await client.close()


@pytest.mark.parametrize("invalid", [r"\textbf{训练}", "$x$", "⟪broken", "```latex"])
async def test_table_repair_retries_invalid_prose_before_final_restore(invalid):
    from app.latex import segments

    item = segments(
        r"\begin{tabular}{ll}{\bf Parser} & {\bf Training} \\ \end{tabular}"
    )[0]
    client = Translator(Settings())
    payloads = []

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        payloads.append(payload)
        if len(payloads) == 1:
            assert [v.strip() for v in payload["slots"].values()] == [
                "Parser",
                "Training",
            ]
            return json.dumps({"0": "解析器", "1": invalid})
        assert set(payload["slots"]) == {"1"}
        assert payload["slot_validation_failures"] == {"1": "invalid_syntax"}
        return json.dumps({"1": "训练"})

    client.complete = complete
    try:
        output = await client.translate_slots(item)
        restored = item.restore(output)
        assert restored == item.source.replace("Parser", "解析器").replace(
            "Training", "训练"
        )
        assert len(payloads) == 2
    finally:
        await client.close()


@pytest.mark.parametrize(
    "value", ["训练\n有效", r"训练\n\t有效", "训练\n\n有效", "% & _ # $ { } ^ ~"]
)
async def test_valid_slot_prose_uses_existing_normalization_without_retry(value):
    from app.latex import Segment, normalize_generated_prose

    item = Segment(0, 8, "Training", "Training", [])
    client = Translator(Settings())
    calls = []

    async def complete(messages, **kwargs):
        calls.append(messages)
        return json.dumps({"0": value})

    client.complete = complete
    try:
        output = await client.translate_slots(item)
        assert output == normalize_generated_prose(value)
        assert item.restore(output) == item.restore(value)
        assert len(calls) == 1
    finally:
        await client.close()


async def test_slot_recovery_rejects_attempt_to_replace_previously_accepted_slot():
    from app.latex import segments

    client = Translator(Settings())
    item = segments("First text $x$ middle text $y$ final text.")[0]
    calls = []

    async def complete(messages, **kwargs):
        calls.append(json.loads(messages[1]["content"]))
        return json.dumps(
            {"0": "合格首句", "1": "", "2": "合格尾句"}
            if len(calls) == 1
            else {"0": "擅自替换", "1": "修复中句"}
        )

    client.complete = complete
    try:
        with pytest.raises(ValueError, match="增加了正文片段"):
            await client.translate_slots(item)
        assert len(calls) == 2 and set(calls[1]["slots"]) == {"1"}
    finally:
        await client.close()


async def test_missing_slot_after_single_recovery_still_fails():
    from app.latex import segments

    client = Translator(Settings())
    item = segments("First text $x$ middle text $y$ final text.")[0]
    calls = []

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        calls.append(payload)
        return json.dumps({"0": "合格首句", "2": "合格尾句"} if len(calls) == 1 else {})

    client.complete = complete
    try:
        with pytest.raises(ValueError, match="结构修复片段 2 未返回"):
            await client.translate_slots(item)
        assert len(calls) == 2
    finally:
        await client.close()


async def test_cancelling_a_slot_recovery_closes_pipeline_client(pipeline, monkeypatch):
    manager, job, _, _, _ = pipeline
    entered = asyncio.Event()
    hold = asyncio.Event()
    instances = []

    class RepairClient(Translator):
        def __init__(self, settings):
            super().__init__(settings)
            self.calls = []
            instances.append(self)

        async def translate(self, *args, **kwargs):
            raise ValueError("Injected initial validation failure")

        async def complete(self, messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            self.calls.append(payload)
            if "slot_validation_failures" not in payload:
                return json.dumps({key: "" for key in payload["slots"]})
            entered.set()
            await hold.wait()
            raise AssertionError("Cancelled recovery unexpectedly continued")

    monkeypatch.setattr(jobs, "Translator", RepairClient)
    manager.start(job["id"])
    await entered.wait()
    await manager.cancel(job["id"])
    assert job["status"] == "cancelled"
    assert len(instances) == 1 and len(instances[0].calls) == 2
    assert instances[0].client.is_closed
    assert not manager.slot.locked()


async def test_provider_error_during_slot_recovery_propagates_without_more_requests():
    from app.latex import segments

    client = Translator(Settings())
    item = segments("First text $x$ middle text.")[0]
    calls = []

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        calls.append(payload)
        if len(calls) == 1:
            return json.dumps({"0": "合格首句", "1": ""})
        raise ProviderError("Injected provider outage")

    client.complete = complete
    try:
        with pytest.raises(ProviderError, match="provider outage"):
            await client.translate_slots(item)
        assert len(calls) == 2 and set(calls[1]["slots"]) == {"1"}
    finally:
        await client.close()


async def test_dense_line_repair_falls_back_only_for_failed_line_and_preserves_others():
    from collections import Counter

    from app.latex import MARKER, segments

    source = "".join(
        r"\STATE Compute $x_{" + str(index) + r"}$ on chip." + "\n"
        for index in range(27)
    )
    item = segments(source)[0]
    client = Translator(Settings())
    translated_lines, slot_requests = [], []

    async def translate(line, context="", feedback="", **kwargs):
        translated_lines.append(line.source)
        if "$x_{7}$" in line.source:
            return "Missing protected tokens"
        return line.masked.replace("Compute", "计算").replace("on chip", "在芯片上")

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        slot_requests.append(payload)
        assert "$x_{7}$" in payload["protected_tokens"].values()
        assert payload["paper_context"] == "An unchanged abstract."
        assert payload["surrounding_source"] == source
        return json.dumps(
            {
                key: "恢复计算" if "Compute" in value else "在芯片上"
                for key, value in payload["slots"].items()
            }
        )

    client.translate = translate
    client.complete = complete
    try:
        output = await client.translate_slots(item, "An unchanged abstract.")
        restored = item.restore(output)  # The original large segment still validates.
        counts = Counter(translated_lines)
        assert len(counts) == 27
        assert all(
            number == (2 if "$x_{7}$" in line else 1) for line, number in counts.items()
        )
        assert len(slot_requests) == 1
        assert restored.count(r"\STATE") == 27
        assert MARKER.findall(output) == MARKER.findall(item.masked)
        assert "恢复计算" in restored
    finally:
        await client.close()


async def test_single_dense_unit_does_not_repeat_whole_segment_repair():
    from app.latex import MARKER, segments

    item = segments(
        "".join("Text $x_{" + str(index) + "}$ " for index in range(30)) + "\n"
    )[0]
    client = Translator(Settings())
    attempts, requests = [], []

    async def translate(line, context="", feedback="", **kwargs):
        attempts.append(line.source)
        return "Missing protected tokens"

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        requests.append(payload)
        return json.dumps({key: "译文" for key in payload["slots"]})

    client.translate = translate
    client.complete = complete
    try:
        output = await client.translate_slots(item)
        item.restore(output)
        assert len(attempts) == 0
        assert len(requests) == 4
        assert MARKER.findall(output) == MARKER.findall(item.masked)
    finally:
        await client.close()


@pytest.mark.parametrize(
    "source, expected",
    [
        (
            "I.e. $p_k$ approximates the maximum. The count is $K$.",
            ["I.e. $p_k$ approximates the maximum.", " The count is $K$."],
        ),
        (
            "The result follows\nfrom Eq. $E = m c^2$ and Fig. 2. It remains valid.",
            [
                "The result follows\nfrom Eq. $E = m c^2$ and Fig. 2.",
                " It remains valid.",
            ],
        ),
        (
            r"The phrase \textbf{First clause. Second clause} stays together. Another follows.",
            [
                r"The phrase \textbf{First clause. Second clause} stays together.",
                " Another follows.",
            ],
        ),
        (
            r"An interval $[0,1)$ has no closing TeX scope. Another holds.",
            [
                r"An interval $[0,1)$ has no closing TeX scope.",
                " Another holds.",
            ],
        ),
    ],
)
def test_sentence_repair_keeps_math_abbreviations_and_closed_scopes(source, expected):
    from app.latex import MARKER, segments
    from app.llm import repair_chunks

    item = segments(source)[0]
    bound, _ = item.compact(arguments_only=True)
    chunks = repair_chunks(bound)
    assert chunks is not None and "".join(chunks) == bound.masked
    restored = [
        MARKER.sub(lambda m: bound.protected[int(m[0][2:-1])], chunk)
        for chunk in chunks
    ]
    assert restored == expected


def test_sentence_repair_request_groups_are_bounded_and_source_spans_are_exact():
    from app.latex import segments
    from app.llm import repair_chunks

    source = " ".join(f"Result {i} remains significant." for i in range(100))
    item = segments(source)[0]
    chunks = repair_chunks(item)
    assert chunks is not None and 1 < len(chunks) <= 32
    assert "".join(chunks) == item.masked


async def test_short_paragraph_repair_translates_whole_sentences_before_slots():
    from app.latex import segments

    source = (
        "We set the learning rate to 0.02, which is decreased by 10 at 120k iterations. "
        "The class count is $K$, while $p_k$ is a probability."
    )
    item = segments(source)[0]
    client = Translator(Settings())
    calls = []

    async def complete(messages, **kwargs):
        request = json.loads(messages[1]["content"])
        calls.append(request)
        assert "slots" not in request  # Not separate 'is', 'by', 'at' fragments.
        assert request["surrounding_source"] == source
        if "learning rate" in request["paragraph"]:
            assert "which is decreased by" in request["paragraph"]
            return "学习率设为⟪P0000⟫，在第⟪P0002⟫k次迭代时降低⟪P0001⟫倍。"
        return "类别数量为⟪P0000⟫，而⟪P0001⟫是概率。"

    client.complete = complete
    try:
        restored = item.restore(await client.translate_slots(item))
        assert len(calls) == 2
        assert restored == (
            "学习率设为0.02，在第120k次迭代时降低10倍。 类别数量为$K$，而$p_k$是概率。"
        )
    finally:
        await client.close()


async def test_feedback_prompt_and_validation_allow_value_reordering_within_scope():
    from app.latex import segments

    item = segments("We decrease the rate by 10 at 120k iterations.")[0]
    client = Translator(Settings())
    calls = []

    async def complete(messages, **kwargs):
        calls.append(messages)
        request = json.loads(messages[1]["content"])
        assert request["fixed_format_order"] == []
        assert request["value_tokens"] == {"⟪P0000⟫": "10", "⟪P0001⟫": "120"}
        assert (
            "Movable value_tokens may and should change order" in messages[0]["content"]
        )
        assert "Follow ALL protected tokens" not in messages[0]["content"]
        return "在第⟪P0001⟫k次迭代时将学习率降低⟪P0000⟫倍。"

    client.complete = complete
    try:
        result = await client.translate(item, feedback="A previous token was missing")
        assert item.restore(result) == "在第120k次迭代时将学习率降低10倍。"
        assert len(calls) == 1
        with pytest.raises(ValueError, match="标记被修改"):
            item.restore(result.replace("⟪P0000⟫", "⟪P0001⟫"))
    finally:
        await client.close()


@pytest.mark.parametrize("guidance", [False, True])
@pytest.mark.parametrize("route", ["initial", "feedback", "slots"])
async def test_every_translation_route_carries_exact_same_paragraph_source(
    guidance, route
):
    from app.latex import segments

    source = "The archive was accessed between May 14 and May 27, 2018."
    item = segments(source)[0]
    client = Translator(Settings(context_guidance=guidance))
    requests = []

    async def complete(messages, **kwargs):
        request = json.loads(messages[1]["content"])
        requests.append(request)
        assert request["surrounding_source"] == source
        assert request["paragraph"] != source  # Mask and exact original coexist.
        assert ("paper_context" in request) == guidance
        if not guidance:
            assert "ABSTRACT_SENTINEL" not in json.dumps(messages)
        return (
            json.dumps(request["slots"]) if "slots" in request else request["paragraph"]
        )

    client.complete = complete
    try:
        if route == "slots":
            output = await client.translate_slots(item, "ABSTRACT_SENTINEL")
        else:
            output = await client.translate(
                item,
                "ABSTRACT_SENTINEL",
                feedback="Injected validation error" if route == "feedback" else "",
            )
        assert item.restore(output) == source
        assert len(requests) == 1
    finally:
        await client.close()


async def test_title_macro_from_compiled_context_sets_arxiv_name_and_is_translated(
    pipeline, translator
):
    manager, job, folder, settings, _ = pipeline
    source = folder / "source"
    (source / "main.tex").write_text(
        r"\documentclass{article}\input{title}\title{\mytitle}" + "\n"
        r"\begin{document}\maketitle\input{body}\end{document}",
        encoding="utf-8",
    )
    (source / "title.tex").write_text(
        r"\def\mytitle{A Controlled Academic Example}", encoding="utf-8"
    )
    job["kind"] = "arxiv"
    await manager.pipeline(job, settings)
    assert job["status"] == "completed"
    assert job["name"] == "A Controlled Academic Example"
    assert "A Controlled Academic Example" in translator.calls


async def test_provider_failure_from_dense_line_slots_propagates_immediately():
    from app.latex import segments

    item = segments("Text $x$ " * 30 + "\n")[0]
    client = Translator(Settings())
    requests = []

    async def translate(*args, **kwargs):
        return "Missing protected tokens"

    async def complete(messages, **kwargs):
        requests.append(messages)
        raise ProviderError("Injected line-repair outage")

    client.translate = translate
    client.complete = complete
    try:
        with pytest.raises(ProviderError, match="line-repair outage"):
            await client.translate_slots(item)
        assert len(requests) == 1
    finally:
        await client.close()


async def test_cancel_dense_line_slots_closes_pipeline_client(pipeline, monkeypatch):
    manager, job, folder, _, _ = pipeline
    (folder / "source/body.tex").write_text("Text $x$ " * 30 + "\n", encoding="utf-8")
    entered, hold = asyncio.Event(), asyncio.Event()
    instances = []

    class DenseRepairClient(Translator):
        def __init__(self, settings):
            super().__init__(settings)
            instances.append(self)

        async def translate(self, *args, **kwargs):
            return "Missing protected tokens"

        async def complete(self, messages, **kwargs):
            payload = json.loads(messages[1]["content"])
            assert "slots" in payload
            entered.set()
            await hold.wait()
            raise AssertionError("Cancelled line repair unexpectedly continued")

    monkeypatch.setattr(jobs, "Translator", DenseRepairClient)
    manager.start(job["id"])
    await entered.wait()
    await manager.cancel(job["id"])
    assert job["status"] == "cancelled" and len(instances) == 1
    assert instances[0].client.is_closed and not manager.slot.locked()


async def test_slot_requests_use_stable_global_ids_and_exact_source_anchors():
    from app.latex import segments

    source = "".join(f"Value $a_{index}$ is $b_{index}$. " for index in range(10))
    item = segments(source)[0]
    client = Translator(Settings(target_language="English"))
    requests = []

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        requests.append(payload)
        anchored = payload["paragraph_with_slots"]
        for key, value in payload["slots"].items():
            opening, closing = f"⟪S{int(key):04d}⟫", f"⟪/S{int(key):04d}⟫"
            assert anchored.count(opening) == anchored.count(closing) == 1
            assert anchored.split(opening, 1)[1].split(closing, 1)[0] == value
        return json.dumps(payload["slots"])

    client.complete = complete
    try:
        output = await client.translate_slots(item, allow_line_repair=False)
        assert item.restore(output) == source
        ids = [key for request in requests for key in request["slots"]]
        assert ids == [str(index) for index in range(20)]
        assert len({request["paragraph_with_slots"] for request in requests}) == 1
        assert (
            "⟪P0000⟫⟪S0001⟫ is ⟪/S0001⟫⟪P0001⟫" in requests[0]["paragraph_with_slots"]
        )
    finally:
        await client.close()


async def test_slot_context_anchors_cannot_leak_into_translation():
    from app.latex import segments

    client = Translator(Settings())
    item = segments("A short source paragraph.")[0]
    requests = []

    async def complete(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        requests.append(payload)
        key = next(iter(payload["slots"]))
        return json.dumps({key: "⟪S0000⟫不应输出定位标记⟪/S0000⟫"})

    client.complete = complete
    try:
        with pytest.raises(ValueError, match="包含保护标记"):
            await client.translate_slots(item)
        assert len(requests) == 2
    finally:
        await client.close()
