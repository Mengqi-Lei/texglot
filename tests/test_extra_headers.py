import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings, merge_settings, public_settings
from app.llm import Translator

GATEWAY = "https://gateway.example/v1"
OTHER_GATEWAY = "https://other-gateway.example/v1"
HEADERS = {"x-org-id": "org_123", "x-opencode-session": "session-1"}


async def test_extra_headers_are_sent_with_model_requests():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"total_tokens": 3},
            },
        )

    translator = Translator(
        Settings(
            base_url=GATEWAY,
            model="custom-model",
            api_key="sk-test",
            extra_headers=HEADERS,
        )
    )
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await translator.complete([{"role": "user", "content": "hi"}])
    finally:
        await translator.close()

    assert seen["headers"]["x-org-id"] == "org_123"
    assert seen["headers"]["x-opencode-session"] == "session-1"
    assert seen["headers"]["authorization"] == "Bearer sk-test"


def test_headers_are_normalized_and_empty_names_dropped():
    settings = Settings(extra_headers={" x-org-id ": " org_123 ", "": "dropped"})
    assert settings.extra_headers == {"x-org-id": "org_123"}


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "authorization",
        "AUTHORIZATION",
        "Host",
        "Content-Length",
        "Content-Type",
    ],
)
def test_managed_headers_cannot_be_overridden(name):
    with pytest.raises(ValidationError):
        Settings(extra_headers={name: "value"})


@pytest.mark.parametrize(
    "headers",
    [
        {"bad name": "value"},
        {"bad:name": "value"},
        {"bad/name": "value"},
        {"x-org-id": "line\nbreak"},
        {"x-org-id": "carriage\rreturn"},
        {"x-org-id": "v" * 4001},
        {f"x-header-{index}": "value" for index in range(21)},
    ],
)
def test_invalid_headers_are_rejected(headers):
    with pytest.raises(ValidationError):
        Settings(extra_headers=headers)


def test_switching_endpoint_drops_headers():
    settings = Settings(base_url=GATEWAY, extra_headers=HEADERS)
    assert merge_settings(settings, {"base_url": OTHER_GATEWAY}).extra_headers == {}


def test_switching_endpoint_keeps_explicit_headers():
    settings = Settings(base_url=GATEWAY, extra_headers=HEADERS)
    merged = merge_settings(
        settings, {"base_url": OTHER_GATEWAY, "extra_headers": {"x-org-id": "org_456"}}
    )
    assert merged.extra_headers == {"x-org-id": "org_456"}


def test_same_endpoint_keeps_headers():
    settings = Settings(base_url=GATEWAY, extra_headers=HEADERS)
    assert merge_settings(settings, {"model": "another-model"}).extra_headers == HEADERS


def test_trailing_slash_does_not_count_as_endpoint_change():
    settings = Settings(base_url=GATEWAY, extra_headers=HEADERS)
    assert (
        merge_settings(settings, {"base_url": f"{GATEWAY}/"}).extra_headers == HEADERS
    )


def test_public_settings_expose_headers():
    settings = Settings(base_url=GATEWAY, api_key="sk-test", extra_headers=HEADERS)
    exposed = public_settings(settings)
    assert exposed["extra_headers"] == HEADERS
    assert "api_key" not in exposed
