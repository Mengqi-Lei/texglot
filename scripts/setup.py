"""Build and install this checkout on Windows, macOS, or Linux."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.platforms import configure_stdio, venv_python  # noqa: E402


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    configure_stdio()
    uv = shutil.which("uv")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    node = shutil.which("node")
    if not uv:
        raise SystemExit(
            "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
        )
    if not npm or not node:
        raise SystemExit(
            "Install Node.js 22.12 or newer, then reopen your terminal: https://nodejs.org/"
        )
    version = subprocess.check_output(
        [node, "--version"], text=True, encoding="utf-8"
    ).strip()
    if not re.match(r"v\d+\.\d+", version) or tuple(
        map(int, version[1:].split(".")[:2])
    ) < (22, 12):
        raise SystemExit(f"Node.js 22.12+ is required; found {version}.")
    env = dict(os.environ, PYTHONUTF8="1")

    def run(*args, cwd=ROOT, quiet=False):
        subprocess.run(
            [str(a) for a in args],
            cwd=cwd,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL if quiet else None,
        )

    run(npm, "ci", cwd=ROOT / "frontend")
    run(npm, "run", "build", cwd=ROOT / "frontend")
    run(uv, "sync", "--locked", "--python", "3.13")
    python = venv_python(ROOT)
    run(python, "scripts/install_workspace_cli.py")
    with tempfile.TemporaryDirectory(prefix="texglot-install-") as temporary:
        constraints = Path(temporary) / "constraints.txt"
        run(
            uv,
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--output-file",
            constraints,
            quiet=True,
        )
        run(
            uv,
            "tool",
            "install",
            "--editable",
            ".",
            "--force",
            "--python",
            "3.13",
            "--constraints",
            constraints,
        )
    run(python, "scripts/install_compiler.py", "--if-missing")
    print(
        "TeXGlot installed. Run texglot --help; if missing, run uv tool update-shell and reopen the terminal."
    )
    print("Open start-texglot.cmd" if os.name == "nt" else "Open start-texglot.command")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Installation stopped (exit {exc.returncode}). Fix the error above and run setup again."
        ) from None
