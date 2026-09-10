"""Export reviewed public sources and build local release assets. Never publishes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tomllib
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_ROOT = (
    ".github/workflows/verify.yml",
    ".github/workflows/desktop.yml",
    "README.md",
    "README_CN.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING_CN.md",
    "LICENSE",
    "THIRD_PARTY.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    ".gitattributes",
    "start-texglot.command",
    "start-texglot.cmd",
    "install-texglot.cmd",
)
PUBLIC_DOCS = (
    "cli.md",
    "cli.en.md",
    "platforms.md",
    "platforms.en.md",
    "reader.md",
    "translation-context.md",
    "troubleshooting.md",
    "troubleshooting_CN.md",
    "releasing.md",
    "releasing_CN.md",
    "desktop.md",
    "desktop_CN.md",
    "assets/home-en.png",
    "assets/home-zh.png",
    "assets/reader-en.png",
    "assets/reader-zh.png",
)
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".json",
    ".toml",
    ".yml",
    ".tex",
    ".txt",
    ".sh",
    ".cmd",
    ".command",
    ".cjs",
    ".html",
}
LEAKS = re.compile(
    r"sk-[A-Za-z0-9._-]{20,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----|/Users/[a-zA-Z0-9_-]+/|texglot(?:-dev)"
)
LINKS = re.compile(r'\]\(([^\s)]+)(?:\s+"[^"]*")?\)|(?:href|src)="([^"]+)"')


def public_files(root: Path, version: str) -> list[Path]:
    files = [root / name for name in PUBLIC_ROOT]
    files += [root / "docs" / name for name in PUBLIC_DOCS]
    files += [
        root / "docs/releases" / f"v{version}{suffix}.md" for suffix in ("", "_CN")
    ]
    for folder, pattern in (
        ("app", "*.py"),
        ("tests", "*.py"),
        ("scripts", "*.py"),
        ("scripts", "*.sh"),
        ("frontend/src", "*"),
        ("frontend/tests", "*.cjs"),
        ("examples", "*"),
        (".github", "*.md"),
        ("app/resources", "*"),
    ):
        files += [
            p
            for p in (root / folder).rglob(pattern)
            if p.is_file() and "__pycache__" not in p.parts
        ]
    for pattern in ("*.json", "*.ts", "*.html"):
        files += list((root / "frontend").glob(pattern))
    for pattern in ("*.json", "*.cjs", "*.html", "*.py"):
        files += list((root / "desktop").glob(pattern))
    files += list((root / "desktop/tests").glob("*.cjs"))
    files += [
        root / "desktop/build" / name
        for name in ("TECTONIC-LICENSE", "PYTHON-LICENSE.txt")
    ]
    return sorted(set(files))


def check_sources(root: Path) -> None:
    errors = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        content = path.read_text(encoding="utf-8")
        if LEAKS.search(content):
            errors.append(f"Possible private data: {path.relative_to(root)}")
        if path.suffix != ".md":
            continue
        content = re.sub(r"```[^\n]*\n.*?```", "", content, flags=re.S)
        for match in LINKS.finditer(content):
            link = match[1] or match[2]
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target = (path.parent / unquote(parsed.path)).resolve()
            if not target.is_relative_to(root.resolve()) or not target.exists():
                errors.append(f"Broken local link: {path.relative_to(root)} -> {link}")
    if errors:
        raise ValueError("\n".join(errors))


def release_body(root: Path, version: str) -> str:
    def expand(path: Path) -> str:
        content = path.read_text(encoding="utf-8")

        def replace(match):
            link = match[1] or match[2]
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                return match[0]
            target = (path.parent / parsed.path).resolve().relative_to(root.resolve())
            url = f"https://github.com/Mengqi-Lei/texglot/blob/v{version}/{target.as_posix()}"
            if parsed.fragment:
                url += "#" + parsed.fragment
            return match[0].replace(link, url)

        return LINKS.sub(replace, content)

    return (
        "\n\n---\n\n".join(
            expand(root / "docs/releases" / f"v{version}{suffix}.md")
            for suffix in ("", "_CN")
        )
        + "\n"
    )


def prepare(source: Path, output: Path, installers: list[Path] | None = None) -> None:
    source, output = source.resolve(), output.resolve()
    if output.exists() or source.is_relative_to(output):
        raise ValueError(
            "Choose a new output directory that does not contain the source checkout."
        )
    version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Expected a stable x.y.z version.")
    bundle = source / "frontend/dist"
    if (
        not (bundle / "index.html").is_file()
        or not (bundle / "THIRD_PARTY_LICENSES.txt").is_file()
    ):
        raise ValueError("Build the frontend before preparing a release.")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv is required to build release packages.")
    tree, assets = output / "repository", output / "artifacts"
    tree.mkdir(parents=True)
    assets.mkdir()
    manifest = []
    for path in public_files(source, version):
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                f"Missing or symlinked public input: {path.relative_to(source)}"
            )
        rel = path.relative_to(source)
        dest = tree / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        if dest.suffix == ".cmd":
            dest.write_bytes(
                dest.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            )
        if dest.suffix in {".command", ".sh"}:
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    changelog = tree / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    sections = re.split(r"(?=^## )", text, flags=re.M)
    if len(sections) < 2 or not sections[1].startswith(f"## {version}"):
        raise ValueError("Changelog must begin with the current release.")
    changelog.write_text(sections[0] + sections[1], encoding="utf-8")
    check_sources(tree)
    for path in sorted(tree.rglob("*")):
        if path.is_file():
            manifest.append(
                {
                    "path": path.relative_to(tree).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    archive = assets / f"texglot-{version}-source.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for item in manifest:
            zipped.write(tree / item["path"], f"texglot-{version}/{item['path']}")
    # The repository/source ZIP remain build-free; Python distributions bundle the UI.
    shutil.copytree(bundle, tree / "frontend/dist")
    try:
        subprocess.run([uv, "build", "--out-dir", str(assets)], cwd=tree, check=True)
    finally:
        shutil.rmtree(tree / "frontend/dist")
    # uv creates a build-output ignore file; it is not a release attachment.
    (assets / ".gitignore").unlink(missing_ok=True)
    for installer in installers or []:
        pattern = rf"TeXGlot-{re.escape(version)}-(?:macOS-(?:arm64|x64)\.dmg|Windows-x64-Setup\.exe)"
        if not installer.is_file() or not re.fullmatch(pattern, installer.name):
            raise ValueError(f"Unexpected installer: {installer.name}")
        target = assets / installer.name
        if target.exists():
            raise ValueError(f"Duplicate installer: {installer.name}")
        shutil.copyfile(installer, target)
    checksums = []
    for path in sorted(assets.iterdir()):
        checksums.append(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        )
    (assets / "SHA256SUMS.txt").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8"
    )
    (output / "manifest.json").write_text(
        json.dumps({"version": version, "files": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "release-body.md").write_text(
        release_body(tree, version), encoding="utf-8"
    )
    print(f"Prepared TeXGlot {version}: {len(manifest)} public files; {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--installer",
        type=Path,
        action="append",
        help="Attach a verified native installer; repeatable",
    )
    args = parser.parse_args()
    prepare(ROOT, args.output, args.installer)


if __name__ == "__main__":
    main()
