"""Native platform smoke check with a local model stub; no paid API calls."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import platform
import re
import socket
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.platforms import (  # noqa: E402
    configure_stdio,
    process_options,
    terminate_process_tree,
)
from scripts.install_compiler import install  # noqa: E402

SOURCE = r"""\documentclass{article}
\usepackage[accsupp]{axessibility}
\usepackage{graphicx,minted}
\title{Platform check}
\author{TeXGlot}
\begin{document}
\maketitle
\begin{abstract}We verify a formula and a reference.\end{abstract}
\section{Method}\label{sec:method}
We preserve \(E=mc^2\) and see Section~\ref{sec:method}.
The Greek letter alpha is a parameter.
\end{document}
"""


def translate(text):
    for original, target in {
        "Platform check": "平台检查",
        "We verify a formula and a reference.": "我们验证公式与引用。",
        "Method": "方法",
        "We preserve ": "我们保留",
        " and see Section": "，并参见章节",
        "Native description.": "本地说明。",
        "Native table.": "本地表格。",
        "The Greek letter alpha is a parameter.": "希腊字母 α 是参数。",
    }.items():
        text = text.replace(original, target)
    return text


class Model(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = json.loads(request["messages"][-1]["content"])
        if "slots" in prompt:
            content = json.dumps(
                {key: translate(value) for key, value in prompt["slots"].items()},
                ensure_ascii=False,
            )
        else:
            content = translate(prompt["paragraph"])
        content = "<think>TEST_REASONING</think><answer>" + content + "</answer>"
        output = json.dumps(
            {
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 20},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(output)))
        self.end_headers()
        self.wfile.write(output)


async def run(output, portable_compiler, engine=None, eps=False):
    folder = output.resolve() / "用户 研究 & data"
    data = folder / "data"
    data.mkdir(parents=True, exist_ok=True)
    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    with socket.socket() as temporary:
        temporary.bind(("127.0.0.1", 0))
        port = temporary.getsockname()[1]
    env = dict(os.environ, TEXGLOT_DATA_DIR=str(data), PYTHONUTF8="1")
    if engine:
        engine = engine.resolve()
        # Prove that the frozen program does not need checkout modules or a PATH compiler.
        env.pop("PYTHONPATH", None)
        env["PATH"] = (
            str(Path(os.environ["SystemRoot"]) / "System32")
            if os.name == "nt"
            else "/usr/bin:/bin:/usr/sbin:/sbin"
        )
    if portable_compiler:
        binary = install(data / "tools")
        env["PATH"] = str(binary.parent) + os.pathsep + env.get("PATH", "")
    (data / "settings.json").write_text(
        json.dumps(
            {
                "base_url": f"http://127.0.0.1:{model.server_port}/v1",
                "model": "platform-smoke",
                "api_key": "",
                "compiler": "tectonic",
                "glossary": "保持公式",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source = folder / "论文 sample.tex"
    source.write_text(SOURCE, encoding="utf-8")
    font_archive = folder / "字体与代码示例.zip"
    with zipfile.ZipFile(font_archive, "w") as zipped:
        zipped.writestr(
            "font-proof.cls",
            "\\ProvidesClass{font-proof}\n\\LoadClass{article}\n"
            "\\RequirePackage{unicode-math}\n"
            "\\setmathfont{libertinusmath-regular.otf}\n",
        )
        zipped.writestr(
            "listing.sty",
            "\\RequirePackage{fancyvrb}\n"
            "\\DefineVerbatimEnvironment{ExampleCode}{Verbatim}{}\n",
        )
        zipped.writestr(
            "main.tex",
            "\\documentclass{font-proof}\n\\usepackage{amssymb}\n"
            "\\usepackage{listing}\n\\begin{document}\nNative description.\n"
            "\\begin{ExampleCode}\n\\usepackage{amssymb}\n\\end{ExampleCode}\n"
            "$\\mathbb{R}+\\eth$\n\\end{document}\n",
        )
    archive = folder / "多文件 paper.zip"
    section = SOURCE[SOURCE.index(r"\section") : SOURCE.index(r"\end{document}")]
    main = SOURCE.replace(
        section,
        r"\newcommand{\papersection}{sections/章节 一}"
        + "\n"
        + r"\input{\papersection}"
        + "\n",
    )
    main = main.replace(r"\author{TeXGlot}", r"\author{\NativeAffiliation}")
    main = main.replace(
        r"\begin{document}",
        r"\usepackage{native-proof,booktabs,xcolor}"
        + "\n"
        + r"\input{preamble}"
        + "\n"
        + r"\begin{document}",
    )
    section += r"""

\NativeDoc{api\_name}{Native description.}

\begin{table}[h]
\caption{Native table.}
\begin{tabular}{ll}
\toprule
\rowcolor{gray!20}
$a$ & 1 \\
\cmidrule(lr){1-2}
$b$ & 2 \\
\bottomrule
\end{tabular}
\end{table}
"""
    if eps:
        main = main.replace(
            r"\begin{document}", r"\usepackage{graphicx}" + "\n" + r"\begin{document}"
        )
        section += "\n" + r"\includegraphics{figure.eps}" + "\n"
    # Exercise the shipped recovery code on every native release platform.
    # Three independent broken figures must not exhaust package-repair retries.
    broken_figures = {}
    for index in range(3):
        writer = PdfWriter()
        page = writer.add_blank_page(width=120, height=80)
        drawing = DecodedStreamObject()
        drawing.set_data(b"0 0 1 rg 10 10 50 30 re f")
        page[NameObject("/Contents")] = writer._add_object(drawing)
        stream = io.BytesIO()
        writer.write(stream)
        name = f"figure-{index}.pdf"
        broken_figures[name] = re.sub(
            rb"startxref\s+(\d+)",
            lambda m: b"startxref\n" + str(int(m[1]) - 21).encode(),
            stream.getvalue(),
        )
        section += rf"\includegraphics[width=0.15\linewidth]{{{name}}}" + "\n"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("main.tex", main.encode("utf-8"))
        zipped.writestr("preamble.tex", r"\usepackage[table]{xcolor}".encode("utf-8"))
        zipped.writestr("sections/章节 一.tex", section.encode("utf-8"))
        for name, content in broken_figures.items():
            zipped.writestr(name, content)
        zipped.writestr(
            "native-proof.sty",
            (
                r"\ProvidesPackage{native-proof}"
                + "\n"
                + r"\newcommand{\NativeAffiliation}{{\usefont{OT1}{phv}{m}{n}Univerzitní, Plzeň}}"
                + "\n"
                + r"\newcommand{\NativeDoc}[2]{\texttt{#1}: #2}"
                + "\n"
            ).encode("utf-8"),
        )
        if eps:
            zipped.writestr(
                "figure.eps",
                b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 80\nnewpath 0 0 moveto 100 80 lineto stroke showpage\n%%EOF\n",
            )
    with (folder / "service.log").open("wb") as log:
        service_command = (
            [str(engine), "--engine-server", "--parent-pipe"]
            if engine
            else [sys.executable, "-m", "app.server"]
        )
        service = await asyncio.create_subprocess_exec(
            *service_command,
            "--port",
            str(port),
            cwd=folder if engine else ROOT,
            env=env,
            stdin=asyncio.subprocess.PIPE if engine else None,
            stdout=log,
            stderr=log,
            **process_options(background=True),
        )
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for _ in range(600 if engine else 100):
                    try:
                        response = await client.get(
                            f"http://127.0.0.1:{port}/api/health"
                        )
                        response.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if service.returncode is not None:
                            raise RuntimeError("Service exited; inspect service.log")
                        await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("Service did not become ready")
                page = await client.get(f"http://127.0.0.1:{port}/")
                assert page.status_code == 200 and "TeXGlot" in page.text
            command = (
                [str(engine)] if engine else [sys.executable, "-m", "app.cli"]
            ) + [
                str(source),
                str(archive),
                str(font_archive),
                "--port",
                str(port),
                "--json",
                "--no-start",
                "--locale",
                "zh",
                "-o",
                str(folder / "译文 output"),
            ]
            with (folder / "cli.log").open("wb") as log_cli:
                cli = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=folder if engine else ROOT,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=log_cli,
                    **process_options(),
                )
                try:
                    stdout, _ = await asyncio.wait_for(cli.communicate(), 600)
                except BaseException:
                    await terminate_process_tree(cli)
                    raise
            if cli.returncode:
                raise RuntimeError(f"CLI failed ({cli.returncode}); inspect cli.log")
            result = json.loads(stdout)
            assert result["completed"] == 3
            pages = []
            for paper in result["results"][:2]:
                pdf = PdfReader(paper["files"]["translated"])
                text = "\n".join(p.extract_text() for p in pdf.pages)
                assert "平台检查" in re.sub(r"\s+", "", text)
                assert "我们保留" in re.sub(r"\s+", "", text)
                assert "α" in text
                assert not paper["warnings"]
                assert any(
                    b"/ActualText" in page.get_contents().get_data()
                    for page in pdf.pages
                )
                with zipfile.ZipFile(paper["files"]["source"]) as exported:
                    assert "axessibility.sty" in exported.namelist()
                    assert "axessibility.sty.texglot-original" in exported.namelist()
                pages.append(len(pdf.pages))
            if eps:
                assert pdf.pages[0]["/Resources"].get("/XObject")
            assert all(word in text for word in ("Univerzitní", "Plzeň", "api_name"))
            assert "本地说明" in re.sub(r"\s+", "", text)
            assert "本地表格" in re.sub(r"\s+", "", text)
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.get(
                    f"http://127.0.0.1:{port}/api/jobs/{paper['id']}"
                )
                response.raise_for_status()
                details = response.json()
            assert "sections/章节 一.tex" in details["translation_files"]
            assert "native-proof.sty" in details["source_dependencies"]
            assert "preamble.tex" in details["source_dependencies"]
            assert any(
                "已按编译诊断调整 xcolor 宏包选项" in entry["message"]
                for entry in details["logs"]
            )
            with zipfile.ZipFile(paper["files"]["source"]) as exported:
                assert r"\PassOptionsToPackage{table}{xcolor}" in exported.read(
                    "main.tex"
                ).decode("utf-8")
                assert (
                    exported.read("preamble.tex").decode("utf-8")
                    == r"\usepackage[table]{xcolor}"
                )
                for name, original in broken_figures.items():
                    assert exported.read(name + ".texglot-original") == original
                    repaired = PdfReader(io.BytesIO(exported.read(name)), strict=True)
                    assert (
                        repaired.pages[0].get_contents().get_data()
                        == b"0 0 1 rg 10 10 50 30 re f"
                    )
            assert any(
                "已移除未使用的 minted" in entry["message"] for entry in details["logs"]
            )
            assert (
                sum(
                    "已修复 PDF 插图索引" in entry["message"]
                    for entry in details["logs"]
                )
                == 3
            )
            font_paper = result["results"][2]
            font_pdf = PdfReader(font_paper["files"]["translated"])
            font_text = "\n".join(page.extract_text() for page in font_pdf.pages)
            assert "本地说明" in re.sub(r"\s+", "", font_text)
            assert r"\usepackage{amssymb}" in font_text
            assert not font_paper["warnings"]
            with zipfile.ZipFile(font_paper["files"]["source"]) as exported:
                assert b"LibertinusMath-Regular.otf" in exported.read("font-proof.cls")
                assert b"\\IfPackageLoadedTF{unicode-math}" in exported.read("main.tex")
                assert (
                    b"\\begin{ExampleCode}\n\\usepackage{amssymb}\n\\end{ExampleCode}"
                    in exported.read("main.tex")
                )
            pages.append(len(font_pdf.pages))
            for completed in result["results"]:
                pdf = PdfReader(completed["files"]["translated"])
                assert all(
                    "TEST_REASONING" not in page.extract_text() for page in pdf.pages
                )
                caches = list((data / "jobs" / completed["id"]).glob("cache-*.json"))
                assert caches
                for cache in caches:
                    assert "TEST_REASONING" not in cache.read_text(encoding="utf-8")
            report = {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "frozen_engine": bool(engine),
                "eps_conversion": eps,
                "pages": pages,
                "source_types": [
                    "tex",
                    "zip with Unicode include",
                    "font recovery zip",
                ],
                "status": paper["status"],
                "unicode_paths": True,
                "compiler_recorded_dynamic_input": True,
                "legacy_unicode_fonts": True,
                "generated_unicode_math": True,
                "external_package_recovery": True,
                "formula_accessibility_retained": True,
                "custom_prose_arguments": True,
                "booktabs_column_rules": True,
                "included_package_option_recovery": True,
                "unused_minted_recovery": True,
                "pdf_figure_index_recovery": True,
                "font_filename_recovery": True,
                "unicode_math_package_recovery": True,
                "literal_examples_retained": True,
                "reasoning_outputs_clean": True,
                "model": "local stub (no paid API)",
                "result": result,
            }
            (output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {k: v for k, v in report.items() if k != "result"},
                    ensure_ascii=False,
                )
            )
        finally:
            if engine and service.returncode is None:
                service.stdin.close()
                try:
                    await asyncio.wait_for(service.wait(), 15)
                except TimeoutError:
                    await terminate_process_tree(service)
                    raise RuntimeError(
                        "Frozen service did not stop after parent EOF"
                    ) from None
            else:
                await terminate_process_tree(service)
            model.shutdown()
            model.server_close()


if __name__ == "__main__":
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/platform-smoke"))
    parser.add_argument("--portable-compiler", action="store_true")
    parser.add_argument("--engine", type=Path, help="Validate a frozen desktop engine")
    parser.add_argument(
        "--eps",
        action="store_true",
        help="Also validate EPS conversion (requires Ghostscript)",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.output, args.portable_compiler, args.engine, args.eps))
