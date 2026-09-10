"""Provide explicit workspace launchers, including the macOS hidden-.pth workaround."""

import os
import shlex
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if os.name == "nt":
    launcher = root / ".venv/Scripts/texglot.cmd"
    launcher.write_text(
        '@echo off\nsetlocal DisableDelayedExpansion\nset "PYTHONUTF8=1"\n"%~dp0python.exe" "%~dp0..\\..\\scripts\\cli.py" %*\n',
        encoding="utf-8",
        newline="\r\n",
    )
else:
    python = root / ".venv/bin/python"
    launcher = root / ".venv/bin/texglot"
    launcher.write_text(
        f'#!/bin/sh\nexec {shlex.quote(str(python))} {shlex.quote(str(root / "scripts/cli.py"))} "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
