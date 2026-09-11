"""TeXGlot command line client. The local service owns all durable task state."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .config import DATA
from .i18n import english
from .platforms import configure_stdio, process_options
from .runtime import server_command

ACTIVE = {"queued", "downloading", "preparing", "translating", "compiling"}
LANGUAGES = {
    "zh": "简体中文",
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
    "en": "English",
}
SUFFIXES = (".tex", ".zip", ".tar", ".tar.gz", ".tgz", ".gz")
MAX_UPLOAD = 80 * 1024 * 1024


class CLIError(Exception):
    pass


def parser():
    p = argparse.ArgumentParser(
        prog="texglot",
        description="TeXGlot · arXiv / LaTeX → translated PDF · 本地论文翻译",
        epilog="Examples:\n  texglot https://arxiv.org/abs/1706.03762\n  texglot paper.tex project.zip -o ./papers\n  texglot --batch papers.txt --language zh\n  texglot --resume TASK_ID\n  texglot --configure --model deepseek-v4-flash --key-env DEEPSEEK_API_KEY",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "inputs",
        nargs="*",
        metavar="SOURCE",
        help="arXiv link/ID or local source file · 链接、ID 或源码",
    )
    p.add_argument(
        "-b",
        "--batch",
        action="append",
        default=[],
        metavar="FILE",
        help="UTF-8 list: one source per line; repeatable · 批量清单",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("texglot-output"),
        metavar="DIR",
        help="export directory (default: ./texglot-output) · 输出目录",
    )
    p.add_argument(
        "-l",
        "--language",
        choices=LANGUAGES,
        help="translation target; default uses saved settings · 目标语言",
    )
    p.add_argument(
        "--main", default="", help="main .tex path within uploaded project · 主文件"
    )
    p.add_argument(
        "--context-guidance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="use the abstract as context; defaults to saved preference (initially on). With --configure, save the default · 上下文引导",
    )
    p.add_argument(
        "--resume",
        action="append",
        default=[],
        metavar="ID",
        help="resume/wait/export an existing task; repeatable · 恢复任务",
    )
    p.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop batch after first failure · 遇错停止",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="machine-readable result on stdout; progress on stderr",
    )
    p.add_argument(
        "--locale",
        choices=["zh", "en"],
        default="zh",
        help="message language, independent of translation target",
    )
    p.add_argument(
        "--port",
        type=int,
        default=int(
            os.environ.get("TEXGLOT_PORT", os.environ.get("MOYI_PORT", "8765"))
        ),
        help="local service port (default: 8765)",
    )
    p.add_argument(
        "--no-start",
        action="store_true",
        help="require an already running local service",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--serve",
        action="store_true",
        help="run the local web service in this terminal",
    )
    mode.add_argument("--list", action="store_true", help="list saved tasks · 查看任务")
    mode.add_argument("--status", metavar="ID", help="inspect one task · 任务详情")
    mode.add_argument(
        "--configure",
        action="store_true",
        help="save model settings; prompt securely if no flags · 配置模型",
    )
    mode.add_argument(
        "--show-config",
        action="store_true",
        help="show settings without exposing the API key",
    )
    p.add_argument("--base-url", help="API base URL (with --configure)")
    p.add_argument("--model", help="model name (with --configure)")
    p.add_argument(
        "--provider",
        choices=("qwen", "deepseek", "custom"),
        help="provider preset or saved connection (with --configure) · 模型服务商",
    )
    p.add_argument(
        "--key-env",
        metavar="NAME",
        help="read API key from named environment variable (with --configure)",
    )
    p.add_argument(
        "--clear-key", action="store_true", help="remove saved key (with --configure)"
    )
    p.add_argument(
        "--test", action="store_true", help="test API connection after --configure"
    )
    p.add_argument("--version", action="version", version="TeXGlot 1.0.4")
    return p


class Service:
    def __init__(self, port=8765, locale="zh", transport=None):
        self.url = f"http://127.0.0.1:{port}"
        self.locale = locale
        self.client = httpx.Client(
            base_url=self.url,
            timeout=30,
            trust_env=False,
            transport=transport,
            headers={"Accept-Language": locale},
        )

    def say(self, zh, en):
        print(en if self.locale == "en" else zh, file=sys.stderr, flush=True)

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, "/api" + path, **kwargs)
        except httpx.HTTPError as exc:
            raise CLIError(
                f"Local service connection failed: {type(exc).__name__}"
            ) from None
        if not response.is_success:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = f"HTTP {response.status_code}"
            raise CLIError(str(detail))
        return response.json()

    def health(self, *, timeout=2, allow_startup_timeout=False):
        try:
            response = self.client.get("/api/health", timeout=timeout)
        except httpx.ConnectError:
            return None
        except httpx.HTTPError as exc:
            if allow_startup_timeout and isinstance(exc, httpx.TimeoutException):
                return None
            raise CLIError(
                f"Local service is not responding: {type(exc).__name__}"
            ) from None
        try:
            health = response.json()
        except ValueError:
            raise CLIError(f"Port is used by another application: {self.url}") from None
        if (
            not response.is_success
            or not isinstance(health, dict)
            or health.get("name") != "TeXGlot"
            or not health.get("ok")
        ):
            raise CLIError(f"Port is used by another application: {self.url}")
        if Path(health.get("data_dir", "")).resolve() != DATA:
            raise CLIError(
                f"A different TeXGlot data directory is using {self.url}. Set TEXGLOT_PORT to another port."
            )
        return health

    def ensure(self, auto_start=True):
        if self.health():
            return
        if not auto_start:
            raise CLIError("Local service is not running. Run texglot --serve.")
        log_path = DATA / "service.log"
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "ab") as log:
            process = subprocess.Popen(
                server_command(self.client.base_url.port),
                cwd=Path(__file__).resolve().parent.parent,
                env=dict(os.environ, TEXGLOT_DATA_DIR=str(DATA), PYTHONUTF8="1"),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                **process_options(background=True),
            )
        deadline = time.monotonic() + 60
        while (remaining := deadline - time.monotonic()) > 0:
            # Only our own startup phase may outlive a brief health timeout.
            # The initial probe above must still reject an unresponsive port.
            if self.health(timeout=min(2, remaining), allow_startup_timeout=True):
                self.say(
                    f"本地服务已启动：{self.url}", f"Local service started: {self.url}"
                )
                return
            if process.poll() is not None:
                # A concurrent caller may have acquired the service lock.
                time.sleep(min(0.3, max(0, deadline - time.monotonic())))
                remaining = deadline - time.monotonic()
                if remaining > 0 and self.health(
                    timeout=min(2, remaining), allow_startup_timeout=True
                ):
                    return
                break
            time.sleep(min(0.15, max(0, deadline - time.monotonic())))
        raise CLIError(f"Could not start TeXGlot. See {log_path}")

    def wait(self, job):
        last = None
        while job["status"] in ACTIVE:
            state = (job["status"], job["progress"], job["message"])
            if state != last:
                print(
                    f"  {job['id']}  {job['progress']:3}%  {job['message']}",
                    file=sys.stderr,
                    flush=True,
                )
                last = state
            time.sleep(1)
            job = self.request("GET", f"/jobs/{job['id']}")
        return job

    def export(self, job, output: Path):
        # Job id isolates repeated inputs, similarly named papers, and batches.
        stem = (
            re.sub(
                r"[^\w.-]+", "-", job.get("arxiv_id") or job["name"], flags=re.UNICODE
            ).strip(".-")[:72]
            or "paper"
        )
        directory = output.resolve() / f"{stem}-{job['id']}"
        directory.mkdir(parents=True, exist_ok=True)
        files = {}
        for kind, filename in {
            "translated": "translated.pdf",
            "original": "original.pdf",
            "source": "translated-source.zip",
            "log": "compile.log",
        }.items():
            if kind not in job.get("artifacts", {}):
                continue
            destination = directory / filename
            # Never replace an existing export, including after a later reprocess.
            index = 2
            while destination.exists():
                destination = (
                    directory / f"{Path(filename).stem}-{index}{Path(filename).suffix}"
                )
                index += 1
            created = False
            try:
                with self.client.stream(
                    "GET", f"/api/jobs/{job['id']}/artifacts/{kind}"
                ) as response:
                    response.raise_for_status()
                    with destination.open("xb") as target:
                        created = True
                        for chunk in response.iter_bytes():
                            target.write(chunk)
            except BaseException:
                if created:
                    destination.unlink(missing_ok=True)
                raise
            files[kind] = str(destination)
        return files


def batch_sources(inputs, lists):
    """Batch paths are relative to their list, not to the caller's working directory."""
    sources = list(inputs)
    for name in lists:
        path = Path(name).expanduser().resolve()
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            if "://" not in value and (path.parent / value).is_file():
                value = str((path.parent / value).resolve())
            sources.append(value)
    return sources


def submit(service, source, language, main="", context_guidance=None):
    path = Path(source).expanduser()
    if path.is_file():
        if not path.name.lower().endswith(SUFFIXES):
            raise CLIError(
                "Unsupported source file. Use .tex, .zip, .tar, .tar.gz, .tgz, or .gz."
            )
        if not 0 < path.stat().st_size <= MAX_UPLOAD:
            raise CLIError("File is empty or exceeds 80 MB")
        with path.open("rb") as file:
            return service.request(
                "POST",
                "/jobs/file",
                data={
                    "language": language,
                    "main": main,
                    **(
                        {"context_guidance": str(context_guidance).lower()}
                        if context_guidance is not None
                        else {}
                    ),
                },
                files={"file": (path.name, file, "application/octet-stream")},
            )
    if main:
        raise CLIError(
            "--main applies only to local source files; use task details for arXiv projects"
        )
    return service.request(
        "POST",
        "/jobs/arxiv",
        json={
            "url": source,
            "language": language,
            **(
                {"context_guidance": context_guidance}
                if context_guidance is not None
                else {}
            ),
        },
    )


def configure(service, args):
    values = {}
    for key in ("provider", "base_url", "model"):
        if getattr(args, key) is not None:
            values[key] = getattr(args, key)
    if args.key_env:
        key = os.environ.get(args.key_env, "").strip()
        if not key:
            raise CLIError(f"Environment variable {args.key_env} is empty")
        values["api_key"] = key
    if args.clear_key:
        values["clear_api_key"] = True
    if args.language:
        values["target_language"] = LANGUAGES[args.language]
    if args.context_guidance is not None:
        values["context_guidance"] = args.context_guidance
    if not values:
        if not sys.stdin.isatty():
            raise CLIError(
                "Use configuration flags such as --model, --key-env or --no-context-guidance in non-interactive scripts"
            )
        old = service.request("GET", "/settings")
        values["base_url"] = (
            input(f"Base URL [{old['base_url']}]: ").strip() or old["base_url"]
        )
        values["model"] = input(f"Model [{old['model']}]: ").strip() or old["model"]
        values["api_key"] = getpass.getpass(
            "API key (blank to keep for the same endpoint): "
        )
    result = service.request("PUT", "/settings", json=values)
    if args.test:
        result["connection_test"] = service.request("POST", "/settings/test", json={})
    return result


def run(args, service):
    inputs = batch_sources(args.inputs, args.batch)
    if args.serve:
        if service.health():
            service.say(
                f"本地服务已在运行：{service.url}",
                f"Local service is already running: {service.url}",
            )
            return 0
        from .server import run as serve

        service.say(
            f"TeXGlot：{service.url} · Ctrl+C 停止",
            f"TeXGlot: {service.url} · Ctrl+C to stop",
        )
        serve(args.port)
        return 0
    if not (
        inputs
        or args.resume
        or args.configure
        or args.show_config
        or args.list
        or args.status
    ):
        raise CLIError("Batch list contains no sources")
    service.ensure(not args.no_start)
    if args.configure or args.show_config or args.list or args.status:
        if args.configure:
            value = configure(service, args)
        elif args.show_config:
            value = service.request("GET", "/settings")
        elif args.status:
            value = service.request("GET", f"/jobs/{args.status}")
        else:
            value = service.request("GET", "/jobs")
        if args.json or not args.list:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            for job in value:
                print(f"{job['id']}  {job['status']:12} {job['name']}")
        return 0
    saved = (
        service.request("GET", "/settings")
        if inputs and (args.language is None or args.context_guidance is None)
        else {}
    )
    language = (
        LANGUAGES[args.language]
        if args.language
        else saved.get("target_language", "简体中文")
    )
    guidance = (
        args.context_guidance
        if args.context_guidance is not None
        else saved.get("context_guidance", True)
    )
    output = args.output.expanduser()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    items = [(False, source) for source in inputs] + [
        (True, job_id) for job_id in args.resume
    ]
    current = None
    interrupted = False
    try:
        for index, (resume, source) in enumerate(items, 1):
            current = None
            result = {"input": source, "status": "failed", "files": {}}
            service.say(
                f"[{index}/{len(items)}] {'恢复' if resume else '翻译'} {source}",
                f"[{index}/{len(items)}] {'Resume' if resume else 'Translate'} {source}",
            )
            try:
                if resume:
                    current = service.request("GET", f"/jobs/{source}")
                    previous = current.get(
                        "context_guidance",
                        current.get("config", {}).get("context_guidance", True),
                    )
                    guidance_changed = (
                        args.context_guidance is not None
                        and args.context_guidance != previous
                    )
                    main_changed = bool(args.main and args.main != current.get("main"))
                    changed = guidance_changed or main_changed
                    if changed and current["status"] in ACTIVE:
                        raise CLIError(
                            "任务正在处理，无法切换主文件或上下文引导；请停止后重试"
                        )
                    if current["status"] not in ACTIVE | {"completed"} or changed:
                        values = {"main": args.main} if args.main else {}
                        if args.context_guidance is not None:
                            values["context_guidance"] = args.context_guidance
                        current = service.request(
                            "POST",
                            f"/jobs/{source}/retry",
                            json=values,
                        )
                else:
                    current = submit(service, source, language, args.main, guidance)
                result["id"] = current["id"]
                current = service.wait(current)
                result.update(
                    status=current["status"],
                    pages=current["pages"],
                    tokens=current["tokens"],
                    error=current.get("error", ""),
                    warnings=current.get("warnings", []),
                    context_guidance=current.get(
                        "context_guidance",
                        current.get("config", {}).get("context_guidance", True),
                    ),
                )
                result["files"] = service.export(current, output)
                if current["status"] in {"completed", "partial"}:
                    service.say(
                        f"已导出：{result['files'].get('translated', output)}",
                        f"Exported: {result['files'].get('translated', output)}",
                    )
                else:
                    service.say(
                        f"任务未完成：{current.get('error') or current['message']}",
                        f"Task did not complete: {current.get('error') or current['message']}",
                    )
            except (CLIError, OSError, httpx.HTTPError) as exc:
                result.update(status="failed", error=str(exc))
                print(f"  {exc}", file=sys.stderr)
            results.append(result)
            if args.fail_fast and result["status"] != "completed":
                break
    except KeyboardInterrupt:
        interrupted = True
        if current and current["status"] in ACTIVE:
            try:
                service.request("POST", f"/jobs/{current['id']}/cancel")
            except CLIError:
                pass
            service.say(
                f"已中断等待。用 texglot --resume {current['id']} 查看或继续任务。",
                f"Interrupted. Use texglot --resume {current['id']} to inspect or resume.",
            )
        results.append(
            {
                "input": source,
                "id": current["id"] if current else None,
                "status": "interrupted",
                "files": {},
            }
        )
    report = {
        "results": results,
        "processed": len(results),
        "remaining": len(items) - len(results),
        "completed": sum(r["status"] == "completed" for r in results),
    }
    # A unique manifest preserves batch outcomes without touching existing reports.
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="batch-",
        suffix=".json",
        dir=output,
        delete=False,
    ) as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        report["manifest"] = str(Path(file.name).resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['completed']}/{len(items)} completed · {report['manifest']}")
    return 130 if interrupted else (0 if report["completed"] == len(items) else 1)


def main(argv=None):
    configure_stdio()
    p = parser()
    args = p.parse_args(argv)
    modes = args.serve or args.list or args.status or args.configure or args.show_config
    if modes and (args.inputs or args.batch or args.resume):
        p.error("management options cannot be combined with translation inputs")
    if not args.configure and any(
        (
            args.provider,
            args.base_url,
            args.model,
            args.key_env,
            args.clear_key,
            args.test,
        )
    ):
        p.error("model configuration flags require --configure")
    if args.key_env and args.clear_key:
        p.error("--key-env and --clear-key cannot be combined")
    if args.resume and args.language:
        p.error("--resume keeps the original target language; omit --language")
    if modes and not args.configure and args.context_guidance is not None:
        p.error(
            "context guidance flags require translation inputs, --resume or --configure"
        )
    if not (modes or args.inputs or args.batch or args.resume):
        p.print_help()
        return 0
    if not 1 <= args.port <= 65535:
        p.error("port must be between 1 and 65535")
    service = Service(args.port, args.locale)
    try:
        return run(args, service)
    except (CLIError, OSError, ValueError) as exc:
        message = english(str(exc)) if args.locale == "en" else str(exc)
        if args.json:
            print(json.dumps({"error": message}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        service.client.close()


if __name__ == "__main__":
    sys.exit(main())
