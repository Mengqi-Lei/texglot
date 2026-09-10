"""Paths and child commands for source, wheel and frozen desktop installations."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bundled_tools() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "tools"
    return None


def server_command(port: int, *, parent_pipe: bool = False) -> list[str]:
    command = (
        [sys.executable, "--engine-server"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "app.server"]
    )
    command += ["--port", str(port)]
    if parent_pipe:
        command.append("--parent-pipe")
    return command


def child_environment() -> dict[str, str]:
    env = dict(os.environ)
    # External compilers must not load the frozen Python runtime's shared libraries.
    if getattr(sys, "frozen", False):
        for key in ("LD_LIBRARY_PATH", "LIBPATH", "DYLD_LIBRARY_PATH"):
            original = env.get(key + "_ORIG")
            if original is None:
                env.pop(key, None)
            else:
                env[key] = original
    return env
