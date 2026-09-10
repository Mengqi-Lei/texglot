# Scope and troubleshooting

**English** · [简体中文](troubleshooting_CN.md) · [Back to README](../README.md)

TeXGlot translates **LaTeX source**, not arbitrary uploaded PDFs or scanned documents. An arXiv PDF URL is accepted only as a way to identify a paper whose source is available.

| Situation | What to check |
| :--- | :--- |
| arXiv import fails | Confirm that the paper has downloadable TeX source and that arXiv is reachable. |
| EPS figures | Install optional Ghostscript and resume. Original EPS files are retained; PDF copies are generated for compilation. See the [desktop guide](desktop.md). |
| Compilation fails | Include missing `.sty`, images and bibliography files; inspect the compile log. Templates needing shell escape or unavailable external tools may not work. An installed XeLaTeX/LuaLaTeX can be selected in settings. |
| API errors | Check the endpoint, region, model access, balance and rate limits. Reduce concurrency or increase timeout when needed. |
| Some prose stays untranslated | Review task warnings and resume to retry failed segments. Unknown macros, authors and bibliography entries may intentionally remain unchanged. |
| Different page counts | Translation changes text length and pagination. Synchronization uses shared content landmarks where available; otherwise it falls back to page-local positions. It is not sentence-level alignment. |
| `texglot` is missing | Reopen the terminal after `uv tool update-shell`, or use `uv run python -m app.cli` in the checkout. |

Text embedded in images is not OCR-translated or redrawn. Model output still needs human review for research use. No automatic check proves semantic correctness for every sentence.
