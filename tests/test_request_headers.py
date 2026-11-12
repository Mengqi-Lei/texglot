"""Gateway authentication stays scoped, validated and absent from public data."""

import json
import os

import httpx
import pytest
from pydantic import ValidationError

from app import config
from app.config import Settings, merge_settings, public_settings, save_settings
from app.llm import ProviderError, Translator
from app.request_headers import RESERVED_HEADERS, validate_extra_headers
from app.translation import cache_settings

A = "https://gateway.example/team-a/v1"
B = "https://gateway.example/team-b/v1"
SECRET = "gateway-test-secret"


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "{}",
        {"x-org-id": 1},
        {"x-org-id": None},
        {"x-org-id": True},
        {"x-org-id": ["private-value"]},
        {1: "value"},
        {"": "value"},
        {" x-org-id": "value"},
        {"x:org": "value"},
        {"x-org-id\n": "value"},
        {"组织": "value"},
        {"x-org-id": "one\r\nHost: evil"},
        {"x-org-id": "one\x00two"},
        {"x-org-id": "one\ttwo"},
        {"x-org-id": "one\x7f"},
        {"x-org-id": "组织"},
        {"X-Org-Id": "one", "x-org-id": "two"},
        {"x" * 129: "value"},
        {"x-org-id": "a" * 4097},
        {f"x-{i}": "a" for i in range(17)},
        {**{f"x-{i}": "a" * 4089 for i in range(4)}, "x-0": "a" * 4090},
    ],
)
def test_reject_invalid_headers_without_echoing_values(value):
    with pytest.raises(ValidationError) as caught:
        Settings(extra_headers=value)
    assert "input_value" not in str(caught.value)
    assert "private-value" not in str(caught.value)


@pytest.mark.parametrize("name", sorted(RESERVED_HEADERS))
def test_transport_and_authorization_headers_cannot_be_overridden(name):
    with pytest.raises(ValidationError, match="不能覆盖") as caught:
        Settings(extra_headers={name.upper(): SECRET})
    assert SECRET not in str(caught.value)


def test_header_limits_and_case_normalization():
    assert validate_extra_headers({"x-org-id": " org-A "}) == {"x-org-id": "org-A"}
    assert validate_extra_headers({"x-quoted": '" two words "'}) == {
        "x-quoted": '" two words "'
    }
    assert Settings(
        extra_headers={"X-Org-ID": "a", "x-opencode-session": ""}
    ).extra_headers == {
        "x-org-id": "a",
        "x-opencode-session": "",
    }
    for value in [
        {"x" * 128: "ok"},
        {"x-org-id": "a" * 4096},
        {f"x-{i}": "" for i in range(16)},
        {f"x-{i}": "a" * 4089 for i in range(4)},
        {"__proto__": "value", "!#$%&'*+.^_`|~": "value"},
    ]:
        assert validate_extra_headers(value) == value


def test_connection_scope_preserve_replace_clear_and_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    a = save_settings({"base_url": A, "extra_headers": {"X-Org-ID": SECRET}})
    assert merge_settings(a, {"model": "new-model"}).extra_headers == a.extra_headers
    assert (
        merge_settings(a, {"base_url": A + "/chat/completions/"}).extra_headers
        == a.extra_headers
    )
    assert merge_settings(a, {"base_url": B}).extra_headers == {}
    assert (
        merge_settings(a, {"base_url": "https://other.example/v1"}).extra_headers == {}
    )
    b = save_settings({"base_url": B, "extra_headers": {"x-org-id": "team-b"}})
    assert b.extra_headers == {"x-org-id": "team-b"}
    restored = save_settings({"base_url": A})
    assert restored.extra_headers == a.extra_headers  # Only A's own profile.
    replaced = save_settings({"extra_headers": {"x-new": "replacement"}})
    assert replaced.extra_headers == {"x-new": "replacement"}
    # Manual URL editing uses explicit {}, even when the destination is saved.
    cleared = save_settings({"base_url": B, "extra_headers": {}})
    assert not cleared.extra_headers
    assert config.load_settings().extra_headers == {}
    if os.name != "nt":
        assert config.CONFIG.stat().st_mode & 0o777 == 0o600
        assert (
            config.CONFIG.with_name("connections.json").stat().st_mode & 0o777 == 0o600
        )


def test_header_values_are_private_and_do_not_change_cache_identity():
    plain = Settings(base_url=A, model="test-model")
    secured = plain.model_copy(update={"extra_headers": {"x-org-id": SECRET}})
    assert public_settings(plain) == public_settings(secured)
    assert cache_settings(plain, "paper context") == cache_settings(
        secured, "paper context"
    )
    view = public_settings(secured, connection_status=True)
    assert view["extra_header_names"] == ["x-org-id"]
    assert "extra_headers" not in view and SECRET not in json.dumps(view)
    assert SECRET not in repr(secured)


def test_zotero_fingerprint_matches_the_released_schema(monkeypatch):
    from app import integrations

    settings = Settings(base_url=A, model="test-model", api_key="api-test-key")
    monkeypatch.setattr(integrations, "load_settings", lambda: settings)
    # Captured from v1.2.6 before adding the extra_headers field, not recomputed
    # using the new serializer. Old tasks must remain eligible for reuse.
    expected = "68fb2f134162e39804da66bfa1bd4d39ec35aa79dfb856969b497cfb2742714e"
    assert integrations._settings_fingerprint("简体中文", True) == expected
    settings.extra_headers = {"x-org-id": SECRET}
    assert integrations._settings_fingerprint("简体中文", True) == expected


def test_old_profiles_and_deepl_remain_compatible(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    config.CONFIG.write_text(json.dumps({"base_url": A, "model": "old-model"}))
    assert config.load_settings().extra_headers == {}
    save_settings({"extra_headers": {"x-org-id": SECRET}})
    before = config.CONFIG.read_bytes()
    profile = next(p for p in config.provider_options() if p["id"] == "custom")
    assert profile["extra_header_names"] == ["x-org-id"]
    assert SECRET not in json.dumps(profile)
    assert merge_settings(config.load_settings(), {"base_url": B}).extra_headers == {}
    assert config.CONFIG.read_bytes() == before  # Test does not persist anything.
    deepl = save_settings({"provider": "deepl"})
    assert deepl.extra_headers == {}
    assert (
        Settings(
            base_url="https://api.deepl.com", extra_headers={"x-org-id": SECRET}
        ).extra_headers
        == {}
    )
    assert save_settings({"provider": "custom"}).extra_headers == {"x-org-id": SECRET}


async def translator(settings, handler):
    value = Translator(settings)
    await value.close()
    value.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return value


@pytest.mark.parametrize(
    "url", [A, "https://api.openai.com/v1", "https://api.anthropic.com/v1"]
)
async def test_connection_translation_and_retries_use_headers_without_changing_payload(
    url,
):
    calls = []
    settings = Settings(
        base_url=url, api_key="api-test-key", extra_headers={"x-org-id": SECRET}
    )

    def handler(request):
        calls.append(request)
        if len(calls) == 1 and url != A:
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
        return httpx.Response(200, json={"choices": [{"message": {"content": "译文"}}]})

    client = await translator(settings, handler)
    try:
        assert (await client.test())["ok"]
        assert (
            await client.complete(
                [{"role": "user", "content": "paragraph"}], max_tokens=321
            )
            == "译文"
        )
        for request in calls:
            assert request.headers["x-org-id"] == SECRET
            assert request.headers["authorization"] == "Bearer api-test-key"
            assert request.headers["content-type"] == "application/json"
            assert SECRET.encode() not in request.content
        body = json.loads(calls[-1].content)
        assert body.get("max_tokens", body.get("max_completion_tokens")) == 321
    finally:
        await client.close()


async def test_running_translator_keeps_a_snapshot_of_the_connection():
    settings = Settings(base_url=A, extra_headers={"x-org-id": SECRET})
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "译文"}}]})

    client = await translator(settings, handler)
    settings.base_url = B
    settings.extra_headers["x-org-id"] = "changed-after-start"
    try:
        await client.complete([])
        assert str(calls[0].url) == A + "/chat/completions"
        assert calls[0].headers["x-org-id"] == SECRET
    finally:
        await client.close()


async def test_redirect_does_not_forward_gateway_credentials():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": B + "/chat/completions"})

    client = await translator(
        Settings(base_url=A, extra_headers={"x-org-id": SECRET}), handler
    )
    try:
        with pytest.raises(ProviderError):
            await client.complete([])
        assert len(calls) == 1
    finally:
        await client.close()


async def test_error_and_connection_test_echoes_are_redacted():
    secret = 'gateway-"quoted\\credential'
    content = SECRET + " " + json.dumps(secret) + " api-test-key"
    responses = [
        httpx.Response(400, json={"error": {"message": content}}),
        httpx.Response(200, json={"choices": [{"message": {"content": content}}]}),
    ]
    client = await translator(
        Settings(
            api_key="api-test-key",
            extra_headers={"x-org-id": SECRET, "x-session": secret},
        ),
        lambda _: responses.pop(0),
    )
    try:
        with pytest.raises(ProviderError) as caught:
            await client.complete([])
        result = await client.test()
        for value in [str(caught.value), result["message"]]:
            assert (
                SECRET not in value
                and secret not in value
                and json.dumps(secret)[1:-1] not in value
            )
            assert "api-test-key" not in value and "密钥已隐藏" in value
    finally:
        await client.close()


async def test_settings_api_validates_hides_values_and_tests_unsaved_headers(
    tmp_path, monkeypatch
):
    from app import main

    monkeypatch.setattr(config, "CONFIG", tmp_path / "settings.json")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": request.headers.get("x-org-id", "ok")}}
                ]
            },
        )

    class TestTranslator(Translator):
        def __init__(self, settings):
            super().__init__(settings)
            original = self.client
            self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            self.original = original

        async def close(self):
            await super().close()
            await self.original.aclose()

    monkeypatch.setattr(main, "Translator", TestTranslator)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as api:
        saved = await api.put(
            "/api/settings", json={"base_url": A, "extra_headers": {"x-org-id": SECRET}}
        )
        assert saved.status_code == 200 and SECRET not in saved.text
        assert saved.json()["extra_header_names"] == ["x-org-id"]
        before = config.CONFIG.read_bytes()
        tested = await api.post(
            "/api/settings/test",
            json={"extra_headers": {"x-org-id": "unsaved-test-secret"}},
        )
        assert tested.status_code == 200 and "unsaved-test-secret" not in tested.text
        assert requests[-1].headers["x-org-id"] == "unsaved-test-secret"
        assert config.CONFIG.read_bytes() == before
        invalid = await api.put(
            "/api/settings", json={"extra_headers": {"Authorization": SECRET}}
        )
        assert invalid.status_code == 400 and SECRET not in invalid.text
        assert config.CONFIG.read_bytes() == before
        loaded = await api.get("/api/settings")
        assert SECRET not in loaded.text and loaded.json()["extra_header_names"] == [
            "x-org-id"
        ]
        cleared = await api.put("/api/settings", json={"extra_headers": {}})
        assert cleared.json()["extra_header_names"] == []
