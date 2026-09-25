"""Audit a built TeXGlot Zotero XPI without starting Zotero.

The XPI is a ZIP archive, but it is a user-facing release artifact rather than
an ordinary source archive.  This audit deliberately checks the package
boundary: a manifest must be present and valid, paths must be safe, and source
checkouts, credentials, private paths, model files, documents, and generated
dependency trees must not be shipped.

Usage::

    python scripts/audit_zotero.py integrations/zotero/dist/texglot-zotero-0.1.0.xpi
    python scripts/audit_zotero.py --json report.json package.xpi

The script has no Zotero or Node.js dependency and is therefore suitable for
CI and release preparation on all supported platforms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024

# These directories belong to a development checkout or a build workspace.
# An XPI must contain only the runtime plugin, not a second package manager or
# an accidental copy of the TeXGlot data directory.
FORBIDDEN_PARTS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "__pycache__",
        "node_modules",
        "coverage",
        ".scaffold",
        "output",
        "data",
    }
)
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".pdf",
        ".tex",
        ".bib",
        ".aux",
        ".log",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".bin",
        ".safetensors",
        ".gguf",
        ".onnx",
        ".pth",
        ".pt",
        ".zip",
    }
)
FORBIDDEN_NAMES = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "tsconfig.json",
    }
)
LEAK_RE = re.compile(
    rb"(?:sk-[A-Za-z0-9._-]{20,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----|"
    rb"(?:/Users/|/home/|/private/tmp/|[A-Za-z]:\\Users\\)|"
    rb"(?:TEXGLOT|OPENAI|DEEPSEEK|DASHSCOPE)_API_KEY\s*[:=])"
)


class ZoteroPackageError(ValueError):
    """Raised when an XPI violates a release boundary check."""


def _normal_member_name(name: str) -> str:
    """Return a safe POSIX member name or raise for traversal/absolute paths."""

    if "\x00" in name:
        raise ZoteroPackageError("archive member contains a NUL byte")
    if "\\" in name:
        raise ZoteroPackageError(f"archive member uses a Windows separator: {name}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ZoteroPackageError(f"archive member is absolute: {name}")
    normalized = posixpath.normpath(name)
    if normalized in {"", "."} or normalized == ".." or normalized.startswith("../"):
        raise ZoteroPackageError(f"archive member escapes its root: {name}")
    if normalized != name.rstrip("/"):
        raise ZoteroPackageError(f"archive member is not normalized: {name}")
    return normalized


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _manifest_candidates(names: set[str]) -> list[str]:
    candidates = [name for name in names if PurePosixPath(name).name == "manifest.json"]
    # The implementation plan supports both a root manifest and a bootstrap
    # folder.  Keep this flexible while still requiring exactly one runtime
    # manifest in the built artifact.
    return sorted(candidates)


def _manifest_metadata(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZoteroPackageError(f"invalid UTF-8 JSON manifest: {name}") from exc
    if not isinstance(value, dict):
        raise ZoteroPackageError("manifest root must be an object")
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        raise ZoteroPackageError("manifest.name is required")
    if not isinstance(value.get("version"), str) or not value["version"].strip():
        raise ZoteroPackageError("manifest.version is required")
    # Zotero manifests normally use applications.gecko, while newer WebExtension
    # tooling uses browser_specific_settings.  One of these IDs is required;
    # accepting either keeps the check compatible with Zotero 8/9 toolchains.
    applications = value.get("applications")
    browser = value.get("browser_specific_settings")
    gecko = applications.get("gecko") if isinstance(applications, dict) else None
    zotero = applications.get("zotero") if isinstance(applications, dict) else None
    browser_gecko = browser.get("gecko") if isinstance(browser, dict) else None
    if not isinstance(gecko, dict) and not isinstance(zotero, dict) and not isinstance(browser_gecko, dict):
        raise ZoteroPackageError(
            "manifest must declare applications.zotero, applications.gecko, or browser_specific_settings.gecko"
        )
    gecko = (
        gecko
        if isinstance(gecko, dict)
        else zotero
        if isinstance(zotero, dict)
        else browser_gecko
    )
    if not isinstance(gecko.get("id"), str) or not gecko["id"].strip():
        raise ZoteroPackageError("manifest Gecko application id is required")
    if isinstance(zotero, dict):
        update_url = zotero.get("update_url")
        if not isinstance(update_url, str) or not update_url.startswith("https://"):
            raise ZoteroPackageError(
                "manifest applications.zotero.update_url must be an HTTPS URL"
            )
    return {"name": value["name"], "version": value["version"], "manifest": name}


def audit_package(path: Path) -> dict[str, Any]:
    """Audit *path* and return a JSON-serializable report.

    The returned report intentionally contains only package metadata and member
    names.  It never includes member contents, paths from the host, or request
    data that could contain credentials.
    """

    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ZoteroPackageError(f"XPI does not exist: {path.name}")
    if path.suffix.lower() != ".xpi":
        raise ZoteroPackageError("expected a .xpi file")
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ZoteroPackageError("XPI is larger than the 256 MiB release limit")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not infos:
            raise ZoteroPackageError("XPI is empty")
        seen: set[str] = set()
        manifest_raw: bytes | None = None
        manifest_name: str | None = None
        total_uncompressed = 0
        for info in infos:
            name = _normal_member_name(info.filename)
            if name in seen:
                raise ZoteroPackageError(f"duplicate archive member: {name}")
            seen.add(name)
            if _is_symlink(info):
                raise ZoteroPackageError(f"symbolic link is not allowed: {name}")
            if info.is_dir():
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                raise ZoteroPackageError(f"archive member is too large: {name}")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_ARCHIVE_BYTES:
                raise ZoteroPackageError("uncompressed XPI exceeds the 256 MiB limit")
            lower_parts = {part.lower() for part in PurePosixPath(name).parts}
            if lower_parts & FORBIDDEN_PARTS:
                raise ZoteroPackageError(f"development/generated path is not allowed: {name}")
            leaf = PurePosixPath(name).name.lower()
            if leaf in FORBIDDEN_NAMES or PurePosixPath(name).suffix.lower() in FORBIDDEN_SUFFIXES:
                raise ZoteroPackageError(f"non-runtime artifact is not allowed: {name}")
            content = archive.read(info)
            if LEAK_RE.search(content):
                raise ZoteroPackageError(f"possible credential or private path in: {name}")
            if leaf == "manifest.json":
                if manifest_raw is not None:
                    raise ZoteroPackageError("XPI contains more than one manifest.json")
                manifest_raw, manifest_name = content, name
        candidates = _manifest_candidates(seen)
        if manifest_raw is None or manifest_name is None or not candidates:
            raise ZoteroPackageError("XPI must contain exactly one manifest.json")
        metadata = _manifest_metadata(manifest_raw, manifest_name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    files = sorted(name for name in seen if not name.endswith("/"))
    return {
        "path": path.name,
        "size": path.stat().st_size,
        "sha256": digest,
        "member_count": len(files),
        "uncompressed_size": total_uncompressed,
        "manifest": metadata,
        "members": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xpi", type=Path)
    parser.add_argument("--json", type=Path, metavar="REPORT", help="write the audit report")
    args = parser.parse_args()
    try:
        report = audit_package(args.xpi)
    except (OSError, zipfile.BadZipFile, ZoteroPackageError) as exc:
        parser.error(str(exc))
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
