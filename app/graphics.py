"""Convert legacy EPS figures before compiling; source archives stay untouched."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
from pathlib import Path

from pypdf import PdfReader

from .compiler import find_compiler, sandbox_command
from .platforms import process_options, terminate_process_tree
from .runtime import child_environment
from .sources import visible_tex


def redirect_compiled_eps(root: Path, main: str, conversions: dict[Path, Path]) -> None:
    """Route the exact EPS selected by graphicx, after macro/path resolution.

    The driver hashes the file it actually opened. This works with parameterized
    figure macros, scoped paths and identical basenames without evaluating TeX
    in Python. MD5 is only a lookup key; reject ambiguous keys before compiling.
    Generated destinations use ASCII names under the document directory.
    """
    mappings = {}
    for source, target in conversions.items():
        data = source.read_bytes()
        key = hashlib.md5(data, usedforsecurity=False).hexdigest().upper()
        fingerprint = hashlib.sha256(data).hexdigest()
        if key in mappings and mappings[key][0] != fingerprint:
            raise ValueError("EPS 图片校验值冲突，无法安全映射插图")
        relative = target.relative_to((root / main).parent).with_suffix("").as_posix()
        mappings[key] = (fingerprint, relative)
    entries = "\n".join(
        rf"\prop_gput:Nnn \g_texglot_eps_prop {{{key}}}{{{relative}}}"
        for key, (_, relative) in sorted(mappings.items())
    )
    block = (
        r"""% texglot: redirect only compiler-observed EPS assets
\makeatletter
\ExplSyntaxOn
\prop_new:N \g_texglot_eps_prop
"""
        + entries
        + r"""
\AddToHook{package/graphics/after}{
  \cs_new_eq:NN \texglot_eps_setfile:nnn \Gin@setfile
  \cs_set_protected:Npn \Gin@setfile #1#2#3 {
    \str_if_eq:eeTF {#1}{eps} {
      \exp_args:NNx \prop_get:NnNTF \g_texglot_eps_prop
        {\file_mdfive_hash:n{#3}} \l_tmpa_tl {
        \edef\Gin@base{\l_tmpa_tl}
        \def\Gin@ext{.pdf}
        \texglot_eps_setfile:nnn{pdf}{.pdf}{\Gin@base.pdf}
      }{\texglot_eps_setfile:nnn{#1}{#2}{#3}}
    }{\texglot_eps_setfile:nnn{#1}{#2}{#3}}
  }
}
\ExplSyntaxOff
\makeatother
% texglot: end EPS redirection
"""
    )
    document = root / main
    document.write_text(block + document.read_text(encoding="utf-8"), encoding="utf-8")


def find_ghostscript():
    for name in ("gs", "gswin64c", "gswin32c"):
        found = find_compiler(name)
        if found:
            return found
    if os.name == "nt":
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            folder = os.environ.get(key)
            if folder:
                for binary in sorted(
                    (Path(folder) / "gs").glob("gs*/bin/gswin*c.exe"), reverse=True
                ):
                    if binary.is_file():
                        return str(binary)
    return None


REFERENCES = (
    r"\\includegraphics\*?\s*(?:\[[^]]*\]\s*)?\{((?:[^{}]|\{\})+)\}",
    r"\bfile\s*=\s*([^,}\s]+\.eps)",
)

AMBIGUOUS_EPS = "EPS 插图路径包含重定义或作用域不明确的宏，无法安全确定图片；请改为明确的工程内相对路径"
AMBIGUOUS_PATH = "EPS 插图在不同 graphicspath 下指向不同文件，无法安全转换；请为图片指定明确的工程内相对路径"


def scoped_positions(text, positions):
    """Conservatively identify declarations inside explicit local TeX groups."""
    pending = iter(sorted(positions))
    current = next(pending, None)
    scoped = set()
    groups = 0
    environments = []
    for match in re.finditer(
        r"\\(begin|end)\s*\{([^{}]+)\}|\\(begingroup|endgroup)(?![A-Za-z@])|\\[A-Za-z@]+|\\.|[{}]",
        text,
        re.S,
    ):
        while current is not None and current <= match.start():
            if groups or any(name != "document" for name in environments):
                scoped.add(current)
            current = next(pending, None)
        if match[1] == "begin":
            environments.append(match[2])
        elif match[1] == "end" and environments:
            environments.pop()
        elif match[0] == "{" or match[3] == "begingroup":
            groups += 1
        elif match[0] == "}" or match[3] == "endgroup":
            groups = max(0, groups - 1)
    return scoped


def graphics_context(root, main, documents):
    """Collect only literal, unambiguous path declarations; never evaluate TeX."""
    from .latex import group_end

    texts = {}
    pending = [root / main, *documents]
    while pending:
        document = pending.pop(0).resolve()
        if (
            document in texts
            or not document.is_relative_to(root.resolve())
            or not document.is_file()
        ):
            continue
        text = visible_tex(document.read_text(encoding="utf-8"))
        texts[document] = text
        # Figure macros and graphicspath can live in an author-supplied package.
        for match in re.finditer(
            r"\\(usepackage|RequirePackage|documentclass)\s*(?:\[[^]]*\]\s*)?\{([^}]+)\}",
            text,
        ):
            extension = ".cls" if match[1] == "documentclass" else ".sty"
            for name in match[2].split(","):
                for base in ((root / main).parent, document.parent, root):
                    candidate = base / (name.strip() + extension)
                    if candidate.is_file():
                        pending.append(candidate)
                        break

    definitions, values, aliases = {}, {}, {}
    ambiguous = set()
    for text in texts.values():
        matches = list(
            re.finditer(
                r"\\(?:newcommand|renewcommand|providecommand)\*?\s*(?:\{(\\[A-Za-z@]+)\}|(\\[A-Za-z@]+))\s*(?:\[(\d+)\]\s*)?\{|\\(?:def|gdef|edef|xdef)\s*(\\[A-Za-z@]+)([^{}]*)\{",
                text,
            )
        )
        scoped = scoped_positions(text, [match.start() for match in matches])
        for match in matches:
            name = match[1] or match[2] or match[4]
            stop = group_end(text, match.end() - 1)
            body = text[match.end() : stop - 1].strip()
            values.setdefault(name, set()).add(body)
            # Parameterized/redefined macros are deliberately not expanded.
            value = (
                body
                if (
                    match[3] in (None, "0")
                    and not (match[5] or "").strip()
                    and not re.search(r"[#{}$]", body)
                    and match.start() not in scoped
                )
                else None
            )
            if name in definitions and definitions[name] != value:
                definitions[name] = None
                ambiguous.add(name)
            else:
                definitions.setdefault(name, value)
            if match.start() in scoped:
                ambiguous.add(name)
        # A literal def dictionary cannot model later aliases or dynamic defs.
        for match in re.finditer(
            r"\\(?:let|futurelet)(?![A-Za-z@])\s*(\\[A-Za-z@]+)\s*=?\s*(\\[A-Za-z@]+)?",
            text,
        ):
            ambiguous.add(match[1])
            if match[2]:
                aliases.setdefault(match[1], set()).add(match[2])
        for match in re.finditer(
            r"\\(?:csdef|csedef|csgdef|csxdef|cslet|csletcs|letcs)\s*\{([A-Za-z@]+)\}|\\(?:def|gdef|edef|xdef|let)\s*\\csname\s*([A-Za-z@]+)\s*\\endcsname",
            text,
        ):
            ambiguous.add("\\" + (match[1] or match[2]))
    for name in ambiguous:
        definitions[name] = None
    return {
        "texts": texts,
        "macros": definitions,
        "ambiguous_macros": ambiguous,
        "macro_values": values,
        "aliases": aliases,
    }


def expand_graphic_path(value, macros):
    value = re.sub(r"(\\[A-Za-z@]+)\{\}", r"\1 ", value)
    seen = set()
    for _ in range(16):
        if value in seen or re.search(r"[#{}$]", value):
            return None
        seen.add(value)
        matches = list(re.finditer(r"\\[A-Za-z@]+", value))
        if not matches:
            return value.strip() if "\\" not in value else None
        if any(macros.get(match[0]) is None for match in matches):
            return None
        for match in reversed(matches):
            # TeX consumes the whitespace after a control word. Explicit {}
            # terminators are handled separately to retain filename spaces.
            end = match.end()
            while end < len(value) and value[end].isspace():
                end += 1
            value = value[: match.start()] + macros[match[0]] + value[end:]
    return None


def ambiguous_eps_macro(value, context):
    pending = re.findall(r"\\[A-Za-z@]+", value)
    seen = set()
    ambiguous = False
    possible_eps = ".eps" in value.lower()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        ambiguous |= name in context["ambiguous_macros"]
        for body in context["macro_values"].get(name, ()):
            possible_eps |= ".eps" in body.lower()
            pending.extend(re.findall(r"\\[A-Za-z@]+", body))
        pending.extend(context["aliases"].get(name, ()))
    return ambiguous and possible_eps


def resolve_context_eps(value, document, root, main, context, *, known_sources=()):
    """Resolve only when all potentially active search paths agree on an asset."""
    if Path(value).suffix and Path(value).suffix.lower() != ".eps":
        return None
    cwd = root / Path(main).parent
    states, input_states, extension_states = set(), set(), set()
    default_extensions = (".pdf", ".png", ".jpg", ".jpeg", ".eps")
    for text in context["texts"].values():
        groups = list(
            re.finditer(r"\\graphicspath\s*\{((?:\s*\{[^{}]*\}\s*)+)\}", text)
        )
        scoped = scoped_positions(text, [match.start() for match in groups])
        for group in groups:
            paths = tuple(
                expand_graphic_path(item, context["macros"])
                for item in re.findall(r"\{([^{}]*)\}", group[1])
            )
            states.add(paths)
            if group.start() in scoped:
                states.add(())
        inputs = list(
            re.finditer(
                r"(?:\\(?:gdef|def)\s*\\input@path|\\(?:csdef|csgdef)\s*\{input@path\})\s*\{((?:\s*\{[^{}]*\}\s*)+)\}",
                text,
            )
        )
        scoped_inputs = scoped_positions(text, [match.start() for match in inputs])
        for group in inputs:
            input_states.add(
                tuple(
                    expand_graphic_path(item, context["macros"])
                    for item in re.findall(r"\{([^{}]*)\}", group[1])
                )
            )
            if group.start() in scoped_inputs:
                input_states.add(())
        extensions = list(
            re.finditer(r"\\DeclareGraphicsExtensions\s*\{([^}]+)\}", text)
        )
        scoped_extensions = scoped_positions(
            text, [match.start() for match in extensions]
        )
        for match in extensions:
            extension_states.add(tuple(item.strip() for item in match[1].split(",")))
            if match.start() in scoped_extensions:
                extension_states.add(default_extensions)
    # graphicx uses input@path unless graphicspath supplies an override.
    if not states or () in states:
        states.discard(())
        states.update(input_states or {()})
    if not extension_states:
        extension_states.add(default_extensions)
    candidates = set()
    for paths in states:
        for extensions in extension_states:
            candidate = resolve_graphic_asset(
                value,
                [cwd, *(cwd / path for path in paths if path is not None)],
                root,
                extensions=extensions,
                known_sources=known_sources,
            )
            candidates.add(candidate)
            if None in paths or any("\\" in extension for extension in extensions):
                candidates.add(None)
    eps = {
        candidate
        for candidate in candidates
        if candidate is not None and candidate.suffix.lower() == ".eps"
    }
    used_images = context.get("used_images")
    if used_images is not None and not eps.intersection(used_images):
        return None
    if len(candidates) > 1 and eps:
        raise ValueError(AMBIGUOUS_PATH)
    return next(iter(eps)) if eps else None


def resolve_graphic_asset(value, directories, root, *, extensions, known_sources=()):
    # graphicx tries extensions in order, then each search directory for that
    # extension. The selected native PDF must not be displaced by another EPS.
    for suffix in ("",) if Path(value).suffix else extensions:
        for base in directories:
            candidate = (base / (value + suffix)).resolve()
            if candidate.is_relative_to(root.resolve()) and (
                candidate.is_file() or candidate in known_sources
            ):
                return candidate
    return None


def referenced_eps(root, main, documents, context=None):
    context = context or graphics_context(root, main, documents)
    found = set()
    context["resolved_references"] = {}
    for document in context["texts"]:
        visible = visible_tex(document.read_text(encoding="utf-8"))
        plans = {}
        for pattern in REFERENCES:
            for match in re.finditer(pattern, visible, re.I):
                value = expand_graphic_path(match[1].strip(), context["macros"])
                if value is None:
                    if ambiguous_eps_macro(match[1], context):
                        raise ValueError(AMBIGUOUS_EPS)
                    continue
                candidate = resolve_context_eps(value, document, root, main, context)
                if candidate:
                    found.add(candidate)
                    plans[match.span(1)] = candidate
        context["resolved_references"][document.resolve()] = plans
    return found


def rewrite_eps_references(text, document, root, main, conversions, context=None):
    context = context or graphics_context(root, main, [document])
    visible = visible_tex(text)
    plans = context.get("resolved_references", {}).get(document.resolve())
    changes = []
    for pattern in REFERENCES:
        for match in re.finditer(pattern, visible, flags=re.I):
            value = expand_graphic_path(match[1].strip(), context["macros"])
            if value is None:
                if ambiguous_eps_macro(match[1], context):
                    raise ValueError(AMBIGUOUS_EPS)
                continue
            source = (
                plans.get(match.span(1))
                if plans is not None
                else resolve_context_eps(
                    value, document, root, main, context, known_sources=conversions
                )
            )
            if source in conversions:
                target = conversions[source]
                replacement = Path(
                    os.path.relpath(target, root / Path(main).parent)
                ).as_posix()
                changes.append((match.start(1), match.end(1), replacement))
    for a, b, value in sorted(set(changes), reverse=True):
        text = text[:a] + value + text[b:]
    return text


async def prepare_eps(
    root: Path, main: str, notify, timeout=120, source_files=None, used_images=None
):
    context = None
    if used_images is None:
        # External engines without an XDV trace retain conservative static handling.
        documents = [root / value for value in (source_files or [main])]
        context = graphics_context(root, main, documents)
        images = sorted(referenced_eps(root, main, documents, context))
    else:
        images = sorted({Path(path).resolve() for path in used_images})
        if any(
            not path.is_relative_to(root.resolve())
            or not path.is_file()
            or path.suffix.lower() != ".eps"
            for path in images
        ):
            raise ValueError("编译记录包含无效的 EPS 图片路径")
    if not images:
        return 0
    executable = find_ghostscript()
    if not executable:
        raise ValueError(
            "论文含 EPS 插图，需要安装 Ghostscript 后继续；macOS 可运行 brew install ghostscript，Windows 请安装 Ghostscript 64 位版"
        )
    env = {
        k: v
        for k, v in child_environment().items()
        if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    env.pop("GS_OPTIONS", None)
    env.pop("GS_LIB", None)
    # Scratch files obey the same write boundary as the converted figures.
    env.update(TMPDIR=str(root), TEMP=str(root), TMP=str(root))
    conversions = {}
    target_dir = None
    if context is None:
        parent = (root / main).parent
        target_dir = parent / "texglot-eps"
        index = 1
        while target_dir.exists():
            target_dir = parent / f"texglot-eps-{index}"
            index += 1
        target_dir.mkdir()
    for index, source in enumerate(images, 1):
        if target_dir is not None:
            target = target_dir / (
                hashlib.sha256(source.read_bytes()).hexdigest() + ".pdf"
            )
            if target.exists():
                conversions[source] = target
                continue
        else:
            target = source.with_suffix(".pdf")
        if target_dir is None and target.exists():
            digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
            target = source.with_name(source.stem + f".texglot-{digest}.pdf")
            if target.exists():
                raise ValueError("EPS 转换文件名与源码文件冲突，请检查重复的插图文件")
        fd, temporary = tempfile.mkstemp(
            prefix=".texglot-eps-", suffix=".part.pdf", dir=target.parent
        )
        os.close(fd)
        temp = Path(temporary)
        await notify(f"正在转换 EPS 插图 · {index} / {len(images)}")
        command = [
            executable,
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=pdfwrite",
            "-dEPSCrop",
            "-dCompatibilityLevel=1.5",
            "-dEmbedAllFonts=true",
            "-dOmitInfoDate=true",
            "-dOmitID=true",
            "-dOmitXMP=true",
            f"-sOutputFile={temp}",
            "-f",
            str(source),
        ]
        process = await asyncio.create_subprocess_exec(
            *sandbox_command(command, root, root),
            cwd=root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **process_options(),
        )
        try:
            try:

                async def collect():
                    chunks, size = [], 0
                    while chunk := await process.stdout.read(8192):
                        if size < 1024 * 1024:
                            chunks.append(chunk)
                            size += len(chunk)
                    await process.wait()
                    return b"".join(chunks)

                output = await asyncio.wait_for(collect(), timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                await terminate_process_tree(process)
                if asyncio.current_task().cancelling():
                    raise
                raise ValueError(f"EPS 插图转换超时：{source.name}") from None
            if process.returncode or not temp.is_file():
                detail = output.decode(errors="replace")[-1200:]
                raise ValueError(f"EPS 插图转换失败：{source.name}\n{detail}")
            reader = PdfReader(temp)
            if len(reader.pages) != 1:
                raise ValueError(f"EPS 插图转换页数异常：{source.name}")
            temp.replace(target)
            conversions[source.resolve()] = target
        finally:
            temp.unlink(missing_ok=True)
    if context is None:
        redirect_compiled_eps(root, main, conversions)
    else:
        for document in context["texts"]:
            text = document.read_text(encoding="utf-8")
            document.write_text(
                rewrite_eps_references(
                    text, document, root, main, conversions, context
                ),
                encoding="utf-8",
            )
    return len(images)
