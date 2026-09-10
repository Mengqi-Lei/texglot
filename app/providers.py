"""Provider recognition is based on trusted API hosts, never the model name alone."""

import re
from urllib.parse import urlsplit

PROVIDERS = {
    "qwen": {
        "name": "Qwen · 百炼",
        "base_url": "",
        "model": "qwen3.7-plus",
        "placeholder": "https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "docs": "https://help.aliyun.com/zh/model-studio/first-api-call-to-qwen",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "placeholder": "https://api.deepseek.com",
        "docs": "https://api-docs.deepseek.com/",
    },
    "custom": {
        "name": "自定义",
        "base_url": "http://localhost:11434/v1",
        "model": "",
        "placeholder": "https://your-api.example/v1",
        "docs": "",
    },
}


def provider_for_url(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
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
