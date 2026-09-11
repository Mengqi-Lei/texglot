"""Diagnostic recovery for engine-specific code in external TeX packages."""

import asyncio
import hashlib
import tomllib
from pathlib import Path

import pytest
from pypdf import PdfReader

import app.compiler as compiler

PACKAGE = rb"""% Copyright: synthetic test package; retain this notice.
\pdfcompresslevel=0
\pdfobjcompresslevel=3
\pdfoptionpdfminorversion=6
\input{glyphtounicode}
\pdfgentounicode=1
\def\VisibleResult{The scientific content stays intact.}
% Literal example: \pdfcompresslevel=0
"""


def diagnostic(name="fictional-output.sty", *, line=2, command="pdfcompresslevel"):
    return compiler.CompilationError(
        "failure",
        f"error: {name}:{line}: Undefined control sequence",
        tex_log=f"! Undefined control sequence.\nl.{line} \\{command}\n =0\n",
        bundle="https://example.org/pinned-tex-bundle.tar",
    )


@pytest.fixture
def project(tmp_path):
    root, out = tmp_path / "source", tmp_path / "build"
    (root / "paper folder").mkdir(parents=True)
    out.mkdir()
    (root / "paper folder/main.tex").write_text(
        r"\documentclass{article}\begin{document}Paper text.\end{document}"
    )
    return root, "paper folder/main.tex", out


@pytest.mark.parametrize("name", ["fictional-output.sty", "another-layout.cls"])
async def test_recovery_is_package_independent_and_keeps_exact_original(
    project, monkeypatch, name
):
    root, main, out = project

    async def cached(filename, bundle, *_):
        assert filename == name and bundle == diagnostic().bundle
        return PACKAGE

    monkeypatch.setattr(compiler, "_cached_bundle_file", cached)
    assert (
        await compiler.recover_external_package(
            root, main, out, "tectonic", diagnostic(name)
        )
        == name
    )
    target = (root / main).parent / name
    assert target.with_name(name + ".texglot-original").read_bytes() == PACKAGE
    modified = target.read_text()
    assert hashlib.sha256(PACKAGE).hexdigest() in modified
    assert PACKAGE.decode().splitlines()[0] in modified
    assert r"\def\VisibleResult{The scientific content stays intact.}" in modified
    assert r"% Literal example: \pdfcompresslevel=0" in modified
    assert r"\pdfcompresslevel" not in compiler.visible_tex(modified)
    assert r"\input{glyphtounicode}" not in modified
    assert (
        await compiler.recover_external_package(
            root, main, out, "tectonic", diagnostic(name)
        )
        == ""
    )  # A retry never overwrites the first repair.
    assert target.read_text() == modified


@pytest.mark.parametrize(
    "case",
    [
        "unknown-command",
        "wrong-trace-line",
        "missing-trace",
        "missing-bundle",
        "path-traversal",
        "document-file",
        "different-engine",
    ],
)
async def test_ambiguous_or_unsupported_diagnostics_do_not_fetch_or_edit(
    project, monkeypatch, case
):
    root, main, out = project
    error, engine = diagnostic(), "tectonic"
    if case == "unknown-command":
        error = diagnostic(command="UndefinedScientificMacro")
    elif case == "wrong-trace-line":
        error.tex_log = error.tex_log.replace("l.2 ", "l.99 ")
    elif case == "missing-trace":
        error.tex_log = ""
    elif case == "missing-bundle":
        error.bundle = None
    elif case == "path-traversal":
        error = diagnostic("../outside.sty")
    elif case == "document-file":
        error = diagnostic("main.tex")
    else:
        engine = "xelatex"

    async def forbidden(*_):
        pytest.fail("An unconfirmed diagnostic must not query a package")

    monkeypatch.setattr(compiler, "_cached_bundle_file", forbidden)
    assert await compiler.recover_external_package(root, main, out, engine, error) == ""
    assert [p for p in root.rglob("*") if p.is_file()] == [root / main]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        b"",
        b"% missing expected command\n\\pdfgentounicode=1\n",
        b"% shifted source\n% another version\n\\pdfcompresslevel=0\n",
        b"% dynamic assignment\n\\pdfcompresslevel=\\SomeValue\n",
        b"% commented code\n% \\pdfcompresslevel=0\n",
        b"% literal example\n\\verb|\\pdfcompresslevel=0|\n",
    ],
)
async def test_resource_must_match_the_reported_literal_assignment(
    project, monkeypatch, payload
):
    root, main, out = project

    async def cached(*_):
        return payload

    monkeypatch.setattr(compiler, "_cached_bundle_file", cached)
    assert (
        await compiler.recover_external_package(
            root, main, out, "tectonic", diagnostic()
        )
        == ""
    )
    assert [p for p in root.rglob("*") if p.is_file()] == [root / main]


@pytest.mark.parametrize("where", ["local", "nested", "generated", "backup"])
async def test_authored_generated_and_saved_files_are_never_overwritten(
    project, monkeypatch, where
):
    root, main, out = project
    name = "fictional-output.sty"
    if where == "generated":
        path = out / name
    elif where == "nested":
        path = root / "other" / name
    else:
        path = (root / main).parent / (
            name + ".texglot-original" if where == "backup" else name
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"User-owned content")

    async def forbidden(*_):
        pytest.fail("Existing files must be checked before bundle access")

    monkeypatch.setattr(compiler, "_cached_bundle_file", forbidden)
    assert (
        await compiler.recover_external_package(
            root, main, out, "tectonic", diagnostic()
        )
        == ""
    )
    assert path.read_bytes() == b"User-owned content"


async def test_partial_write_is_rolled_back_without_removing_existing_files(
    project, monkeypatch
):
    root, main, out = project
    target = (root / main).parent / "fictional-output.sty"
    original_open = Path.open

    async def cached(*_):
        return PACKAGE

    class FailedWrite:
        def __enter__(self):
            self.stream = original_open(target, "xb")
            return self

        def write(self, _):
            self.stream.write(b"partial")
            raise OSError("Disk full")

        def __exit__(self, *_):
            self.stream.close()

    def failing_open(path, *args, **kwargs):
        return FailedWrite() if path == target else original_open(path, *args, **kwargs)

    monkeypatch.setattr(compiler, "_cached_bundle_file", cached)
    monkeypatch.setattr(Path, "open", failing_open)
    assert (
        await compiler.recover_external_package(
            root, main, out, "tectonic", diagnostic()
        )
        == ""
    )
    assert [p for p in root.rglob("*") if p.is_file()] == [root / main]


@pytest.mark.parametrize("size,exitcode", [(16, 0), (16, 1), (1024 * 1024 + 1, 0)])
async def test_bundle_query_is_isolated_bounded_and_uses_exact_bundle(
    project, monkeypatch, size, exitcode
):
    root, _, out = project
    stream = asyncio.StreamReader()
    stream.feed_data(b"x" * size)
    stream.feed_eof()

    class Process:
        stdout = stream
        returncode = None

        async def wait(self):
            self.returncode = exitcode

    process = Process()

    async def spawn(*command, cwd, env, **kwargs):
        config = tomllib.loads((cwd / "Tectonic.toml").read_text())
        assert config["doc"]["bundle"] == diagnostic().bundle
        assert command[-3:] == ("cat", "--only-cached", "fictional-output.sty")
        assert "UNRELATED_API_KEY" not in env
        assert cwd.is_relative_to(out) and cwd != root
        return process

    async def terminate(child):
        assert child is process
        child.returncode = -1

    monkeypatch.setenv("UNRELATED_API_KEY", "test-secret")
    monkeypatch.setattr(compiler.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(compiler, "terminate_process_tree", terminate)
    result = await compiler._cached_bundle_file(
        "fictional-output.sty", diagnostic().bundle, root, out
    )
    assert result == (b"x" * size if size <= 1024 * 1024 and exitcode == 0 else None)
    assert process.returncode is not None
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("failure", [asyncio.TimeoutError, asyncio.CancelledError])
async def test_bundle_query_terminates_children_on_timeout_or_cancellation(
    project, monkeypatch, failure
):
    root, _, out = project

    class Process:
        returncode = None

    child = Process()

    async def spawn(*_, **kwargs):
        return child

    async def interrupted(coro, **kwargs):
        coro.close()
        raise failure

    async def terminate(process):
        process.returncode = -1

    monkeypatch.setattr(compiler.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(compiler.asyncio, "wait_for", interrupted)
    monkeypatch.setattr(compiler, "terminate_process_tree", terminate)
    query = compiler._cached_bundle_file("fixture.sty", diagnostic().bundle, root, out)
    if failure is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await query
    else:
        assert await query is None
    assert child.returncode == -1
    assert list(out.iterdir()) == []


async def test_native_axessibility_recovery_keeps_formulas_and_actualtext(tmp_path):
    if not compiler.find_compiler("tectonic"):
        pytest.skip("Optional native Tectonic not installed")
    root, out = tmp_path / "source", tmp_path / "build"
    root.mkdir()
    source = r"""\documentclass{article}
\usepackage[accsupp]{axessibility}
\begin{document}
Inline energy: \(E=mc^2\). Displayed fraction:
\[x=\frac{a}{b}\]
The scientific content stays intact.
\end{document}"""
    (root / "main.tex").write_text(compiler.normalize_engine(source, "tectonic"))
    # An authored workspace file must not redirect the recovery's resource lookup.
    (root / "Tectonic.toml").write_text(
        '[doc]\nbundle="https://invalid.invalid/bundle"'
    )
    messages = []

    async def notify(message):
        messages.append(message)

    pdf, warnings = await compiler.compile_pdf(
        root, "main.tex", out, "tectonic", notify
    )
    assert not warnings
    assert sum("已按编译诊断调整 axessibility.sty" in m for m in messages) == 1
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1
    assert "scientific content stays intact" in reader.pages[0].extract_text()
    content = reader.pages[0].get_contents().get_data()
    assert content.count(b"/ActualText") == 2
    original = (root / "axessibility.sty.texglot-original").read_bytes()
    assert b"\\pdfcompresslevel=0" in original
    assert original == await compiler._cached_bundle_file(
        "axessibility.sty", compiler.tectonic_bundle(), root, out
    )  # The shared bundle still contains the unmodified package.
    assert "axessibility.sty" in compiler.compiled_dependencies(
        root, "main.tex", out, "tectonic"
    )


async def test_recovery_keeps_existing_attempt_limit_and_exposes_last_failure(
    project, monkeypatch
):
    root, main, out = project
    attempts = []

    async def failing_compile(*args, **kwargs):
        name = f"different-package-{len(attempts)}.sty"
        attempts.append(name)
        raise diagnostic(name)

    async def cached(*_):
        return PACKAGE

    async def notify(_):
        pass

    monkeypatch.setattr(compiler, "_compile_document", failing_compile)
    monkeypatch.setattr(compiler, "_cached_bundle_file", cached)
    with pytest.raises(compiler.CompilationError) as raised:
        await compiler.compile_pdf(root, main, out, "tectonic", notify)
    assert len(attempts) == 3 and attempts[-1] in raised.value.log
    assert len(list(root.rglob("*.sty"))) == 2
