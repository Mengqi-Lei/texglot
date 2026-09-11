"""Build native TeXGlot installers with a bundled Python engine and Tectonic."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.install_compiler import VERSION, install  # noqa: E402


def prepare_icons(folder: Path):
    # Supply the native icon's white tile explicitly instead of leaving the OS
    # to place the transparent web logo on its own tinted background.
    image = Image.new("RGBA", (2048, 2048))
    ImageDraw.Draw(image).rounded_rectangle(
        (160, 160, 1887, 1887), radius=384, fill="white"
    )
    with Image.open(ROOT / "frontend/src/assets/texglot-logo.png") as source:
        logo = source.convert("RGBA")
    logo = ImageOps.contain(logo, (1680, 1680), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, ((2048 - logo.width) // 2, (2048 - logo.height) // 2))
    image = image.resize((1024, 1024), Image.Resampling.LANCZOS)
    image.save(folder / "icon.png")
    image.save(folder / "icon.ico", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    if sys.platform == "darwin":
        image.save(folder / "icon.icns")


def prepare_assets():
    folder = ROOT / "desktop/build"
    folder.mkdir(parents=True, exist_ok=True)
    prepare_icons(folder)
    notices = [
        (ROOT / "LICENSE").read_text(encoding="utf-8"),
        (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8"),
    ]
    # electron-builder removes upstream license files while repackaging macOS.
    # Keep the notices from the exact, checksum-verified Electron distribution.
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to collect Electron licenses")
    electron_zip = (
        subprocess.run(
            [
                node,
                "--input-type=module",
                "-e",
                """
import { downloadArtifact } from '@electron/get';
import fs from 'node:fs';
const version = JSON.parse(fs.readFileSync('package.json', 'utf8')).devDependencies.electron;
console.log(await downloadArtifact({version, artifactName: 'electron', platform: process.platform, arch: process.arch}));
""",
            ],
            cwd=ROOT / "desktop",
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()[-1]
    )
    with zipfile.ZipFile(electron_zip) as archive:
        notices.append(archive.read("LICENSE").decode("utf-8"))
        (folder / "LICENSES.chromium.html").write_bytes(
            archive.read("LICENSES.chromium.html")
        )
    for distribution in importlib.metadata.distributions():
        if distribution.metadata.get("Name", "").lower() in {
            "pytest",
            "ruff",
            "texglot",
        }:
            continue
        for file in distribution.files or []:
            if "dist-info" in str(file) and any(
                x in file.name.lower() for x in ("license", "copying", "notice")
            ):
                path = distribution.locate_file(file)
                if path.is_file():
                    notices.append(
                        f"\n{distribution.metadata['Name']}\n{'=' * 72}\n"
                        + path.read_text(errors="replace", encoding="utf-8")
                    )
    compiler_license = ROOT / "desktop/build/TECTONIC-LICENSE"
    if not compiler_license.exists():
        raise RuntimeError("The pinned Tectonic license is missing")
    notices.append(
        f"\nTectonic {VERSION}\n" + compiler_license.read_text(encoding="utf-8")
    )
    notices.append(
        (ROOT / "frontend/dist/THIRD_PARTY_LICENSES.txt").read_text(encoding="utf-8")
    )
    notices.append((folder / "PYTHON-LICENSE.txt").read_text(encoding="utf-8"))
    (folder / "THIRD_PARTY_NOTICES.txt").write_text(
        "\n\n".join(notices), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir-only",
        action="store_true",
        help="build the app folder without an installer",
    )
    parser.add_argument(
        "--skip-engine", action="store_true", help="reuse an already-built engine"
    )
    args = parser.parse_args()
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Desktop installers currently target macOS and Windows.")
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine
    )
    if arch is None or (sys.platform == "win32" and arch != "x64"):
        raise SystemExit(f"Unsupported native build architecture: {machine}")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit(
            "Build the frontend first: cd frontend && npm ci && npm run build"
        )
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise SystemExit("npm is required to build installers")
    env = dict(
        os.environ,
        PYTHONUTF8="1",
        TEXGLOT_DATA_DIR=str(ROOT / "output/desktop-build-data"),
        TEXGLOT_BUILD_PYTHON=sys.executable,
    )
    prepare_assets()
    if not args.skip_engine:
        tool_dir = ROOT / "output/desktop-build-tools"
        binary = tool_dir / ("tectonic.exe" if os.name == "nt" else "tectonic")
        # Always verify the pinned upstream archive; never bundle an unknown PATH executable.
        install(tool_dir)
        args_pyinstaller = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--console",
            "--name",
            "texglot-engine",
            "--distpath",
            str(ROOT / "desktop/engine-dist"),
            "--workpath",
            str(ROOT / "output/desktop-pyinstaller"),
            "--specpath",
            str(ROOT / "output/desktop-pyinstaller"),
            "--paths",
            str(ROOT),
            "--collect-submodules",
            "app",
            "--collect-submodules",
            "uvicorn",
            "--collect-data",
            "opencc",
            "--collect-data",
            "certifi",
            "--add-data",
            f"{ROOT / 'frontend/dist'}:app/web",
            "--add-data",
            f"{ROOT / 'app/resources'}:app/resources",
            "--add-data",
            f"{ROOT / 'THIRD_PARTY.md'}:app/resources",
            "--add-binary",
            f"{binary}:tools",
            "--exclude-module",
            "tkinter",
            "--exclude-module",
            "pytest",
            "--exclude-module",
            "PIL",
            str(ROOT / "desktop/engine.py"),
        ]
        subprocess.run(args_pyinstaller, cwd=ROOT, env=env, check=True)
    command = [
        npm,
        "run",
        "pack" if args.dir_only else "dist",
        "--",
        "--mac" if sys.platform == "darwin" else "--win",
        f"--{arch}",
    ]
    # Cloud-synced checkouts can attach Finder metadata during signing. Build the
    # native app outside that tree, then copy only completed installer artifacts.
    native_output = Path(tempfile.mkdtemp(prefix="texglot-desktop-native-"))
    command.append(f"--config.directories.output={native_output}")
    subprocess.run(command, cwd=ROOT / "desktop", env=env, check=True)
    output = ROOT / "desktop/out"
    output.mkdir(parents=True, exist_ok=True)
    for artifact in native_output.iterdir():
        if artifact.suffix in {".dmg", ".exe", ".zip", ".blockmap"}:
            shutil.copyfile(artifact, output / artifact.name)
    (output / "build-info.json").write_text(
        json.dumps({"native_output": str(native_output), "arch": arch}),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "version": json.loads((ROOT / "desktop/package.json").read_text())[
                    "version"
                ],
                "platform": sys.platform,
                "arch": arch,
                "output": str(ROOT / "desktop/out"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
