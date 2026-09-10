import asyncio
import os
import subprocess
import sys

import pytest

from scripts import setup


@pytest.mark.parametrize("quiet", [False, True])
async def test_setup_command_preserves_directory_environment_and_output(
    tmp_path, capfd, quiet
):
    directory = tmp_path / "安装 test"
    directory.mkdir()
    await setup.run_command(
        [
            sys.executable,
            "-c",
            "import os,pathlib,sys; pathlib.Path('result.txt').write_text("
            "os.environ['TEXGLOT_SETUP_TEST']); print('installed'); "
            "print('diagnostic', file=sys.stderr)",
        ],
        cwd=directory,
        env=dict(os.environ, TEXGLOT_SETUP_TEST="ok"),
        quiet=quiet,
    )
    assert (directory / "result.txt").read_text() == "ok"
    captured = capfd.readouterr()
    assert captured.out.splitlines() == ([] if quiet else ["installed"])
    assert captured.err.splitlines() == ["diagnostic"]


@pytest.mark.skipif(os.name != "nt", reason="Windows batch entry point")
async def test_setup_runs_windows_cmd_entry_with_spaces(tmp_path, capfd):
    script = tmp_path / "setup step.cmd"
    script.write_text("@echo off\necho installed\n", encoding="ascii")
    await setup.run_command([str(script)], cwd=tmp_path, timeout=10)
    assert capfd.readouterr().out.splitlines() == ["installed"]


async def test_setup_command_preserves_failure_exit_code():
    command = [sys.executable, "-c", "raise SystemExit(17)"]
    with pytest.raises(subprocess.CalledProcessError) as error:
        await setup.run_command(command)
    assert error.value.returncode == 17
    assert error.value.cmd == command


@pytest.mark.parametrize("stop", ["timeout", "cancel"])
async def test_setup_stops_real_parent_and_child(tmp_path, monkeypatch, stop):
    parent_heartbeat = tmp_path / "parent.txt"
    child_heartbeat = tmp_path / "child.txt"
    heartbeat = (
        "import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile True:\n"
        " p.write_text(str(time.monotonic())); time.sleep(.02)"
    )
    parent = (
        "import subprocess,sys\n"
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])\n"
        "sys.argv = [sys.argv[0], sys.argv[3]]\n" + heartbeat
    )
    stopped = []
    terminate = setup.terminate_process_tree

    async def record_termination(process):
        await terminate(process)
        stopped.append(process.returncode)

    monkeypatch.setattr(setup, "terminate_process_tree", record_termination)
    task = asyncio.create_task(
        setup.run_command(
            [
                sys.executable,
                "-c",
                parent,
                heartbeat,
                str(child_heartbeat),
                str(parent_heartbeat),
            ],
            timeout=10 if stop == "timeout" else None,
        )
    )
    try:
        for _ in range(400):
            if parent_heartbeat.exists() and child_heartbeat.exists():
                break
            await asyncio.sleep(0.02)
        assert parent_heartbeat.exists() and child_heartbeat.exists()
        if stop == "cancel":
            task.cancel()
            expected = asyncio.CancelledError
        else:
            expected = subprocess.TimeoutExpired
        with pytest.raises(expected):
            await task
        assert len(stopped) == 1 and stopped[0] is not None
        before = (parent_heartbeat.read_bytes(), child_heartbeat.read_bytes())
        await asyncio.sleep(0.15)
        assert before == (parent_heartbeat.read_bytes(), child_heartbeat.read_bytes())
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.parametrize("build_times_out", [False, True])
def test_only_local_build_is_bounded_and_timeout_stops_setup(
    monkeypatch, build_times_out
):
    calls = []

    async def run(command, **options):
        calls.append((command, options))
        if command[1:] == ["run", "build"] and build_times_out:
            raise subprocess.TimeoutExpired(command, options["timeout"])

    monkeypatch.setattr(sys, "argv", ["setup.py"])
    monkeypatch.setattr(setup.shutil, "which", lambda name: name)
    monkeypatch.setattr(setup.subprocess, "check_output", lambda *a, **k: "v22.12.0")
    monkeypatch.setattr(setup, "run_command", run)
    if build_times_out:
        with pytest.raises(SystemExit, match="Frontend build exceeded 10 minutes"):
            setup.main()
        assert len(calls) == 2
    else:
        setup.main()
        assert calls[-1][0][1:] == ["scripts/install_compiler.py", "--if-missing"]
    for command, options in calls:
        assert options["timeout"] == (600 if command[1:] == ["run", "build"] else None)
