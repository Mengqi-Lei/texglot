"""Extract a bounded source-language abstract without executing TeX."""

from __future__ import annotations

import re
from pathlib import Path

from .latex import COMMAND, definition_end, group_end, inline_literal_end
from .sources import visible_tex

MAX_PAPER_CONTEXT_CHARS = 6000
MAX_CONTEXT_SOURCE_CHARS = 2_000_000
MAX_INCLUDE_DEPTH = 32
DEFINITIONS = {
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareRobustCommand",
    "newenvironment",
    "renewenvironment",
    "def",
    "edef",
    "gdef",
    "xdef",
}
OPAQUE = {
    "comment",
    "verbatim",
    "verbatim*",
    "Verbatim",
    "lstlisting",
    "minted",
    "filecontents",
    "filecontents*",
    "CCSXML",
}


def limit_context(text: str) -> str:
    """Cap characters (not tokens), preferring a nearby complete sentence."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= MAX_PAPER_CONTEXT_CHARS:
        return text
    prefix = text[: MAX_PAPER_CONTEXT_CHARS - 1]
    sentences = list(re.finditer(r"[.!?](?:\s|$)|[。！？]", prefix))
    if sentences and sentences[-1].start() >= MAX_PAPER_CONTEXT_CHARS * 0.7:
        prefix = prefix[: sentences[-1].start() + 1]
    elif prefix.rfind(" ") >= MAX_PAPER_CONTEXT_CHARS * 0.8:
        prefix = prefix[: prefix.rfind(" ")]
    return prefix.rstrip() + "…"


def _space(text, pos):
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _closed_group_end(text, pos):
    """Unlike group_end, distinguish a missing closing brace from end-of-input."""
    depth = 0
    while pos < len(text):
        if match := COMMAND.match(text, pos):
            pos = match.end()
            continue
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return None


def _argument(text, pos):
    pos = _space(text, pos)
    if pos < len(text) and text[pos] == "{":
        end = group_end(text, pos)
        return text[pos + 1 : end - 1], end
    match = re.match(r"[^\s{}%]+", text[pos:])
    return (match.group(), pos + match.end()) if match else ("", pos)


def _definition_end(text, pos, name):
    return definition_end(text, pos, name)


def _document_source(
    root: Path, main: str, source_files: list[str] | None = None
) -> str:
    root = root.resolve()
    main_path = (root / main).resolve()
    allowed = (
        {(root / name).resolve() for name in source_files} | {main_path}
        if source_files is not None
        else None
    )
    remaining = MAX_CONTEXT_SOURCE_CHARS

    def visit(path, stack):
        nonlocal remaining
        if (
            remaining <= 0
            or len(stack) >= MAX_INCLUDE_DEPTH
            or path in stack
            or not path.is_relative_to(root)
            or not path.is_file()
            or allowed is not None
            and path not in allowed
        ):
            return ""
        with path.open(encoding="utf-8") as file:
            text = file.read(remaining)
        remaining -= len(text)
        text = visible_tex(text)
        parts, cursor, pos = [], 0, 0
        while match := COMMAND.search(text, pos):
            name = match.group()[1:].rstrip("*")
            pos = match.end()
            replacement = None
            if name in DEFINITIONS:
                pos = _definition_end(text, pos, name)
                replacement = " "
            elif name in {"verb", "lstinline"}:
                pos = inline_literal_end(text, pos, name)
                replacement = " "
            elif name in {"input", "include", "subfile"}:
                filename, pos = _argument(text, pos)
                replacement = " "
                if filename and not any(c in filename for c in "\\#{}|\x00"):
                    if not filename.endswith(".tex"):
                        filename += ".tex"
                    for base in (main_path.parent, path.parent, root):
                        child = (base / filename).resolve()
                        if child.is_relative_to(root) and child.is_file():
                            replacement = visit(child, stack | {path})
                            break
            elif name in {"begin", "end"}:
                env, end = _argument(text, pos)
                if name == "end" and env == "document":
                    parts.append(text[cursor:end])
                    return "".join(parts)
                if name == "begin" and env in OPAQUE:
                    closing = re.search(
                        r"\\end\s*\{" + re.escape(env) + r"\}", text[end:]
                    )
                    pos = end + closing.end() if closing else len(text)
                    replacement = " "
            if replacement is not None:
                parts.extend((text[cursor : match.start()], replacement))
                cursor = pos
        parts.append(text[cursor:])
        return "".join(parts)

    return visit(main_path, set())


def extract_paper_context(
    root: Path, main: str, source_files: list[str] | None = None
) -> str:
    """Use the first explicit abstract in include order; no arbitrary prose fallback.

    Recognizes abstract environments and abstract commands. Formatting and math
    inside the abstract remain readable LaTeX, preserving numbers and symbols.
    Macro-generated/conditional abstracts are not evaluated by this extractor.
    """
    try:
        text = _document_source(root, main, source_files)
        structured_abstract = bool(
            re.search(r"\\documentclass\s*(?:\[[^]]*\]\s*)?\{aa\}", text)
        )
        for match in re.finditer(r"\\begin\s*\{(abstract\*?)\}|\\abstract\b", text):
            pos = _space(text, match.end())
            if env := match.group(1):
                end = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", text[pos:])
                if not end:
                    continue
                raw = text[pos : pos + end.start()]
            else:
                if pos < len(text) and text[pos] == "[":
                    pos = _space(text, group_end(text, pos))
                if pos < len(text) and text[pos] == "{":
                    end = _closed_group_end(text, pos)
                    if end is None:
                        continue
                    raw = text[pos + 1 : end - 1]
                    if structured_abstract:
                        # Astronomy & Astrophysics has five explicit fields:
                        # context, aims, methods, results and conclusions.
                        fields = [raw]
                        for _ in range(4):
                            pos = _space(text, end)
                            if pos >= len(text) or text[pos] != "{":
                                break
                            end = _closed_group_end(text, pos)
                            if end is None:
                                break
                            fields.append(text[pos + 1 : end - 1])
                        raw = " ".join(fields)
                elif end := re.search(r"\\endabstract\b", text[pos:]):
                    raw = text[pos : pos + end.start()]
                else:
                    continue
            context = limit_context(raw)
            # A bare unknown macro such as \abstract{\summarytext} provides no
            # readable background unless TeX evaluates it; leave context empty.
            if context and re.search(r"[^\W\d_]{2,}", COMMAND.sub("", context)):
                return context
    except (OSError, UnicodeError, RecursionError, ValueError):
        # Context is optional; unsupported source must not stop translation.
        return ""
    return ""
