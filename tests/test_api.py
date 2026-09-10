import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.llm import ProviderError, Translator


async def test_slot_repair_preserves_latex_and_rejects_missing_or_injected_slots():
    from app.latex import MARKER, segments

    item = segments(r"Our \textbf{small} model uses 175 billion parameters.")[0]
    translator = Translator(Settings(context_guidance=False))
    mode = "valid"

    async def complete(messages, **kwargs):
        content = json.loads(messages[1]["content"])
        assert "paper_context" not in content
        slots = content["slots"]
        result = {
            key: value.replace("Our", "我们的")
            .replace("small", "小型")
            .replace("model uses", "模型使用")
            .replace("parameters", "个参数")
            for key, value in slots.items()
        }
        if mode == "missing":
            result.pop(next(iter(result)))
        elif mode == "injected":
            result[next(iter(result))] = "⟪P9999⟫"
        return json.dumps(result)

    translator.complete = complete
    try:
        output = await translator.translate_slots(item, "ignored abstract")
        assert MARKER.findall(output) == MARKER.findall(item.masked)
        assert r"\textbf{小型}" in item.restore(output)
        assert "175 billion" in item.restore(output)
        for mode in ("missing", "injected"):
            with pytest.raises(ValueError):
                await translator.translate_slots(item)
    finally:
        await translator.close()


async def test_provider_retry_and_usage(monkeypatch):
    original_sleep = asyncio.sleep

    async def fast_sleep(_):
        await original_sleep(0)

    monkeypatch.setattr("app.llm.asyncio.sleep", fast_sleep)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "译文"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 17},
            },
        )

    translator = Translator(Settings(api_key="not-a-real-key"))
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert (
            await translator.complete([{"role": "user", "content": "test"}]) == "译文"
        )
        assert translator.tokens == 17 and len(calls) == 2
        assert calls[-1].url.path == "/chat/completions"
    finally:
        await translator.close()


async def test_auth_error_is_actionable_and_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": "a sensitive provider response"})

    translator = Translator(Settings())
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="认证失败"):
            await translator.complete([])
        assert len(calls) == 1
    finally:
        await translator.close()


async def test_api_hides_credentials_and_blocks_cross_origin():
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/settings")
        assert response.status_code == 200
        assert "api_key" not in response.json()
        response = await client.put(
            "/api/settings",
            headers={"Origin": "https://evil.test"},
            json={"model": "untrusted"},
        )
        assert response.status_code == 403
        assert (
            await client.get("/api/jobs/missing/artifacts/source")
        ).status_code == 404


async def test_failed_retry_downloads_latest_log_including_dependency_discovery(
    tmp_path, monkeypatch
):
    import os
    from types import SimpleNamespace

    import app.main as main

    monkeypatch.setattr(main, "JOBS", tmp_path)
    monkeypatch.setattr(
        main,
        "manager",
        SimpleNamespace(
            get=lambda _: {"id": "paper", "name": "paper", "artifacts": {}}
        ),
    )
    for index, phase in enumerate(
        ("build-translated", "build-probe", "build-original", "build-dependencies"), 1
    ):
        log = tmp_path / "paper" / phase / "compile.log"
        log.parent.mkdir(parents=True)
        log.write_text(phase)
        os.utime(log, (1000 + index, 1000 + index))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/jobs/paper/artifacts/log")
        assert response.status_code == 200
        assert response.text == "build-dependencies"
        latest = tmp_path / "paper/build-translated/compile.log"
        os.utime(latest, (2000, 2000))
        response = await client.get("/api/jobs/paper/artifacts/log")
        assert response.text == "build-translated"


def test_macos_compiler_isolation(tmp_path):
    import subprocess
    import sys

    from app.compiler import sandbox_command

    if sys.platform != "darwin":
        pytest.skip("macOS sandbox verification")
    # Create the sentinel under home, outside both allowed job paths and system temp.
    from app.config import DATA

    sentinel = DATA / "isolation-test-sentinel.txt"
    sentinel.write_text("TEXGLOT_PRIVATE_SENTINEL", encoding="utf-8")
    try:
        cmd = sandbox_command(
            ["/bin/cat", str(sentinel)], tmp_path / "source", tmp_path / "out"
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0
        assert "TEXGLOT_PRIVATE_SENTINEL" not in result.stdout
    finally:
        sentinel.unlink()
