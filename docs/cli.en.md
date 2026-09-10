# TeXGlot CLI

**English** · [简体中文](cli.md) · [Back to README](../README.md)

The CLI and GUI share local settings, jobs, translation caches and the library. If necessary, the CLI starts a background service and reuses it for subsequent commands. It does not require a browser to be open.

## Installation and single inputs

Run the setup for your [platform](platforms.en.md), then `uv tool update-shell` and reopen the terminal. In a built source checkout, use `uv run python -m app.cli` as an alternative to the global command.

```bash
texglot https://arxiv.org/abs/1706.03762v7
texglot ./paper.tex
texglot ./project.zip --main main.tex --language zh -o ./translated
```

Supported inputs: arXiv abstract/PDF URLs and IDs, `.tex`, `.zip`, `.tar`, `.tar.gz`, `.tgz`, `.gz`. Include figures, bibliography and template files in multi-file archives. Quote paths containing spaces, for example `texglot "C:\Papers\My paper.tex" -o "D:\Translated Papers"` on Windows.

`--language zh`, `zh-TW` or `en` selects the translation target; when omitted, saved settings apply. `--locale en` changes CLI messages only.

## Context guidance

Initially enabled. Without an explicit option, new tasks inherit the saved default. The following options apply to all newly submitted inputs in the command:

```bash
texglot 1706.03762v7 --context-guidance
texglot ./paper.tex --no-context-guidance
texglot --batch papers.txt --no-context-guidance
texglot --configure --no-context-guidance  # save the default
```

Guidance uses the original abstract (maximum 6,000 characters). Turning it off removes the abstract and guidance instructions from requests, while the standard translation prompt, glossary and structure protection remain active.

`--resume ID` keeps the existing task mode unless explicitly overridden. Changing the mode of a finished task reprocesses it with a distinct cache; leaving the mode unchanged exports its artifacts. A running task's mode cannot be changed until stopped. Each batch JSON result records `context_guidance`.

## Batch processing

```bash
texglot 1706.03762v7 ./paper.tex ./project.zip -o ./translated
texglot --batch papers.txt --batch more-papers.txt --json
```

A UTF-8 batch file has one source per line. Blank lines and lines starting with `#` are ignored. Relative paths in a batch file resolve from **that file's directory**. Command-line paths and the output directory resolve from the current working directory. Try the bundled [small-source batch](../examples/cli-batch.txt) or [Attention batch](../examples/attention-is-all-you-need/papers.txt).

Papers are processed in sequence, with bounded paragraph concurrency within each paper. Failure of one paper does not stop the rest unless `--fail-fast` is set. `Ctrl+C` stops the active task and ends the batch; completed tasks and paragraphs are retained, and inputs not yet started are not submitted. If the service connection also fails, the CLI prints the task ID for later inspection or resumption.

## Exports and resumption

The default output directory is `./texglot-output/`:

```text
texglot-output/
  1706.03762v7-<task-id>/
    translated.pdf
    original.pdf
    translated-source.zip
    compile.log
  batch-<unique-id>.json
```

Available artifacts are also exported for failed tasks. Re-exporting adds a numeric suffix instead of overwriting existing files. Batch JSON contains status, errors, page counts, cumulative recorded token usage and output paths.

```bash
texglot --list
texglot --status TASK_ID
texglot --resume TASK_ID -o ./translated
texglot --resume FIRST_ID --resume SECOND_ID
```

Resumption waits for running tasks, continues interrupted/failed tasks, and exports completed tasks. The target language stays with the task; submit a new task to change it. A `partial` result has paragraphs that failed validation and remain in the source language; inspect warnings and resume to retry.

| Exit code | Meaning |
| :--- | :--- |
| `0` | All requested work succeeded |
| `1` | Failure, partial result requiring review, or service error |
| `2` | Invalid command arguments |
| `130` | User interruption |

`--json` writes machine-readable results to stdout and progress to stderr.

## Model configuration

Settings saved in the GUI work in the CLI. You can also configure from the terminal:

```bash
texglot --configure
texglot --configure --provider qwen --base-url https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1 --key-env DASHSCOPE_API_KEY --test
texglot --configure --provider deepseek --key-env DEEPSEEK_API_KEY --test
texglot --configure --provider qwen
texglot --show-config
```

Plain `--configure` prompts for the endpoint, model and a hidden key. In scripts, set a secret environment variable and use `--key-env` to read it; avoid key literals in command arguments. `--show-config` reports only whether a key exists.

`--provider qwen|deepseek|custom` is used with `--configure`. Qwen defaults to `qwen3.7-plus`; its initial configuration needs the OpenAI-compatible endpoint from your Alibaba workspace. Replace the workspace placeholder above. Switching to a previously saved provider restores its connection; a new endpoint never inherits another endpoint's key. An empty key preserves the saved key for the same address. `--configure --clear-key` removes only the current address's saved key.

## Service and storage

```bash
texglot --serve
texglot --no-start --list
texglot --port 8877 paper.tex
```

A background service continues after a CLI batch exits, and serves the GUI at `http://127.0.0.1:8765`. For a service that stops with its terminal, run `texglot --serve` and submit jobs from a second terminal. If the service already exists, `--serve` reports its URL.

Source installs default to the checkout's `data/`; standalone wheel installs use `~/.texglot/`. `TEXGLOT_DATA_DIR` and `TEXGLOT_PORT` override these defaults. A data directory can only have one owning service. A port belonging to another application or data directory is rejected to avoid operating on the wrong library.

Release wheels bundle the frontend, PDF resources and fallback font. The default Attention example downloads its source from arXiv when run. They still need a TeX compiler; the recommended source-archive setup prepares it automatically. Native Windows support is a preview; see [platform verification](platforms.en.md).
