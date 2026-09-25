import asyncio

import httpx
import pytest

from app import arxiv_versions as versions


@pytest.fixture(autouse=True)
def isolated_lookup(monkeypatch):
    monkeypatch.setattr(versions, "_lookup_lock", asyncio.Lock())
    monkeypatch.setattr(versions, "_last_request", -10)


def mock_responses(monkeypatch, responses):
    calls = []
    client = httpx.AsyncClient

    def handle(request):
        calls.append(request)
        # Skip rate pacing in these deterministic HTTP contract tests.
        versions._last_request = -10
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(
        versions.httpx,
        "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(handle), **kw),
    )
    return calls


def atom(identifier="1706.03762v7"):
    return f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/{identifier}</id><title>Paper &amp; research</title></entry></feed>'


def page(identifier="1706.03762"):
    return f'<head><meta name="citation_arxiv_id" content="{identifier}"><meta name="citation_title" content="Paper"></head><body>[v999]<div class="submission-history"><a>[v1]</a><strong>[v7]</strong></div>[v888]</body>'


async def test_resolves_official_version_without_model_credentials(monkeypatch):
    calls = mock_responses(monkeypatch, [httpx.Response(200, text=atom())])
    result = await versions.resolve_arxiv_version("https://arxiv.org/abs/1706.03762")
    assert result == {
        "id": "1706.03762v7",
        "title": "Paper & research",
        "evidence": "arxiv",
    }
    assert calls[0].url.params["id_list"] == "1706.03762"
    assert "authorization" not in calls[0].headers


async def test_explicit_versions_are_never_upgraded_or_queried(monkeypatch):
    calls = mock_responses(monkeypatch, [])
    assert (await versions.resolve_arxiv_version("hep-th/9901001v2"))[
        "id"
    ] == "hep-th/9901001v2"
    assert calls == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, text="broken xml"),
        httpx.Response(200, text=atom("2401.12345v2")),
        httpx.Response(200, text=atom("1706.03762")),
        httpx.Response(302, headers={"Location": "https://example.com/"}),
        httpx.Response(200, content=b"x" * (256 * 1024 + 1)),
    ],
)
async def test_official_abstract_fallback_uses_only_matching_submission_history(
    monkeypatch, response
):
    calls = mock_responses(monkeypatch, [response, httpx.Response(200, text=page())])
    assert (await versions.resolve_arxiv_version("1706.03762"))["id"] == "1706.03762v7"
    assert len(calls) == 2
    assert str(calls[1].url) == "https://arxiv.org/abs/1706.03762"


async def test_mismatched_metadata_and_offline_fail_without_guessing(monkeypatch):
    mock_responses(
        monkeypatch, [httpx.Response(503), httpx.Response(200, text=page("2401.12345"))]
    )
    with pytest.raises(ValueError):
        await versions.resolve_arxiv_version("1706.03762")


async def test_invalid_url_never_leaves_the_machine(monkeypatch):
    calls = mock_responses(monkeypatch, [])
    with pytest.raises(ValueError):
        await versions.resolve_arxiv_version("https://example.com/private")
    assert calls == []


async def test_api_resolution_is_read_only_and_failures_are_actionable(monkeypatch):
    from app import main

    before = set(main.manager.jobs)

    async def resolve(identifier):
        if identifier == "2401.12345":
            raise httpx.ReadTimeout("private details")
        return {"id": "1706.03762v7", "title": "Paper", "evidence": "arxiv"}

    monkeypatch.setattr(main, "resolve_arxiv_version", resolve)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as client:
        success = await client.post(
            "/api/integrations/zotero/sources/resolve", json={"id": "1706.03762"}
        )
        failed = await client.post(
            "/api/integrations/zotero/sources/resolve", json={"id": "2401.12345"}
        )
        invalid = await client.post(
            "/api/integrations/zotero/sources/resolve", json={"id": "not-an-id"}
        )
    assert success.status_code == 200 and success.json()["id"] == "1706.03762v7"
    assert (
        failed.status_code == 503
        and failed.json()["code"] == "ARXIV_RESOLUTION_UNAVAILABLE"
    )
    assert "private details" not in failed.text
    assert invalid.status_code == 422
    assert set(main.manager.jobs) == before
