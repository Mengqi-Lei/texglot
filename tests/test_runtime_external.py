"""External tools must not inherit a frozen Windows application's DLL scope."""

import ctypes
import io
import sys
from types import SimpleNamespace

import pytest

from app import runtime


@pytest.mark.parametrize("fails", [False, True])
async def test_external_spawn_restores_dll_directory_even_on_failure(
    monkeypatch, fails
):
    original = "C:/bundle/_internal"
    state = [original]
    changes = []

    class GetDirectory:
        def __call__(self, size, buffer):
            if not size:
                return len(state[0]) + 1
            buffer.value = state[0]
            return len(state[0])

    class SetDirectory:
        def __call__(self, value):
            state[0] = value
            changes.append(value)
            return 1

    kernel = SimpleNamespace(
        GetDllDirectoryW=GetDirectory(), SetDllDirectoryW=SetDirectory()
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: kernel, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def spawn(args, **kwargs):
        assert state[0] is None
        assert args == ("tool.exe", "--noconf") and kwargs["cwd"] == "work"
        if fails:
            raise OSError("Cannot start tool")
        return SimpleNamespace(
            pid=123, stdout=io.BytesIO(b"output"), poll=lambda: 0, wait=lambda: 0
        )

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    if fails:
        with pytest.raises(OSError, match="Cannot start"):
            await runtime.external_subprocess("tool.exe", "--noconf", cwd="work")
    else:
        process = await runtime.external_subprocess("tool.exe", "--noconf", cwd="work")
        assert await process.stdout.read(1024) == b"output"
        assert await process.wait() == 0 and process.returncode == 0
    assert state == [original] and changes == [None, original]
