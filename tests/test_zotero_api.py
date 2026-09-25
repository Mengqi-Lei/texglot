import asyncio
import base64
import hashlib
import importlib
import json

import httpx
import pytest
from pypdf import PdfWriter


def _manager(tmp_path, monkeypatch):
    config = importlib.import_module("app.config")
    jobs = importlib.import_module("app.jobs")
    main = importlib.import_module("app.main")

    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    monkeypatch.setattr(jobs, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(main, "JOBS", tmp_path / "jobs")
    (tmp_path / "jobs").mkdir()
    manager = jobs.JobManager()
    starts = []
    monkeypatch.setattr(manager, "start", starts.append)
    monkeypatch.setattr(main, "manager", manager)
    return manager, starts


async def _client():
    from app.main import app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


async def test_zotero_health_and_capabilities_are_explicit(monkeypatch, tmp_path):
    _manager(tmp_path, monkeypatch)
    async with await _client() as client:
        health = await client.get("/api/integrations/zotero/health")
        capabilities = await client.get("/api/integrations/zotero/capabilities")
    assert health.status_code == 200
    payload = health.json()
    assert payload["ok"] is True
    assert payload["name"] == "TeXGlot"
    assert payload["integration_api"] == "zotero.v1"
    assert payload["capabilities"]["arxiv_latex"] is True
    assert payload["capabilities"]["reader_deep_link"] is True
    assert payload["capabilities"]["library_reuse"] is True
    assert capabilities.json()["capabilities"]["pdf_reflow"] is False


async def test_zotero_arxiv_requires_version_and_replays_idempotently(
    monkeypatch, tmp_path
):
    manager, starts = _manager(tmp_path, monkeypatch)
    body = {
        "source": {"type": "arxiv", "id": "2401.12345v2"},
        "target_language": "简体中文",
        "context_guidance": False,
        "client": {"name": "zotero", "item_key": "ABCD1234"},
    }
    async with await _client() as client:
        missing_version = await client.post(
            "/api/integrations/zotero/jobs",
            json={"source": {"type": "arxiv", "id": "2401.12345"}},
        )
        first = await client.post(
            "/api/integrations/zotero/jobs",
            headers={"Idempotency-Key": "zotero-request-1"},
            json=body,
        )
        replay = await client.post(
            "/api/integrations/zotero/jobs",
            headers={"Idempotency-Key": "zotero-request-1"},
            json=body,
        )
        conflict = await client.post(
            "/api/integrations/zotero/jobs",
            headers={"Idempotency-Key": "zotero-request-1"},
            json={
                **body,
                "source": {"type": "arxiv", "id": "2401.12345v3"},
            },
        )
    assert missing_version.status_code == 409
    assert missing_version.json()["code"] == "ARXIV_VERSION_REQUIRED"
    assert first.status_code == 202
    assert replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert first.json()["source"] == {"type": "arxiv", "id": "2401.12345v2"}
    assert first.json()["context_guidance"] is False
    assert starts == [first.json()["id"]]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    record = manager.get(first.json()["id"])
    assert record["integration"]["idempotency_key"] == "zotero-request-1"
    assert record["integration"]["client"]["item_key"] == "ABCD1234"
    # A fresh manager reads the persisted integration metadata and still
    # deduplicates a replay after a service restart.
    import app.main as main

    restarted = type(manager)()
    monkeypatch.setattr(main, "manager", restarted)
    async with await _client() as client:
        after_restart = await client.post(
            "/api/integrations/zotero/jobs",
            headers={"Idempotency-Key": "zotero-request-1"},
            json=body,
        )
    assert after_restart.status_code == 200
    assert after_restart.json()["id"] == first.json()["id"]


async def test_zotero_latex_upload_is_bounded_and_deduplicated(monkeypatch, tmp_path):
    manager, starts = _manager(tmp_path, monkeypatch)
    blob = b"\\documentclass{article}\\begin{document}Hello\\end{document}"
    body = {
        "source": {
            "type": "latex",
            "filename": "paper.tex",
            "content_base64": base64.b64encode(blob).decode(),
            "main": "paper.tex",
        },
        "import": {"translated_pdf": True, "translated_source": False},
    }
    async with await _client() as client:
        first = await client.post("/api/integrations/zotero/jobs", json=body)
        replay = await client.post("/api/integrations/zotero/jobs", json=body)
        unsupported = await client.post(
            "/api/integrations/zotero/jobs",
            json={"source": {"type": "pdf", "id": "ignored"}},
        )
        malformed = await client.post(
            "/api/integrations/zotero/jobs",
            json={
                "source": {
                    "type": "latex",
                    "filename": "paper.tex",
                    "content_base64": "not-base64",
                }
            },
        )
    assert first.status_code == 202
    assert replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert starts == [first.json()["id"]]
    job = manager.get(first.json()["id"])
    assert (tmp_path / "jobs" / job["id"] / "upload.bin").read_bytes() == blob
    assert job["main"] == ""
    assert job["integration"]["source"]["sha256"] == hashlib.sha256(blob).hexdigest()
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "SOURCE_NOT_SUPPORTED"
    assert malformed.status_code == 400
    assert malformed.json()["code"] == "SOURCE_NOT_SUPPORTED"


async def test_zotero_status_maps_partial_error_and_retry_cancel(monkeypatch, tmp_path):
    manager, starts = _manager(tmp_path, monkeypatch)
    body = {
        "source": {"type": "arxiv", "id": "1706.03762v7"},
        "idempotency_key": "status-check",
    }
    async with await _client() as client:
        created = await client.post("/api/integrations/zotero/jobs", json=body)
        job_id = created.json()["id"]
        job = manager.get(job_id)
        job.update(
            status="partial",
            progress=100,
            done=4,
            total=4,
            warnings=["one paragraph"],
            artifacts={"original": "original.pdf", "translated": "translated.pdf"},
        )
        partial = await client.get(f"/api/integrations/zotero/jobs/{job_id}")
        assert partial.json()["status"] == "completed_with_warnings"
        assert partial.json()["quality"] == "completed_with_warnings"
        assert partial.json()["artifacts"] == {
            "translated_pdf": True,
            "translated_source": False,
            "original_pdf": True,
        }
        job.update(status="failed", error="LaTeX 编译失败: private/path/main.tex")
        failed = await client.get(f"/api/integrations/zotero/jobs/{job_id}")
        assert failed.json()["error"] == {
            "code": "COMPILATION_ERROR",
            "message": "LaTeX 编译失败，请在 TeXGlot 中查看处理记录",
        }
        assert "private/path" not in failed.text
        retried = await client.post(f"/api/integrations/zotero/jobs/{job_id}/retry")
        job["status"] = "queued"
        assert retried.status_code == 200
        await client.post(f"/api/integrations/zotero/jobs/{job_id}/cancel")
        missing = await client.get("/api/integrations/zotero/jobs/no-such-task")
    assert starts.count(job_id) == 2
    assert missing.status_code == 404
    assert missing.json()["code"] == "TASK_NOT_FOUND"


async def test_zotero_artifact_contract_rejects_unknown_kind(monkeypatch, tmp_path):
    _manager(tmp_path, monkeypatch)
    async with await _client() as client:
        response = await client.get(
            "/api/integrations/zotero/jobs/unknown/artifacts/reader"
        )
    assert response.status_code == 404
    assert response.json()["code"] == "ARTIFACT_NOT_READY"


@pytest.mark.parametrize("header,body", [("same", "different"), ("", "bad\nkey")])
async def test_zotero_idempotency_header_mismatch_is_rejected(
    monkeypatch, tmp_path, header, body
):
    _manager(tmp_path, monkeypatch)
    request = {"source": {"type": "arxiv", "id": "2401.12345v2"}}
    if body:
        request["idempotency_key"] = body
    headers = {"Idempotency-Key": header} if header else None
    async with await _client() as client:
        response = await client.post(
            "/api/integrations/zotero/jobs", headers=headers, json=request
        )
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IDEMPOTENCY_KEY"


ARXIV_REQUEST = {
    "source": {"type": "arxiv", "id": "2401.12345v2"},
    "target_language": "简体中文",
}
ZOTERO_JOBS = "/api/integrations/zotero/jobs"


def _library_job(manager, tmp_path, **kwargs):
    job = manager.create("arxiv", "Test paper", arxiv_id="2401.12345v2")
    folder = tmp_path / "jobs" / job["id"]
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.write(folder / "translated.pdf")
    job.update(status="completed", artifacts={"translated": "translated.pdf"}, **kwargs)
    manager.persist(job)
    return job


async def test_zotero_reuses_app_or_cli_pdf_without_model_call(monkeypatch, tmp_path):
    manager, starts = _manager(tmp_path, monkeypatch)
    job = _library_job(manager, tmp_path, config={"model": "previous-model"})
    job["context_guidance"] = False
    # Reading/annotation state and the existing task metadata must be untouched.
    folder = tmp_path / "jobs" / job["id"]
    reader = folder / "reader.json"
    reader.write_text('{"revision": 3, "annotations": ["keep"]}')
    before = json.dumps(job, sort_keys=True)
    starts.clear()
    async with await _client() as client:
        response = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
        downloaded = await client.get(f"{ZOTERO_JOBS}/{job['id']}/artifacts/translated")
    assert response.status_code == 200
    assert response.json()["id"] == job["id"]
    assert response.json()["reuse"] == "library"
    assert downloaded.status_code == 200
    assert downloaded.content == (folder / "translated.pdf").read_bytes()
    assert not starts
    assert len(manager.jobs) == 1
    assert json.dumps(job, sort_keys=True) == before
    assert reader.read_text() == '{"revision": 3, "annotations": ["keep"]}'


@pytest.mark.parametrize(
    "different",
    [
        {"arxiv_id": "2401.12345v1"},
        {"arxiv_id": "2401.12345"},
        {"arxiv_id": "2401.99999v2"},
        {"language": "English"},
        {"language": "繁體中文"},
        {"kind": "file"},
    ],
)
async def test_library_reuse_requires_exact_source_and_language(
    monkeypatch, tmp_path, different
):
    manager, starts = _manager(tmp_path, monkeypatch)
    old = _library_job(manager, tmp_path)
    old.update(different)
    starts.clear()
    async with await _client() as client:
        response = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
    assert response.status_code == 202
    assert response.json()["id"] != old["id"]
    assert starts == [response.json()["id"]]


@pytest.mark.parametrize(
    "damage", ["missing", "truncated", "empty", "encrypted", "outside", "symlink"]
)
async def test_library_reuse_rejects_unusable_pdfs(monkeypatch, tmp_path, damage):
    manager, starts = _manager(tmp_path, monkeypatch)
    old = _library_job(manager, tmp_path)
    path = tmp_path / "jobs" / old["id"] / "translated.pdf"
    if damage == "missing":
        path.unlink()
    elif damage == "truncated":
        path.write_bytes(b"%PDF-1.7\nThis is not a PDF")
    elif damage == "empty":
        PdfWriter().write(path)
    elif damage == "encrypted":
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.encrypt("secret")
        writer.write(path)
    else:
        outside = tmp_path / "outside.pdf"
        path.rename(outside)
        if damage == "outside":
            old["artifacts"]["translated"] = str(outside)
        else:
            path.symlink_to(outside)
    starts.clear()
    async with await _client() as client:
        response = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
    assert response.status_code == 202
    assert response.json()["id"] != old["id"]
    assert starts == [response.json()["id"]]


async def test_reuse_prefers_valid_completed_and_preserves_partial(
    monkeypatch, tmp_path
):
    manager, starts = _manager(tmp_path, monkeypatch)
    complete = _library_job(manager, tmp_path)
    partial = _library_job(manager, tmp_path)
    partial.update(
        status="partial", warnings=["one untranslated segment"], done=3, total=3
    )
    active = manager.create("arxiv", "active", arxiv_id="2401.12345v2")
    starts.clear()
    async with await _client() as client:
        preferred = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
        assert preferred.json()["id"] == complete["id"]
        # Invalidating a previously validated PDF must invalidate the cached check.
        path = tmp_path / "jobs" / complete["id"] / "translated.pdf"
        path.write_bytes(b"broken")
        fallback = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
        assert fallback.json()["id"] == partial["id"]
        assert fallback.json()["status"] == "completed_with_warnings"
        assert fallback.json()["quality"] == "completed_with_warnings"
        (tmp_path / "jobs" / partial["id"] / "translated.pdf").unlink()
        following = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
        assert following.json()["id"] == active["id"]
        assert following.json()["reuse"] == "active"
    assert not starts


async def test_reuse_skips_newer_broken_result(monkeypatch, tmp_path):
    manager, starts = _manager(tmp_path, monkeypatch)
    valid = _library_job(manager, tmp_path)
    newer = _library_job(manager, tmp_path)
    (tmp_path / "jobs" / newer["id"] / "translated.pdf").unlink()
    starts.clear()
    async with await _client() as client:
        response = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
    assert response.json()["id"] == valid["id"]
    assert not starts


async def test_reuse_prefers_clean_result_over_newer_completed_with_warnings(
    monkeypatch, tmp_path
):
    manager, starts = _manager(tmp_path, monkeypatch)
    clean = _library_job(manager, tmp_path)
    _library_job(manager, tmp_path, warnings=["requires review"])
    starts.clear()
    async with await _client() as client:
        response = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
    assert response.json()["id"] == clean["id"]
    assert response.json()["quality"] == "completed"
    assert not starts


@pytest.mark.parametrize(
    "status", ["failed", "cancelled", "interrupted", "needs_selection"]
)
async def test_new_menu_action_does_not_replay_failed_implicit_request(
    monkeypatch, tmp_path, status
):
    manager, starts = _manager(tmp_path, monkeypatch)
    async with await _client() as client:
        first = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
        manager.get(first.json()["id"])["status"] = status
        second = await client.post(ZOTERO_JOBS, json=ARXIV_REQUEST)
    assert second.status_code == 202
    assert first.json()["id"] != second.json()["id"]
    assert len(starts) == 2


async def test_explicit_retranslation_and_its_replay(monkeypatch, tmp_path):
    manager, starts = _manager(tmp_path, monkeypatch)
    old = _library_job(manager, tmp_path)
    body = {
        **ARXIV_REQUEST,
        "reuse_existing": False,
        "idempotency_key": "deliberate-new-translation",
    }
    starts.clear()
    async with await _client() as client:
        new = await client.post(ZOTERO_JOBS, json=body)
        replay = await client.post(ZOTERO_JOBS, json=body)
    assert new.status_code == 202
    assert new.json()["id"] != old["id"]
    assert replay.status_code == 200
    assert replay.json()["id"] == new.json()["id"]
    assert replay.json()["reuse"] == "replay"
    assert starts == [new.json()["id"]]
    assert old["status"] == "completed"


async def test_explicit_request_binding_survives_reusing_an_app_job(
    monkeypatch, tmp_path
):
    manager, starts = _manager(tmp_path, monkeypatch)
    job = _library_job(manager, tmp_path)
    timestamp = job["updated_at"]
    body = {**ARXIV_REQUEST, "idempotency_key": "request-bound-to-app-job"}
    starts.clear()
    async with await _client() as client:
        reused = await client.post(ZOTERO_JOBS, json=body)
    assert reused.json()["id"] == job["id"]
    assert job["updated_at"] == timestamp
    restarted = type(manager)()
    monkeypatch.setattr(importlib.import_module("app.main"), "manager", restarted)
    async with await _client() as client:
        replay = await client.post(ZOTERO_JOBS, json=body)
        conflict = await client.post(
            ZOTERO_JOBS, json={**body, "target_language": "English"}
        )
    assert replay.json()["id"] == job["id"]
    assert replay.json()["reuse"] == "replay"
    assert conflict.status_code == 409
    assert not starts


async def test_concurrent_default_requests_create_only_one_job(monkeypatch, tmp_path):
    manager, starts = _manager(tmp_path, monkeypatch)
    async with await _client() as client:
        responses = await asyncio.gather(
            *[client.post(ZOTERO_JOBS, json=ARXIV_REQUEST) for _ in range(20)]
        )
    assert sum(response.status_code == 202 for response in responses) == 1
    assert {response.json()["id"] for response in responses} == set(starts)
    assert len(manager.jobs) == len(starts) == 1


@pytest.mark.parametrize("legacy", [False, True])
async def test_upload_reuse_is_content_based_and_main_specific(
    monkeypatch, tmp_path, legacy
):
    manager, starts = _manager(tmp_path, monkeypatch)
    blob = b"archive-content"
    old = manager.create("file", "first-name.zip", blob=blob, main="a.tex")
    old.update(status="compiling", main="a.tex")
    if legacy:
        del old["upload_sha256"], old["requested_main"]
    body = {
        "source": {
            "type": "latex",
            "filename": "renamed.zip",
            "content_base64": base64.b64encode(blob).decode(),
            "main": "a.tex",
        }
    }
    starts.clear()
    async with await _client() as client:
        same = await client.post(ZOTERO_JOBS, json=body)
        other_main = await client.post(
            ZOTERO_JOBS, json={"source": {**body["source"], "main": "b.tex"}}
        )
        other_content = await client.post(
            ZOTERO_JOBS,
            json={
                "source": {
                    **body["source"],
                    "content_base64": base64.b64encode(b"changed").decode(),
                }
            },
        )
    assert same.json()["id"] == old["id"]
    assert same.json()["reuse"] == "active"
    assert other_main.status_code == other_content.status_code == 202
    assert other_main.json()["id"] != other_content.json()["id"]
    assert len(starts) == 2


async def test_auto_main_upload_identity_survives_preparation(monkeypatch, tmp_path):
    manager, starts = _manager(tmp_path, monkeypatch)
    blob = b"archive-content"
    old = manager.create("file", "source.zip", blob=blob)
    old.update(status="compiling", main="nested/main.tex")
    body = {
        "source": {
            "type": "latex",
            "filename": "source.zip",
            "content_base64": base64.b64encode(blob).decode(),
        }
    }
    starts.clear()
    async with await _client() as client:
        response = await client.post(ZOTERO_JOBS, json=body)
    assert response.json()["id"] == old["id"]
    assert not starts
