# Scope and troubleshooting

**English** · [简体中文](troubleshooting_CN.md) · [Back to README](../README.md)

TeXGlot translates **LaTeX source**, not arbitrary uploaded PDFs or scanned documents. An arXiv PDF URL is accepted only as a way to identify a paper whose source is available.

| Situation | What to check |
| :--- | :--- |
| arXiv import fails | Confirm that the paper has downloadable TeX source and that arXiv is reachable. |
| EPS figures | Install optional Ghostscript and resume. Original EPS files are retained; PDF copies are generated for compilation. See the [desktop guide](desktop.md). |
| minted requires shell-escape | The unused package load is removed only when no project use is detected. Used listings and frozen caches are retained; supply a complete cache matching the compilation environment or use listings. External command execution remains disabled. |
| An existing PDF figure cannot be loaded | Compiler-confirmed recoverable index corruption is repaired with a `.texglot-original` backup in the prepared project. Missing, encrypted or unrecoverable figures are reported by filename; add the file, check its reference path or re-export it. Missing content is never hidden behind placeholder figures. |
| PSTricks / PostScript drawings | The default Tectonic bundle does not provide a full PostScript toolchain. Prefer pre-converted PDF figures. A separate full TeX setup needs the matching driver and external tools; verify the drawings as well as the exit status. |
| acmart cannot find `libertinusmath-regular` | TeXGlot normalizes this known bundled font filename. Project-supplied fonts and explicit font paths/extensions take precedence. After updating, use Resume / Retry to refresh prepared sources and reuse valid translations. |
| `amssymb` conflicts with `unicode-math` | A confirmed clash and actual compiler load record allow one unambiguous package call to be guarded. It skips `amssymb` while `unicode-math` is loaded and retains the original call otherwise. Printed code, package options and load order are preserved. Ambiguous loads retain the compiler error for inspection. |
| Compilation fails | Include missing `.sty`, images and bibliography files; inspect the compile log. Templates needing shell escape or unavailable external tools may not work. An installed XeLaTeX/LuaLaTeX can be selected in settings. |
| API errors | Check the endpoint, region, model access, balance and rate limits. Reduce concurrency or increase timeout when needed. |
| Official OpenAI / Claude returns HTTP 400 | Select Custom and enter `https://api.openai.com/v1` or `https://api.anthropic.com/v1`, with a complete model ID available to your account. Use the Chat Completions compatibility endpoint, not native `/responses` or `/messages` URLs. OpenAI output-token limits are adapted; an explicit official temperature rejection is retried with the model default without changing your saved preference. Other 400 errors include redacted provider details. Report the model ID, Base URL, app version and error message, without API keys. |
| A separate preamble causes “main file not found” | Documents that reference a local preamble through `\input` / `\include` are supported. Update and use Resume / Retry; copying the preamble into the main file is unnecessary. Dynamically generated filenames or document entries defined entirely through macros may still need an explicit main file and local references. |
| Some prose stays untranslated | Review task warnings and resume to retry failed segments. Unknown macros, authors and bibliography entries may intentionally remain unchanged. |
| Model reasoning appears in the translation | Update and use Resume / Retry. Recognized LLM response envelopes are cleaned before use, including older cached responses. Incomplete answers are retried. Tags quoted in the source and valid translation caches are preserved. |
| Different page counts | Translation changes text length and pagination. Synchronization uses shared content landmarks where available; otherwise it falls back to page-local positions. It is not sentence-level alignment. |
| Source installation times out during frontend build | The local build stops after 10 minutes. Inspect the output; if directory access is hanging, extract the source into an ordinary local project folder and rerun setup. Dependency downloads are not subject to this build timeout. |
| `texglot` is missing | Reopen the terminal after `uv tool update-shell`, or use `uv run python -m app.cli` in the checkout. |

Text embedded in images is not OCR-translated or redrawn. Model output still needs human review for research use. No automatic check proves semantic correctness for every sentence.
