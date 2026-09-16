"""Public title lookup is bounded, optional, and tied to the requested paper."""

import asyncio

import httpx
import pytest

from app import sources


def metadata_html(title=r"VGGT-$\omega$", identifier="2512.12345"):
    return (
        '<html><head><meta name="citation_title" content="' + title + '">'
        '<meta name="citation_arxiv_id" content="' + identifier + '">'
        "</head><body>Paper</body></html>"
    )


def mock_metadata(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        sources.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


async def test_official_title_retains_math_entities_and_the_full_long_title(
    monkeypatch,
):
    title = r"VGGT-$\omega$ &amp; Geometry: " + "A long paper title " * 30
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, text=metadata_html(title))

    mock_metadata(monkeypatch, handle)
    actual = await sources.fetch_arxiv_title("2512.12345v2")
    assert actual == title.replace("&amp;", "&").strip()
    assert len(actual) > 200
    assert str(calls[0].url) == "https://arxiv.org/abs/2512.12345v2"
    assert "authorization" not in calls[0].headers


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text=metadata_html(identifier="2512.54321")),
        httpx.Response(200, text=metadata_html(identifier="2512.12345v3")),
        httpx.Response(200, text=metadata_html(identifier="not-an-id")),
        httpx.Response(
            200, text="<html><head><title>Unavailable</title></head></html>"
        ),
        httpx.Response(
            200,
            text='<head><meta name="citation_title" content="One"><meta name="citation_title" content="Two"><meta name="citation_arxiv_id" content="2512.12345"></head>',
        ),
        httpx.Response(200, content=b"<head>" + b"X" * (256 * 1024)),
        httpx.Response(200, content=b"\xff\xff"),
        httpx.Response(302, headers={"Location": "https://example.com/other-paper"}),
        httpx.Response(404),
        httpx.Response(429, headers={"Retry-After": "600"}),
        httpx.Response(503),
    ],
)
async def test_missing_untrusted_or_oversized_metadata_falls_back_without_retry(
    monkeypatch, response
):
    calls = []

    def handle(request):
        calls.append(request)
        return response

    mock_metadata(monkeypatch, handle)
    assert await sources.fetch_arxiv_title("2512.12345v2") == ""
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("offline"), httpx.ReadTimeout("slow"), TimeoutError()]
)
async def test_transport_failures_do_not_fail_the_job(monkeypatch, error):
    def handle(_):
        raise error

    mock_metadata(monkeypatch, handle)
    assert await sources.fetch_arxiv_title("2512.12345") == ""


async def test_invalid_identifiers_never_make_a_network_request(monkeypatch):
    def unexpected(_):
        raise AssertionError("Invalid identifiers must stay local")

    mock_metadata(monkeypatch, unexpected)
    assert await sources.fetch_arxiv_title("https://example.com/private") == ""


async def test_metadata_reads_only_the_head_and_handles_unicode_chunk_boundaries(
    monkeypatch,
):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            # Position a multibyte character across the 4096-byte read boundary.
            prefix = '<head><meta name="citation_title" content="'
            title = "X" * (4095 - len(prefix)) + "中文 &amp; α"
            body = (
                prefix
                + title
                + '"><meta name="citation_arxiv_id" content="hep-th/9901001"></head>'
            ).encode()
            yield body + b" " * (8192 - len(body))
            raise AssertionError("The body must not be downloaded")

    mock_metadata(monkeypatch, lambda _: httpx.Response(200, stream=Stream()))
    title = await sources.fetch_arxiv_title("hep-th/9901001v2")
    assert title.endswith("中文 & α")


async def test_cancelled_metadata_lookup_propagates_cancellation(monkeypatch):
    def handle(_):
        raise asyncio.CancelledError()

    mock_metadata(monkeypatch, handle)
    with pytest.raises(asyncio.CancelledError):
        await sources.fetch_arxiv_title("2512.12345")


async def test_total_deadline_covers_a_server_that_keeps_sending_tiny_chunks(
    monkeypatch,
):
    timeout = asyncio.timeout
    monkeypatch.setattr(sources.asyncio, "timeout", lambda _: timeout(0.02))

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                yield b" "
                await asyncio.sleep(0.005)

    mock_metadata(monkeypatch, lambda _: httpx.Response(200, stream=Stream()))
    assert await sources.fetch_arxiv_title("2512.12345") == ""
