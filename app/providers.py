"""Provider recognition is based on trusted API hosts, never the model name alone."""

import re
from urllib.parse import urlsplit

PROVIDERS = {
    "qwen": {
        "name": "Qwen · 百炼",
        "base_url": "",
        "model": "qwen3.8-flash",
        "placeholder": "https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "docs": "https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "placeholder": "https://api.deepseek.com",
        "docs": "https://api-docs.deepseek.com/",
    },
    "deepl": {
        "name": "DeepL",
        "base_url": "https://api.deepl.com",
        "model": "DeepL",
        "placeholder": "https://api.deepl.com",
        "docs": "https://developers.deepl.com/docs/getting-started/auth",
    },
    "custom": {
        "name": "自定义",
        "base_url": "http://localhost:11434/v1",
        "model": "",
        "placeholder": "https://your-api.example/v1",
        "docs": "",
    },
}


def official_chat_api(url: str) -> str:
    """Recognize direct official endpoints without changing the saved UI preset.

    Third-party gateways (including lookalike hosts and nonstandard ports) keep
    their own Chat Completions contract, regardless of the configured model name.
    """
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        return ""
    return {
        "api.openai.com": "openai",
        "api.anthropic.com": "anthropic",
    }.get((parsed.hostname or "").lower(), "")


def normalize_official_chat_url(url: str) -> str:
    parsed = urlsplit(url)
    if official_chat_api(url) and parsed.path.rstrip("/") in (
        "",
        "/v1",
        "/chat/completions",
        "/v1/chat/completions",
    ):
        return f"https://{parsed.hostname.lower()}/v1"
    return url


def provider_for_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host in {"api.deepl.com", "api-free.deepl.com"}:
        return "deepl"
    if host == "api.deepseek.com":
        return "deepseek"
    if host in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    } or re.fullmatch(
        r"[a-z0-9-]+\.(?:cn-beijing|ap-southeast-1|ap-northeast-1|eu-central-1|cn-hongkong)\.maas\.aliyuncs\.com",
        host,
    ):
        return "qwen"
    return "custom"
