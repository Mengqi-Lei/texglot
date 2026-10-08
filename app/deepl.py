"""DeepL text translation with a validated, reversible XML transport.

Only prose is translated. XML IDs refer to local source slices; no API output
can replace a formula or create LaTeX syntax. No LLM is used for recovery.
"""

from __future__ import annotations

import asyncio
import json
import re
import ssl
import xml.etree.ElementTree as ET
from html import escape

import httpx

from .latex import MARKER, Segment
from .llm import ProviderError, normalize_language, retry_delay
from .paper_context import limit_context

DEEPL_VERSION = "deepl-xml-v1"
TARGET_LANGUAGES = {"简体中文": "ZH-HANS", "繁體中文": "ZH-HANT", "English": "EN-US"}
MAX_REQUEST_BYTES = 128 * 1024
MAX_TEXTS = 50


def encode_segment(segment: Segment) -> tuple[str, dict[str, str]]:
    values = {}

    def placeholder(match):
        token = match[0]
        value = segment.protected[int(token[2:-1])]
        # Give the engine useful numeric/math/name context, but never send a
        # large opaque environment or a formatting instruction as prose.
        display = segment.literal_value(value) or value
        if not segment.is_movable(value) or len(display) > 512:
            display = token[1:-1]
        values[token[1:-1]] = display
        return f'<ph id="{token[1:-1]}">{escape(display)}</ph>'

    parts = []
    end = 0
    for match in MARKER.finditer(segment.masked):
        parts.extend((escape(segment.masked[end : match.start()]), placeholder(match)))
        end = match.end()
    parts.append(escape(segment.masked[end:]))
    xml = "<p>" + "".join(parts) + "</p>"
    try:
        ET.fromstring(xml)
    except ET.ParseError:
        raise ValueError("段落包含无法发送至 DeepL 的 XML 字符") from None
    return xml, values


def decode_segment(xml: str, values: dict[str, str]) -> str:
    # Do not accept DTDs/entities, processing instructions, comments or any
    # provider-generated tags. Parse as data, never as a document to execute.
    if "<!" in xml or "<?" in xml:
        raise ValueError("DeepL 返回的段落结构无效")
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, ValueError):
        raise ValueError("DeepL 返回的段落结构无效") from None
    if root.tag != "p" or root.attrib:
        raise ValueError("DeepL 返回的段落结构无效")
    result = [root.text or ""]
    seen = set()
    for child in root:
        ident = child.get("id", "")
        if (
            child.tag != "ph"
            or set(child.attrib) != {"id"}
            or len(child)
            or ident not in values
            or ident in seen
            or (child.text or "") != values[ident]
        ):
            raise ValueError("DeepL 修改、遗漏或重复了受保护标记")
        seen.add(ident)
        result.extend((f"⟪{ident}⟫", child.tail or ""))
    if seen != set(values):
        raise ValueError("DeepL 修改、遗漏或重复了受保护标记")
    return "".join(result)


class DeepLTranslator:
    max_structure_attempts = 2

    def __init__(self, settings):
        self.settings = settings
        self.tokens = 0
        self.characters = 0
        self.characters_estimated = False
        self.requests = 0
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout, connect=20), follow_redirects=False
        )

    async def close(self):
        await self.client.aclose()

    def body(self, texts: list[str], context: str) -> dict:
        s = self.settings
        data = {
            "text": texts,
            "target_lang": TARGET_LANGUAGES[s.target_language],
            "tag_handling": "xml",
            "tag_handling_version": "v2",
            "ignore_tags": ["ph"],
            "split_sentences": "nonewlines",
            "preserve_formatting": True,
            "show_billed_characters": True,
        }
        if context:
            data["context"] = limit_context(context)
        if s.deepl_source_language:
            data["source_lang"] = s.deepl_source_language
        if s.deepl_glossary_id:
            data["glossary_id"] = s.deepl_glossary_id
        return data

    async def _request(self, body: dict) -> list[str]:
        s = self.settings
        if not s.api_key.strip():
            raise ProviderError("请在翻译设置中填写 DeepL API key")
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("段落超过 DeepL 单次请求大小限制")
        # Official Free keys end in :fx. Keep exact stored endpoint identities
        # for key isolation, but make first-time setup work with either key kind.
        endpoint = s.base_url
        if endpoint == "https://api.deepl.com" and s.api_key.strip().endswith(":fx"):
            endpoint = "https://api-free.deepl.com"
        headers = {
            "Authorization": "DeepL-Auth-Key " + s.api_key.strip(),
            "Content-Type": "application/json",
        }
        for attempt in range(3):
            try:
                self.requests += 1
                response = await self.client.post(
                    endpoint + "/v2/translate", headers=headers, content=encoded
                )
            except (httpx.TransportError, ssl.SSLError):
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise ProviderError(
                    "DeepL 连接超时或网络不可达，请检查网络后重试"
                ) from None
            code = response.status_code
            if code in (401, 403):
                raise ProviderError("DeepL 认证失败，请检查 API key 和 API 套餐")
            if code == 456:
                raise ProviderError(
                    "DeepL 字符额度已用完或已达到用量上限，请检查 API 账户后继续任务"
                )
            if code == 413:
                raise ValueError("段落超过 DeepL 单次请求大小限制")
            if code in (408, 429) or code >= 500:
                if attempt < 2:
                    delay = retry_delay(response, attempt)
                    if delay > 60:
                        raise ProviderError("DeepL 要求较长的重试等待，可稍后继续任务")
                    await asyncio.sleep(delay)
                    continue
                raise ProviderError("DeepL 服务暂时不可用，可稍后继续任务")
            if code != 200:
                # Never echo a remote response, which may contain source text
                # or credentials. Authentication failures must not trigger LLMs.
                raise ProviderError("DeepL 拒绝请求，请检查源语言、术语表和 API 套餐")
            try:
                if len(response.content) > 2 * 1024 * 1024:
                    raise ValueError("Response too large")
                rows = response.json()["translations"]
                if not isinstance(rows, list) or len(rows) != len(body["text"]):
                    raise ValueError("Invalid translation count")
                result = []
                for source, row in zip(body["text"], rows):
                    text = row["text"]
                    if not isinstance(text, str):
                        raise ValueError("Invalid translated text")
                    billed = row.get("billed_characters")
                    if type(billed) is int and billed >= 0:
                        self.characters += billed
                    else:
                        self.characters += len(
                            "".join(ET.fromstring(source).itertext())
                        )
                        self.characters_estimated = True
                    result.append(text)
                return result
            except (KeyError, TypeError, ValueError, ET.ParseError):
                raise ProviderError("DeepL 返回格式无效，可稍后继续任务") from None
        raise ProviderError("DeepL 服务暂时不可用，可稍后继续任务")

    async def _texts(self, texts: list[str], context: str) -> list[str]:
        result, batch = [], []
        for text in texts:
            candidate = batch + [text]
            size = len(
                json.dumps(self.body(candidate, context), ensure_ascii=False).encode(
                    "utf-8"
                )
            )
            if batch and (len(candidate) > MAX_TEXTS or size > MAX_REQUEST_BYTES):
                result.extend(await self._request(self.body(batch, context)))
                batch = []
            batch.append(text)
        if batch:
            result.extend(await self._request(self.body(batch, context)))
        return result

    async def translate(
        self, segment, context="", feedback="", *, surrounding_source=""
    ):
        if feedback:
            # DeepL cannot act on LLM-style repair prompts. A second attempt
            # fixes syntax positions locally, instead of repeating the same call.
            return await self.translate_slots(segment, context)
        compact, expansion = segment.compact(arguments_only=True)
        xml, values = encode_segment(compact)
        output = (
            await self._texts([xml], context if self.settings.context_guidance else "")
        )[0]
        masked = decode_segment(output, values)
        restored_ids = MARKER.sub(lambda m: expansion[m[0]], masked)
        restored_ids = normalize_language(restored_ids, self.settings.target_language)
        segment.restore(restored_ids)
        return restored_ids

    async def translate_slots(self, segment, context="", feedback="", **_):
        # Keep fixed syntax in the client. Translate complete runs between
        # fixed boundaries, allowing inline values to move inside their scope.
        fixed = {
            f"⟪P{i:04d}⟫"
            for i, v in enumerate(segment.protected)
            if not segment.is_movable(v)
        }
        parts, cursor = [], 0
        for match in MARKER.finditer(segment.masked):
            if match[0] in fixed:
                parts.extend((segment.masked[cursor : match.start()], match[0]))
                cursor = match.end()
        parts.append(segment.masked[cursor:])
        requests, targets = [], []
        for index, piece in enumerate(parts):
            if piece in fixed or not re.search(r"[^\W\d_]", MARKER.sub("", piece)):
                continue
            tokens = MARKER.findall(piece)
            local = {token: f"⟪P{i:04d}⟫" for i, token in enumerate(tokens)}
            values = [segment.protected[int(token[2:-1])] for token in tokens]
            masked = MARKER.sub(lambda m: local[m[0]], piece)
            source = MARKER.sub(lambda m: values[int(m[0][2:-1])], masked)
            item = Segment(
                0,
                len(source),
                source,
                masked,
                values,
                role=segment.role,
                literal_macros=segment.literal_macros,
            )
            xml, protected = encode_segment(item)
            requests.append(xml)
            targets.append(
                (index, piece, item, protected, {v: k for k, v in local.items()})
            )
        # Include the complete paragraph as disambiguation for small formatted
        # phrases. The optional paper abstract remains controlled by the toggle.
        guidance = segment.source
        if self.settings.context_guidance and context:
            guidance += "\n\n" + context
        outputs = await self._texts(requests, limit_context(guidance))
        for output, (index, piece, item, values, reverse) in zip(outputs, targets):
            translated = normalize_language(
                decode_segment(output, values), self.settings.target_language
            )
            item.restore(translated)
            prefix = piece[: len(piece) - len(piece.lstrip())]
            suffix = piece[len(piece.rstrip()) :]
            parts[index] = (
                prefix
                + MARKER.sub(lambda m: reverse[m[0]], translated.strip())
                + suffix
            )
        result = "".join(parts)
        segment.restore(result)
        return result

    async def test(self):
        sample = "<p>The experiment confirms the hypothesis.</p>"
        output = (await self._texts([sample], ""))[0]
        message = decode_segment(output, {})
        if not message.strip():
            raise ProviderError("DeepL 返回格式无效，可稍后继续任务")
        return {
            "ok": True,
            "model": "DeepL",
            "message": message,
            "characters": self.characters,
            "characters_estimated": self.characters_estimated,
        }
