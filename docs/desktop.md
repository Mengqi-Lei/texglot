# Desktop app

**English** · [简体中文](desktop_CN.md) · [README](../README.md)

TeXGlot's desktop packages include the interface, Python service and Tectonic 0.17.0. End users do not need Python, Node.js, uv or a separately installed TeX distribution. The app runs locally; API configuration and translation behavior are shared with the browser version.

## Install and open

- **Apple Silicon Mac:** download `TeXGlot-1.0.5-macOS-arm64.dmg`, open it, drag TeXGlot into Applications and launch TeXGlot.
- **Intel Mac:** use `TeXGlot-1.0.5-macOS-x64.dmg` when attached to the release.
- **Windows x64:** use `TeXGlot-1.0.5-Windows-x64-Setup.exe` when attached to the release. The installer runs for the current user and creates Start menu and desktop shortcuts; administrator access is not required.

Only attached, verified assets are release downloads. See the [platform table](platforms.en.md) for current validation status. The initial packages do not have an Apple Developer ID/notarization or a Windows publisher certificate. Your OS may display an unknown-publisher warning; the release hashes verify file integrity, not publisher identity. Do not disable system security settings to install the app.

On first launch, open **Model settings**, configure Qwen, DeepSeek or your own endpoint, then test the connection. First compilation needs internet access to fetch TeX packages and fonts. These resources are cached for later use. No model key is included in the installer.

## Papers containing EPS figures

These papers need an additional **Ghostscript** installation; Ghostscript is not bundled with TeXGlot. On macOS use `brew install ghostscript`. On Windows install the 64-bit version from the [official Ghostscript download page](https://www.ghostscript.com/releases/gsdnld.html); TeXGlot detects its standard installation folder. On Linux use your distribution's `ghostscript` package.

Resume the existing task after installation. Original EPS files are retained; PDF copies and updated references are generated in the task's prepared source. Conversion uses Ghostscript's restricted mode and retains the macOS compilation sandbox. LaTeX shell escape stays disabled. Redistributing Ghostscript requires complying with its own license separately.

## Daily use and upgrades

The **File** menu opens the main window, the local browser interface or the data folder. On macOS, closing the window keeps the app running; use **Quit TeXGlot** or `Cmd+Q` to exit. Quitting during translation asks whether to keep running. Interrupted work can be resumed from the saved library.

Settings, papers, paragraph caches and annotations live in `~/.texglot` (Windows: `%USERPROFILE%\.texglot`). The embedded browser has its own `desktop-profile` subfolder. Updates replace application files while preserving this data; Windows uninstall also retains the library. Back it up before upgrading.

Source checkouts use their own `data/` directory by default. To migrate, stop both services and copy the contents of that directory into an **empty** `~/.texglot`, or set `TEXGLOT_DATA_DIR` before launching. Do not merge two nonempty libraries blindly. Existing source tasks are not moved automatically.

The desktop app binds to loopback and chooses an available port near 8765. It only shares an existing service when both own the same data directory and run the same version. Close an older service for that directory before opening an upgraded app. If 8765 is occupied, use **File → Open in Browser** for the actual address. Local service errors are recorded in `desktop-service.log` inside the data directory.

## Update reminders

The desktop app checks for stable releases on launch and every 12 hours. A quiet notice appears when an update is available. You can also use **Help → Check for Updates** or **Model settings → Check for updates**, and turn automatic checks off in the update window. Checking does not download or install anything.

Choose **Download update** to fetch the installer for this computer from the official GitHub repository. The app verifies its size and SHA-256 digest, supports cancelling a download, and reuses a verified download after reopening the app. Downloading does not interrupt reading or translation. **Quit and open installer** is available after verification; installation waits until translation tasks are finished or stopped, and pending reader writes are saved first.

On macOS, drag TeXGlot from the opened DMG into Applications and confirm replacement. On Windows, complete the opened installer. This is an assisted installation flow: the current unsigned packages do not replace themselves silently. Native automatic updating on macOS requires signing, as described in the [Electron documentation](https://www.electronjs.org/docs/latest/api/auto-updater#macos).

Only desktop builds containing this feature offer these controls; older versions need one manual upgrade. Source/browser installations continue to use their existing installation workflow. The update check contacts GitHub for release information and does not send papers, API keys or library paths. GitHub REST rate limits fall back to the official latest-release redirect; network or verification failures leave the installed application unchanged.

## Bundled command line

The installer also contains the complete CLI engine. Open TeXGlot and use its actual service port for a shared session, or run the engine on its own. For the standard macOS installation:

```bash
"/Applications/TeXGlot.app/Contents/Resources/engine/texglot-engine" --help
"/Applications/TeXGlot.app/Contents/Resources/engine/texglot-engine" 1706.03762v7 --language zh
```

On Windows, the executable is `resources\engine\texglot-engine.exe` inside the installation folder. The engine accepts the same [CLI options](cli.en.md), including batches and resumption. The desktop installer does not change the shell's PATH; a source or wheel installation can provide the shorter `texglot` command.

## Build installers from source

Each installer must be built on its target operating system and architecture. Install Node.js 22.12+ and uv, then run:

```bash
cd frontend
npm ci
npm test
npm run build
cd ..
uv sync --locked --group desktop --python 3.13.11
cd desktop
npm ci
npm test
cd ..
uv run python scripts/build_desktop.py
```

Finished installers appear in `desktop/out`. PyInstaller freezes the service; electron-builder packages the native window and installer. The compiler download is pinned and checksum verified. The frozen engine lives under `desktop/engine-dist/texglot-engine`; validate it with:

```bash
# Use texglot-engine.exe on Windows.
uv run python scripts/smoke_platform.py --engine desktop/engine-dist/texglot-engine/texglot-engine --output output/desktop-smoke
```

The check removes development tools from PATH, calls a local model stub, translates `.tex` and Unicode multi-file ZIP inputs, verifies Chinese PDF text and tests parent-process shutdown. It does not spend model credits or establish translation quality for arbitrary papers.

[Native build workflow](../.github/workflows/desktop.yml) builds Windows x64 and Intel macOS on GitHub-hosted runners, verifies frozen engines and exercises Windows silent installation. It is manually dispatched and uploads build artifacts to the workflow run; it never publishes a release. Configure trusted signing credentials separately before producing signed public packages. Third-party notices are included in the app and exposed through **Help → Third-party Licenses**.
