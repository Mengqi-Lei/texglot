import json
import os

import httpx
import pytest

from app import config
from app.config import Settings, merge_settings, provider_options, save_settings
from app.llm import Translator, redact
from app.providers import provider_for_url

URL = "https://example-space.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


@pytest.mark.parametrize(
    "url,expected",
    [
        (URL, "qwen"),
        (
            "https://example-space.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
            "qwen",
        ),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen"),
        ("https://api.deepseek.com/v1", "deepseek"),
        ("https://api.deepseek.com.attacker.example/v1", "custom"),
        (
            "https://example-space.cn-beijing.maas.aliyuncs.com.attacker.example/v1",
            "custom",
        ),
        ("https://attacker.example/api.deepseek.com", "custom"),
        ("http://localhost:11434/v1", "custom"),
    ],
)
def test_provider_host_boundaries(url, expected):
    assert provider_for_url(url) == expected


@pytest.mark.parametrize(
    "url,provider_fields", [(URL, True), ("https://third-party.example/v1", False)]
)
async def test_qwen_non_thinking_and_json_mode_stay_on_official_host(
    url, provider_fields
):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"translation":"译文"}'}}],
                "usage": {"total_tokens": 12},
            },
        )

    t = Translator(Settings(base_url=url, model="qwen3.7-plus"))
    await t.client.aclose()
    t.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await t.complete([{"role": "user", "content": "Return JSON"}], json_output=True)
        assert ("enable_thinking" in calls[0]) == provider_fields
        assert ("response_format" in calls[0]) == provider_fields
        if provider_fields:
            assert calls[0]["enable_thinking"] is False
            assert calls[0]["response_format"] == {"type": "json_object"}
        assert "thinking" not in calls[0] and "extra_body" not in calls[0]
        assert t.tokens == 12
    finally:
        await t.close()


def test_provider_switch_remembers_exact_endpoint_keys_without_exposing_them(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    deep = save_settings({"api_key": "deep-private-key"})
    qwen = save_settings(
        {"provider": "qwen", "base_url": URL, "api_key": "qwen-private-key"}
    )
    assert qwen.model == "qwen3.7-plus"
    assert save_settings({"provider": "deepseek"}).api_key == "deep-private-key"
    assert save_settings({"provider": "qwen"}).api_key == "qwen-private-key"
    assert merge_settings(qwen, {"base_url": URL + "/another"}).api_key == ""
    assert merge_settings(qwen, {"base_url": "https://other.example/v1"}).api_key == ""
    public = json.dumps(provider_options())
    assert "private-key" not in public and '"api_key"' not in public
    assert all(p["has_api_key"] for p in provider_options() if p["id"] != "custom")
    before = config.CONFIG.read_bytes()
    merge_settings(qwen, {"provider": "deepseek"})
    assert config.CONFIG.read_bytes() == before  # connection tests never save
    cleared = save_settings({"clear_api_key": True})
    assert cleared.api_key == ""
    assert save_settings({"provider": "deepseek"}).api_key == deep.api_key
    assert save_settings({"provider": "qwen"}).api_key == ""
    if os.name != "nt":
        assert (tmp_path / "connections.json").stat().st_mode & 0o777 == 0o600


def test_first_qwen_preset_requires_workspace_address_and_env_is_provider_scoped(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-env-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deep-env-key")
    with pytest.raises(ValueError, match="OpenAI"):
        save_settings({"provider": "qwen"})
    config.CONFIG.write_text(
        json.dumps({"base_url": URL, "model": "qwen3.7-plus"}), encoding="utf-8"
    )
    assert config.load_settings().api_key == "qwen-env-key"
    config.CONFIG.write_text(
        json.dumps({"base_url": "http://localhost:11434/v1"}), encoding="utf-8"
    )
    assert config.load_settings().api_key == ""


def test_dotted_provider_keys_are_fully_redacted():
    assert redact("Failure " + "sk-" + "test.payload.signature") == "Failure [密钥已隐藏]"


async def test_cli_selects_provider_without_sending_credentials_in_command_line(
    monkeypatch,
):
    from app.cli import Service, configure, parser

    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "qwen3.7-plus", "has_api_key": True})

    monkeypatch.setenv("TEST_QWEN_KEY", "fake-qwen-key")
    args = parser().parse_args(
        [
            "--configure",
            "--provider",
            "qwen",
            "--base-url",
            URL,
            "--key-env",
            "TEST_QWEN_KEY",
        ]
    )
    service = Service(transport=httpx.MockTransport(handler))
    try:
        result = configure(service, args)
        assert calls == [
            {"provider": "qwen", "base_url": URL, "api_key": "fake-qwen-key"}
        ]
        assert "api_key" not in result
    finally:
        service.client.close()
