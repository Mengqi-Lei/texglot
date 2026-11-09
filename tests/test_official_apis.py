"""Official endpoint contracts; all provider responses are simulated, key-free."""

import json

import httpx
import pytest

from app import config
from app.config import Settings, merge_settings
from app.llm import ProviderError, Translator

SUCCESS = {"choices": [{"message": {"content": "译文"}}], "usage": {"total_tokens": 9}}


async def client_with_handler(settings, handler):
    client = Translator(settings)
    await client.close()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.parametrize("host", ["api.openai.com", "api.anthropic.com"])
@pytest.mark.parametrize(
    "suffix", ["", "/", "/v1/", "/chat/completions/", "/v1/chat/completions/"]
)
async def test_official_endpoint_normalization_and_output_budget(host, suffix):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=SUCCESS)

    client = await client_with_handler(
        Settings(base_url=f"https://{host}{suffix}", model="user-selected-model"),
        handler,
    )
    try:
        assert await client.complete([], max_tokens=1234, json_output=True) == "译文"
        request = calls[0]
        assert str(request.url) == f"https://{host}/v1/chat/completions"
        body = json.loads(request.content)
        token_field = (
            "max_completion_tokens" if host == "api.openai.com" else "max_tokens"
        )
        assert body[token_field] == 1234
        assert ("max_tokens" in body) != ("max_completion_tokens" in body)
        assert body["temperature"] == 0.2
        assert "response_format" not in body  # Claude rejects json_object.
        assert "enable_thinking" not in body and "thinking" not in body
        assert client.tokens == 9
    finally:
        await client.close()


@pytest.mark.parametrize(
    "url,error",
    [
        (
            "https://api.openai.com/v1",
            {
                "message": "Only the default temperature is supported.",
                "param": "temperature",
                "code": "unsupported_value",
                "type": "invalid_request_error",
            },
        ),
        (
            "https://api.openai.com/v1",
            {
                "message": "This model does not support temperature.",
                "param": "temperature",
                "code": "unsupported_parameter",
                "type": "invalid_request_error",
            },
        ),
        (
            "https://api.anthropic.com/v1",
            {
                "message": "temperature must be set to 1 for this model.",
                "type": "invalid_request_error",
            },
        ),
        (
            "https://api.anthropic.com/v1",
            {
                "message": "temperature: Only the default (1) value is supported.",
                "type": "invalid_request_error",
            },
        ),
        (
            "https://api.anthropic.com/v1",
            {
                "message": "This model only supports temperature=1.",
                "type": "invalid_request_error",
            },
        ),
        (
            "https://api.anthropic.com/v1",
            {
                "message": "This model does not support temperature.",
                "type": "invalid_request_error",
            },
        ),
    ],
)
async def test_explicit_temperature_rejection_recovers_and_is_remembered(url, error):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": error})
        return httpx.Response(200, json=SUCCESS)

    client = await client_with_handler(Settings(base_url=url), handler)
    try:
        for _ in range(2):
            assert (
                await client.complete(
                    [{"role": "user", "content": "test"}], max_tokens=321
                )
                == "译文"
            )
        assert len(calls) == 3
        assert (
            {k: v for k, v in calls[0].items() if k != "temperature"}
            == calls[1]
            == calls[2]
        )
        assert client.settings.temperature == 0.2  # No persistent setting change.
        assert client.requests == 3 and client.tokens == 18
    finally:
        await client.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://gateway.example/v1",
        "https://api.openai.com.attacker.example/v1",
        "https://api.anthropic.com:8443/v1",
        "http://localhost:11434/v1",
    ],
)
async def test_custom_gateways_keep_their_contract_even_with_official_model_names(url):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            400,
            json={
                "error": {
                    "param": "temperature",
                    "code": "unsupported_parameter",
                    "message": "temperature unsupported",
                }
            },
        )

    client = await client_with_handler(Settings(base_url=url, model="gpt-5"), handler)
    try:
        with pytest.raises(ProviderError, match="HTTP 400"):
            await client.complete([])
        assert len(calls) == 1
        assert calls[0]["max_tokens"] == 7000 and calls[0]["temperature"] == 0.2
        assert "max_completion_tokens" not in calls[0]
    finally:
        await client.close()


@pytest.mark.parametrize(
    "error",
    [
        {
            "param": "max_completion_tokens",
            "code": "context_length_exceeded",
            "message": "Context is too long.",
        },
        {
            "type": "invalid_request_error",
            "message": "Temperature testing project is disabled.",
        },
        {"type": "invalid_request_error", "message": "Invalid model."},
    ],
)
async def test_unrelated_400_is_not_retried_and_keeps_the_reason(error):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": error})

    client = await client_with_handler(
        Settings(base_url="https://api.openai.com/v1"), handler
    )
    try:
        with pytest.raises(ProviderError) as failure:
            await client.complete([])
        assert error["message"] in str(failure.value) and len(calls) == 1
    finally:
        await client.close()


async def test_parameter_adaptation_cannot_retry_forever():
    def handler(request):
        return httpx.Response(
            400,
            json={
                "error": {
                    "param": "temperature",
                    "code": "unsupported_parameter",
                    "message": "temperature is not supported",
                }
            },
        )

    client = await client_with_handler(
        Settings(base_url="https://api.openai.com/v1"), handler
    )
    try:
        with pytest.raises(ProviderError, match="HTTP 400"):
            await client.complete([])
        assert client.requests == 2
    finally:
        await client.close()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "error": {
                "message": "X" * 480
                + " private-test-key Bearer other-test-key "
                + "sk-" + "test.payload.signature\n"
                + "Y" * 500
            }
        },
        {"error": "private-test-key\nAPI version is unsupported."},
    ],
)
async def test_provider_diagnostics_are_bounded_and_redacted(payload):
    client = await client_with_handler(
        Settings(api_key="private-test-key"),
        lambda _: httpx.Response(400, json=payload),
    )
    try:
        with pytest.raises(ProviderError) as failure:
            await client.complete([])
        message = str(failure.value)
        assert "private-test-key" not in message and "other-test-key" not in message
        assert "sk-test" not in message and "\n" not in message
        assert len(message) < 560 and "密钥已隐藏" in message
    finally:
        await client.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, text="<html>SECRET_PROXY_DUMP</html>"),
        httpx.Response(400, json=["SECRET_PROXY_DUMP"]),
        httpx.Response(400, json={"error": {"message": ["SECRET_PROXY_DUMP"]}}),
        httpx.Response(400, json={"error": {"message": "SECRET_PROXY_DUMP" * 6000}}),
    ],
)
async def test_unstructured_errors_never_dump_raw_responses(response):
    client = await client_with_handler(Settings(), lambda _: response)
    try:
        with pytest.raises(ProviderError) as failure:
            await client.complete([])
        assert str(failure.value) == "模型拒绝请求（HTTP 400），请检查模型设置"
    finally:
        await client.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1/responses",
        "https://api.anthropic.com/v1/messages",
    ],
)
async def test_native_endpoint_has_actionable_error_without_breaking_saved_settings(
    url,
):
    settings = Settings(base_url=url)

    def handler(_):
        pytest.fail("Wrong-protocol endpoints must be rejected before sending a key")

    client = await client_with_handler(settings, handler)
    try:
        with pytest.raises(ProviderError, match="Chat Completions 兼容地址"):
            await client.complete([])
        assert client.requests == 0
    finally:
        await client.close()


def test_old_official_connection_keys_survive_normalization(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    (tmp_path / "connections.json").write_text(
        json.dumps(
            {
                "https://api.openai.com": {
                    "base_url": "https://api.openai.com",
                    "model": "gpt-5",
                    "api_key": "private-test-key",
                }
            }
        )
    )
    settings = merge_settings(Settings(), {"base_url": "https://api.openai.com/v1"})
    assert settings.api_key == "private-test-key"
    assert (
        merge_settings(settings, {"base_url": "https://gateway.example/v1"}).api_key
        == ""
    )
