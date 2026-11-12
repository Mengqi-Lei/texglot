"""Validate user-supplied gateway headers without exposing their values."""

import re

MAX_HEADERS = 16
MAX_NAME_LENGTH = 128
MAX_VALUE_LENGTH = 4096
MAX_TOTAL_BYTES = 16384
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
# Authentication and message framing remain under TeXGlot/httpx control.
RESERVED_HEADERS = frozenset(
    {
        "authorization",
        "host",
        "content-length",
        "content-type",
        "content-encoding",
        "accept-encoding",
        "connection",
        "keep-alive",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "expect",
    }
)


def validate_extra_headers(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("额外请求头必须是名称和值均为字符串的 JSON 对象")
    if len(value) > MAX_HEADERS:
        raise ValueError("额外请求头最多 16 项")
    result = {}
    size = 0
    for name, text in value.items():
        if not isinstance(name, str) or not isinstance(text, str):
            raise ValueError("额外请求头必须是名称和值均为字符串的 JSON 对象")
        if len(name) > MAX_NAME_LENGTH or not HEADER_NAME.fullmatch(name):
            raise ValueError("请求头名称无效，须为 HTTP token 且不超过 128 个字符")
        name = name.lower()
        if name in RESERVED_HEADERS:
            raise ValueError(
                "不能覆盖 Authorization、Host、Content-Type 或传输控制请求头"
            )
        if name in result:
            raise ValueError("请求头名称不能重复（不区分大小写）")
        if len(text) > MAX_VALUE_LENGTH:
            raise ValueError("单个请求头的值不能超过 4096 个字符")
        if any(not 32 <= ord(char) <= 126 for char in text):
            raise ValueError("请求头值不能包含换行、控制字符或非 ASCII 字符")
        size += len(name) + len(text) + 4
        if size > MAX_TOTAL_BYTES:
            raise ValueError("额外请求头总大小不能超过 16 KiB")
        # Surrounding spaces have no field-value semantics and h11 rejects them.
        # Preserve internal/quoted spaces while accepting pasted credentials.
        result[name] = text.strip(" ")
    return result


def extra_header_names(value: object) -> list[str]:
    # A manually damaged inactive profile must not leak raw input or stop the
    # settings screen from opening. Activating it still requires validation.
    try:
        return sorted(validate_extra_headers(value))
    except ValueError:
        return []
