# TeXGlot for Zotero

**English** · [简体中文](README_CN.md) · [Back to TeXGlot](../../README.md)

Start paper translations from Zotero, save the results as attachments and read the original and translation side by side. The plugin connects to TeXGlot on your computer; TeXGlot handles source retrieval, model requests and PDF compilation.

<p align="center"><img src="../../docs/assets/zotero-reader.png" width="100%" alt="TeXGlot inside Zotero: English original on the left and Chinese translation on the right"></p>
<p align="center"><sub>Attention Is All You Need and its Chinese translation in Zotero's native PDF reader.</sub></p>

[Installation](#installation) · [First translation](#first-translation) · [Reading](#reading) · [Versions and reuse](#versions-and-reuse) · [Troubleshooting](#troubleshooting)

## Features

- Translate arXiv papers from the item context menu, or select an attached LaTeX project.
- Identify arXiv versions automatically without adding `v1` or `v2` to item fields by hand.
- Reuse matching translations already saved in Zotero or your TeXGlot library.
- Read both PDFs in one native Zotero tab, with scrolling from either pane and a draggable divider.
- Save translations as child attachments while preserving existing PDFs and annotations.
- See translation availability and task status in a compact TeXGlot column.

## Installation

### 1. Prepare TeXGlot and Zotero

You need **Zotero 9** and a compatible **TeXGlot App or local service**. The plugin does not contain a model or a compiler and cannot translate on its own. Native interaction has been tested with Zotero 9.0.6 on macOS; equivalent plugin testing on other platforms is still pending.

Use a [TeXGlot Release](https://github.com/Mengqi-Lei/texglot/releases) that includes the plugin, and download its matching desktop installer and `texglot-zotero-<version>.xpi`. See the [main installation guide](../../README.md#quick-start).

**Plugin 1.0.0 requires TeXGlot 1.2.0 or newer.** Download the matching desktop installer and `texglot-zotero-1.0.0.xpi` from the [v1.2.0 Release](https://github.com/Mengqi-Lei/texglot/releases/tag/v1.2.0). The older 1.1.3 App does not have the library-reuse interface; updating only the XPI is not enough. Developers can also [build from source](docs/development.md).

Open TeXGlot, configure your provider, model and API key under **Model settings**, test the connection and save. Local models use the same TeXGlot configuration. You do not enter the key again in Zotero.

### 2. Install the XPI

1. In Zotero, open **Tools → Plugins**.
2. Click the gear button and choose **Install Plugin From File…**.
3. Select the `.xpi` file and complete the installation. Restart Zotero if prompted.
4. Return to the library and right-click a paper. The menu should include **使用 TeXGlot 翻译并对照阅读** (Use TeXGlot to translate and read).

The main translation command currently uses this Chinese label. To update the plugin, install the new XPI the same way; there is no need to remove the plugin or existing attachments first. After updating the desktop App, quit the old App and reopen it to activate the new service.

### 3. Keep the local service running

Keep TeXGlot running on the same computer when starting translations or importing results from its library. Source and CLI users can run `texglot --serve`. The plugin discovers the default local address `127.0.0.1:8765` and the desktop fallback port `8766`.

If your App and CLI use separate data directories, the plugin searches only the library of the connected service; it does not merge the two libraries.

## First translation

1. Select the paper's **bibliographic item** in Zotero. An ordinary arXiv item imported by Zotero normally needs no version-field edits.
2. Right-click and choose **使用 TeXGlot 翻译并对照阅读**.
3. The plugin identifies the source and version. It asks you to select a file only when several original PDFs cannot be distinguished automatically.
4. An existing translation is opened or imported. A matching active task is followed. A new translation starts only when neither is available.
5. The completed PDF is saved under the paper as **`[TeXGlot] 简体中文 · arXiv …`**, and comparison opens inside Zotero.

The TeXGlot column shows task activity. For processing logs, stopping a task or continuing/retrying, open the task details in the TeXGlot App. Keep Zotero open to import the result automatically; if you close Zotero during processing, use the same context-menu command later to find the completed result or active task.

The current context-menu action defaults to **Simplified Chinese** with **context guidance enabled**. Model, API and concurrency settings come from TeXGlot. There is no separate translation-options panel in the plugin yet; use the App or CLI to start translations into other languages.

### Supported inputs

| What you have in Zotero | How to use it |
| --- | --- |
| A paper with an arXiv link or ID | Select the paper and use the context-menu command. arXiv must provide LaTeX source. |
| An arXiv ID without `vN` | Supported: the plugin checks the PDF's first page, attachment metadata and, when needed, the official version. |
| An arXiv item without a local PDF | Supported: the plugin obtains the original associated with the translation task. |
| A local LaTeX project | Attach the `.tex`, `.zip`, `.tar`, `.tar.gz`, `.tgz` or `.gz` file to a bibliographic item, select **that source attachment**, then use the command. Include figures and template files in a complete project archive. |
| Only a conference or journal PDF, with no arXiv ID or LaTeX source | Not directly supported. If you verify that the same paper has an arXiv version, add `arXiv:ID` to the item's Extra field before using the plugin. |

A PDF helps identify the source and provides the original for reading. It does not mean that PDF-to-LaTeX conversion or OCR is supported. Paper titles alone are never used to guess identity.

## Reading

### Choose comparison, original or translation

| Reading mode | Action |
| --- | --- |
| Side by side | By default, double-click the **parent paper** when it has a unique matching translation, or use the translation-and-reading context-menu command. |
| Original only | Expand the paper and double-click its original PDF attachment. |
| Translation only | Expand the paper and double-click the `[TeXGlot] …` PDF attachment. |
| Always use ordinary single-PDF opening on double-click | Turn off **TeXGlot: Open comparison on double-click** in the paper's context menu. The translation-and-reading command remains available for comparison. |

The double-click setting persists across restarts. When no matching translation exists, the original is uncertain or several translations are possible, double-click keeps Zotero's ordinary behavior; it does not start a paid translation. To compare a specific translated attachment, select it and use the translation-and-reading context-menu command.

### Split-reader controls

- **Divider:** drag the middle divider to resize the two panes.
- **同步：开 / 关 (Sync: On / Off):** scrolling either pane moves the other while enabled. Disable it to navigate independently.
- **定位基准：译文 / 原文 (Alignment reference: Translation / Original):** choose the pane to follow when enabling synchronization or realigning. This does not restrict scrolling to that pane or swap the documents.
- **Per-pane toolbar:** click the pane you want to use, then search, zoom, navigate or annotate. The horizontal arrows inside a rectangle are Zotero's **Reset zoom** button, not a left/right document switch.

The current Zotero split reader synchronizes by page and position within the page, not sentence by sentence. Translation can change pagination; disable synchronization and locate each passage independently when necessary. Each pane's annotations belong to its Zotero attachment and do not overwrite annotations in the TeXGlot App.

## Versions and reuse

### No manual version suffix required

An explicitly selected PDF takes priority. When a parent item is selected, the plugin examines candidate originals, preferring an arXiv version stamp on the actual PDF over attachment metadata. A parent URL with only the base ID is normal.

When several confirmed versions belong to the same paper, the highest local version is selected; ambiguous files get a picker. If a local PDF's version remains unknown, the plugin resolves the official version and asks whether to use its matching original. Accepting adds a matching original while keeping your old PDF and annotations. Cancelling creates no task.

Once selected, source retrieval, translation lookup and comparison all use that same complete version. Conflicting paper IDs are not silently paired.

### Will a paper translated in the App be translated again?

The ordinary context-menu command checks, in order:

1. A usable corresponding translation under the selected Zotero item.
2. A usable result with the **same complete version and target language** in the connected TeXGlot library, including tasks started from the App, browser, CLI or plugin.
3. A matching task already being processed.
4. Only then, creation of a new translation task.

Reusing a complete result makes no model requests. Changing your model or context settings does not automatically invalidate an existing translation. To translate again with current settings, explicitly choose **Retranslate with TeXGlot (keep existing translations)**. That creates a new task and incurs normal provider usage.

Different versions or languages, damaged or missing result files, and older tasks without a recorded full version may prevent safe reuse. LaTeX uploads match by content and main-file selection, not filename. You can continue/retry failed tasks in the App to reuse their completed paragraph caches.

## Library status icons

The TeXGlot column is initially added beside Title. Show or hide it through the column-header context menu, or drag it to change its position. Its header uses the TeXGlot TG logo. Hover over an item icon for details.

| Icon | Meaning |
| --- | --- |
| Green check | This Zotero item has a TeXGlot translation attachment. |
| Blue clock | A task is being processed in the current plugin session. |
| Amber warning | A task or translation needs review; hover for details. |
| Faint dash | No TeXGlot translation attachment has been recognized under this item. |

**The column does not scan the entire TeXGlot library in advance.** A paper already translated in the App may still show a dash in Zotero. Its first context-menu action finds and imports that result, after which the icon becomes a check. Saved attachment status remains available when the App is closed.

## Troubleshooting

| Situation | What to do |
| --- | --- |
| No TeXGlot context-menu command | Check the Zotero version and plugin's enabled state, select a paper or its attachment, and restart Zotero if installation requested it. |
| Local service unavailable | Start TeXGlot on the same computer, wait for it to load and retry. |
| Prompt to update TeXGlot | Update the matching App and XPI, then quit and reopen the App. The plugin will not silently create a new translation through an older service. |
| No recognized source | Check the arXiv information or attach a complete LaTeX project. An arbitrary PDF alone is not enough. |
| Several originals or translations | Select the specific attachment you want to use; the plugin does not guess from titles. |
| Compilation or model request fails | Review task details and processing logs in the App, correct the configuration or source and continue/retry there. |
| Translation finished but attachment is missing | Keep the App running and use the ordinary context-menu command again to reuse the result and retry importing. |
| A completed App paper starts a new task | Check its complete version, target language, running App build and whether App/CLI installations use different data directories. |
| Double-click does not open comparison | Check the double-click setting, select the parent item, and confirm both local PDFs exist with an unambiguous pairing. |
| The two passages are not precisely aligned | Different page counts are expected; turn synchronization off to position each pane. Sentence-level alignment is not provided. |

PDFs already downloaded into Zotero remain readable without TeXGlot running. New translations, first-time imports from its library and recovery of missing files require the service. If another reader extension behaves differently in split view, open a single PDF in Zotero's ordinary reader.

## Data and development

TeXGlot manages model credentials and translation caches; the plugin does not store another copy of your model key. Imported attachments follow your existing Zotero sync settings. Uninstalling the plugin does not actively delete papers, translated attachments or annotations. See [data and privacy](../../README.md#data-and-privacy) for the App's storage and backup information.

The plugin shares this repository with the core, ships as a separate `.xpi` and uses [Apache 2.0](../../LICENSE). Build commands, tests and the integration contract are in the [development guide](docs/development.md).
