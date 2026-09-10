import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from app import runtime


def test_frozen_child_command_uses_engine_dispatch(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    command = runtime.server_command(8877, parent_pipe=True)
    assert command == [
        sys.executable,
        "--engine-server",
        "--port",
        "8877",
        "--parent-pipe",
    ]


def test_frozen_compiler_prefers_bundled_binary_and_keeps_sandbox(
    tmp_path, monkeypatch
):
    from app import compiler

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    tools = tmp_path / "tools"
    tools.mkdir()
    binary = tools / ("tectonic.exe" if sys.platform == "win32" else "tectonic")
    binary.write_bytes(b"not executed")
    binary.chmod(0o755)
    assert compiler.find_compiler("tectonic") == str(binary)
    if sys.platform == "darwin":
        assert (
            str(tools)
            in compiler.sandbox_command(
                [str(binary)], tmp_path / "job", tmp_path / "out"
            )[2]
        )


def test_desktop_parent_pipe_stops_service_and_releases_data_lock(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, TEXGLOT_DATA_DIR=str(tmp_path))
    command = [sys.executable, "-m", "app.server", "--port", str(port), "--parent-pipe"]
    with (tmp_path / "service.log").open("wb") as log:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=log, stderr=log, env=env
        )
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                for _ in range(70):
                    try:
                        health = client.get(
                            f"http://127.0.0.1:{port}/api/health"
                        ).json()
                        assert Path(health["data_dir"]).resolve() == tmp_path.resolve()
                        break
                    except httpx.HTTPError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("desktop service did not start")
            process.stdin.close()
            assert process.wait(timeout=15) == 0
            from app.platforms import service_lock

            with service_lock(tmp_path / "service.lock"):
                pass
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_frozen_external_environment_restores_library_paths(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/frozen/internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/system/libs")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/frozen/internal")
    monkeypatch.delenv("DYLD_LIBRARY_PATH_ORIG", raising=False)
    env = runtime.child_environment()
    assert env["LD_LIBRARY_PATH"] == "/system/libs"
    assert "DYLD_LIBRARY_PATH" not in env
