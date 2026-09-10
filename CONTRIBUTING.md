# Contributing to TeXGlot

**English** · [简体中文](CONTRIBUTING_CN.md) · [Project overview](README.md)

Thank you for improving TeXGlot. Bug fixes, template compatibility, translations, documentation and native Windows/macOS testing are all useful contributions. For a substantial change, open an issue describing the problem and proposed behavior before implementing it. Small fixes can go straight to a pull request.

## Set up a development checkout

Fork [Mengqi-Lei/texglot](https://github.com/Mengqi-Lei/texglot), clone your fork and create a branch. Use a descriptive name such as `fix/reader-position` or `feat/provider-name`.

Install **uv** and **Node.js 22.12+**. From the project root:

```bash
cd frontend
npm ci
npm run build
cd ..
uv sync --locked --python 3.13
uv run python scripts/install_compiler.py --if-missing
```

Build the frontend **before** installing the Python project: the wheel bundles `frontend/dist`. The runtime supports Python 3.11+, while the setup scripts use Python 3.13. This development flow does not replace your globally installed `texglot` command.

Use a separate data directory when developing against an existing installation:

```bash
# macOS / Linux, backend terminal
export TEXGLOT_DATA_DIR="$PWD/output/dev-data"
uv run python -m app.server
```

```powershell
# Windows PowerShell, backend terminal
$env:TEXGLOT_DATA_DIR = Join-Path $PWD 'output/dev-data'
uv run python -m app.server
```

In a second terminal:

```bash
cd frontend
npm run dev
```

Open the URL printed by Vite. Its `/api` proxy points to port **8765**. Stop your other TeXGlot service first, or choose another backend port and update `frontend/vite.config.ts` for that local session. The backend does not auto-reload; restart it after Python edits when no tasks are active. For CLI development, use `uv run python -m app.cli` with the same data directory and port.

## Project map

| Path | Responsibility |
| :--- | :--- |
| `app/main.py`, `app/server.py` | HTTP routes, loopback service and ownership lock |
| `app/cli.py` | CLI configuration, batch submission, polling and export |
| `app/sources.py`, `app/jobs.py` | Input validation, source discovery and job lifecycle |
| `app/latex.py`, `app/paper_context.py`, `app/llm.py` | Extraction, abstract context, prompts, validation and caching |
| `app/compiler.py`, `app/pdf.py`, `app/alignment.py` | TeX compilation, PDF preparation and reading landmarks |
| `app/providers.py`, `app/config.py`, `app/platforms.py` | Provider behavior, persisted settings and OS differences |
| `frontend/src/` | React UI, PDF.js reader, geometry and annotations |
| `tests/`, `frontend/tests/` | Backend and frontend regression tests |
| `examples/` | Small reusable source projects and the Attention walkthrough |
| `scripts/` | Setup, launch, compiler installation, native smoke test and release export |

For a new provider, update backend recognition and presets, frontend presets and translated text together. Support should be based on the documented endpoint contract, not a model-name guess. For prompt changes, review validation and cache fingerprints so old translations cannot silently bypass a changed rule.

## Behavior to preserve

- **Source integrity:** preserve protected LaTeX syntax, math, citations and asset files. Failed segment validation must be visible; do not label mixed failed output as fully translated.
- **Reader behavior:** use shared content destinations and local interpolation for synchronization. Enabling sync follows the translated pane; entering comparison follows the previously visible document; leaving comparison preserves the selected pane. Preserve anchors across resize and zoom. Render only nearby page canvases.
- **Annotations:** store normalized page coordinates and the PDF's SHA-256 version in `reader.json`. Retain revision checks and reversible deletion. Never embed annotations in exported PDFs or source archives.
- **Privacy:** never log keys or send one endpoint's credentials to another. Keep configurations, task files, PDFs, caches and annotations out of commits and fixtures. Use synthetic inputs and mocked providers in automated tests.
- **Localization and platforms:** update both UI languages. Keep UI locale independent of the translation target. Use UTF-8 explicitly and platform helpers for paths, locks and subprocess cleanup; avoid introducing shell-specific runtime assumptions.

## Validate your change

Run from the root, in this order:

```bash
cd frontend
npm ci
npm test
npm run build
cd ..
uv sync --locked
uv run ruff check app tests scripts
uv run python -m pytest -q
uv build
```

These tests do not need paid model credentials. Add focused regression coverage for behavior changes; documentation-only edits usually need link/content checks rather than new unit tests. Test the UI in Chinese and English and at a narrow width when layout changes.

For installation, compiler or process-management changes, also run this on the affected OS:

```bash
uv run python scripts/smoke_platform.py --portable-compiler
```

It downloads the pinned compiler and uses a local model stub with an isolated temporary service. It writes results under `output/platform-smoke/`. It tests the native pipeline, **not** real-model translation quality. Tests of Windows branches on macOS are not a substitute for a Windows run. State the OS and checks you actually executed in the PR.

[Continuous integration](.github/workflows/verify.yml) runs source, frontend and native pipeline checks on Linux, macOS and Windows for pushes to `main` and pull requests. The [desktop build workflow](.github/workflows/desktop.yml) is dispatched manually. Neither workflow publishes a release or requires model API keys; read the actual run results when assessing platform coverage.

## Commits and pull requests

1. Keep each change focused. Include a short problem statement, resulting behavior and relevant validation.
2. Use commit subjects such as `fix(reader): preserve position when switching views`, `feat(provider): add endpoint support` or `docs: clarify Windows setup`. English subjects help shared history; issue/PR discussion can be Chinese or English.
3. Update both language versions of affected documentation and user-facing text. Record user-visible changes in `CHANGELOG.md`.
4. Commit lockfile changes only when dependencies change. Do not include `.venv`, `node_modules`, build output, local configuration, model keys, task data or downloaded research papers.
5. Open a PR against `main`. Include screenshots for visual changes, a minimal reproducer for bugs and remaining limitations. Do not claim tests passed unless you ran them. Wait for review before merging; avoid unrelated reformatting.

The [PR template](.github/pull_request_template.md) and [issue templates](.github/ISSUE_TEMPLATE) provide starting points. Remove credentials, personal paths and paper content you cannot share from logs before attaching them.

## Redistribution and releases

TeXGlot uses [Apache 2.0](LICENSE). Keep its license, preserve third-party notices and describe substantial changes in redistributed versions. By contributing, you agree to license your contribution under the project's Apache 2.0 license and confirm you have the right to submit it. There is no separate CLA or mandatory DCO sign-off.

A release should contain the source archive, wheel, sdist, checksums and bilingual notes. [Release preparation](docs/releasing.md) explains the clean export and verification process. Do not publish private data or assume a paper's availability on arXiv grants permission to redistribute it.

## Desktop packaging

The desktop shell lives in `desktop/`; `scripts/build_desktop.py` builds installers. See [desktop build instructions](docs/desktop.md#build-installers-from-source) for native builds and frozen-engine validation. After changing service startup or shutdown, run `npm test --prefix desktop` and verify an actual installer on the target OS.
