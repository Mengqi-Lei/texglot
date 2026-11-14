"""Runtime-level regressions independent of any particular paper identifier."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest
from pypdf import PdfReader

from app import bibliography, compiler, tex_runtime

FIXTURES = Path(__file__).parent / "fixtures"


def test_runtime_distribution_is_complete_and_unmodified():
    for name, profile in tex_runtime.profiles().items():
        for relative, meta in profile["files"].items():
            data = (tex_runtime.RESOURCES / name / relative).read_bytes()
            assert hashlib.sha256(data).hexdigest() == meta["sha256"]
            assert meta["origin"].startswith("https://")
        assert (tex_runtime.RESOURCES / "LICENSE.txt").is_file()
    assert "v3.7.0" in (tex_runtime.RESOURCES / "minted3/minted.sty").read_text(
        encoding="utf-8"
    )
    assert "v3.8.0" in (tex_runtime.RESOURCES / "minted3-modern/minted.sty").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "profile", ["minted3", "minted3-modern", "pstricks", "biblatex"]
)
@pytest.mark.parametrize("nested", [False, True])
def test_runtime_never_overwrites_an_author_package(tmp_path, profile, nested):
    main = tmp_path / "main.tex"
    main.write_text("Author content", encoding="utf-8")
    names = [
        n for n, m in tex_runtime.profiles()[profile]["files"].items() if m["runtime"]
    ]
    target = tmp_path / ("custom" if nested else "") / names[-1]
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(b"% AUTHOR CUSTOM PACKAGE\r\n")
    original = {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert not tex_runtime.RuntimeOverlay(tmp_path, "main.tex").install(profile)
    assert {
        str(p.relative_to(tmp_path)): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    } == original


def test_runtime_upgrade_only_replaces_its_own_unmodified_files(tmp_path):
    (tmp_path / "main.tex").write_text("Body", encoding="utf-8")
    cache = tmp_path / "code.highlight.minted"
    cache.write_bytes(b"Original cached code")
    loader = tex_runtime.RuntimeOverlay(tmp_path, "main.tex")
    assert loader.install("minted3")
    assert loader.install("minted3-modern")
    assert (tmp_path / "minted.sty").read_bytes() == (
        tex_runtime.RESOURCES / "minted3-modern/minted.sty"
    ).read_bytes()
    assert cache.read_bytes() == b"Original cached code"
    assert "minted.sty" in tex_runtime.managed_runtime_paths(tmp_path)
    (tmp_path / "minted.sty").write_bytes(b"User edited this file")
    assert "minted.sty" not in tex_runtime.managed_runtime_paths(tmp_path)
    assert not tex_runtime.RuntimeOverlay(tmp_path, "main.tex").install("minted3")


def test_partial_install_failure_preserves_a_racing_file(tmp_path, monkeypatch):
    (tmp_path / "main.tex").write_text("Body", encoding="utf-8")
    normal = Path.open
    count = 0
    created = []

    def fail(path, *args, **kwargs):
        nonlocal count
        if args and args[0] == "xb" and path.is_relative_to(tmp_path):
            count += 1
            if count == 2:
                path.write_bytes(b"Concurrent author edit")
                created.append(path)
                raise FileExistsError(path)
        return normal(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(FileExistsError):
        tex_runtime.RuntimeOverlay(tmp_path, "main.tex").install("minted3")
    assert created[0].read_bytes() == b"Concurrent author edit"
    assert {p for p in tmp_path.rglob("*") if p.is_file()} == {
        tmp_path / "main.tex",
        created[0],
    }


def test_runtime_rejects_internal_symlink_directory_without_writing(tmp_path):
    (tmp_path / "main.tex").write_text("Body", encoding="utf-8")
    destination = tmp_path / "author-files"
    destination.mkdir()
    try:
        (tmp_path / "texglot-runtime").symlink_to(destination, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable")
    assert not tex_runtime.RuntimeOverlay(tmp_path, "main.tex").install("minted3")
    assert not list(destination.iterdir())
    assert not (tmp_path / "minted.sty").exists()


def native():
    if not compiler.find_compiler("tectonic"):
        pytest.skip("Optional Tectonic not installed")


async def notify(_):
    pass


@pytest.mark.parametrize("alias", ["C:/TEMP/SAFE~1", None, "C:/用户/临时"])
def test_windows_runtime_alias_requires_ascii_and_existing_os_alias(monkeypatch, alias):
    class ShortPath:
        def __call__(self, value, buffer, size):
            if buffer is None:
                return len(alias) + 1 if alias else 0
            buffer.value = alias
            return len(alias)

    class Kernel:
        GetShortPathNameW = ShortPath()

    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: Kernel(), raising=False)
    if alias and alias.isascii():
        assert bibliography.windows_runtime_path(Path("C:/用户/临时")) == Path(alias)
    else:
        with pytest.raises(ValueError, match="TEMP"):
            bibliography.windows_runtime_path(Path("C:/用户/临时"))


@pytest.mark.parametrize("profile", ["minted3", "minted3-modern"])
async def test_real_frozen_cache_selection_keeps_two_code_blocks_in_order(
    tmp_path, profile
):
    native()
    root = tmp_path / "source"
    shutil.copytree(FIXTURES / ("frozen-" + profile), root)
    original = {p.name: p.read_bytes() for p in root.glob("*.minted")}
    compiler.prepare_engine_sources(root, "tectonic", main="main.tex")
    pdf, _ = await compiler.compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    text = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert (
        text.count("first") == 1
        and text.count("second") == 1
        and text.index("first") < text.index("second")
    )
    assert {p.name: p.read_bytes() for p in root.glob("*.minted")} == original
    assert ("v3.8.0" if profile.endswith("modern") else "v3.7.0") in (
        root / "minted.sty"
    ).read_text(encoding="utf-8")


async def test_incomplete_frozen_cache_does_not_insert_empty_code(tmp_path):
    native()
    root = tmp_path / "source"
    shutil.copytree(FIXTURES / "frozen-minted3", root)
    next(root.glob("*.highlight.minted")).unlink()
    original = {p.name: p.read_bytes() for p in root.glob("*.minted")}
    compiler.prepare_engine_sources(root, "tectonic", main="main.tex")
    with pytest.raises(compiler.CompilationError):
        await compiler.compile_pdf(
            root, "main.tex", tmp_path / "build", "tectonic", notify
        )
    assert {p.name: p.read_bytes() for p in root.glob("*.minted")} == original
    assert 'print("second")' in (root / "main.tex").read_text(encoding="utf-8")


async def test_unused_pstricks_runs_real_packages_and_keeps_other_diagrams(tmp_path):
    native()
    root = tmp_path / "source"
    root.mkdir()
    source = r"\documentclass{article}\usepackage{pstricks-add,tikz}\psset{linewidth=1pt}\begin{document}Retained text $\psi$.\begin{tikzpicture}\draw (0,0) rectangle (1,1);\node at (0.5,0.5){Diagram};\end{tikzpicture}\end{document}"
    (root / "main.tex").write_text(source, encoding="utf-8")
    compiler.prepare_engine_sources(root, "tectonic", main="main.tex")
    pdf, _ = await compiler.compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", notify
    )
    text = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert "Retained text" in text and "Diagram" in text
    assert r"\usepackage{pstricks-add,tikz}" in (root / "main.tex").read_text(
        encoding="utf-8"
    )


async def test_real_postscript_cannot_be_silently_omitted(tmp_path):
    native()
    root = tmp_path / "source"
    root.mkdir()
    source = r"\documentclass{article}\usepackage{pstricks}\begin{document}\begin{pspicture}(0,0)(1,1)\psline(0,0)(1,1)\end{pspicture}\end{document}"
    (root / "main.tex").write_text(source, encoding="utf-8")
    compiler.prepare_engine_sources(root, "tectonic", main="main.tex")
    with pytest.raises(ValueError):
        await compiler.compile_pdf(
            root, "main.tex", tmp_path / "build", "tectonic", notify
        )
    assert r"\psline(0,0)(1,1)" in (root / "main.tex").read_text(encoding="utf-8")


def control(tmp_path, value="refs.bib", version="3.11", **attrs):
    root = tmp_path / "source"
    root.mkdir(exist_ok=True)
    (root / "main.tex").write_text("Body", encoding="utf-8")
    (root / "refs.bib").write_text("@book{a,title={Retained}}", encoding="utf-8")
    ns = "{https://sourceforge.net/projects/biblatex}"
    xml = ET.Element(ns + "controlfile", version=version)
    ET.SubElement(
        xml,
        ns + "datasource",
        {"type": "file", "datatype": "bibtex", "glob": "false"} | attrs,
    ).text = value
    section = ET.SubElement(xml, ns + "section", number="0")
    ET.SubElement(section, ns + "citekey").text = "a"
    path = tmp_path / "main.bcf"
    ET.ElementTree(xml).write(path, encoding="utf-8")
    return root, path


@pytest.mark.parametrize(
    "value",
    [
        "https://example.org/data.bib",
        "../../outside.bib",
        "/etc/passwd",
        "file:///tmp/a.bib",
        "*.bib",
    ],
)
def test_biber_rejects_nonlocal_data_sources(tmp_path, value):
    root, path = control(tmp_path, value)
    with pytest.raises(ValueError):
        bibliography.bcf_inputs(root, "main.tex", path)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-32-le"])
def test_biber_rejects_xml_entities(tmp_path, encoding):
    root, path = control(tmp_path)
    path.write_bytes(
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><x>&y;</x>'.encode(
            encoding
        )
    )
    with pytest.raises(ValueError):
        bibliography.bcf_inputs(root, "main.tex", path)


def test_biber_handles_unicode_paths_and_checks_sections_separately(tmp_path):
    root, path = control(tmp_path, "文献 & data.bib")
    (root / "refs.bib").rename(root / "文献 & data.bib")
    xml, inputs = bibliography.bcf_inputs(root, "main.tex", path)
    assert inputs[0][1].name == "文献 & data.bib"
    good = (
        "% $ biblatex bbl format version 3.3 $\n" + r"\refsection{0}\entry{a}{book}{}{}"
    )
    bibliography.validate_bibliography(xml, good)
    with pytest.raises(ValueError, match="缺少引用条目"):
        bibliography.validate_bibliography(xml, good.replace("{0}", "{1}", 1))


@pytest.mark.parametrize(
    "option", ["configfile", "output_directory", "output_file", "input_directory"]
)
def test_biber_rejects_command_line_overrides(tmp_path, option):
    root, path = control(tmp_path)
    xml = ET.parse(path)
    ET.SubElement(
        xml.getroot(), "{https://sourceforge.net/projects/biblatex}key"
    ).text = option
    xml.write(path)
    with pytest.raises(ValueError):
        bibliography.bcf_inputs(root, "main.tex", path)


def archive(
    tmp_path,
    data=b"Executable fixture",
    *,
    member="bin/windows/biber.exe",
    symlink=False,
):
    path = tmp_path / "biber.tar.xz"
    with tarfile.open(path, "w:xz") as tf:
        entry = tarfile.TarInfo(member)
        entry.size = len(data)
        if symlink:
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/outside"
        tf.addfile(entry, io.BytesIO(data))
    return path, (
        "windows",
        hashlib.sha256(path.read_bytes()).hexdigest(),
        hashlib.sha256(data).hexdigest(),
        None,
    )


def test_binary_installer_verifies_archive_and_executable_independently(tmp_path):
    path, asset = archive(tmp_path)
    assert bibliography.binary_bytes(path, asset) == b"Executable fixture"
    bad = list(asset)
    bad[2] = "0" * 64
    with pytest.raises(ValueError):
        bibliography.binary_bytes(path, bad)
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        bibliography.binary_bytes(path, asset)


def test_binary_installer_refuses_symlink_archive_members(tmp_path):
    path, asset = archive(tmp_path, symlink=True)
    with pytest.raises(ValueError):
        bibliography.binary_bytes(path, asset)


def test_mac_binary_slice_requires_matching_architecture_and_hash(tmp_path):
    payload = b"arm64 executable fixture"
    data = (
        struct.pack(">II", 0xCAFEBABE, 1)
        + struct.pack(">IIIII", 0x0100000C, 0, 28, len(payload), 0)
        + payload
    )
    path, asset = archive(tmp_path, data, member="bin/universal-darwin/biber")
    asset = (
        "universal-darwin",
        asset[1],
        hashlib.sha256(payload).hexdigest(),
        0x0100000C,
    )
    assert bibliography.binary_bytes(path, asset) == payload
    with pytest.raises(ValueError):
        bibliography.binary_bytes(path, (*asset[:3], 0x01000007))


async def test_biber_download_is_pinned_and_then_reused(tmp_path, monkeypatch):
    path, asset = archive(tmp_path)
    blob = path.read_bytes()
    monkeypatch.setattr(bibliography, "asset_for", lambda: asset)
    monkeypatch.setattr(bibliography, "DATA", tmp_path / "data")
    original = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        assert str(request.url) == bibliography.ASSET_ROOT + "biber.windows.tar.xz"
        return httpx.Response(200, content=blob)

    monkeypatch.setattr(
        bibliography.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handle), **kw),
    )
    first = await bibliography.ensure_biber(notify)
    second = await bibliography.ensure_biber(notify)
    assert (
        first == second
        and first.read_bytes() == b"Executable fixture"
        and len(requests) == 1
    )
    assert (first.parent / "LICENSE.txt").is_file()


async def test_real_biber_rebuilds_stale_bibliography_without_losing_citations(
    tmp_path, monkeypatch
):
    native()
    binary = os.environ.get("TEXGLOT_TEST_BIBER")
    if not binary:
        pytest.skip("Optional validated native Biber fixture not provided")

    async def installed(_):
        return Path(binary)

    monkeypatch.setattr(bibliography, "ensure_biber", installed)
    root = tmp_path / "用户 研究 & source"
    root.mkdir()
    source = r"\documentclass{article}\usepackage[backend=biber,style=numeric]{biblatex}\addbibresource{refs.bib}\begin{document}Two citations \cite{a,b}.\printbibliography\end{document}"
    (root / "main.tex").write_text(source, encoding="utf-8")
    (root / "refs.bib").write_text(
        "@book{a,author={Alpha, Ada},title={First verified reference},year={2020}}\n@book{b,author={Beta, Bob},title={Second verified reference},year={2021}}",
        encoding="utf-8",
    )
    stale = (
        "% $ biblatex auxiliary file $\n% $ biblatex bbl format version 3.3 $\n"
        + r"\refsection{0}\endrefsection\endinput"
    )
    (root / "main.bbl").write_text(stale, encoding="utf-8")
    compiler.prepare_engine_sources(root, "tectonic", main="main.tex")
    build = tmp_path / "编译 & build"
    pdf, warnings = await compiler.compile_pdf(
        root, "main.tex", build, "tectonic", notify
    )
    text = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert "First verified reference" in text and "Second verified reference" in text
    assert (root / "main.bbl.texglot-original").read_text(encoding="utf-8") == stale
    assert not any("未解析" in w for w in warnings)
    report = json.loads(
        (build / "bibliography-verification.json").read_text(encoding="utf-8")
    )
    assert report["cited"] == 2 and report["entries"] == 2


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
async def test_biber_stops_its_process_and_preserves_source_on_interruption(
    tmp_path, monkeypatch, stop
):
    root, bcf = control(tmp_path)
    out = tmp_path / "build"
    out.mkdir()
    shutil.copyfile(bcf, out / "main.bcf")
    original = {p.name: p.read_bytes() for p in root.iterdir()}
    started = asyncio.Event()
    native_spawn = asyncio.create_subprocess_exec
    native_wait = asyncio.wait_for
    processes = []
    working_directories = []

    async def installed(_):
        return Path(sys.executable)

    async def spawn(*args, **kwargs):
        # Substitute only Biber, not Windows taskkill used by real cleanup.
        if "--noconf" not in args:
            return await native_spawn(*args, **kwargs)
        working_directories.append(Path(kwargs["cwd"]))
        process = await native_spawn(
            sys.executable,
            "-c",
            "import time; print('started', flush=True); time.sleep(120)",
            **kwargs,
        )
        processes.append(process)
        started.set()
        return process

    async def bounded_wait(awaitable, timeout):
        return await native_wait(awaitable, timeout=0.2 if timeout == 240 else timeout)

    monkeypatch.setattr(bibliography, "ensure_biber", installed)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    if stop == "timeout":
        monkeypatch.setattr(asyncio, "wait_for", bounded_wait)
    task = asyncio.create_task(
        bibliography.rebuild_bibliography(root, "main.tex", out, notify)
    )
    try:
        await native_wait(started.wait(), timeout=5)
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ValueError, match="超时"):
                await task
        assert processes[0].returncode is not None
        assert not working_directories[0].exists()
        assert not list(out.glob("texglot-biber-*"))
        assert {p.name: p.read_bytes() for p in root.iterdir()} == original
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("placement", ["htbp", "H"])
async def test_oversized_custom_code_float_retains_caption_and_last_line(
    tmp_path, placement
):
    native()
    root = tmp_path / "source"
    root.mkdir()
    source = r"\documentclass{article}\usepackage{float}\newfloat{codepanel}{htbp}{loc}\begin{document}\begin{codepanel}\begin{minipage}{0.7\textwidth}First code line.\par\vspace{1.3\textheight}Last code line.\end{minipage}\caption{Retained caption}\end{codepanel}\end{document}"
    (root / "main.tex").write_text(
        source.replace(r"\begin{codepanel}", r"\begin{codepanel}[" + placement + "]"),
        encoding="utf-8",
    )
    compiler.prepare_engine_sources(root, "tectonic", main="main.tex")
    notices = []

    async def record(message):
        notices.append(message)

    pdf, warnings = await compiler.compile_pdf(
        root, "main.tex", tmp_path / "build", "tectonic", record
    )
    text = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert (
        "First code line" in text
        and "Last code line" in text
        and "Retained caption" in text
    )
    assert compiler.FLOAT_FIT_NOTICE in notices
    assert not any("裁切" in w for w in warnings)
    positions = []
    for page in PdfReader(pdf).pages:

        def visit(value, cm, tm, _font, _size):
            if "code line" in value or "Retained caption" in value:
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                assert 0 < x < float(page.mediabox.width)
                assert 0 < y < float(page.mediabox.height)
                positions.append((x, y))

        page.extract_text(visitor_text=visit)
    assert len(positions) >= 3


def test_float_hook_upgrade_is_idempotent_and_does_not_wrap_itself(tmp_path):
    source = (
        r"\documentclass{article}"
        + compiler.LEGACY_FLOAT_SIZING
        + r"\begin{document}\begin{figure}Content\end{figure}\end{document}"
    )
    p = tmp_path / "main.tex"
    p.write_text(source, encoding="utf-8")
    compiler.prepare_float_sizing(tmp_path)
    once = p.read_text(encoding="utf-8")
    compiler.prepare_float_sizing(tmp_path)
    assert p.read_text(encoding="utf-8") == once
    assert once.count(r"\let\texglot@largefloatcheck\@largefloatcheck") == 1
    assert compiler.FLOAT_SIZING in once and compiler.LEGACY_FLOAT_SIZING not in once
