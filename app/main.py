from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .compiler import available_compilers
from .config import (
    DATA,
    ROOT,
    Settings,
    load_settings,
    merge_settings,
    provider_options,
    public_settings,
    save_settings,
)
from .i18n import localize_payload
from .jobs import ACTIVE, JOBS, JobManager
from .llm import ProviderError, Translator
from .reader import (
    AnnotationInput,
    AnnotationPatch,
    ReaderStore,
    ReadingState,
    document_info,
)
from .sources import MAX_UPLOAD, parse_arxiv

manager = JobManager()
reader_store = ReaderStore(JOBS)


@asynccontextmanager
async def lifespan(app):
    yield
    await manager.close()


app = FastAPI(title="TeXGlot", lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
)


@app.middleware("http")
async def local_only(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail": "只接受本地页面发起的请求"}, 403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "禁止跨站请求"}, 403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def response_language(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api") and response.headers.get(
        "content-type", ""
    ).startswith("application/json"):
        response.headers["Vary"] = "Accept-Language"
        locale = (
            request.headers.get("accept-language", "zh")
            .split(",")[0]
            .split(";")[0]
            .strip()
            .lower()
        )
        if locale.startswith("en"):
            body = b"".join([chunk async for chunk in response.body_iterator])
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return JSONResponse(
                localize_payload(json.loads(body)),
                status_code=response.status_code,
                headers=headers,
                background=response.background,
            )
    return response


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(KeyError)
async def key_error(request, exc):
    return JSONResponse({"detail": "任务不存在"}, status_code=404)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "name": "TeXGlot",
        "compilers": available_compilers(),
        "data_dir": str(DATA),
        "version": "1.0.0",
    }


@app.get("/api/settings")
def settings_get():
    return public_settings(load_settings())


@app.get("/api/providers")
def providers_get():
    return provider_options()


@app.put("/api/settings")
async def settings_put(request: Request):
    values = await request.json()
    try:
        return public_settings(save_settings(values))
    except ValidationError as exc:
        raise HTTPException(400, "; ".join(e["msg"] for e in exc.errors())) from None


@app.post("/api/settings/test")
async def settings_test(request: Request):
    values = await request.json()
    client = Translator(merge_settings(load_settings(), values))
    try:
        return await client.test()
    except (ProviderError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from None
    finally:
        await client.close()


@app.get("/api/jobs")
def job_list():
    return sorted(manager.jobs.values(), key=lambda x: x["created_at"], reverse=True)


class TranslationOptions(BaseModel):
    context_guidance: bool | None = None


class ArxivInput(TranslationOptions):
    url: str = Field(max_length=500)
    language: str = "简体中文"


class ExampleInput(TranslationOptions):
    language: str = "简体中文"


class RetryInput(TranslationOptions):
    main: str = ""


def validate_language(language):
    Settings(target_language=language)


@app.post("/api/jobs/arxiv", status_code=202)
async def job_arxiv(data: ArxivInput):
    arxiv_id = parse_arxiv(data.url)
    validate_language(data.language)
    return manager.create(
        "arxiv",
        f"arXiv {arxiv_id}",
        arxiv_id=arxiv_id,
        language=data.language,
        context_guidance=data.context_guidance,
    )


@app.post("/api/jobs/file", status_code=202)
async def job_file(
    file: UploadFile = File(...),
    language: str = Form("简体中文"),
    main: str = Form(""),
    context_guidance: bool | None = Form(None),
):
    validate_language(language)
    name = file.filename or "source.zip"
    if not name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".tex")):
        raise HTTPException(400, "支持 .tex、.zip、.tar、.tar.gz 和 .tgz 源码文件")
    blob = await file.read(MAX_UPLOAD + 1)
    await file.close()
    if not blob or len(blob) > MAX_UPLOAD:
        raise HTTPException(400, "文件为空或超过 80 MB")
    return manager.create(
        "file",
        name,
        blob=blob,
        main=main,
        language=language,
        context_guidance=context_guidance,
    )


@app.post("/api/jobs/example", status_code=202)
async def job_example(data: ExampleInput | None = None):
    options = data or ExampleInput()
    validate_language(options.language)
    return manager.create(
        "arxiv",
        "Attention Is All You Need",
        arxiv_id="1706.03762v7",
        language=options.language,
        context_guidance=options.context_guidance,
    )


@app.get("/api/jobs/{job_id}")
def job_get(job_id: str):
    return manager.get(job_id)


@app.post("/api/jobs/{job_id}/cancel")
async def job_cancel(job_id: str):
    await manager.cancel(job_id)
    return manager.get(job_id)


@app.post("/api/jobs/{job_id}/retry")
async def job_retry(job_id: str, data: RetryInput):
    job = manager.get(job_id)
    if job["status"] in ACTIVE:
        raise HTTPException(409, "任务正在处理")
    if data.main:
        if data.main not in job.get("candidates", []):
            raise HTTPException(400, "主文件无效")
        job["main"] = data.main
    if data.context_guidance is not None:
        job["context_guidance"] = data.context_guidance
    manager.start(job_id)
    return job


@app.get("/api/jobs/{job_id}/artifacts/{kind}")
def artifact(job_id: str, kind: str, download: bool = False, version: str = ""):
    job = manager.get(job_id)
    relative = job["artifacts"].get(kind)
    if kind == "log" and not relative:
        logs = []
        for priority, candidate in enumerate(
            (
                "build-translated/compile.log",
                "build-probe/compile.log",
                "build-original/compile.log",
                "build-dependencies/compile.log",
            )
        ):
            path = JOBS / job_id / candidate
            try:
                if path.is_file():
                    logs.append((path.stat().st_mtime_ns, -priority, candidate))
            except OSError:
                continue
        if logs:
            relative = max(logs)[2]
    if not relative or not (JOBS / job_id / relative).is_file():
        raise HTTPException(404, "文件尚未生成")
    if (
        version
        and kind in ("original", "translated")
        and document_info(JOBS / job_id / relative)["version"] != version
    ):
        raise HTTPException(409, "PDF 已更新，请重新打开阅读器")
    media = (
        "application/pdf"
        if kind in ("original", "translated")
        else "application/zip"
        if kind == "source"
        else "text/plain"
    )
    filename = {
        "translated": "texglot-translated.pdf",
        "original": "original.pdf",
        "source": "translated-source.zip",
        "log": "compile.log",
    }[kind]
    return FileResponse(
        JOBS / job_id / relative,
        media_type=media,
        filename=filename if download else None,
    )


@app.get("/api/jobs/{job_id}/reader")
def reader_get(job_id: str):
    return reader_store.get(manager.get(job_id))


@app.post("/api/jobs/{job_id}/annotations")
def annotation_create(job_id: str, data: AnnotationInput):
    return reader_store.create(manager.get(job_id), data)


@app.patch("/api/jobs/{job_id}/annotations/{annotation_id}")
def annotation_patch(job_id: str, annotation_id: str, data: AnnotationPatch):
    return reader_store.patch(manager.get(job_id), annotation_id, data)


@app.put("/api/jobs/{job_id}/reader/position")
def reader_position(job_id: str, data: ReadingState):
    return reader_store.position(manager.get(job_id), data)


dist = ROOT / "frontend" / "dist"
if not dist.is_dir():
    dist = Path(__file__).parent / "web"
if (dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
if (dist / "pdfjs").exists():
    app.mount("/pdfjs", StaticFiles(directory=dist / "pdfjs"), name="pdfjs")


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    if path == "THIRD_PARTY_LICENSES.txt":
        notices = dist / path
        if not notices.is_file():
            raise HTTPException(404)
        return FileResponse(notices, media_type="text/plain; charset=utf-8")
    if (dist / "index.html").exists():
        return FileResponse(dist / "index.html")
    return HTMLResponse(
        """<!doctype html><html lang="zh"><meta charset="utf-8"><title>TeXGlot · 本地设置</title><style>body{font:16px system-ui;max-width:600px;margin:100px auto;background:#f5f5f7;color:#1d1d1f}input,button{padding:14px;margin:12px 0;width:100%;box-sizing:border-box}button{background:#0071e3;color:white;border:0}</style><h1>TeXGlot · 本地设置</h1><p>界面构建中。API key 仅保存至本地服务。</p><form id="f"><label>模型 API key<input id="key" type="password" autocomplete="off"></label><button>保存本地配置</button></form><p id="result"></p><script>f.onsubmit=async e=>{e.preventDefault();const r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:key.value})});result.textContent=r.ok?'配置已保存':'保存失败';if(r.ok)key.value='';}</script></html>"""
    )
