"""Resolve a bare arXiv ID once, before choosing sources or cached translations."""

from __future__ import annotations

import asyncio
import re
import time
from xml.etree import ElementTree

import httpx

from .sources import _ArxivTitleParser, parse_arxiv

_lookup_lock = asyncio.Lock()
_last_request = 0.0


def _versioned(value: str, expected: str) -> str:
    identifier = parse_arxiv(value)
    if re.sub(r"v\d+$", "", identifier).lower() != expected.lower():
        raise ValueError("arXiv returned another paper")
    if not re.search(r"v[1-9]\d*$", identifier):
        raise ValueError("arXiv did not identify a specific version")
    return identifier


class _VersionPageParser(_ArxivTitleParser):
    def __init__(self):
        super().__init__()
        self.history_depth = 0
        self.versions: set[int] = set()

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "div":
            classes = dict(attrs).get("class", "").split()
            if self.history_depth or "submission-history" in classes:
                self.history_depth += 1

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "div" and self.history_depth:
            self.history_depth -= 1

    def handle_data(self, text):
        if self.history_depth:
            self.versions.update(int(v) for v in re.findall(r"\[v([1-9]\d*)\]", text))


async def _read(client: httpx.AsyncClient, url: str, **kwargs) -> str:
    global _last_request
    # The official API requests clients to leave three seconds between calls.
    async with _lookup_lock:
        await asyncio.sleep(max(0, 3 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        async with client.stream("GET", url, **kwargs) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 256 * 1024:
                    raise ValueError("arXiv metadata is too large")
            return body.decode("utf-8")


async def resolve_arxiv_version(value: str) -> dict[str, str]:
    identifier = parse_arxiv(value)
    if re.search(r"v[1-9]\d*$", identifier):
        return {"id": identifier, "title": "", "evidence": "explicit"}
    async with asyncio.timeout(18):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5, connect=3),
            headers={"User-Agent": "TeXGlot (personal research; version resolution)"},
            follow_redirects=False,
        ) as client:
            try:
                text = await _read(
                    client,
                    "https://export.arxiv.org/api/query",
                    params={"id_list": identifier, "max_results": 1},
                )
                root = ElementTree.fromstring(text)
                ns = "{http://www.w3.org/2005/Atom}"
                entries = root.findall(f"{ns}entry")
                if len(entries) != 1:
                    raise ValueError("Expected one arXiv paper")
                entry = entries[0]
                resolved = _versioned(entry.findtext(f"{ns}id", ""), identifier)
                return {
                    "id": resolved,
                    "title": " ".join(entry.findtext(f"{ns}title", "").split()),
                    "evidence": "arxiv",
                }
            except (httpx.HTTPError, ValueError, ElementTree.ParseError):
                # The abstract page is a separate official source when the API
                # is temporarily unavailable. Only its own history is evidence.
                text = await _read(client, f"https://arxiv.org/abs/{identifier}")
                parser = _VersionPageParser()
                parser.feed(text)
                title = parser.title(identifier)
                if not title or not parser.versions:
                    raise ValueError("Cannot verify the arXiv version") from None
                return {
                    "id": f"{identifier}v{max(parser.versions)}",
                    "title": title,
                    "evidence": "arxiv",
                }
