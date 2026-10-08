import asyncio
import json
import xml.etree.ElementTree as ET

import httpx
import pytest

from app import config
from app.config import Settings, merge_settings, public_settings, save_settings
from app.deepl import (
    MAX_REQUEST_BYTES,
    DeepLTranslator,
    decode_segment,
    encode_segment,
)
from app.latex import MARKER, segments
from app.llm import PROMPT_VERSION, ProviderError
from app.llm import Translator as LLMTranslator
from app.translation import Translator, cache_settings


def settings(**values):
    return Settings(
        base_url="https://api.deepl.com", api_key="test-deepl-key", **values
    )


async def mock_client(handler, **values):
    client = DeepLTranslator(settings(**values))
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def translated_response(request):
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "translations": [
                {
                    "text": text.replace("The model", "该模型").replace(
                        "improves accuracy", "提高准确率"
                    ),
                    "billed_characters": 20,
                }
                for text in body["text"]
            ]
        },
    )


@pytest.mark.parametrize(
    "source",
    [
        r"The model minimizes $L(x)$ with \cite{paper} at 95\% accuracy.",
        r"Our \textbf{small} model uses \textit{nested $x$ values} with \ref{tab:a}.",
        r"Values $a<b$ and $x&y$ stay unchanged with \href{https://example.com?a=1&b=2}{the link}.",
        r"The model name is \method{} and the result improves significantly.",
    ],
)
def test_xml_transport_roundtrip_is_lossless(source):
    item = segments(source)[0]
    xml, values = encode_segment(item)
    result = decode_segment(xml, values)
    assert result == item.masked
    assert item.restore(result) == item.restore(item.masked)


@pytest.mark.parametrize(
    "xml",
    [
        '<p><ph id="P0000">x</ph><ph id="P0000">x</ph></p>',
        "<p>missing</p>",
        '<p><ph id="P0001">x</ph></p>',
        '<p><ph id="P0000">modified</ph></p>',
        '<p><ph id="P0000" extra="x">x</ph></p>',
        '<p><ph id="P0000"><b>x</b></ph></p>',
        '<p><b>extra</b><ph id="P0000">x</ph></p>',
        '<p extra="x"><ph id="P0000">x</ph></p>',
        '<!DOCTYPE p [<!ENTITY e "x">]><p><ph id="P0000">&e;</ph></p>',
        '<p><!--comment--><ph id="P0000">x</ph></p>',
        '<?xml version="1.0"?><p><ph id="P0000">x</ph></p>',
        '<p><ph id="P0000">x</p>',
    ],
)
def test_xml_corruption_is_rejected(xml):
    with pytest.raises(ValueError):
        decode_segment(xml, {"P0000": "x"})


@pytest.mark.parametrize(
    "language,code",
    [("简体中文", "ZH-HANS"), ("繁體中文", "ZH-HANT"), ("English", "EN-US")],
)
async def test_native_request_auth_context_usage_and_language(language, code):
    calls = []

    def handler(request):
        calls.append(request)
        return translated_response(request)

    t = await mock_client(
        handler, target_language=language, glossary="A model-only preference"
    )
    try:
        item = segments("The model improves accuracy.")[0]
        output = await t.translate(item, "An abstract with useful terminology.")
        assert ("該模型" if language == "繁體中文" else "该模型") in output
        body = json.loads(calls[0].content)
        assert body["target_lang"] == code
        assert body["context"] == "An abstract with useful terminology."
        assert body["tag_handling"] == "xml" and body["ignore_tags"] == ["ph"]
        assert "model" not in body and "messages" not in body and "glossary" not in body
        assert calls[0].headers["Authorization"] == "DeepL-Auth-Key test-deepl-key"
        assert str(calls[0].url) == "https://api.deepl.com/v2/translate"
        assert t.characters == 20 and t.tokens == 0 and not t.characters_estimated
        assert t.requests == 1
    finally:
        await t.close()


async def test_free_key_context_off_and_glossary():
    calls = []

    def handler(request):
        calls.append(request)
        return translated_response(request)

    t = await mock_client(
        handler,
        context_guidance=False,
        deepl_source_language="EN",
        deepl_glossary_id="12345678-1234-1234-1234-123456789abc",
    )
    t.settings.api_key = "test-free-key:fx"
    try:
        await t.translate(
            segments("The model improves accuracy.")[0], "must not be sent"
        )
        body = json.loads(calls[0].content)
        assert "context" not in body
        assert (
            body["source_lang"] == "EN"
            and body["glossary_id"] == t.settings.deepl_glossary_id
        )
        assert calls[0].url.host == "api-free.deepl.com"
    finally:
        await t.close()


async def test_movable_values_keep_their_semantic_identity():
    item = segments("Accuracy increases from 10 to 20 after 5 steps.")[0]

    def handler(request):
        root = ET.fromstring(json.loads(request.content)["text"][0])
        values = {
            child.text: ET.tostring(child, encoding="unicode").split("</ph>")[0]
            + "</ph>"
            for child in root
        }
        xml = f"<p>在 {values['5']} 步后，准确率从 {values['10']} 提升到 {values['20']}。</p>"
        return httpx.Response(
            200, json={"translations": [{"text": xml, "billed_characters": 45}]}
        )

    t = await mock_client(handler)
    try:
        assert (
            item.restore(await t.translate(item))
            == "在 5 步后，准确率从 10 提升到 20。"
        )
    finally:
        await t.close()


async def test_recovery_freezes_formatting_boundaries_without_an_llm():
    item = segments(r"The \textbf{small} model uses $x$ values with \cite{a}.")[0]
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert all(r"\textbf" not in text for text in body["text"])
        assert "small" in body["context"]
        translated = [
            text.replace("The ", "这个 ")
            .replace("small", "小型")
            .replace("model uses", "模型使用")
            .replace("values with", "值参见")
            for text in body["text"]
        ]
        return httpx.Response(
            200,
            json={
                "translations": [
                    {"text": text, "billed_characters": 10} for text in translated
                ]
            },
        )

    t = await mock_client(handler, context_guidance=False)
    try:
        output = await t.translate_slots(item)
        result = item.restore(output)
        assert r"\textbf{小型}" in result and "$x$" in result and r"\cite{a}" in result
        assert sorted(MARKER.findall(output)) == sorted(MARKER.findall(item.masked))
        assert len(calls) == 1
    finally:
        await t.close()


@pytest.mark.parametrize(
    "status,message",
    [(403, "认证失败"), (456, "字符额度"), (400, "拒绝请求"), (302, "拒绝请求")],
)
async def test_fatal_errors_do_not_retry_or_echo_response(status, message):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            text="private text test-deepl-key",
            headers={"Location": "https://evil.example"},
        )

    t = await mock_client(handler)
    try:
        with pytest.raises(ProviderError, match=message) as exc:
            await t.test()
        assert (
            len(calls) == 1
            and "private" not in str(exc.value)
            and "test-deepl-key" not in str(exc.value)
        )
    finally:
        await t.close()


async def test_retry_after_and_billed_usage(monkeypatch):
    waits, calls = [], []

    async def sleep(value):
        waits.append(value)

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "7"})
            if len(calls) == 1
            else translated_response(request)
        )

    monkeypatch.setattr("app.deepl.asyncio.sleep", sleep)
    t = await mock_client(handler)
    try:
        await t.test()
        assert waits == [7] and t.characters == 20 and t.requests == 2
    finally:
        await t.close()


async def test_missing_key_fails_without_network():
    def handler(_):
        raise AssertionError("must not call API")

    t = await mock_client(handler)
    t.settings.api_key = ""
    try:
        with pytest.raises(ProviderError, match="API key"):
            await t.test()
        assert t.requests == 0
    finally:
        await t.close()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"translations": []},
        {"translations": [{"text": None}]},
        {"translations": [{"text": "<p/>"}]},
    ],
)
async def test_malformed_or_empty_test_responses_fail(payload):
    t = await mock_client(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises((ProviderError, ValueError)):
            await t.test()
    finally:
        await t.close()


async def test_batch_limits_use_utf8_bytes_and_preserve_order():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert len(request.content) <= MAX_REQUEST_BYTES and len(body["text"]) <= 50
        return httpx.Response(
            200,
            json={
                "translations": [
                    {"text": text, "billed_characters": 1} for text in body["text"]
                ]
            },
        )

    t = await mock_client(handler)
    try:
        texts = [f"<p>{i}" + "中" * 1200 + "</p>" for i in range(105)]
        assert await t._texts(texts, "context") == texts
        assert len(calls) > 2 and t.characters == 105
        with pytest.raises(ValueError, match="大小限制"):
            await t._texts(["<p>" + "中" * MAX_REQUEST_BYTES + "</p>"], "")
    finally:
        await t.close()


async def test_cancellation_propagates_without_retries():
    started = asyncio.Event()

    async def handler(_):
        started.set()
        await asyncio.Event().wait()

    t = await mock_client(handler)
    try:
        task = asyncio.create_task(t.test())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert t.requests == 1
    finally:
        await t.close()


async def test_factory_and_engine_specific_caches():
    llm = Translator(Settings())
    deepl = Translator(settings())
    try:
        assert isinstance(llm, LLMTranslator) and isinstance(deepl, DeepLTranslator)
        old = cache_settings(Settings(), "abstract")
        assert old == {
            "version": PROMPT_VERSION,
            "base": "https://api.deepseek.com",
            "model": "deepseek-flash",
            "language": "简体中文",
            "glossary": "",
            "paper_context": "abstract",
            "context_guidance": True,
        }
        base = cache_settings(settings(), "abstract")
        assert base != old
        assert base == cache_settings(settings(glossary="LLM-only"), "abstract")
        assert base != cache_settings(settings(deepl_source_language="EN"), "abstract")
        assert base != cache_settings(settings(), "another abstract")
    finally:
        await llm.close()
        await deepl.close()


def test_settings_switch_key_isolation_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    save_settings({"api_key": "llm-private", "glossary": "attention = 注意力"})
    t = save_settings({"provider": "deepl", "api_key": "deepl-private"})
    assert t.model == "DeepL" and t.glossary == "attention = 注意力"
    assert save_settings({"provider": "deepseek"}).api_key == "llm-private"
    assert save_settings({"provider": "deepl"}).api_key == "deepl-private"
    assert merge_settings(t, {"base_url": "https://evil.example"}).api_key == ""
    assert "private" not in json.dumps(public_settings(t))
    assert (
        Settings(base_url="https://api.deepl.com/v2/translate").base_url
        == "https://api.deepl.com"
    )
    for url in ["https://api.deepl.com/custom", "https://api.deepl.com:123"]:
        with pytest.raises(ValueError):
            Settings(base_url=url)
    with pytest.raises(ValueError, match="源语言"):
        settings(deepl_glossary_id="12345678-1234-1234-1234-123456789abc")
    monkeypatch.setenv("DEEPL_API_KEY", "deepl-env-private")
    config.CONFIG.write_text(json.dumps({"base_url": "https://api.deepl.com"}))
    assert config.load_settings().api_key == "deepl-env-private"
    config.CONFIG.write_text(json.dumps({"base_url": "http://localhost:11434/v1"}))
    assert config.load_settings().api_key != "deepl-env-private"


async def test_settings_api_uses_deepl_and_never_exposes_key_in_validation_errors(
    tmp_path, monkeypatch
):
    import app.main as main

    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    key = "private-validation-key"
    network = []

    def handler(request):
        network.append(request)
        return translated_response(request)

    def factory(s):
        client = DeepLTranslator(s)
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return client

    monkeypatch.setattr(main, "Translator", factory)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as client:
        payload = {"provider": "deepl", "api_key": key}
        saved = await client.put("/api/settings", json=payload)
        assert saved.status_code == 200 and saved.json()["model"] == "DeepL"
        assert key not in saved.text and saved.json()["has_api_key"]
        probe = await client.post("/api/settings/test", json={})
        assert probe.status_code == 200 and probe.json()["characters"] == 20
        assert network[0].url.path == "/v2/translate"
        assert network[0].headers["Authorization"] == "DeepL-Auth-Key " + key
        invalid = payload | {
            "deepl_glossary_id": "12345678-1234-1234-1234-123456789abc",
            "deepl_source_language": "",
        }
        for endpoint in ["/api/settings/test", "/api/settings"]:
            response = await (
                client.post(endpoint, json=invalid)
                if endpoint.endswith("test")
                else client.put(endpoint, json=invalid)
            )
            assert response.status_code == 400 and key not in response.text


@pytest.mark.parametrize("failure", ["timeout", "long-backoff", "server"])
async def test_transport_and_transient_errors_are_bounded(failure, monkeypatch):
    calls, waits = [], []

    async def sleep(delay):
        waits.append(delay)

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("provider data", request=request)
        if failure == "long-backoff":
            return httpx.Response(429, headers={"Retry-After": "120"})
        return httpx.Response(503)

    monkeypatch.setattr("app.deepl.asyncio.sleep", sleep)
    client = await mock_client(handler)
    try:
        with pytest.raises(ProviderError):
            await client.test()
        assert len(calls) == (1 if failure == "long-backoff" else 3)
        assert client.characters == 0
        assert len(waits) == (0 if failure == "long-backoff" else 2)
    finally:
        await client.close()
