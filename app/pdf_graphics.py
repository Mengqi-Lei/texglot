"""Diagnose failed graphics and repair only a confirmed broken PDF index."""

import io
import re
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

MAX_REPAIR_BYTES = 32 * 1024 * 1024


def graphic_failure(log: str) -> str:
    match = re.search(r"Unable to load picture or PDF file ['`]([^'`\r\n]+)['`]", log)
    if not match:
        match = re.search(r"(?:File|file) ['`]([^'`\r\n]+)['`] not found", log)
    if match and Path(match[1]).suffix.lower() in {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".eps",
    }:
        return match[1]
    return ""


def page_signature(reader):
    return [
        (
            tuple(page.mediabox),
            tuple(page.cropbox),
            page.rotation,
            page.get_contents().get_data() if page.get_contents() is not None else b"",
        )
        for page in reader.pages
    ]


def recover_pdf_graphic(root: Path, main: str, name: str) -> tuple[bool, str]:
    """Use the compiler-resolved path; never search for a same-named substitute.

    Keep an untouched backup in the prepared project, which is itself separate
    from the uploaded source. No image is removed, rasterized or fabricated.
    """
    base = (root / main).parent
    candidate = base / name
    try:
        target = candidate.resolve()
    except (OSError, ValueError):
        return False, f"插图文件无法访问：{name}；请检查文件权限和引用路径"
    if candidate.is_symlink() or not target.is_relative_to(root.resolve()):
        return False, f"插图路径超出工程目录或使用符号链接：{name}"
    if not target.is_file():
        return False, f"找不到插图文件：{name}；请补齐文件或检查引用路径后重试"
    if target.suffix.lower() != ".pdf":
        return False, f"插图文件存在但无法读取：{name}；请检查图片格式和文件完整性"
    try:
        size = target.stat().st_size
    except OSError:
        return False, f"插图文件无法访问：{name}；请检查文件权限和引用路径"
    if size > MAX_REPAIR_BYTES:
        return (
            False,
            f"PDF 插图无法读取：{name}；文件超过自动修复大小限制，请重新导出该插图",
        )
    try:
        original = target.read_bytes()
    except OSError:
        return False, f"插图文件无法访问：{name}；请检查文件权限和引用路径"
    try:
        strict = PdfReader(io.BytesIO(original), strict=True)
        if strict.is_encrypted:
            return False, f"PDF 插图已加密：{name}；请提供未加密的插图后重试"
        # Trigger page-tree validation even if the trailer was readable.
        len(strict.pages)
    except PdfReadError as exc:
        if not re.search(r"xref|startxref", str(exc), re.I):
            return False, f"PDF 插图已损坏或格式不受支持：{name}；请重新导出该插图"
    except Exception:
        return False, f"PDF 插图已损坏或格式不受支持：{name}；请重新导出该插图"
    else:
        return (
            False,
            f"PDF 插图存在且索引可读取，但编译器仍无法载入：{name}；请检查 PDF 格式兼容性",
        )
    backup = target.with_name(target.name + ".texglot-original")
    if backup.exists() or backup.is_symlink():
        return (
            False,
            f"PDF 插图修复备份已存在：{name}；为避免覆盖原文件，请检查源码工程",
        )
    temporary = None
    backup_created = False
    try:
        reader = PdfReader(io.BytesIO(original), strict=False)
        if reader.is_encrypted or not 0 < len(reader.pages) <= 100:
            raise ValueError("Unsupported encrypted or oversized page tree")
        before = page_signature(reader)
        buffer = io.BytesIO()
        PdfWriter(clone_from=reader).write(buffer)
        repaired = buffer.getvalue()
        if len(repaired) > MAX_REPAIR_BYTES * 2:
            raise ValueError("Oversized rewritten PDF")
        checked = PdfReader(io.BytesIO(repaired), strict=True)
        if before != page_signature(checked):
            raise ValueError("Changed page geometry or drawing commands")
        with tempfile.NamedTemporaryFile(
            dir=target.parent, prefix=".texglot-pdf-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(repaired)
        with backup.open("xb") as stream:
            backup_created = True
            stream.write(original)
        temporary.replace(target)
    except Exception:
        if backup_created:
            backup.unlink(missing_ok=True)
        return (
            False,
            f"PDF 插图索引异常且无法自动修复：{name}；已保留原文件，请重新导出该插图",
        )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True, f"已修复 PDF 插图索引：{name}；原文件已保留"
