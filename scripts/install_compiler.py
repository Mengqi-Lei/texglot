"""Install a checksum-pinned portable Tectonic without changing the system PATH."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import platform
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.17.0"
ASSETS = {
    ("Windows", "x86_64"): (
        "x86_64-pc-windows-msvc.zip",
        "f61ce51f0b0ade1015b7de7ef368541c5424e9756ecbd0d7af97d6d48030845f",
    ),
    ("Darwin", "arm64"): (
        "aarch64-apple-darwin.tar.gz",
        "a3f1cac7c5678f01661a92212f58480ae3b0634115d880dbc59e2953ded45667",
    ),
    ("Darwin", "x86_64"): (
        "x86_64-apple-darwin.tar.gz",
        "7c90ef5b6ddb1eb1937e4337add5237b79338e4b9676459fa91187d24d6cdf80",
    ),
    ("Linux", "x86_64"): (
        "x86_64-unknown-linux-musl.tar.gz",
        "8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7",
    ),
    ("Linux", "arm64"): (
        "aarch64-unknown-linux-musl.tar.gz",
        "b10954a95404f3ab2328d2fa59a5ebab8e657f893fab096f98be8db7c0c979b8",
    ),
}


def asset_for(system, machine):
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine.lower(), machine.lower())
    try:
        suffix, digest = ASSETS[system, arch]
    except KeyError:
        raise RuntimeError(
            f"No bundled compiler for {system}/{machine}. Install a compatible Tectonic build and add it to PATH."
        ) from None
    filename = f"tectonic-{VERSION}-{suffix}"
    return (
        f"https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40{VERSION}/{filename}",
        digest,
    )


def install(destination: Path, *, system=None, machine=None):
    system = system or platform.system()
    machine = machine or platform.machine()
    url, expected = asset_for(system, machine)
    print(f"Downloading Tectonic {VERSION} for {system}/{machine} …", flush=True)
    with urllib.request.urlopen(url, timeout=90) as response:
        archive = response.read(150 * 1024 * 1024 + 1)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise RuntimeError(
            "Tectonic checksum verification failed; no files were installed."
        )
    binary_name = "tectonic.exe" if system == "Windows" else "tectonic"
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            members = [p for p in source.namelist() if Path(p).name == binary_name]
            if len(members) != 1:
                raise RuntimeError("Unexpected Tectonic archive layout")
            data = source.read(members[0])
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
            members = [
                p
                for p in source.getmembers()
                if p.isfile() and Path(p.name).name == binary_name
            ]
            if len(members) != 1:
                raise RuntimeError("Unexpected Tectonic archive layout")
            data = source.extractfile(members[0]).read()
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / (binary_name + ".download")
    temporary.write_bytes(data)
    temporary.chmod(0o755)
    binary = destination / binary_name
    temporary.replace(binary)
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--if-missing", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.if_missing:
        sys.path.insert(0, str(root))
        from app.compiler import available_compilers

        if available_compilers()["tectonic"]:
            print("Using the installed Tectonic compiler.")
            return
    storage = Path(
        os.environ.get(
            "TEXGLOT_DATA_DIR", os.environ.get("MOYI_DATA_DIR", root / "data")
        )
    ).resolve()
    binary = install(args.destination or storage / "tools")
    subprocess.run([str(binary), "--version"], check=True)
    print(f"Compiler ready: {binary}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from None
