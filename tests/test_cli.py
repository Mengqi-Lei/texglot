import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import app.cli as cli
from app.cli import CLIError, Service, batch_sources, parser, run, submit
from app.config import DATA


def job(job_id="abc123", **values):
    return dict(
        id=job_id,
        name="paper.tex",
        kind="file",
        arxiv_id="",
        status="completed",
        progress=100,
        message="Done",
        pages=1,
        tokens=12,
        artifacts={"translated": "translated.pdf"},
        **values,
    )


def test_batch_resolves_relative_sources_and_keeps_urls(tmp_path, monkeypatch):
    (tmp_path / "paper with spaces.tex").write_text("source", encoding="utf-8")
    listing = tmp_path / "papers.txt"
    listing.write_text(
        "\ufeff# Notes\n\npaper with spaces.tex\nhttps://arxiv.org/abs/1706.03762\n1706.03762\n",
        encoding="utf8",
    )
    monkeypatch.chdir(tmp_path.parent)
    assert batch_sources(["first.tex"], [str(listing)]) == [
        "first.tex",
        str(tmp_path / "paper with spaces.tex"),
        "https://arxiv.org/abs/1706.03762",
        "1706.03762",
    ]


def test_submission_keeps_translation_language_and_uploads_bytes(tmp_path):
    file = tmp_path / "paper.tex"
    file.write_text("\\documentclass{article}", encoding="utf-8")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(202, json=job())

    service = Service(transport=httpx.MockTransport(handler))
    try:
        submit(service, str(file), "繁體中文", "paper.tex")
        assert b"\\documentclass{article}" in requests[0].content
        assert "繁體中文".encode() in requests[0].content
        submit(service, "1706.03762", "English")
        assert json.loads(requests[1].content) == {
            "url": "1706.03762",
            "language": "English",
        }
        assert "Authorization" not in requests[1].headers
    finally:
        service.client.close()


def test_export_never_overwrites_and_removes_incomplete_download(tmp_path):
    service = Service(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"%PDF-test")
        )
    )
    try:
        first = service.export(job(), tmp_path)
        Path(first["translated"]).write_bytes(b"User annotation")
        second = service.export(job(), tmp_path)
        assert first != second
        assert Path(first["translated"]).read_bytes() == b"User annotation"
        assert Path(second["translated"]).read_bytes() == b"%PDF-test"
    finally:
        service.client.close()


@pytest.mark.parametrize("fail_fast,expected", [(False, 3), (True, 1)])
def test_batch_failure_exit_and_manifest(tmp_path, capsys, fail_fast, expected):
    created = []

    def handler(request):
        if request.url.path == "/api/health":
            return httpx.Response(
                200, json={"ok": True, "name": "TeXGlot", "data_dir": str(DATA)}
            )
        if request.url.path == "/api/settings":
            return httpx.Response(200, json={"target_language": "简体中文"})
        if request.url.path == "/api/jobs/arxiv":
            source = json.loads(request.content)["url"]
            created.append(source)
            if source == "bad":
                return httpx.Response(400, json={"detail": "Invalid ID"})
            return httpx.Response(202, json=job(source))
        return httpx.Response(200, content=b"%PDF-test")

    args = parser().parse_args(
        ["bad", "1706.03762", "2503.06072", "--json", "-o", str(tmp_path)]
        + (["--fail-fast"] if fail_fast else [])
    )
    service = Service(transport=httpx.MockTransport(handler))
    try:
        assert run(args, service) == 1
        report = json.loads(capsys.readouterr().out)
        assert len(report["results"]) == expected
        assert report["remaining"] == 3 - expected
        assert report["results"][0]["status"] == "failed"
        assert Path(report["manifest"]).is_file()
        assert created == ["bad", "1706.03762", "2503.06072"][:expected]
    finally:
        service.client.close()


def test_service_rejects_another_data_directory():
    service = Service(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"ok": True, "name": "TeXGlot", "data_dir": str(DATA / "other")},
            )
        )
    )
    try:
        with pytest.raises(CLIError, match="different TeXGlot data directory"):
            service.health()
    finally:
        service.client.close()


@pytest.fixture
def startup_clock(tmp_path, monkeypatch):
    state = SimpleNamespace(now=0.0, spawns=[], sleeps=[], exit_code=None)

    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds

    def spawn(*args, **kwargs):
        state.spawns.append((args, kwargs))
        return SimpleNamespace(poll=lambda: state.exit_code)

    monkeypatch.setattr(cli, "DATA", tmp_path)
    monkeypatch.setattr(
        cli, "time", SimpleNamespace(monotonic=lambda: state.now, sleep=sleep)
    )
    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    return state


def test_own_service_startup_retries_temporary_health_timeout(startup_clock, tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("No listener", request=request)
        if len(calls) < 4:
            startup_clock.now += request.extensions["timeout"]["read"]
            raise httpx.ReadTimeout("Bound but still initializing", request=request)
        return httpx.Response(
            200, json={"ok": True, "name": "TeXGlot", "data_dir": str(tmp_path)}
        )

    service = Service(transport=httpx.MockTransport(handler))
    try:
        service.ensure()
        assert len(calls) == 4 and len(startup_clock.spawns) == 1
        assert 4 <= startup_clock.now < 15
    finally:
        service.client.close()


def test_own_service_health_timeouts_share_one_startup_deadline(startup_clock):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("No listener", request=request)
        timeout = request.extensions["timeout"]["read"]
        assert 0 < timeout <= min(2, 60 - startup_clock.now)
        startup_clock.now += timeout
        raise httpx.ReadTimeout("Still initializing", request=request)

    service = Service(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CLIError, match="Could not start TeXGlot"):
            service.ensure()
        assert startup_clock.now == pytest.approx(60)
        assert len(startup_clock.spawns) == 1
        assert len(calls) < 35
    finally:
        service.client.close()


def test_own_service_ready_after_fifteen_seconds_still_succeeds(
    startup_clock, tmp_path
):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("No listener", request=request)
        if len(calls) < 11:
            startup_clock.now += request.extensions["timeout"]["read"]
            raise httpx.ReadTimeout("Cold startup during heavy I/O", request=request)
        return httpx.Response(
            200, json={"ok": True, "name": "TeXGlot", "data_dir": str(tmp_path)}
        )

    service = Service(transport=httpx.MockTransport(handler))
    try:
        service.ensure()
        assert len(calls) == 11 and len(startup_clock.spawns) == 1
        assert 18 < startup_clock.now < 21
    finally:
        service.client.close()


def test_exited_own_service_still_fails_quickly(startup_clock):
    startup_clock.exit_code = 1
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("No listener after process exit", request=request)

    service = Service(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CLIError, match="Could not start TeXGlot"):
            service.ensure()
        assert len(calls) == 3 and len(startup_clock.spawns) == 1
        assert startup_clock.now == pytest.approx(0.3)
    finally:
        service.client.close()


def test_existing_unresponsive_port_is_not_treated_as_our_startup(startup_clock):
    def handler(request):
        raise httpx.ReadTimeout("Existing listener is unresponsive", request=request)

    service = Service(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CLIError, match="Local service is not responding"):
            service.ensure()
        assert not startup_clock.spawns and not startup_clock.sleeps
    finally:
        service.client.close()


@pytest.mark.parametrize("during_startup", [False, True])
@pytest.mark.parametrize("response", [[], {"ok": True, "name": "OtherApp"}, "html"])
def test_incompatible_port_is_rejected_even_during_startup(
    startup_clock, during_startup, response
):
    calls = []

    def handler(request):
        calls.append(request)
        if during_startup and len(calls) == 1:
            raise httpx.ConnectError("No listener", request=request)
        if response == "html":
            return httpx.Response(200, text="<html>Not TeXGlot</html>")
        return httpx.Response(200, json=response)

    service = Service(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(CLIError, match="Port is used by another application"):
            service.ensure()
        assert len(startup_clock.spawns) == int(during_startup)
        assert not startup_clock.sleeps
    finally:
        service.client.close()


def test_interrupt_stops_only_current_task_and_records_recovery(
    tmp_path, capsys, monkeypatch
):
    calls = []
    current = job()
    current["status"] = "translating"

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/health":
            return httpx.Response(
                200, json={"ok": True, "name": "TeXGlot", "data_dir": str(DATA)}
            )
        return httpx.Response(200, json=current)

    service = Service(transport=httpx.MockTransport(handler))

    def stop(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(service, "wait", stop)
    args = parser().parse_args(
        ["--resume", "abc123", "--json", "-o", str(tmp_path), "--language", "zh"]
    )
    try:
        assert run(args, service) == 130
        assert calls.count("/api/jobs/abc123/cancel") == 1
        result = json.loads(capsys.readouterr().out)
        assert result["results"][0]["id"] == "abc123"
    finally:
        service.client.close()
