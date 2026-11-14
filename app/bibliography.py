"""Run a pinned Biber on validated local inputs, never a document's command line."""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import re
import shutil
import struct
import sys
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from .config import DATA
from .platforms import process_options, terminate_process_tree
from .runtime import child_environment, external_subprocess

ASSET_ROOT = "https://ftp.tu-chemnitz.de/pub/tug/historic/systems/texlive/2024/tlnet-final/archive/"
ASSETS = {
    ("Darwin", "arm64"): (
        "universal-darwin",
        "67a1fd52d4076a1d8c34a2d06e4c901519c8a3ceb489a465a8b6ee8b26bf3d77",
        "3688f90c69f7cdca987db595b9b4601e45a215b0f69581d5a778a306380891a2",
        0x0100000C,
    ),
    ("Darwin", "x86_64"): (
        "universal-darwin",
        "67a1fd52d4076a1d8c34a2d06e4c901519c8a3ceb489a465a8b6ee8b26bf3d77",
        "0bb8cf7cf3875709882a859c46d7977d45316667df86966b5ca1d77d06cc3712",
        0x01000007,
    ),
    ("Windows", "x86_64"): (
        "windows",
        "ba59798edb38218e611bbd73f956b35af46620d9e99b3e945c8bd02e1c2b043f",
        "388a267a2739f23cda94e6abfcb28f4172e037b0eb15f213e7b79f69a5394621",
        None,
    ),
    ("Linux", "x86_64"): (
        "x86_64-linux",
        "3240c6a35ad62ca4d8f1208b47e47334721abcb8ee3d7e45160f86f8df68c720",
        "8a74dcc9e087be4b2dbcae6247f029296015cfe33f8069a3be32e8b835bafa3a",
        None,
    ),
}
ASSETS["Linux", "arm64"] = (
    "aarch64-linux",
    "9c359d5aa4713a11db1f999ee4b3f3ca6a4dbcdbabb54be57a7f7fc98e146998",
    "daf422766a900e2ddf20a8914707f384c3e9454a5f5ab40aefc53217efe57082",
    None,
)
MAX_BYTES = 150 * 1024 * 1024
FROZEN_BIB = r"""% texglot: validated bibliography rebuilt by Biber 2.20
\makeatletter
\AddToHook{package/biblatex/after}{\def\blx@check@logreq{}}
\makeatother
"""


def asset_for(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    machine = {"aarch64": "arm64", "amd64": "x86_64"}.get(machine, machine)
    try:
        return ASSETS[system, machine]
    except KeyError:
        raise ValueError(
            "此平台尚无已验证的 Biber 运行时，请使用完整 TeX Live"
        ) from None


def binary_bytes(archive: Path, asset) -> bytes:
    arch, digest, binary_digest, cpu = asset
    if (
        archive.stat().st_size > MAX_BYTES
        or hashlib.sha256(archive.read_bytes()).hexdigest() != digest
    ):
        raise ValueError("Biber 下载校验失败，未安装或执行文件")
    expected = f"bin/{arch}/" + ("biber.exe" if arch == "windows" else "biber")
    with tarfile.open(archive) as tf:
        matches = [m for m in tf.getmembers() if m.name == expected]
        if len(matches) != 1 or not matches[0].isfile() or matches[0].size > MAX_BYTES:
            raise ValueError("Biber 安装包结构异常")
        data = tf.extractfile(matches[0]).read(MAX_BYTES + 1)
    if cpu is not None:
        # Upstream's universal launcher calls lipo. Extract the authenticated
        # architecture slice directly so end users do not need Xcode tools.
        if len(data) < 8:
            raise ValueError("Biber 通用二进制结构异常")
        magic, count = struct.unpack(">II", data[:8])
        if magic != 0xCAFEBABE or count > 16 or len(data) < 8 + 20 * count:
            raise ValueError("Biber 通用二进制结构异常")
        slices = []
        for i in range(count):
            kind, _, offset, size, _ = struct.unpack(
                ">IIIII", data[8 + 20 * i : 28 + 20 * i]
            )
            if kind == cpu and offset >= 8 + 20 * count and offset + size <= len(data):
                slices.append(data[offset : offset + size])
        if len(slices) != 1:
            raise ValueError("Biber 安装包缺少当前架构")
        data = slices[0]
    if hashlib.sha256(data).hexdigest() != binary_digest:
        raise ValueError("Biber 程序校验失败")
    return data


async def ensure_biber(notify) -> Path:
    try:
        return await _ensure_biber(notify)
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        raise ValueError("参考文献工具准备失败，请检查网络与磁盘空间后重试") from exc


async def _ensure_biber(notify) -> Path:
    asset = asset_for()
    arch, _, digest, _ = asset
    name = "biber.exe" if platform.system() == "Windows" else "biber"
    directory = (
        DATA
        / "tools"
        / "biber-2.20"
        / (platform.system() + "-" + platform.machine().lower())
    )
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / name
    license_source = Path(__file__).parent / "resources/tex/profiles/BIBER-LICENSE.txt"
    (directory / "LICENSE.txt").write_bytes(license_source.read_bytes())
    (directory / "provenance.json").write_text(
        json.dumps(
            {
                "version": "2.20",
                "source": "https://github.com/plk/biber/tree/v2.20",
                "archive": ASSET_ROOT + f"biber.{arch}.tar.xz",
                "binary_sha256": digest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if binary.is_symlink():
        raise ValueError("Biber 程序路径不能是符号链接")
    if binary.is_file() and hashlib.sha256(binary.read_bytes()).hexdigest() == digest:
        return binary
    await notify("首次处理此参考文献格式，正在下载并校验 Biber 运行时")
    with tempfile.TemporaryDirectory(prefix="biber-download-", dir=directory) as temp:
        archive = Path(temp) / "archive.tar.xz"
        async with (
            asyncio.timeout(240),
            httpx.AsyncClient(
                follow_redirects=True, timeout=httpx.Timeout(180, connect=30)
            ) as client,
        ):
            async with client.stream(
                "GET", ASSET_ROOT + f"biber.{arch}.tar.xz"
            ) as response:
                response.raise_for_status()
                size = 0
                with archive.open("wb") as stream:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError("Biber 安装包超过大小限制")
                        stream.write(chunk)
        data = await asyncio.to_thread(binary_bytes, archive, asset)
        staged = Path(temp) / name
        staged.write_bytes(data)
        staged.chmod(0o755)
        if (
            not binary.is_file()
            or hashlib.sha256(binary.read_bytes()).hexdigest() != digest
        ):
            staged.replace(binary)
    return binary


def bcf_inputs(root: Path, main: str, control: Path):
    """Resolve only local BibTeX files; do not follow URLs, globs or XML entities."""
    raw = control.read_bytes()
    if (
        len(raw) > 8 * 1024 * 1024
        or b"\x00" in raw
        or re.search(rb"<!DOCTYPE|<!ENTITY", raw, re.I)
    ):
        raise ValueError("参考文献控制文件包含不支持的内容")
    try:
        document = ET.fromstring(raw.decode("utf-8"))
    except (ET.ParseError, UnicodeError) as exc:
        raise ValueError("参考文献控制文件格式无效") from exc
    if document.tag != "{https://sourceforge.net/projects/biblatex}controlfile":
        raise ValueError("参考文献控制文件格式无效")
    if document.attrib.get("version") != "3.11":
        raise ValueError("参考文献控制文件与内置 Biber 版本不匹配")
    inputs = []
    for node in document.iter():
        local = node.tag.rsplit("}", 1)[-1]
        if local == "key" and (node.text or "").strip().lower() in {
            "configfile",
            "output_directory",
            "input_directory",
            "output_file",
            "logfile",
            "tool",
            "outfile",
            "output_resolve",
            "output_format",
        }:
            raise ValueError("参考文献控制文件不能覆盖程序的文件访问设置")
        if local != "datasource":
            continue
        value = (node.text or "").strip()
        if (
            node.get("type") != "file"
            or node.get("datatype") != "bibtex"
            or node.get("glob", "false") != "false"
            or not value
        ):
            raise ValueError("参考文献仅支持源码包内的本地 BibTeX 文件")
        if re.search(r"[:\x00-\x1f*?]", value) or Path(value).is_absolute():
            raise ValueError("参考文献数据文件路径超出源码工程")
        path = ((root / main).parent / value).resolve()
        if (
            not path.is_relative_to(root.resolve())
            or path.suffix.lower() != ".bib"
            or not path.is_file()
        ):
            raise ValueError("参考文献数据文件缺失或位于工程之外")
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("参考文献数据文件过大")
        inputs.append((node, path))
    if not inputs:
        raise ValueError("没有找到可重建参考文献的数据文件")
    return document, inputs


def citation_keys(document) -> dict[str, set[str]]:
    result = {}
    for section in document.iter():
        if section.tag.rsplit("}", 1)[-1] != "section":
            continue
        key = section.get("number", "0")
        result.setdefault(key, set()).update(
            n.text
            for n in section
            if n.tag.rsplit("}", 1)[-1] == "citekey" and n.text and n.text != "*"
        )
    return result


def bibliography_keys(text: str) -> dict[str, set[str]]:
    sections = {}
    current = None
    for match in re.finditer(r"\\(refsection|entry)\{([^{}]*)\}", text):
        if match[1] == "refsection":
            current = match[2]
            sections.setdefault(current, set())
        elif current is not None:
            sections[current].add(match[2])
    return sections


def validate_bibliography(document, text: str):
    if "% $ biblatex bbl format version 3.3 $" not in text[:512]:
        raise ValueError("生成的参考文献格式不匹配")
    entries = bibliography_keys(text)
    missing = {
        k: sorted(v - entries.get(k, set()))
        for k, v in citation_keys(document).items()
        if v - entries.get(k, set())
    }
    if missing:
        raise ValueError(
            "参考文献仍缺少引用条目："
            + ", ".join(x for keys in missing.values() for x in keys)[:400]
        )


def windows_runtime_path(path: Path) -> Path:
    """Use an existing ASCII alias for PAR's narrow Windows filesystem APIs."""
    if str(path).isascii():
        return path
    import ctypes
    from ctypes import wintypes

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    function.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    function.restype = wintypes.DWORD
    size = function(str(path), None, 0)
    if size:
        buffer = ctypes.create_unicode_buffer(size)
        length = function(str(path), buffer, size)
        if 0 < length < size and buffer.value.isascii():
            return Path(buffer.value)
    raise ValueError(
        "Windows 参考文献工具无法使用当前临时目录，请将 TEMP 设置为可写的英文路径后重试"
    )


async def rebuild_bibliography(root: Path, main: str, out: Path, notify):
    from .compiler import sandbox_command

    path = root / main
    document, inputs = bcf_inputs(root, main, out / (path.stem + ".bcf"))
    await notify("正在按源码重建参考文献并核对引用条目")
    binary = await ensure_biber(notify)
    windows = platform.system() == "Windows"
    # The Windows PAR loader cannot unpack in a Unicode cache directory. Keep
    # the paper where it is; run a private copy in the user's OS temp directory.
    with tempfile.TemporaryDirectory(
        prefix="texglot-biber-", dir=None if windows else out
    ) as temp:
        work = Path(temp)
        if windows:
            work = windows_runtime_path(work)
            local_binary = work / "biber.exe"
            shutil.copyfile(binary, local_binary)
            binary = local_binary
        sources = {}
        for node, src in inputs:
            if src not in sources:
                name = f"data-{len(sources)}.bib"
                (work / name).write_bytes(src.read_bytes())
                sources[src] = name
            node.text = sources[src]
        ET.ElementTree(document).write(
            work / "control.bcf", encoding="utf-8", xml_declaration=True
        )
        cache = work / "cache"
        cache.mkdir()
        env = {
            k: v
            for k, v in child_environment().items()
            if not any(x in k.upper() for x in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
            and k
            not in (
                "PERL5LIB",
                "PERL5OPT",
                "PERL_LOCAL_LIB_ROOT",
                "BIBINPUTS",
                "BIBINPUT",
                "PAR_TEMP",
                "PAR_GLOBAL_TEMP",
            )
        }
        env.update(
            PAR_GLOBAL_TEMP=str(cache),
            TMPDIR=str(cache),
            TEMP=str(cache),
            TMP=str(cache),
            BIBINPUTS=str(work),
        )
        cmd = sandbox_command(
            [
                str(binary),
                "--noconf",
                # Keep CLI paths ASCII: packaged Perl can decode absolute
                # Unicode arguments differently from native filesystem paths.
                "--input-directory=.",
                "--output-directory=.",
                "control",
            ],
            root,
            out,
        )
        if cmd[:2] == ["/usr/bin/sandbox-exec", "-p"]:
            cmd[2] += "\n(deny network*)\n"
        log_path = out / "biber.log"
        log_path.write_text(
            f"TeXGlot Biber 2.20; frozen={bool(getattr(sys, 'frozen', False))}; windows={windows}\n",
            encoding="utf-8",
        )
        proc = await external_subprocess(
            *cmd,
            cwd=work,
            env=env,
            # The desktop service uses stdin as a parent-liveness pipe. An
            # external tool must receive EOF, not inherit that open pipe.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **process_options(),
        )
        try:

            async def collect():
                chunks = []
                size = 0
                with log_path.open("ab") as stream:
                    while chunk := await proc.stdout.read(65536):
                        if size < 8 * 1024 * 1024:
                            chunks.append(chunk)
                            size += len(chunk)
                            stream.write(chunk)
                            stream.flush()
                await proc.wait()
                return b"".join(chunks)

            try:
                data = await asyncio.wait_for(collect(), timeout=240)
            except TimeoutError as exc:
                raise ValueError("参考文献重建超时，请重试或检查参考文献数据") from exc
            log = data.decode("utf-8", errors="replace")
            if proc.returncode:
                raise ValueError("参考文献重建失败，请查看 Biber 日志：" + log[-700:])
            result = (work / "control.bbl").read_text(encoding="utf-8")
            validate_bibliography(document, result)
            target = path.with_suffix(".bbl")
            backup = target.with_name(target.name + ".texglot-original")
            if target.is_symlink() or backup.is_symlink():
                raise ValueError("参考文献输出路径不能是符号链接")
            if target.exists():
                original = target.read_bytes()
                if backup.exists() and backup.read_bytes() != original:
                    backup = target.with_name(
                        target.name
                        + ".texglot-original-"
                        + hashlib.sha256(original).hexdigest()[:16]
                    )
                if backup.is_symlink():
                    raise ValueError("参考文献备份路径不能是符号链接")
                if not backup.exists():
                    with backup.open("xb") as stream:
                        stream.write(original)
                elif backup.read_bytes() != original:
                    raise ValueError("参考文献备份校验失败")
            target.write_text(result, encoding="utf-8")
            text = path.read_text(encoding="utf-8")
            if FROZEN_BIB not in text:
                path.write_text(FROZEN_BIB + text, encoding="utf-8")
            (out / "bibliography-verification.json").write_text(
                json.dumps(
                    {
                        "entries": sum(
                            len(s) for s in bibliography_keys(result).values()
                        ),
                        "cited": sum(len(s) for s in citation_keys(document).values()),
                        "biber": "2.20",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        finally:
            if proc.returncode is None:
                await terminate_process_tree(proc)


def validate_frozen_bibliography(root: Path, main: str, out: Path):
    path = root / main
    if FROZEN_BIB not in path.read_text(encoding="utf-8"):
        return
    control = out / (path.stem + ".bcf")
    if not control.is_file():
        raise ValueError("未生成参考文献核对记录")
    document, _ = bcf_inputs(root, main, control)
    validate_bibliography(
        document, path.with_suffix(".bbl").read_text(encoding="utf-8")
    )
