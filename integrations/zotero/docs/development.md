# Zotero integration development

User-facing installation and operation are documented in the [English guide](../README.md) and [中文指南](../README_CN.md).

## Build and test

Use Node.js 20 or newer. From the repository root:

```bash
cd integrations/zotero
npm ci
npm run typecheck
npm test
npm run build
npm run smoke
```

The build writes disposable files to `.scaffold/` and produces `.scaffold/texglot-zotero-<version>.xpi`. These generated files and `node_modules` stay untracked and are excluded from the Python wheel and desktop package. The XPI is distributed separately, from the same repository.

From the repository root, audit a package before release:

```bash
python scripts/audit_zotero.py integrations/zotero/.scaffold/texglot-zotero-1.0.0.xpi
```

Use the filename produced by the build if the plugin version changes.

## Code boundaries

- `src/arxiv.ts`: identifier parsing and reading explicitly selected LaTeX source attachments.
- `src/pdf-source.ts`: asynchronous first-page extraction and file-fingerprint caching through host APIs.
- `src/source-resolution.ts`: shared source selection, version evidence, official-version fallback and original/translation pairing.
- `src/bridge.ts`: local-service discovery, HTTP timeouts, capability checks and task polling.
- `src/attachments.ts`: validated artifact import and saved source bindings.
- `src/menus.ts`: translation/reuse workflow and default comparison selection.
- `src/zotero-runtime.ts`: native Zotero APIs behind the `ZoteroRuntime` interface in `src/types.ts`.
- `src/split-reader.ts`: embedded Zotero readers, synchronization, annotations and tab lifecycle.
- `src/status-column.ts`: lazy attachment-based status and transient task activity.

Business logic should use the runtime interface instead of directly accessing Zotero globals. Automated tests use in-memory items, mocked HTTP and adapters; they must not write a user's Zotero database.

## Core contract

The core exposes an integration adapter:

```text
GET  /api/integrations/zotero/health
POST /api/integrations/zotero/sources/resolve
POST /api/integrations/zotero/jobs
GET  /api/integrations/zotero/jobs/{id}
GET  /api/integrations/zotero/jobs/{id}/artifacts/{original|translated|source}
```

Task creation requires the core to advertise `library_reuse`. Never fall back from a missing integration submission endpoint to the legacy create endpoint: that would spend model tokens on a paper the user expected to reuse. Health checks, task reads and artifact downloads retain read-only compatibility paths.

Official version lookup requires `arxiv_resolution`; the updated core also advertises `original_pdf`. A locally confirmed complete version can avoid official lookup. New attachment metadata records the complete source identity, original attachment key and SHA-256 fingerprints. Existing pairs can reopen without a running core.

The broader API and integration design are described in the [shared design document](../../../docs/zotero-integration-design.md).

## Native verification

The XPI currently permits Zotero 9 only. Real-host checks have used macOS Zotero 9.0.6; Node tests do not establish compatibility with other Zotero versions or platforms. Split view uses Zotero internal reader APIs, so new host versions require native verification before expanding the manifest range.

Before shipping an XPI:

1. Run type checking, tests, build, bootstrap smoke and the package audit.
2. Verify that the archive contains only `manifest.json`, `bootstrap.js`, `dist/addon.js` and the icon; no credentials, user papers, source maps or dependency trees.
3. Exercise a disposable Zotero profile or explicitly scoped test collection with an isolated TeXGlot service and a local test provider.
4. Cover complete IDs, bare parent and attachment URLs with PDF version stamps, ambiguous files, unknown-version confirmation and cancellation, conflicting paper IDs and changed file fingerprints.
5. Verify core-library reuse, active-task following, duplicate-import prevention and the old-core update prompt without model requests.
6. Verify original-only, translation-only and comparison opening; double-click enabled/disabled; scrolling from both panes; resizing; search; annotations; closing and reopening tabs; service and Zotero restarts.
7. Confirm original files and annotations are unchanged and each translated PDF is attached to the intended parent.
8. Verify the **installed** App and XPI as well as the source build. A shared development version string does not establish that the installed files contain the current code; check capabilities and artifact hashes.

Keep test papers, profiles, keys and native QA output outside exported release assets.

## Licensing

The plugin follows TeXGlot's [Apache 2.0 license](../../../LICENSE). It is independently implemented rather than copied from third-party translation add-ons. Zotero hosts both reader panes; other reader extensions may not receive identical events in embedded readers and can use the ordinary single-PDF reader when needed.
