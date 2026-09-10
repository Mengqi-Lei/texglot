# Preparing a release

**English** · [简体中文](releasing_CN.md)

This guide describes the repeatable release process for maintainers. Local preparation does not push commits, upload to PyPI or publish a GitHub Release.

## Version and validation

1. Finish the relevant checks in [CONTRIBUTING.md](../CONTRIBUTING.md), including the [source CI](../.github/workflows/verify.yml). Record the operating systems and checks actually completed.
2. Keep the version aligned in `pyproject.toml`, `uv.lock`, `app/main.py`, `app/cli.py`, both frontend and desktop `package.json` files and their lockfiles. Add bilingual notes under `docs/releases/` and update `CHANGELOG.md`.
3. Build each native installer on its target OS/architecture using the [desktop guide](desktop.md). The [desktop workflow](../.github/workflows/desktop.yml) builds and tests Windows x64 and Intel Mac installers; Apple Silicon is built on an ARM Mac. These workflows do not publish releases.

## Prepare the files

Build the frontend, then export a new directory from the project root:

```bash
uv run python scripts/prepare_release.py --output output/release-1.0.2 --installer desktop/out/TeXGlot-1.0.2-macOS-arm64.dmg
```

Repeat `--installer PATH` for each verified DMG or EXE. The output directory must not already exist. The script exports an explicit source-file list, checks documentation links and common credential/path leaks, and builds the source ZIP, wheel and sdist. It also generates SHA-256 checksums, a source manifest and bilingual release text with versioned repository links.

| Output | Purpose |
| :--- | :--- |
| `repository/` | Source snapshot without Git metadata, local data or build environments |
| `artifacts/` | Verified installers, source ZIP, wheel, sdist and `SHA256SUMS.txt` |
| `manifest.json` | Source paths and SHA-256 hashes |
| `release-body.md` | Bilingual GitHub Release description |

Inspect the exported tree and archives. Check that fonts and third-party licenses are present and that no settings, model keys, task PDFs, annotations or local environments are included. Test wheel installation in an isolated environment and verify native installers on their target platforms. Source archives, wheels and installers must use the same runtime and frontend code.

## Publish

Commit the reviewed source changes while preserving the repository's history. Create the matching `vX.Y.Z` tag on the release commit, then prepare a draft [GitHub Release](https://github.com/Mengqi-Lei/texglot/releases) with the generated description and verified assets. Recheck attachment names, checksums and documentation links before publishing.

Keep installers and generated archives in Release assets, not Git history. Publish only the platforms that have been validated and describe remaining limitations accurately. Publisher signing and Apple notarization are separate from file-integrity verification; do not describe unsigned packages as publisher-signed. PyPI publication is a separate process.
