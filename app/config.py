from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from .providers import PROVIDERS, provider_for_url

ROOT = Path(__file__).resolve().parent.parent
SOURCE_CHECKOUT = (ROOT / "pyproject.toml").is_file() and (ROOT / "frontend").is_dir()
DEFAULT_DATA = ROOT / "data" if SOURCE_CHECKOUT else Path.home() / ".texglot"
DATA = Path(
    os.environ.get("TEXGLOT_DATA_DIR", os.environ.get("MOYI_DATA_DIR", DEFAULT_DATA))
).resolve()
DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
CONFIG = DATA / "settings.json"


class Settings(BaseModel):
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    api_key: str = ""
    target_language: str = "简体中文"
    context_guidance: bool = True
    concurrency: int = Field(default=3, ge=1, le=8)
    temperature: float = Field(default=0.2, ge=0, le=1)
    timeout: int = Field(default=180, ge=15, le=600)
    glossary: str = Field(default="", max_length=12000)
    compiler: str = "auto"

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        value = value.strip().rstrip("/")
        u = urlsplit(value)
        if (
            u.scheme not in ("https", "http")
            or not u.hostname
            or u.username
            or u.password
            or u.query
            or u.fragment
        ):
            raise ValueError("请输入有效的 API Base URL，不要包含密钥或查询参数")
        if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("远程 API 请使用 HTTPS；本地模型可使用 HTTP")
        return value.removesuffix("/chat/completions")

    @field_validator("model")
    @classmethod
    def validate_model(cls, value):
        if not value.strip() or len(value) > 200:
            raise ValueError("请输入模型名称")
        return value.strip()

    @field_validator("target_language")
    @classmethod
    def validate_language(cls, value):
        if value not in ("简体中文", "繁體中文", "English"):
            raise ValueError("暂不支持该目标语言")
        return value

    @field_validator("compiler")
    @classmethod
    def validate_compiler(cls, value):
        if value not in ("auto", "tectonic", "xelatex", "lualatex"):
            raise ValueError("无效编译器")
        return value


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def load_settings() -> Settings:
    data = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    if "api_key" not in data:
        provider = provider_for_url(data.get("base_url", "https://api.deepseek.com"))
        env = {"deepseek": "DEEPSEEK_API_KEY", "qwen": "DASHSCOPE_API_KEY"}.get(
            provider
        )
        if env:
            data["api_key"] = os.environ.get(env, "")
    return Settings(**data)


def public_settings(settings: Settings) -> dict:
    data = settings.model_dump(exclude={"api_key"})
    data["has_api_key"] = bool(settings.api_key)
    return data


def load_connections() -> dict:
    path = CONFIG.with_name("connections.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def provider_options() -> list[dict]:
    connections = load_connections()
    current = load_settings()
    connections.pop(current.base_url, None)
    connections[current.base_url] = current.model_dump(
        include={"base_url", "model", "api_key"}
    )
    result = []
    for provider, preset in PROVIDERS.items():
        saved = [
            v for url, v in connections.items() if provider_for_url(url) == provider
        ]
        chosen = saved[-1] if saved else preset
        result.append(
            {
                **preset,
                "id": provider,
                "base_url": chosen["base_url"],
                "model": chosen["model"],
                "has_api_key": bool(chosen.get("api_key")),
                "saved": bool(saved),
            }
        )
    return result


def merge_settings(old_settings: Settings, values: dict) -> Settings:
    old = old_settings.model_dump()
    values = dict(values)
    values.pop("has_api_key", None)
    provider = values.pop("provider", None)
    if provider is not None:
        if provider not in PROVIDERS:
            raise ValueError("不支持的模型服务商")
        preset = next(p for p in provider_options() if p["id"] == provider)
        values = {"base_url": preset["base_url"], "model": preset["model"]} | values
        if not values["base_url"]:
            raise ValueError("请填写百炼控制台提供的 OpenAI 兼容地址")
    if not values.get("api_key"):
        values.pop("api_key", None)
        new_url = Settings(base_url=values.get("base_url", old["base_url"])).base_url
        if new_url != old["base_url"]:
            old["api_key"] = load_connections().get(new_url, {}).get("api_key", "")
    if values.pop("clear_api_key", False):
        old["api_key"] = ""
    return Settings(**(old | values))


def save_settings(values: dict) -> Settings:
    previous = load_settings()
    settings = merge_settings(previous, values)
    connections = load_connections()
    for connection in (previous, settings):
        connections.pop(connection.base_url, None)
        connections[connection.base_url] = connection.model_dump(
            include={"base_url", "model", "api_key"}
        )
    atomic_json(CONFIG.with_name("connections.json"), connections)
    atomic_json(CONFIG, settings.model_dump())
    return settings
