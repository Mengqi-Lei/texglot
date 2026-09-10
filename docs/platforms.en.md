# Platform support

**English** · [简体中文](platforms.md) · [Back to README](../README.md)

TeXGlot shares its Python service, browser UI, CLI and data format across platforms. Desktop installers bundle the runtime; source launchers remain available. Neither needs WSL.

| Platform | Installer / launcher | Validation coverage |
| :--- | :--- | :--- |
| macOS Apple Silicon | ARM64 DMG; source setup also available | DMG integrity, native desktop window, service startup/shutdown and installed frozen-engine PDF pipeline tested on macOS 26.6.2. |
| macOS Intel | x64 DMG; source setup also available | Built on a native Intel GitHub runner; bundled-engine translation and PDF generation passed. Interactive Intel desktop testing is still pending. |
| Windows 10/11 x64 | x64 EXE; source scripts also available | Native GitHub Windows Server 2025 runner: EXE installation, installed engine, Unicode multi-file input and Chinese PDF generation passed. Interactive Windows 10/11 client testing remains pending. |
| Linux x64 / ARM64 | `bash scripts/setup.sh` / `uv run python scripts/start.py` | Ubuntu x64 CI checks cover the service, CLI and native Chinese PDF pipeline. Native Linux ARM64 verification is still pending. |

Windows ARM64 does not have a bundled portable compiler target. The macOS version above is the tested machine, not an established minimum OS requirement.

## Requirements

- **Desktop:** no separate Python, Node.js or uv installation. The DMG / EXE includes them as needed by the application (Node.js is part of Electron). See the [desktop guide](desktop.md).
- **Source:** uv and Node.js **22.12+**, installed before running setup. Setup manages Python **3.13**; application metadata allows Python 3.11+.
- Internet access for installation and the first TeX package/font downloads. Model translation needs access to the configured endpoint; arXiv input also needs arXiv access.
- A supported model endpoint and, if required, its API key. The API is billed by the provider, not by TeXGlot.
- Tectonic is installed privately under the data directory when not already available. Downloads are pinned to 0.17.0 and verified with SHA-256. XeLaTeX/LuaLaTeX can be selected if separately installed.

Use a short Windows installation path such as `D:\TeXGlot`. Move source and data as needed, but reinstall `.venv` and `node_modules` on the new OS. Do not copy those environments across platforms.

## Diagnostics and custom startup

```bash
# macOS
bash start-texglot.command --check
bash start-texglot.command --no-browser --port 8877
```

```powershell
# Windows
.\start-texglot.cmd --check
.\start-texglot.cmd --no-browser --port 8877
```

`--check` reports Python, frontend and compiler readiness without starting a service. `TEXGLOT_PORT`, `TEXGLOT_DATA_DIR` and `TEXGLOT_NO_BROWSER=1` are also supported. If global CLI discovery fails, run `uv tool update-shell` and reopen the terminal; `uv run python -m app.cli` works in the checkout.

## Isolation and verification

The service uses an OS-specific single-owner lock, native subprocess cleanup and explicit UTF-8 file handling. It binds only to loopback. macOS has an additional compilation sandbox. Windows/Linux do not currently offer equivalent OS-level file isolation; use trusted source projects.

To help validate a platform, run `uv run python scripts/smoke_platform.py --portable-compiler` and attach sanitized results to an issue. This test uses a local model stub, exercises native CLI/PDF generation and does not spend model credits. The [desktop build workflow](../.github/workflows/desktop.yml) builds installers and checks their engines. [Source CI](../.github/workflows/verify.yml) covers Linux, macOS and Windows. Workflow configuration alone does not establish platform support; the table above records the checks completed for this release.
