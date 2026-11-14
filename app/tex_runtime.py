"""Checksum-pinned, opt-in TeX runtime overlays for diagnosed incompatibilities.

Project packages always win. No package is downloaded or removed here. Only
files installed by this invocation can be replaced when trying a second frozen
cache dialect; a cache hit must still use upstream's exact content hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

RESOURCES = Path(__file__).parent / "resources/tex/profiles"


@lru_cache(maxsize=1)
def profiles():
    return json.loads((RESOURCES / "manifest.json").read_text(encoding="utf-8"))[
        "profiles"
    ]


def managed_runtime_paths(root: Path) -> set[str]:
    """Exclude byte-identical runtime libraries from prose, never authored text."""
    digests = {}
    for profile in profiles().values():
        for name, meta in profile["files"].items():
            if meta["runtime"]:
                digests.setdefault(name, set()).add(meta["sha256"])
    result = set()
    for path in root.rglob("*"):
        if path.is_file() and path.name in digests and not path.is_symlink():
            if hashlib.sha256(path.read_bytes()).hexdigest() in digests[path.name]:
                result.add(path.relative_to(root).as_posix())
    return result


class RuntimeOverlay:
    def __init__(self, root: Path, main: str):
        self.root = root.resolve()
        self.directory = (root / main).parent.resolve()
        self.attempted: set[str] = set()
        self.owned: dict[Path, bytes] = {}

    def _safe_destination(self, dest: Path) -> bool:
        return dest.resolve().is_relative_to(self.root) and not any(
            p.is_symlink()
            for p in (dest, *dest.parents)
            if p != self.root and p.is_relative_to(self.root)
        )

    def install(self, name: str) -> bool:
        if name in self.attempted:
            return False
        self.attempted.add(name)
        profile = profiles()[name]
        plan = {}
        for relative, meta in profile["files"].items():
            source = RESOURCES / name / relative
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != meta["sha256"]:
                raise ValueError("内置 TeX 兼容资源校验失败，请重新安装 TeXGlot")
            dest = self.directory / (
                relative
                if meta["runtime"]
                else "texglot-runtime/" + name + "/" + relative
            )
            if not self._safe_destination(dest):
                return False
            if meta["runtime"]:
                matches = list(self.root.rglob(dest.name))
                if any(p != dest for p in matches):
                    return False
            if dest.exists():
                existing = dest.read_bytes()
                if existing == data:
                    continue
                if dest not in self.owned or existing != self.owned[dest]:
                    return False
            plan[dest] = data
        license_data = (RESOURCES / "LICENSE.txt").read_bytes()
        provenance = json.dumps(profile, indent=2).encode() + b"\n"
        for filename, data in [
            ("LICENSE.txt", license_data),
            ("provenance.json", provenance),
        ]:
            dest = self.directory / "texglot-runtime" / name / filename
            if not self._safe_destination(dest):
                return False
            if dest.exists() and dest.read_bytes() != data:
                return False
            if not dest.exists():
                plan[dest] = data
        backups = {}
        previous_owned = dict(self.owned)
        try:
            for path, data in plan.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                previous = path.read_bytes() if path.exists() else None
                with path.open("wb" if path in self.owned else "xb") as stream:
                    backups[path] = previous
                    stream.write(data)
                self.owned[path] = data
        except OSError:
            self.owned = previous_owned
            for path, old in reversed(list(backups.items())):
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(old)
            raise
        return bool(plan)

    def recover(self, error) -> str:
        missing = re.search(r"File [`']([^`'\r\n]+)' not found", error.log)
        if missing and missing[1] in profiles()["pstricks"]["files"]:
            if self.install("pstricks"):
                return "PSTricks 官方宏包依赖"
        if "Package minted Error" in error.log and (
            "frozencache" in error.log or "Cannot highlight code" in error.log
        ):
            if any(self.root.rglob("*.highlight.minted")) and any(
                self.root.rglob("*.style.minted")
            ):
                if "minted3" not in self.attempted and re.search(
                    r"(?m)^Package: minted[^\n]*\bv[23]\.", error.tex_log
                ):
                    if self.install("minted3"):
                        return "minted 3 冻结缓存运行时"
                elif (
                    "minted3" in self.attempted and "Cannot highlight code" in error.log
                ):
                    if self.install("minted3-modern"):
                        return "新版 minted 3 冻结缓存运行时"
        if "Running external tool biber" in error.log:
            if self.install("biblatex"):
                return "biblatex 参考文献运行时"
        return ""
