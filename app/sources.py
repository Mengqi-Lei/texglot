from __future__ import annotations

import asyncio
import gzip
import io
import re
import ssl
import stat
import tarfile
import zipfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import httpx

from .platforms import WINDOWS

MAX_UPLOAD = 80 * 1024 * 1024
MAX_EXPANDED = 300 * 1024 * 1024
MAX_FILES = 4000
TEX_SOURCE_SUFFIXES = {".tex", ".sty", ".cls", ".cfg", ".def", ".clo", ".fd", ".ltx"}
ARXIV_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7})(?:v[1-9]\d*)?", re.I)


def parse_arxiv(value: str) -> str:
    value = value.strip()
    if value.lower().startswith("arxiv:"):
        value = value[6:].strip()
    if "://" in value:
        u = urlsplit(value)
        if (
            u.scheme not in ("https", "http")
            or u.hostname not in ("arxiv.org", "www.arxiv.org", "export.arxiv.org")
            or u.username
            or u.password
        ):
            raise ValueError("请输入 arxiv.org 论文链接或 arXiv ID")
        value = unquote(u.path).strip("/")
        value = re.sub(r"^(abs|pdf|src|e-print|html)/", "", value)
    value = value.removesuffix(".pdf")
    if not ARXIV_ID.fullmatch(value):
        raise ValueError("arXiv 地址格式不正确，例如 https://arxiv.org/abs/1706.03762")
    return value


def safe_path(root: Path, name: str) -> Path:
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if (
        p.is_absolute()
        or ".." in p.parts
        or any(":" in x for x in p.parts)
        or "\x00" in name
    ):
        raise ValueError("压缩包包含不安全的文件路径")
    if WINDOWS and not windows_compatible_path(name):
        raise ValueError("源码包包含 Windows 不支持的文件名，请修改文件名及对应引用")
    target = (root / str(p)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("文件路径超出工程目录")
    return target


def windows_compatible_path(name: str) -> bool:
    for part in PurePosixPath(name.replace("\\", "/")).parts:
        if re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((" ", ".")):
            return False
        stem = part.split(".")[0].rstrip(" ")
        if re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]", stem, re.I):
            return False
    return True


def extract_source(blob: bytes, name: str, root: Path):
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    windows_names = set()

    def write(filename, content, size):
        nonlocal total, count
        target = safe_path(root, filename)
        count += 1
        total += size
        if count > MAX_FILES or total > MAX_EXPANDED or size > MAX_UPLOAD:
            raise ValueError("源码包过大（最多 4000 个文件，解压后 300 MB）")
        if any(x.startswith(".") or x == "__MACOSX" for x in Path(filename).parts):
            return
        if WINDOWS:
            key = str(target).casefold()
            if key in windows_names:
                raise ValueError("源码包有重复或仅大小写不同的文件名，Windows 无法区分")
            windows_names.add(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.read(size + 1)
        if len(data) != size:
            raise ValueError("压缩包内容长度异常")
        target.write_bytes(data)

    stream = io.BytesIO(blob)
    if zipfile.is_zipfile(stream):
        with zipfile.ZipFile(stream) as z:
            if len(z.infolist()) > MAX_FILES:
                raise ValueError("源码包最多包含 4000 个文件或目录")
            for item in z.infolist():
                safe_path(root, item.filename)
                if stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError("源码包不能包含符号链接")
                if not item.is_dir():
                    with z.open(item) as f:
                        write(item.filename, f, item.file_size)
    else:
        try:
            stream.seek(0)
            with tarfile.open(fileobj=stream, mode="r:*") as t:
                for entry_count, item in enumerate(t):
                    if entry_count >= MAX_FILES:
                        raise ValueError("源码包最多包含 4000 个文件或目录")
                    safe_path(root, item.name)
                    if item.isdir():
                        continue
                    if not item.isfile():
                        raise ValueError("源码包只能包含普通文件")
                    write(item.name, t.extractfile(item), item.size)
        except tarfile.ReadError:
            if blob.startswith(b"\x1f\x8b"):
                with gzip.GzipFile(fileobj=io.BytesIO(blob)) as g:
                    blob = g.read(MAX_UPLOAD + 1)
            if len(blob) > MAX_UPLOAD:
                raise ValueError("源码文件过大")
            if blob.startswith(b"%PDF") or b"<html" in blob[:1000].lower():
                raise ValueError("该论文未提供可用 LaTeX 源码；请上传作者提供的源码包")
            text = decode_tex(blob)
            if not re.search(r"\\(?:documentclass|documentstyle|begin|input)", text):
                raise ValueError("文件不是有效的 LaTeX 源码")
            (root / "main.tex").write_text(text, encoding="utf-8")
    tex = list(root.rglob("*.tex"))
    if not tex:
        raise ValueError("压缩包中没有 .tex 文件")
    for file in tex:
        file.write_text(decode_tex(file.read_bytes()), encoding="utf-8")


def decode_tex(blob: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "cp1252", "latin-1"):
        try:
            return blob.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("无法识别源码编码")


def without_comments(text: str) -> str:
    # Preserve offsets so callers can safely insert into the original source.
    chars = list(text)
    i = 0
    while i < len(text):
        if text[i] == chr(92):
            i += 2
        elif text[i] == "%":
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            chars[i:end] = [" "] * (end - i)
            i = end
        else:
            i += 1
    return "".join(chars)


def visible_tex(text: str, *, mask_comment_environments: bool = True) -> str:
    """Mask comments and literal code while retaining exact source offsets."""
    # Literal contents must be skipped before interpreting percent signs. For
    # example, the active package after \verb|%| is not part of a comment.
    chars = list(text)

    def mask(start, stop):
        chars[start:stop] = ["\n" if c == "\n" else " " for c in text[start:stop]]

    i = 0
    while i < len(text):
        if text[i] == "%":
            stop = text.find("\n", i)
            stop = len(text) if stop < 0 else stop
            mask(i, stop)
            i = stop
            continue
        if text[i] != "\\":
            i += 1
            continue
        environment = re.match(
            r"\\begin\s*\{(verbatim\*?|Verbatim|lstlisting|minted|filecontents\*?"
            + ("|comment" if mask_comment_environments else "")
            + r")\}",
            text[i:],
        )
        if environment:
            ending = re.search(
                r"\\end\s*\{" + re.escape(environment[1]) + r"\}",
                text[i + environment.end() :],
            )
            stop = i + environment.end() + ending.end() if ending else len(text)
            mask(i, stop)
            i = stop
            continue
        inline = re.match(r"\\(verb\*?|lstinline\*?)(?![A-Za-z@])", text[i:])
        if inline:
            start = i + inline.end()
            if inline[1].startswith("lstinline"):
                options = re.match(r"\s*(?:\[[^\]\n]*\]\s*)?", text[start:])
                start += options.end()
            if start < len(text) and not text[start].isspace():
                delimiter = text[start]
                end = text.find("}" if delimiter == "{" else delimiter, start + 1)
                newline = text.find("\n", start)
                if end >= 0 and (newline < 0 or end < newline):
                    mask(i, end + 1)
                    i = end + 1
                    continue
        command = re.match(r"\\[A-Za-z@]+|\\.", text[i:], re.S)
        i += command.end() if command else 1
    return "".join(chars)


def retry_delay(value: str | None, fallback: float) -> float:
    """Honor both forms of Retry-After without retrying before the server permits."""
    if not value:
        return fallback
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return fallback
    if not 0 <= seconds < float("inf"):
        return fallback
    return max(fallback, seconds)


def find_main(root: Path, selected: str = "") -> tuple[str, list[str]]:
    candidates = []
    bodies = {}
    for p in sorted(root.rglob("*.tex")):
        text = visible_tex(p.read_text(encoding="utf-8"))
        if re.search(r"\\(?:documentclass|documentstyle)\b", text) and re.search(
            r"\\begin\s*\{document\}", text
        ):
            candidates.append(p.relative_to(root).as_posix())
            bodies[p.relative_to(root).as_posix()] = text.split(r"\begin{document}", 1)[
                -1
            ]
    if not candidates:
        raise ValueError("未找到包含 documentclass 和 begin{document} 的主文件")
    if selected:
        if selected not in candidates:
            raise ValueError("指定的主文件不存在或不是完整文档")
        return selected, candidates

    def language_rank(path):
        # Multiple language editions must not be ranked by UTF-8 byte length:
        # that systematically favors multibyte scripts over the English paper.
        # The translation extractor currently targets Latin-script source prose.
        body = bodies[path]
        letters = sum(char.isalpha() for char in body)
        latin = len(re.findall(r"[A-Za-z]", body))
        return letters > 0 and latin < letters / 2

    candidates.sort(
        key=lambda p: (
            language_rank(p),
            Path(p).name not in ("main.tex", "paper.tex", "ms.tex"),
            len(Path(p).parts),
            -(root / p).stat().st_size,
        )
    )
    return candidates[0], candidates


async def download_arxiv(arxiv_id: str, dest: Path, notify):
    # One request at a time, bounded retries, and a local cache; avoid hammering arXiv.
    url = f"https://arxiv.org/src/{arxiv_id}"
    temporary = dest.with_suffix(".part")
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(120, connect=30),
        headers={"User-Agent": "TeXGlot/0.1 (personal research; source download)"},
    ) as client:
        for attempt in range(3):
            try:
                async with client.stream("GET", url) as response:
                    if response.status_code in (429, 502, 503, 504):
                        if attempt < 2:
                            await notify("arXiv 暂时繁忙，稍后自动重试")
                            await asyncio.sleep(
                                retry_delay(
                                    response.headers.get("Retry-After"),
                                    5 * (attempt + 1),
                                )
                            )
                            continue
                        raise ValueError("arXiv 暂时繁忙，已保留任务；请稍后重试")
                    if response.status_code == 404:
                        raise ValueError("arXiv 未找到这篇论文或其源码，请检查 ID")
                    response.raise_for_status()
                    size = 0
                    with temporary.open("wb") as f:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_UPLOAD:
                                raise ValueError(
                                    "arXiv 源码超过 80 MB，请手动精简后上传"
                                )
                            f.write(chunk)
                temporary.replace(dest)
                return
            except (httpx.TransportError, ssl.SSLError):
                if attempt == 2:
                    raise ValueError(
                        "arXiv 下载超时；已保留任务，可重试或上传源码包"
                    ) from None
                await notify("下载连接中断，正在重试")
                await asyncio.sleep(3 * (attempt + 1))
            finally:
                temporary.unlink(missing_ok=True)
