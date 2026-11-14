"""Paths and child commands for source, wheel and frozen desktop installations."""

from __future__ import annotations

import asyncio
import os
import subprocess
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


class _ExternalPipe:
    def __init__(self, pipe):
        self.pipe = pipe

    async def read(self, size):
        return await asyncio.to_thread(self.pipe.read, size)


class _ExternalProcess:
    """Async interface for a process created within a synchronous DLL scope."""

    def __init__(self, process):
        self.process = process
        self.pid = process.pid
        self.stdout = _ExternalPipe(process.stdout)

    @property
    def returncode(self):
        return self.process.poll()

    def kill(self):
        self.process.kill()

    async def wait(self):
        return await asyncio.to_thread(self.process.wait)


async def external_subprocess(*args, **kwargs):
    """Keep frozen Windows DLLs out of separately distributed executables.

    PyInstaller's SetDllDirectoryW state is inherited by child programs; env
    sanitization alone cannot remove it. Do not yield while changing this
    process-wide state. The original directory is restored even on spawn errors.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return await asyncio.create_subprocess_exec(*args, **kwargs)
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_directory = kernel.GetDllDirectoryW
    get_directory.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
    get_directory.restype = wintypes.DWORD
    set_directory = kernel.SetDllDirectoryW
    set_directory.argtypes = [wintypes.LPCWSTR]
    set_directory.restype = wintypes.BOOL
    size = get_directory(0, None)
    previous = None
    if size:
        buffer = ctypes.create_unicode_buffer(size + 1)
        if not get_directory(len(buffer), buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        previous = buffer.value
    if not set_directory(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        process = subprocess.Popen(args, **kwargs)
    finally:
        set_directory(previous)
    return _ExternalProcess(process)
