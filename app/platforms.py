"""Small OS adapters shared by the service and compiler (standard library only)."""

from __future__ import annotations

import asyncio
import errno
import os
import signal
import sys
from contextlib import contextmanager
from pathlib import Path

WINDOWS = sys.platform == "win32"


def configure_stdio():
    if WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")


def process_options(*, background=False):
    if WINDOWS:
        # Win32 process-creation constants; unavailable as subprocess attributes
        # on POSIX, so keeping their SDK values also permits branch tests there.
        return {
            "creationflags": 0x00000200 | (0x00000008 if background else 0x08000000)
        }
    return {"start_new_session": True}


@contextmanager
def service_lock(path: Path):
    """One owner per data directory, with a kernel lock released on process exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        if WINDOWS:
            import msvcrt

            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)

            def acquire():
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(lock, fcntl.LOCK_UN)

        try:
            acquire()
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise RuntimeError(
                "TeXGlot is already running for this data directory"
            ) from None
        try:
            yield
        finally:
            release()


async def terminate_process_tree(process):
    """Stop compiler descendants as well as their parent, including on Windows."""
    if WINDOWS:
        if process.returncode is None:
            killer = await asyncio.create_subprocess_exec(
                str(
                    Path(os.environ.get("SystemRoot", r"C:\Windows"))
                    / "System32/taskkill.exe"
                ),
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                **process_options(),
            )
            try:
                await asyncio.wait_for(killer.wait(), 15)
            except asyncio.TimeoutError:
                killer.kill()
                await killer.wait()
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    await process.wait()


def venv_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
