"""Build and install this checkout on Windows, macOS, or Linux."""

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.platforms import (  # noqa: E402
    configure_stdio,
    process_options,
    terminate_process_tree,
    venv_python,
)

BUILD_TIMEOUT = 10 * 60


async def run_command(command, *, cwd=ROOT, env=None, quiet=False, timeout=None):
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL if quiet else None,
        **process_options(),
    )
    try:
        returncode = await asyncio.wait_for(process.wait(), timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        await terminate_process_tree(process)
        if isinstance(exc, TimeoutError):
            raise subprocess.TimeoutExpired(command, timeout) from None
        raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)


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

    def run(*args, cwd=ROOT, quiet=False, timeout=None):
        asyncio.run(
            run_command(
                [str(a) for a in args], cwd=cwd, env=env, quiet=quiet, timeout=timeout
            )
        )

    run(npm, "ci", cwd=ROOT / "frontend")
    try:
        run(npm, "run", "build", cwd=ROOT / "frontend", timeout=BUILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise SystemExit(
            "Frontend build exceeded 10 minutes; its processes were stopped. "
            "Check the output above. If file access is hanging, extract TeXGlot into "
            "a normal local folder (for example ~/Projects/TeXGlot or C:\\TeXGlot) "
            "and run setup again."
        ) from None
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
    except KeyboardInterrupt:
        raise SystemExit(
            "Installation cancelled; setup processes were stopped."
        ) from None
