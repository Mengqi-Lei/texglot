"""Stable local integration contracts for external TeXGlot clients.

The Zotero client intentionally receives a small, stable view of a job.  The
web UI and CLI can continue to evolve their richer job payload independently.
This module validates requests, selects reusable jobs, and serializes results;
task execution remains owned by :class:`app.jobs.JobManager`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from . import jobs
from .config import DATA, Settings, atomic_json, load_settings, public_settings
from .sources import MAX_UPLOAD, parse_arxiv
from .version import CORE_VERSION

INTEGRATION_API = "zotero.v1"

# Keep this map deliberately capability based.  A Zotero client must not infer
# support from the core version, because optional parser/compiler components may
# be unavailable on a particular installation.
ZOTERO_CAPABILITIES = {
    "arxiv_latex": True,
    "latex_upload": True,
    "pdf_reflow": False,
    "translated_source": True,
    "reader_deep_link": True,
    "library_reuse": True,
    "arxiv_resolution": True,
    "original_pdf": True,
}


class ZoteroIntegrationError(ValueError):
    """An error with a machine-readable code for the Zotero bridge."""

    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ZoteroSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["arxiv", "latex", "pdf"]
    id: str = Field(default="", max_length=500)
    filename: str = Field(default="source.zip", max_length=200)
    # JSON/base64 is used for the Phase 1 bridge so Zotero never has to send a
    # local filesystem path.  The API can add a streaming multipart variant in
    # a later, backwards-compatible revision.
    content_base64: str | None = Field(default=None, max_length=120 * 1024 * 1024)
    main: str = Field(default="", max_length=500)


class ZoteroResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=500)


class ZoteroImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translated_pdf: bool = True
    translated_source: bool = True
    open: Literal["comparison", "translated", "none"] = "comparison"


class ZoteroClient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="zotero", max_length=80)
    version: str = Field(default="", max_length=80)
    item_key: str = Field(default="", max_length=80)
    library_id: int | None = None


class ZoteroJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: ZoteroSource
    target_language: str = Field(default="简体中文", max_length=30)
    context_guidance: bool | None = None
    import_options: ZoteroImportOptions = Field(
        default_factory=ZoteroImportOptions, alias="import"
    )
    client: ZoteroClient = Field(default_factory=ZoteroClient)
    idempotency_key: str = Field(default="", max_length=256)
    reuse_existing: bool = True


def capabilities() -> dict[str, bool]:
    """Return a copy so callers cannot mutate the process-wide contract."""

    return dict(ZOTERO_CAPABILITIES)


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "name": "TeXGlot",
        "version": CORE_VERSION,
        "core_version": CORE_VERSION,
        "integration_api": INTEGRATION_API,
        "data_dir": str(DATA),
        "capabilities": capabilities(),
    }


def capabilities_payload() -> dict[str, Any]:
    return {
        "name": "TeXGlot",
        "version": CORE_VERSION,
        "core_version": CORE_VERSION,
        "integration_api": INTEGRATION_API,
        "capabilities": capabilities(),
    }


def _strict_arxiv_id(value: str) -> str:
    try:
        arxiv_id = parse_arxiv(value)
    except ValueError:
        raise ZoteroIntegrationError(
            "ARXIV_NOT_FOUND", "请输入有效的 arXiv 论文链接或完整 ID", status_code=400
        ) from None
    # A bare ID is intentionally rejected by this integration contract.  The
    # regular web UI may still resolve the latest version for convenience, but
    # a library integration must never silently change the requested paper.
    if not re.search(r"v[1-9]\d*$", arxiv_id, re.IGNORECASE):
        raise ZoteroIntegrationError(
            "ARXIV_VERSION_REQUIRED",
            "需要完整的 arXiv 版本号，例如 2401.12345v2",
            status_code=409,
        )
    return arxiv_id


def _decode_latex(source: ZoteroSource) -> tuple[bytes, str]:
    if not source.content_base64:
        raise ZoteroIntegrationError(
            "SOURCE_NOT_SUPPORTED",
            "LaTeX 集成请求需要提供 content_base64",
            status_code=400,
        )
    try:
        # validate=True rejects whitespace and malformed input instead of
        # silently accepting a truncated archive.
        blob = base64.b64decode(source.content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise ZoteroIntegrationError(
            "SOURCE_NOT_SUPPORTED", "LaTeX 源码不是有效的 base64 数据", status_code=400
        ) from None
    if not blob or len(blob) > MAX_UPLOAD:
        raise ZoteroIntegrationError(
            "SOURCE_NOT_SUPPORTED", "LaTeX 源码为空或超过 80 MB", status_code=400
        )
    name = source.filename.strip() or "source.zip"
    if not name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".tex")):
        raise ZoteroIntegrationError(
            "SOURCE_NOT_SUPPORTED",
            "LaTeX 源码应为 .tex、.zip、.tar、.tar.gz、.tgz 或 .gz",
            status_code=400,
        )
    return blob, name


def _settings_fingerprint(language: str, context_guidance: bool) -> str:
    settings = load_settings()
    values = public_settings(settings)
    values.update(
        target_language=language,
        context_guidance=context_guidance,
        integration_api=INTEGRATION_API,
    )
    # public_settings excludes the API key.  It is important that retrying the
    # same request never places a credential in the idempotency material.
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def normalized_request(
    request: ZoteroJobRequest,
) -> tuple[dict[str, Any], bytes | None, str | None]:
    """Validate source and return normalized fields, optional upload, and ID.

    This function does not touch the filesystem or the job manager, so malformed
    requests can be tested without starting a translation task.
    """

    try:
        # Keep language validation identical to the normal GUI/CLI path.
        Settings(target_language=request.target_language)
    except ValidationError as exc:
        raise ZoteroIntegrationError(
            "INVALID_TARGET_LANGUAGE", "暂不支持该目标语言", status_code=422
        ) from exc
    context_guidance = (
        load_settings().context_guidance
        if request.context_guidance is None
        else request.context_guidance
    )
    source = request.source
    blob: bytes | None = None
    if source.type == "arxiv":
        arxiv_id = _strict_arxiv_id(source.id)
        source_data = {"type": "arxiv", "id": arxiv_id}
        name = f"arXiv {arxiv_id}"
        main = ""
    elif source.type == "latex":
        blob, name = _decode_latex(source)
        source_data = {
            "type": "latex",
            "filename": name,
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        main = source.main.strip()
        # ``extract_source`` stores a raw .tex upload as ``main.tex``.  A
        # caller's local filename is not a path inside that generated source
        # directory, so never carry ``paper.tex`` through as an invalid main
        # selector for this single-file form.
        if name.lower().endswith(".tex"):
            main = ""
        source_data["main"] = main
    else:
        raise ZoteroIntegrationError(
            "SOURCE_NOT_SUPPORTED",
            "当前版本暂不支持 PDF 输入；请使用 arXiv 或 LaTeX 源码",
            status_code=422,
        )
    settings_fingerprint = _settings_fingerprint(
        request.target_language, context_guidance
    )
    request_key = request.idempotency_key.strip()
    fingerprint_data = {
        "source": source_data,
        "language": request.target_language,
        "context_guidance": context_guidance,
        "settings": settings_fingerprint,
        "reuse_existing": request.reuse_existing,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if request_key:
        # User keys are opaque identifiers; reject control characters that could
        # make logs or diagnostics ambiguous.
        if len(request_key) > 256 or any(ord(char) < 0x20 for char in request_key):
            raise ZoteroIntegrationError(
                "INVALID_IDEMPOTENCY_KEY", "idempotency_key 格式不正确", status_code=422
            )
        key = request_key
    else:
        key = f"sha256:{fingerprint}"
    normalized = {
        "kind": "arxiv" if source.type == "arxiv" else "file",
        "name": name,
        "arxiv_id": source_data.get("id", ""),
        "main": main,
        "language": request.target_language,
        "context_guidance": context_guidance,
        "fingerprint": fingerprint,
        "source": source_data,
        "client": request.client.model_dump(exclude_defaults=True, exclude_none=True),
        "import": request.import_options.model_dump(),
    }
    return normalized, blob, key


def find_idempotent_job(manager, key: str, fingerprint: str):
    for job in manager.jobs.values():
        integration = job.get("integration")
        bindings = job.get("integration_requests", {})
        bound = bindings.get(key) if isinstance(bindings, dict) else None
        if isinstance(integration, dict) and integration.get("idempotency_key") == key:
            bound = integration.get("fingerprint")
        if bound is None:
            continue
        if bound != fingerprint:
            raise ZoteroIntegrationError(
                "IDEMPOTENCY_CONFLICT",
                "idempotency_key 已用于另一份翻译请求",
                status_code=409,
            )
        return job
    return None


@lru_cache(maxsize=64)
def _upload_digest(path: str, size: int, mtime: int, ctime: int) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _matches_source(job: dict, normalized: dict) -> bool:
    if job.get("kind") != normalized["kind"]:
        return False
    source = normalized["source"]
    if source["type"] == "arxiv":
        # Never guess which version an old, versionless App/CLI job downloaded.
        return job.get("arxiv_id") == source["id"]
    raw_tex = str(job.get("name", "")).lower().endswith(".tex")
    if raw_tex != normalized["name"].lower().endswith(".tex"):
        return False
    main = "" if raw_tex else job.get("requested_main", job.get("main", ""))
    if main != normalized["main"]:
        return False
    digest = job.get("upload_sha256")
    if not digest:
        # Older uploads retain upload.bin. A resolved archive main is reusable
        # only when explicitly requested; its original auto-selection is unknown.
        path = jobs.JOBS / job["id"] / "upload.bin"
        try:
            stat = path.stat()
            if not 0 < stat.st_size <= MAX_UPLOAD:
                return False
            digest = _upload_digest(
                str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
            )
        except OSError:
            return False
    return digest == source["sha256"]


@lru_cache(maxsize=64)
def _readable_pdf(path: str, size: int, mtime: int, ctime: int) -> bool:
    try:
        with Path(path).open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                return False
            stream.seek(0)
            reader = PdfReader(stream)
            return not reader.is_encrypted and len(reader.pages) > 0
    except (OSError, PyPdfError, ValueError, TypeError, KeyError, RecursionError):
        return False


def _has_readable_translation(job: dict) -> bool:
    artifacts = job.get("artifacts") or {}
    relative = artifacts.get("translated")
    if not isinstance(relative, str):
        return False
    folder = (jobs.JOBS / job["id"]).resolve()
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder):
        return False
    try:
        stat = path.stat()
        return path.is_file() and _readable_pdf(
            str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
        )
    except OSError:
        return False


def find_reusable_job(manager, normalized: dict):
    # Prefer complete results, then results needing review, then active work.
    # Deterministic newest-first ordering never hides an older valid artifact.
    ranks = {"completed": 0, "partial": 1, **{status: 2 for status in jobs.ACTIVE}}
    candidates = [
        job
        for job in manager.jobs.values()
        if job.get("status") in ranks
        and job.get("language", "简体中文") == normalized["language"]
        and _matches_source(job, normalized)
    ]
    candidates.sort(
        key=lambda job: (
            max(ranks[job["status"]], 1 if job.get("warnings") else 0),
            -float(job.get("created_at", 0)),
            job["id"],
        )
    )
    for job in candidates:
        if job["status"] in jobs.ACTIVE or _has_readable_translation(job):
            return job
    return None


def create_job(manager, request: ZoteroJobRequest):
    normalized, blob, key = normalized_request(request)
    # Explicit request IDs replay the same operation even if it later failed.
    # Ordinary menu actions instead search for a currently usable result.
    if request.idempotency_key.strip():
        existing = find_idempotent_job(manager, key, normalized["fingerprint"])
        if existing is not None:
            return existing, "replay"
    if request.reuse_existing:
        existing = find_reusable_job(manager, normalized)
        if existing is not None:
            if request.idempotency_key.strip():
                existing.setdefault("integration_requests", {})[key] = normalized[
                    "fingerprint"
                ]
                # Binding a request must not reorder the user's library.
                atomic_json(jobs.JOBS / existing["id"] / "job.json", existing)
            reuse = "active" if existing["status"] in jobs.ACTIVE else "library"
            return existing, reuse
    integration = {
        "idempotency_key": key,
        "fingerprint": normalized["fingerprint"],
        "source": normalized["source"],
        "client": normalized["client"],
        "import": normalized["import"],
    }
    job = manager.create(
        normalized["kind"],
        normalized["name"],
        arxiv_id=normalized["arxiv_id"],
        blob=blob,
        main=normalized["main"],
        language=normalized["language"],
        context_guidance=normalized["context_guidance"],
        integration=integration,
    )
    return job, None


def _status(job: dict[str, Any]) -> str:
    return {
        "partial": "completed_with_warnings",
        "interrupted": "needs_retry",
    }.get(job.get("status"), job.get("status", "failed"))


def _error_payload(job: dict[str, Any]) -> dict[str, str] | None:
    if not job.get("error") and job.get("status") not in {"failed"}:
        return None
    error = str(job.get("error") or job.get("message") or "任务失败")
    if "编译" in error or "XeTeX" in error or "LaTeX" in error:
        code, message = (
            "COMPILATION_ERROR",
            "LaTeX 编译失败，请在 TeXGlot 中查看处理记录",
        )
    elif "API" in error or "模型" in error or "翻译" in error:
        code, message = "MODEL_ERROR", "模型翻译失败，请在 TeXGlot 中查看处理记录"
    elif "arXiv" in error or "arxiv" in error:
        code, message = "ARXIV_NOT_FOUND", "无法获取 arXiv 源码，请检查论文版本"
    else:
        code, message = "TASK_FAILED", "任务失败，请在 TeXGlot 中查看处理记录"
    return {"code": code, "message": message}


def serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    integration = job.get("integration")
    source = integration.get("source") if isinstance(integration, dict) else None
    if not isinstance(source, dict):
        source = {
            "type": "arxiv" if job.get("kind") == "arxiv" else "latex",
            **({"id": job["arxiv_id"]} if job.get("arxiv_id") else {}),
        }
    done = int(job.get("done", 0) or 0)
    total = int(job.get("total", 0) or 0)
    percent = int(job.get("progress", 0) or 0)
    if total and done >= total:
        percent = max(percent, 100 if _status(job).startswith("completed") else percent)
    quality = (
        "completed_with_warnings"
        if _status(job) == "completed_with_warnings" or job.get("warnings")
        else "completed"
        if _status(job) == "completed"
        else None
    )
    artifacts = job.get("artifacts") if isinstance(job.get("artifacts"), dict) else {}
    return {
        "id": job.get("id"),
        "status": _status(job),
        "source": source,
        "target_language": job.get("language", "简体中文"),
        "context_guidance": bool(job.get("context_guidance", True)),
        "progress": {
            "done": done,
            "total": total,
            "percent": min(100, max(0, percent)),
        },
        "message": job.get("message", ""),
        "quality": quality,
        "artifacts": {
            "translated_pdf": bool(artifacts.get("translated")),
            "translated_source": bool(artifacts.get("source")),
            "original_pdf": bool(artifacts.get("original")),
        },
        "error": _error_payload(job),
        "protocol": INTEGRATION_API,
    }
