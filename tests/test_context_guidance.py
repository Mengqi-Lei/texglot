import json

import httpx
import pytest

from app.cli import Service, configure, parser, run, submit
from app.config import DATA, Settings
from app.latex import segments
from app.llm import Translator


async def test_disabled_guidance_sends_no_abstract_or_guidance_instructions():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "准确的译文。"}}]}
        )

    translator = Translator(Settings(context_guidance=False))
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        for feedback in ("", "A validation error"):
            await translator.translate(
                segments("A paragraph.")[0], "ABSTRACT_SENTINEL", feedback
            )
    finally:
        await translator.close()
    for request in requests:
        payload = json.loads(request["messages"][1]["content"])
        assert "paper_context" not in payload
        assert "paper_context" not in request["messages"][0]["content"]
        assert "ABSTRACT_SENTINEL" not in json.dumps(request)
        assert payload["paragraph"] == "A paragraph."


async def test_api_defaults_overrides_queue_snapshot_and_retry(tmp_path, monkeypatch):
    import app.config as config_module
    import app.jobs as jobs_module
    import app.main as main_module

    monkeypatch.setattr(config_module, "CONFIG", tmp_path / "settings.json")
    monkeypatch.setattr(jobs_module, "JOBS", tmp_path / "jobs")
    (tmp_path / "jobs").mkdir()
    manager = jobs_module.JobManager()
    monkeypatch.setattr(main_module, "manager", manager)
    starts = []
    monkeypatch.setattr(manager, "start", starts.append)
    assert Settings().context_guidance is True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main_module.app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/api/settings")).json()["context_guidance"] is True
        first = (
            await client.post("/api/jobs/arxiv", json={"url": "1706.03762"})
        ).json()
        assert first["context_guidance"] is True
        saved = await client.put("/api/settings", json={"context_guidance": False})
        assert saved.json()["context_guidance"] is False
        assert (await client.get("/api/settings")).json()["context_guidance"] is False
        default_off = (
            await client.post("/api/jobs/arxiv", json={"url": "1706.03762"})
        ).json()
        assert default_off["context_guidance"] is False
        forced_on = (
            await client.post(
                "/api/jobs/arxiv", json={"url": "1706.03762", "context_guidance": True}
            )
        ).json()
        assert forced_on["context_guidance"] is True
        uploaded = (
            await client.post(
                "/api/jobs/file",
                data={"context_guidance": "false"},
                files={"file": ("a.tex", b"source")},
            )
        ).json()
        assert uploaded["context_guidance"] is False
        example = (
            await client.post(
                "/api/jobs/example",
                json={"context_guidance": True, "language": "繁體中文"},
            )
        ).json()
        assert example["context_guidance"] is True
        assert example["kind"] == "arxiv"
        assert example["arxiv_id"] == "1706.03762v7"
        assert example["language"] == "繁體中文"
        assert example["name"] == "Attention Is All You Need"
        invalid = await client.post(
            "/api/jobs/arxiv", json={"url": "1706.03762", "context_guidance": "invalid"}
        )
        assert invalid.status_code == 422

        # A later change of the global default must not alter an already queued job.
        used = []

        async def capture(job, settings):
            used.append(settings.context_guidance)

        monkeypatch.setattr(manager, "pipeline", capture)
        await manager.run(first["id"])
        assert used == [True]
        legacy = manager.get(forced_on["id"])
        del legacy["context_guidance"]
        await manager.run(legacy["id"])
        assert used == [True, True]
        current = manager.get(first["id"])
        current["status"] = "failed"
        retry = await client.post(f"/api/jobs/{first['id']}/retry", json={})
        assert retry.json()["context_guidance"] is True
        retry = await client.post(
            f"/api/jobs/{first['id']}/retry", json={"context_guidance": False}
        )
        assert retry.json()["context_guidance"] is False
        assert (await client.get("/api/settings")).json()["context_guidance"] is False
        current["status"] = "translating"
        before = len(starts)
        blocked = await client.post(
            f"/api/jobs/{first['id']}/retry", json={"context_guidance": True}
        )
        assert blocked.status_code == 409 and current["context_guidance"] is False
        assert len(starts) == before


def test_cli_flags_and_configure_only_save_the_requested_preference():
    assert parser().parse_args([]).context_guidance is None
    assert parser().parse_args(["--context-guidance"]).context_guidance is True
    args = parser().parse_args(["--configure", "--no-context-guidance"])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"context_guidance": False})

    service = Service(transport=httpx.MockTransport(handler))
    try:
        assert configure(service, args)["context_guidance"] is False
        assert len(requests) == 1
        assert requests[0].method == "PUT"
        assert json.loads(requests[0].content) == {"context_guidance": False}
    finally:
        service.client.close()


def test_cli_transmits_boolean_off_in_json_and_multipart(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(202, json={"id": "test"})

    source = tmp_path / "paper.tex"
    source.write_text("source", encoding="utf-8")
    service = Service(transport=httpx.MockTransport(handler))
    try:
        submit(service, "1706.03762", "简体中文", context_guidance=False)
        submit(service, str(source), "简体中文", context_guidance=False)
        assert json.loads(requests[0].content)["context_guidance"] is False
        assert b'name="context_guidance"\r\n\r\nfalse' in requests[1].content
    finally:
        service.client.close()


@pytest.mark.parametrize(
    "flags,expected",
    [([], False), (["--context-guidance"], True), (["--no-context-guidance"], False)],
)
def test_cli_batch_inherits_default_or_uses_one_run_override(
    tmp_path, flags, expected, capsys
):
    submitted = []

    def handler(request):
        path = request.url.path
        if path == "/api/health":
            return httpx.Response(
                200, json={"ok": True, "name": "TeXGlot", "data_dir": str(DATA)}
            )
        if path == "/api/settings":
            assert request.method == "GET"
            return httpx.Response(
                200, json={"target_language": "简体中文", "context_guidance": False}
            )
        if path == "/api/jobs/arxiv":
            data = json.loads(request.content)
            submitted.append(data)
            return httpx.Response(
                202,
                json={
                    "id": str(len(submitted)),
                    "name": "paper",
                    "status": "completed",
                    "pages": 1,
                    "tokens": 0,
                    "artifacts": {},
                    "context_guidance": data["context_guidance"],
                },
            )
        raise AssertionError(path)

    service = Service(transport=httpx.MockTransport(handler))
    try:
        args = parser().parse_args(
            ["1706.03762", "2503.06072", "--json", "-o", str(tmp_path), *flags]
        )
        assert run(args, service) == 0
        assert [p["context_guidance"] for p in submitted] == [expected, expected]
        assert [
            r["context_guidance"]
            for r in json.loads(capsys.readouterr().out)["results"]
        ] == [expected, expected]
    finally:
        service.client.close()


@pytest.mark.parametrize(
    "status,initial,flag,retries,code",
    [
        ("failed", True, None, [{}], 0),
        ("failed", True, "--no-context-guidance", [{"context_guidance": False}], 0),
        ("completed", True, "--no-context-guidance", [{"context_guidance": False}], 0),
        ("completed", False, "--no-context-guidance", [], 0),
        ("translating", True, "--no-context-guidance", [], 1),
    ],
)
def test_cli_resume_preserves_or_explicitly_changes_task_mode(
    tmp_path, status, initial, flag, retries, code, capsys
):
    retried = []
    current = {
        "id": "old",
        "name": "paper",
        "status": status,
        "pages": 1,
        "tokens": 0,
        "artifacts": {},
        "context_guidance": initial,
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
        else:
            assert request.url.path == "/api/jobs/old"
        return httpx.Response(200, json=current)

    service = Service(transport=httpx.MockTransport(handler))
    try:
        args = parser().parse_args(
            [
                "--resume",
                "old",
                "--json",
                "-o",
                str(tmp_path),
                *([flag] if flag else []),
            ]
        )
        assert run(args, service) == code
        assert retried == retries
    finally:
        service.client.close()
