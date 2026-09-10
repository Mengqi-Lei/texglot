import asyncio
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from app import platforms
from app.config import Settings, atomic_json
from app.sources import windows_compatible_path
from scripts.install_compiler import asset_for


def test_native_lock_excludes_other_process_and_releases(tmp_path):
    path = tmp_path / "研究 paper" / "service.lock"
    script = "from pathlib import Path; from app.platforms import service_lock; import sys\ntry:\n with service_lock(Path(sys.argv[1])): print('acquired')\nexcept RuntimeError: sys.exit(17)\n"

    def probe():
        return subprocess.run(
            [sys.executable, "-c", script, str(path)], capture_output=True, timeout=10
        )

    with platforms.service_lock(path):
        assert probe().returncode == 17
    assert probe().returncode == 0


def test_windows_lock_uses_same_byte_for_acquire_and_release(tmp_path, monkeypatch):
    calls = []

    def locking(fd, mode, count):
        calls.append((os.lseek(fd, 0, os.SEEK_CUR), mode, count))

    monkeypatch.setattr(platforms, "WINDOWS", True)
    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        types.SimpleNamespace(locking=locking, LK_NBLCK=2, LK_UNLCK=0),
    )
    with platforms.service_lock(tmp_path / "service.lock"):
        pass
    assert calls == [(0, 2, 1), (0, 0, 1)]


def test_launch_flags_and_venv_paths_are_platform_specific(tmp_path, monkeypatch):
    monkeypatch.setattr(platforms, "WINDOWS", True)
    assert platforms.process_options() == {"creationflags": 0x200 | 0x08000000}
    assert platforms.process_options(background=True) == {"creationflags": 0x200 | 8}
    assert platforms.venv_python(tmp_path) == tmp_path / ".venv/Scripts/python.exe"
    monkeypatch.setattr(platforms, "WINDOWS", False)
    assert platforms.process_options(background=True) == {"start_new_session": True}
    assert platforms.venv_python(tmp_path) == tmp_path / ".venv/bin/python"


async def test_cancel_stops_native_compiler_process_tree(tmp_path):
    heartbeat = tmp_path / "中文 heartbeat.txt"
    child = "import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile True:\n p.write_text(str(time.time()),encoding='utf-8'); time.sleep(.02)"
    parent = "import subprocess,sys,time\np=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]])\nprint(p.pid,flush=True)\ntime.sleep(120)"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        parent,
        child,
        str(heartbeat),
        stdout=asyncio.subprocess.PIPE,
        **platforms.process_options(),
    )
    try:
        assert await asyncio.wait_for(process.stdout.readline(), 10)
        for _ in range(100):
            if heartbeat.exists():
                break
            await asyncio.sleep(0.02)
        assert heartbeat.exists()
        await asyncio.wait_for(platforms.terminate_process_tree(process), 20)
        before = heartbeat.read_bytes()
        await asyncio.sleep(0.2)
        assert heartbeat.read_bytes() == before
        assert process.returncode is not None
    finally:
        if process.returncode is None:
            await platforms.terminate_process_tree(process)


def test_unicode_config_roundtrip_without_locale_default(tmp_path):
    from app import config

    path = tmp_path / "用户 数据" / "settings.json"
    atomic_json(
        path,
        Settings(glossary="attention = 注意力；café", model="测试模型").model_dump(),
    )
    assert "注意力" in path.read_bytes().decode("utf-8")
    original = config.CONFIG
    try:
        config.CONFIG = path
        assert config.load_settings().glossary == "attention = 注意力；café"
    finally:
        config.CONFIG = original


@pytest.mark.parametrize(
    "name",
    [
        "CON",
        "aux.tex",
        "folder/NUL.bib",
        "COM1.tex",
        "LPT².txt",
        "name. ",
        "foo?.tex",
        "a|b.tex",
    ],
)
def test_windows_reserved_source_names_are_detected(name):
    assert not windows_compatible_path(name)


def test_windows_allows_unicode_spaces_and_normal_tex_names():
    assert windows_compatible_path("章节 1/论文.tex")
    assert windows_compatible_path("main.aux")
    assert windows_compatible_path("computer.tex")


def test_pinned_compiler_assets_cover_supported_platforms():
    for system, machine in [
        ("Windows", "AMD64"),
        ("Darwin", "arm64"),
        ("Darwin", "x86_64"),
        ("Linux", "aarch64"),
    ]:
        url, digest = asset_for(system, machine)
        assert url.startswith(
            "https://github.com/tectonic-typesetting/tectonic/releases/download/"
        )
        assert len(digest) == 64
    assert asset_for("Windows", "AMD64")[0].endswith("windows-msvc.zip")
    with pytest.raises(RuntimeError):
        asset_for("Windows", "ARM64")


def test_portable_installer_rejects_mismatched_checksum(tmp_path, monkeypatch):
    import io

    from scripts import install_compiler

    monkeypatch.setattr(
        install_compiler,
        "asset_for",
        lambda *_: ("https://example.invalid/compiler.zip", "0" * 64),
    )
    monkeypatch.setattr(
        install_compiler.urllib.request,
        "urlopen",
        lambda *_, **__: io.BytesIO(b"corrupted archive"),
    )
    with pytest.raises(RuntimeError, match="checksum"):
        install_compiler.install(tmp_path / "tools", system="Windows", machine="AMD64")
    assert not (tmp_path / "tools").exists()


def test_macos_sandbox_can_read_unicode_project_under_home():
    import tempfile

    from app.compiler import sandbox_command
    from app.config import DATA

    if sys.platform != "darwin":
        pytest.skip("macOS sandbox verification")
    with tempfile.TemporaryDirectory(prefix="沙箱 测试-", dir=DATA) as folder:
        root = Path(folder)
        (root / "out").mkdir()
        source = root / "文本.txt"
        source.write_text("Unicode 路径", encoding="utf-8")
        command = sandbox_command(["/bin/cat", str(source)], root, root / "out")
        result = subprocess.run(command, capture_output=True, timeout=10)
        assert result.returncode == 0
        assert result.stdout.decode("utf-8") == "Unicode 路径"


def test_windows_archive_collisions_preserve_hidden_file_filter(tmp_path, monkeypatch):
    import io
    import zipfile

    from app import sources

    monkeypatch.setattr(sources, "WINDOWS", True)

    def archive(files):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as zipped:
            for name in files:
                zipped.writestr(
                    name,
                    r"\documentclass{article}\begin{document}Example.\end{document}",
                )
        return output.getvalue()

    sources.extract_source(
        archive(["__MACOSX/A", "__MACOSX/a", "main.tex"]),
        "paper.zip",
        tmp_path / "valid",
    )
    assert (tmp_path / "valid/main.tex").exists()
    with pytest.raises(ValueError, match="大小写"):
        sources.extract_source(
            archive(["Main.tex", "main.tex"]), "paper.zip", tmp_path / "collision"
        )
