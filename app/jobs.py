from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
import uuid
import zipfile
from bisect import bisect_right
from pathlib import Path

from pypdf import PdfReader

from .compiler import (
    break_long_code_identifiers,
    choose_compiler,
    compile_pdf,
    compiled_dependencies,
    fit_tables,
    inject_preamble,
    prepare_chinese,
    prepare_engine_sources,
    probe_source_dependencies,
    rebase_project_paths,
    use_bundled_bibliography,
)
from .config import DATA, ROOT, Settings, atomic_json, load_settings, public_settings
from .graphics import prepare_eps
from .latex import (
    apply_translations,
    classify_source_contexts,
    collect_literal_macros,
    collect_math_aliases,
    collect_numeric_registers,
    collect_prose_arguments,
    collect_text_macros,
    collect_title_macros,
    extract_paper_title,
    segments,
)
from .llm import (
    PROMPT_VERSION,
    ProviderError,
    Translator,
    normalize_language,
    redact,
    validate_translation_language,
)
from .paper_context import extract_paper_context
from .sources import download_arxiv, extract_source, find_main

JOBS = DATA / "jobs"
JOBS.mkdir(exist_ok=True)
ACTIVE = {"queued", "downloading", "preparing", "translating", "compiling"}
SOURCE_PREPARATION_VERSION = "native-source-v3"
TITLE_METADATA_VERSION = 1


def refresh_title_metadata(job: dict, folder: Path):
    """Upgrade display-only metadata once, without reordering or rerunning jobs."""
    if (
        job.get("kind") != "arxiv"
        or job.get("title_metadata_version") == TITLE_METADATA_VERSION
    ):
        return
    try:
        source = folder / "prepared-source"
        if not source.is_dir():
            source = folder / "source"
        source = source.resolve()
        main = job.get("main", "")
        dependencies = job.get("source_dependencies", job.get("source_files", []))
        if not isinstance(main, str) or not isinstance(dependencies, list):
            raise ValueError("Invalid source metadata")
        names = list(dict.fromkeys([main, *dependencies]))
        if not main or len(names) > 256:
            raise ValueError("Source metadata limit")
        remaining, texts = 4 * 1024 * 1024, {}
        for name in names:
            path = (source / name).resolve()
            if not path.is_relative_to(source):
                raise ValueError("Invalid source path")
            with path.open("rb") as stream:
                blob = stream.read(remaining + 1)
            remaining -= len(blob)
            if remaining < 0:
                raise ValueError("Source metadata limit")
            texts[name] = blob.decode("utf-8")
        if title := extract_paper_title(
            texts[main], macro_context="\n".join(texts.values())
        ):
            job["name"] = title
    except (OSError, ValueError, TypeError, RecursionError):
        # Missing or malformed old sources must not block loading their PDFs.
        pass
    job["title_metadata_version"] = TITLE_METADATA_VERSION
    try:
        # persist() updates updated_at; a metadata migration must preserve it.
        atomic_json(folder / "job.json", job)
    except OSError:
        pass


def project_signature(source: Path, main: str, engine: str) -> str:
    """Bind the original PDF to every prepared source, template and asset."""
    digest = hashlib.sha256()
    digest.update(json.dumps(["project-v1", main, engine]).encode())
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        relative = path.relative_to(source).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


class JobManager:
    def __init__(self):
        self.jobs = {}
        self.tasks = {}
        self.slot = asyncio.Semaphore(1)
        for path in JOBS.glob("*/job.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(data, dict)
                    or not isinstance(data.get("id"), str)
                    or not isinstance(data.get("status"), str)
                ):
                    continue
                refresh_title_metadata(data, path.parent)
                if data["status"] in ACTIVE:
                    data.update(
                        status="interrupted",
                        message="上次服务停止，译文已保存，点击继续即可恢复",
                    )
                self.jobs[data["id"]] = data
            except (OSError, ValueError, KeyError):
                continue

    def get(self, job_id):
        if job_id not in self.jobs:
            raise KeyError("任务不存在")
        return self.jobs[job_id]

    def persist(self, job):
        job["updated_at"] = time.time()
        atomic_json(JOBS / job["id"] / "job.json", job)

    def update(self, job, **values):
        job.update(values)
        self.persist(job)

    async def log(self, job, message):
        job["logs"].append({"time": time.time(), "message": message})
        job["logs"] = job["logs"][-160:]
        self.update(job, message=message)

    def create(
        self,
        kind,
        name,
        *,
        arxiv_id="",
        blob=None,
        main="",
        language="简体中文",
        context_guidance: bool | None = None,
    ):
        job_id = uuid.uuid4().hex[:16]
        folder = JOBS / job_id
        folder.mkdir(mode=0o700)
        if blob is not None:
            (folder / "upload.bin").write_bytes(blob)
        job = {
            "id": job_id,
            "kind": kind,
            "name": name,
            "arxiv_id": arxiv_id,
            "main": main,
            "language": language,
            "context_guidance": (
                load_settings().context_guidance
                if context_guidance is None
                else context_guidance
            ),
            "status": "queued",
            "progress": 0,
            "message": "等待开始",
            "created_at": time.time(),
            "updated_at": time.time(),
            "done": 0,
            "total": 0,
            "tokens": 0,
            "cached": 0,
            "warnings": [],
            "logs": [],
            "artifacts": {},
            "pages": 0,
        }
        self.jobs[job_id] = job
        self.persist(job)
        self.start(job_id)
        return job

    def start(self, job_id):
        if job_id in self.tasks and not self.tasks[job_id].done():
            raise ValueError("任务已在运行")
        self.update(
            self.get(job_id), status="queued", progress=0, message="等待处理", error=""
        )
        self.tasks[job_id] = asyncio.create_task(self.run(job_id))

    async def cancel(self, job_id):
        job = self.get(job_id)
        task = self.tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if job["status"] in ACTIVE | {"interrupted"}:
            self.update(
                job, status="cancelled", message="任务已停止，已完成段落会在继续时复用"
            )

    async def close(self):
        pending = [t for t in self.tasks.values() if not t.done()]
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def run(self, job_id):
        job = self.get(job_id)
        settings = None
        try:
            settings = load_settings()
            settings.target_language = job["language"]
            # Keep each task's chosen mode across queues, restarts and default changes.
            settings.context_guidance = job.get(
                "context_guidance", job.get("config", {}).get("context_guidance", True)
            )
            async with self.slot:
                await self.pipeline(job, settings)
        except asyncio.CancelledError:
            self.update(
                job, status="interrupted", message="任务已暂停，已完成段落已保存"
            )
            raise
        except Exception as exc:
            error = redact(str(exc), settings.api_key if settings else "")
            self.update(job, status="failed", error=error, message=error[:180])
            await self.log(job, error[:1200])

    async def pipeline(self, job, settings: Settings):
        folder = JOBS / job["id"]
        source = folder / "source"
        work = folder / "translated"

        async def log(message):
            await self.log(job, message)

        engine = choose_compiler(settings.compiler)
        self.update(
            job,
            warnings=[],
            engine=engine,
            config=public_settings(settings),
            context_guidance=settings.context_guidance,
            artifacts={},
            pages=0,
        )
        if not (folder / "source-ready").exists():
            blob_path = folder / "upload.bin"
            if job["kind"] == "arxiv" and not blob_path.exists():
                self.update(job, status="downloading", progress=3)
                await log("正在从 arXiv 获取 LaTeX 源码")
                await download_arxiv(job["arxiv_id"], blob_path, log)
            self.update(job, status="preparing", progress=9)
            await log("解压源码并识别主文件")
            if source.exists():
                shutil.rmtree(source)
            extract_source(blob_path.read_bytes(), job["name"], source)
            (folder / "source-ready").touch()
        main, candidates = find_main(source, job.get("main", ""))
        job["main"] = main
        job["candidates"] = candidates
        if len(candidates) > 1:
            await log(
                f"检测到 {len(candidates)} 个主文件，使用 {main}；可在任务中切换后重新编译"
            )
        reachable = self.reachable_files(source, main)
        if any(
            r"\includepdf" in (source / p).read_text(encoding="utf-8")
            for p in reachable
        ) and not any(
            segments((source / p).read_text(encoding="utf-8")) for p in reachable
        ):
            raise ValueError(
                "这篇论文的 arXiv 源码只是 PDF 包装文件，没有可翻译的 LaTeX 正文。请上传作者提供的真实 LaTeX 工程"
            )
        prepared_source = folder / "prepared-source"
        preparation = [
            SOURCE_PREPARATION_VERSION,
            project_signature(source, main, engine),
        ]
        reusable_source = (
            prepared_source.is_dir()
            and job.get("preparation_signature") == preparation
            and job.get("original_signature")
            == project_signature(prepared_source, main, engine)
        )
        if not reusable_source:
            if prepared_source.exists():
                shutil.rmtree(prepared_source)
            shutil.copytree(source, prepared_source)
            prepare_engine_sources(prepared_source, engine)
            relocated = rebase_project_paths(prepared_source, main)
            if relocated:
                await log(
                    "已将错位的父目录引用定位到源码包内的同路径文件："
                    + "、".join(relocated)
                )
            for p in prepared_source.rglob("*.tex"):
                p.write_text(
                    use_bundled_bibliography(p.read_text(encoding="utf-8"), p),
                    encoding="utf-8",
                )
            eps_dependencies = reachable
            eps_images = None
            if engine == "tectonic" and any(
                path.is_file() and path.suffix.lower() == ".eps"
                for path in prepared_source.rglob("*")
            ):
                await log("检查 EPS 插图的实际源码依赖")
                eps_dependencies, used_eps = await probe_source_dependencies(
                    prepared_source, main, folder / "build-dependencies", log
                )
                eps_images = [prepared_source / value for value in used_eps]
            await prepare_eps(
                prepared_source,
                main,
                log,
                source_files=eps_dependencies,
                used_images=eps_images,
            )
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(prepared_source, work)
        if settings.target_language != "English":
            shutil.copytree(
                ROOT / "app/resources/fonts",
                work / Path(main).parent / "texglot-fonts",
                dirs_exist_ok=True,
            )
        self.update(job, status="preparing", progress=12)
        await log(f"主文件 {main} · 使用 {engine} 检查原文编译")
        original_path = folder / "original.pdf"
        signature = project_signature(prepared_source, main, engine)
        dependencies = (
            compiled_dependencies(
                prepared_source, main, folder / "build-original", engine
            )
            if original_path.exists() and job.get("original_signature") == signature
            else None
        )
        if not dependencies or main not in dependencies:
            dependencies = None
        if dependencies is None:
            pdf, warns = await compile_pdf(
                prepared_source, main, folder / "build-original", engine, log
            )
            shutil.copy2(pdf, original_path)
            job["original_signature"] = project_signature(prepared_source, main, engine)
            job["original_warnings"] = warns
            dependencies = compiled_dependencies(
                prepared_source, main, folder / "build-original", engine
            )
        job["preparation_signature"] = preparation
        job["warnings"].extend(job.get("original_warnings", []))
        if not dependencies or main not in dependencies:
            dependencies = reachable
            warning = "编译依赖记录不可用，已按静态引用识别正文；请检查是否存在遗漏"
            job["warnings"].append(warning)
            await log(warning)
        dependencies = sorted(set(dependencies) | {main})
        reachable = [p for p in dependencies if Path(p).suffix.lower() == ".tex"]
        job["source_dependencies"] = dependencies
        job["source_files"] = reachable
        job["artifacts"]["original"] = "original.pdf"
        macro_context = "\n".join(
            (prepared_source / rel).read_text(encoding="utf-8") for rel in dependencies
        )
        title_macros = collect_title_macros(macro_context)
        main_text = (work / main).read_text(encoding="utf-8")
        if job["kind"] == "arxiv":
            if name := extract_paper_title(
                main_text, title_macros=title_macros, macro_context=macro_context
            ):
                job["name"] = name
            job["title_metadata_version"] = TITLE_METADATA_VERSION
        # Translate the TeX files the original compilation actually consumed.
        # Macro-driven includes and inactive conditionals cannot be determined
        # reliably by matching input/include strings alone.
        files, all_items, locations, source_outputs = {}, [], {}, {}
        text_macros = collect_text_macros(macro_context)
        math_aliases = collect_math_aliases(macro_context)
        literal_macros = collect_literal_macros(macro_context)
        numeric_registers = collect_numeric_registers(macro_context)
        prose_arguments = collect_prose_arguments(macro_context)
        opaque_files, mixed_files = classify_source_contexts(
            prepared_source, main, reachable, math_aliases=math_aliases
        )
        translation_files = [
            rel for rel in reachable if rel not in opaque_files | mixed_files
        ]
        job["translation_files"] = translation_files
        job["opaque_source_files"] = sorted(opaque_files)
        job["mixed_source_files"] = sorted(mixed_files)
        if opaque_files:
            await log(f"已保留 {len(opaque_files)} 个图形或公式源码文件的原始内容")
        if mixed_files:
            warning = "以下源码同时用于正文和图形或公式，已保留原样：" + "、".join(
                sorted(mixed_files)
            )
            job["warnings"].append(warning)
            await log(warning)
        for rel in translation_files:
            text = (prepared_source / rel).read_text(encoding="utf-8")
            items = segments(
                text,
                text_macros=text_macros,
                math_aliases=math_aliases,
                literal_macros=literal_macros,
                numeric_registers=numeric_registers,
                prose_arguments=prose_arguments,
                title_macros=title_macros,
            )
            files[rel] = (text, items)
            all_items.extend(items)
            line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
            for item in items:
                line = bisect_right(line_starts, item.start)
                try:
                    item.validate_source_map()
                    source_outputs[item.key] = item.target_probe(
                        settings.target_language
                    )
                except ValueError:
                    raise ValueError(f"源码分段还原检查失败（{rel}:{line}）") from None
                locations.setdefault(item.key, (rel, line))
        unique = {s.key: s for s in all_items}
        if not unique:
            raise ValueError("没有找到可翻译的正文，请检查主文件或自定义宏")

        compatibility_prefix = ""

        def write_sources(outputs):
            # Preflight and final output must run exactly the same transformations.
            # Otherwise a layout-only change can first fail after paid translation.
            table_count = 0
            for rel, (text, items) in files.items():
                output = apply_translations(text, items, outputs)
                output = break_long_code_identifiers(output, math_aliases=math_aliases)
                output, fitted = fit_tables(output)
                table_count += fitted
                if rel == main:
                    output = prepare_chinese(output, settings.target_language, engine)
                    output = compatibility_prefix + output
                (work / rel).write_text(output, encoding="utf-8")
            if table_count:
                main_path = work / main
                main_path.write_text(
                    inject_preamble(
                        main_path.read_text(encoding="utf-8"),
                        r"\usepackage{adjustbox}" + "\n",
                    ),
                    encoding="utf-8",
                )
            return table_count

        write_sources(source_outputs)
        probe_source = (work / main).read_text(encoding="utf-8")
        await log("检查目标语言字体与论文模板的兼容性")
        await compile_pdf(work, main, folder / "build-probe", engine, log)
        probe_output = (work / main).read_text(encoding="utf-8")
        if probe_output.endswith(probe_source):
            compatibility_prefix = probe_output[: len(probe_output) - len(probe_source)]
        self.update(
            job, status="translating", progress=25, total=len(unique), done=0, cached=0
        )
        await log(f"已提取 {len(unique)} 个段落，公式、引用和排版指令已保护")
        context = (
            extract_paper_context(prepared_source, main, source_files=translation_files)
            if settings.context_guidance
            else ""
        )
        if not settings.context_guidance:
            await log("上下文引导已关闭，仅翻译当前段落")
        elif context:
            await log(f"使用论文摘要作为翻译背景（{len(context)} 字符）")
        else:
            await log("未识别到论文摘要，本次不附加论文背景")
        config_hash = hashlib.sha256(
            json.dumps(
                {
                    "version": PROMPT_VERSION,
                    "base": settings.base_url,
                    "model": settings.model,
                    "language": settings.target_language,
                    "glossary": settings.glossary,
                    "paper_context": context,
                    "context_guidance": settings.context_guidance,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cache_path = folder / f"cache-{config_hash[:16]}.json"
        cache = {}
        if cache_path.exists():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
                if not isinstance(cache, dict):
                    raise ValueError("Invalid cache root")
            except (ValueError, UnicodeError):
                # Keep the damaged file available for diagnosis without letting
                # it prevent resumption or overwrite a fresh, valid cache.
                cache_path.rename(
                    cache_path.with_name(
                        cache_path.stem + f"-invalid-{uuid.uuid4().hex[:8]}.json"
                    )
                )
                cache = {}
                await log("翻译缓存无法读取，已保留副本；本次重新翻译相关段落")
        translated = {}
        for key, item in unique.items():
            if key in cache:
                try:
                    if not isinstance(cache[key], str):
                        raise ValueError("Invalid cached translation")
                    cache[key] = normalize_language(
                        cache[key], settings.target_language
                    )
                    validate_translation_language(
                        item, cache[key], settings.target_language
                    )
                    translated[key] = item.restore(cache[key])
                except ValueError:
                    cache.pop(key, None)
        job["cached"] = len(translated)
        job["done"] = len(translated)
        client = Translator(settings)
        semaphore = asyncio.Semaphore(settings.concurrency)
        failed = []

        async def one(key, item):
            if key in translated:
                return
            async with semaphore:
                feedback = ""
                for attempt in range(3):
                    try:
                        output = await (
                            client.translate_slots(item, context, feedback)
                            if attempt == 2
                            else client.translate(item, context, feedback)
                        )
                        validate_translation_language(
                            item, output, settings.target_language
                        )
                        restored = item.restore(output)
                        translated[key] = restored
                        cache[key] = output
                        atomic_json(cache_path, cache)
                        break
                    except ProviderError:
                        raise
                    except ValueError as exc:
                        feedback = str(exc)
                        if attempt == 2:
                            failed.append(key)
                            rel, line = locations[key]
                            await log(
                                f"有一段译文未通过结构检查，保留原文：{feedback} "
                                f"[segment {key[:12]} · {rel}:{line}]"
                            )
                job["done"] += 1
                self.update(
                    job,
                    progress=25 + int(60 * job["done"] / job["total"]),
                    message=f"正在翻译 · {job['done']} / {job['total']} 段落",
                    tokens=job.get("previous_tokens", 0) + client.tokens,
                )

        pending = [asyncio.create_task(one(k, v)) for k, v in unique.items()]
        try:
            await asyncio.gather(*pending)
        except BaseException:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise
        finally:
            job["previous_tokens"] = job.get("previous_tokens", 0) + client.tokens
            job["tokens"] = job["previous_tokens"]
            await client.close()
            self.persist(job)
        table_count = write_sources(translated)
        if table_count:
            await log(f"为 {table_count} 个表格设置页宽上限，避免译文溢出页边距")
        if failed:
            job["warnings"].append(
                f"{len(failed)} / {len(unique)} 段落未通过翻译检查，PDF 对应位置保留了原文，可点击继续重试"
            )
        self.update(job, status="compiling", progress=90)
        await log("译文已保存，正在编译 PDF 并解析交叉引用")
        try:
            pdf, warns = await compile_pdf(
                work, main, folder / "build-translated", engine, log
            )
        finally:
            # Include compiler adaptations in the source export, even on failure.
            archive = folder / "translated-source.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                for p in work.rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(work))
            job["artifacts"]["source"] = archive.name
        job["warnings"].extend(warns)
        job["warnings"] = list(dict.fromkeys(job["warnings"]))
        shutil.copy2(pdf, folder / "translated.pdf")
        reader = PdfReader(folder / "translated.pdf")
        if not reader.pages:
            raise ValueError("输出 PDF 没有页面")
        job["artifacts"]["translated"] = "translated.pdf"
        job["artifacts"]["log"] = "build-translated/compile.log"
        self.update(
            job,
            status="partial" if failed else "completed",
            progress=100,
            pages=len(reader.pages),
            message="翻译完成" if not failed else "已完成，部分段落保留原文",
        )
        await log(f"PDF 已生成 · {len(reader.pages)} 页 · {job['tokens']:,} tokens")

    @staticmethod
    def reachable_files(source: Path, main: str):
        source = source.resolve()
        seen = set()

        def visit(rel):
            if rel in seen:
                return
            seen.add(rel)
            text = (source / rel).read_text(encoding="utf-8")
            from .sources import without_comments

            for m in re.finditer(
                r"\\(?:input|include\*?|subfile)(?![A-Za-z@])\s*(?:\{([^}]+)\}|([^\s{}%]+))",
                without_comments(text),
            ):
                name = (m.group(1) or m.group(2)).strip()
                if not name.endswith(".tex"):
                    name += ".tex"
                for candidate in (
                    source / Path(main).parent / name,
                    source / Path(rel).parent / name,
                    source / name,
                ):
                    candidate = candidate.resolve()
                    if (
                        candidate.is_relative_to(source.resolve())
                        and candidate.is_file()
                    ):
                        visit(candidate.relative_to(source).as_posix())
                        break

        visit(main)
        return sorted(seen)
