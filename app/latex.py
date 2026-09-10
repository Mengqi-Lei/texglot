"""Lossless source-span translation. The model never gets to generate TeX syntax.

This intentionally does not pretend to implement TeX's execution semantics.
Known prose arguments are opened; unknown macro arguments remain opaque.
Original source slices, rather than a serialized AST, are the authority.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

COMMAND = re.compile(r"\\(?:[a-zA-Z@]+\*?|.)", re.S)
MARKER = re.compile(r"⟪P\d{4,}⟫")


def normalize_generated_prose(text: str) -> str:
    text = re.sub(
        r"\\([nt])(?=[^A-Za-z]|$)",
        lambda m: "\n" if m.group(1) == "n" else "\t",
        text,
    )
    # Blank lines would inject \par into short title/caption/format arguments.
    # Original paragraph breaks inside protected code remain untouched.
    return re.sub(r"\n[ \t\r]*\n(?:[ \t\r]*\n)*", " ", text)


def validate_generated_prose(text: str):
    """Apply the same syntax checks to a repair slot and final unmasked prose."""
    if chr(92) in text or re.search(r"\$[^$]+\$", text):
        raise ValueError("模型生成了额外的 LaTeX 指令")
    if "⟪" in text or "⟫" in text or "```" in text:
        raise ValueError("模型返回了无效格式")


NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)*(?:[eE][+-]?\d+)?"
MAGNITUDE = r"(?:[ \t]+(?:thousand|million|billion|trillion)\b|[KMBT]\b)"
QUANTITY = NUMBER + "(?:" + MAGNITUDE + ")?"
NAMED_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?:[A-Za-z][A-Za-z0-9]*\d[A-Za-z0-9]*|[A-Za-z]+-[A-Za-z]*\d[A-Za-z0-9]*)"
    r"(?:\.\d[A-Za-z0-9]*)*"
    r"(?:-(?:[A-Z][A-Za-z0-9]*|\d[A-Za-z0-9]*)(?:\.\d[A-Za-z0-9]*)*)*"
    r"(?![A-Za-z0-9_])"
)


def named_identifier(value: str) -> bool:
    """Recognize compact names, without freezing ordinary numeric modifiers."""
    if not NAMED_IDENTIFIER.fullmatch(value):
        return False
    prefix = re.split(r"\d", value, maxsplit=1)[0]
    if "-" in prefix:
        prefix = prefix.split("-", maxsplit=1)[0]
        # A normal capitalized word such as Top-5 or Section-3 is still prose.
        return sum(c.isupper() for c in prefix) >= 2 or (
            len(prefix) == 1 and prefix.isupper()
        )
    return True


FONT_SWITCHES = set(
    "tiny scriptsize footnotesize small normalsize large Large LARGE huge Huge bfseries mdseries itshape slshape scshape upshape normalfont rmfamily sffamily ttfamily em bf it sc rm sf tt".split()
)
TEXT_DECLARATIONS = set(
    "noindent indent centering raggedright raggedleft RaggedRight RaggedLeft par smallskip medskip bigskip leavevmode ignorespaces unskip".split()
)
TEXT_ACCENTS = set("\"'`^~=.")
DIMENSION_COMMANDS = set(
    "hskip vskip kern mkern mskip parindent parskip baselineskip lineskip lineskiplimit leftskip rightskip textwidth textheight columnwidth linewidth hsize vsize hangindent topskip hoffset voffset tabcolsep arraycolsep fboxsep fboxrule abovedisplayskip belowdisplayskip abovedisplayshortskip belowdisplayshortskip topmargin oddsidemargin evensidemargin headheight headsep footskip marginparwidth marginparsep leftmargin rightmargin labelwidth labelsep itemindent listparindent itemsep parsep topsep partopsep leftmargini leftmarginii leftmarginiii leftmarginiv leftmarginv leftmarginvi".split()
)
REGISTER_DECLARATIONS = {"newdimen", "newlength", "newskip", "newmuskip", "newcount"}
NULLARY_COMMANDS = set(
    "maketitle tableofcontents listoffigures listoftables clearpage cleardoublepage newpage appendix onecolumn empty".split()
)
INTEGER_COMMANDS = set(
    "char mathchar penalty spacefactor interlinepenalty clubpenalty widowpenalty displaywidowpenalty brokenpenalty hyphenpenalty exhyphenpenalty predisplaypenalty postdisplaypenalty".split()
)
TEXT_ENVIRONMENTS = set(
    "abstract abstract* center flushleft flushright quote quotation verse itemize enumerate description figure figure* table table* proof theorem lemma proposition corollary definition remark example assumption claim".split()
)
ENVIRONMENT_ARGS = {
    "tabular": 1,
    "tabular*": 2,
    "tabularx": 2,
    "tabulary": 2,
    "longtable": 1,
    "array": 1,
    "minipage": 1,
    "multicols": 1,
    "multicols*": 1,
    "list": 2,
    "wrapfigure": 2,
    "wraptable": 2,
    "adjustbox": 1,
}
TABLE_RULE_COMMANDS = {
    "hline",
    "cline",
    "cmidrule",
    "toprule",
    "midrule",
    "bottomrule",
    "hhline",
    "addlinespace",
    "specialrule",
}
CODE_ARGUMENT_COMMANDS = {"code", "texttt", "url", "path", "verb", "lstinline"}


def join_tex(parts: list[str]) -> str:
    """Keep control words separate from translated letters at splice points."""
    result = []
    for part in parts:
        if not part:
            continue
        if result and (part[0].isalpha() or part[0] == "@"):
            previous = result[-1]
            if re.search(r"\\[A-Za-z@]+$", previous):
                commands = list(COMMAND.finditer(previous))
                if (
                    commands
                    and commands[-1].end() == len(previous)
                    and re.fullmatch(r"\\[A-Za-z@]+", commands[-1].group())
                ):
                    result.append(" ")
        result.append(part)
    return "".join(result)


def movable_token(value: str) -> bool:
    # These are semantic text/spacing units, not scope or alignment boundaries.
    value = value.lstrip("~")
    return bool(
        not value
        or value
        in (
            r"\ie",
            r"\eg",
            r"\etc",
            r"\vs",
            r"\etal",
            r"\wrt",
            r"\%",
            r"\#",
            r"\&",
            r"\_",
            r"\$",
            r"\{",
            r"\}",
        )
        or re.fullmatch(r"(?:\\#)?" + QUANTITY + r"(?:\\%)?", value)
        or named_identifier(value)
        or (value.startswith("$") and not value.startswith("$$"))
        or value.startswith(r"\(")
        or re.match(r"\\(?:cite\w*|ref|eqref|pageref|autoref|cref|Cref)\b", value)
    )


OPAQUE_ENV = set(
    "equation equation* align align* alignat alignat* gather gather* multline multline* flalign flalign* eqnarray eqnarray* IEEEeqnarray IEEEeqnarray* IEEEeqnarraybox dmath dmath* dgroup dgroup* mathpar displaymath math tikzpicture pgfpicture axis forest verbatim verbatim* Verbatim lstlisting minted filecontents filecontents* comment CCSXML thebibliography CJK CJK*".split()
)
TEXT_COMMAND = set(
    "title subtitle section subsection subsubsection chapter part paragraph subparagraph caption captionof footnote footnotetext thanks textbf textit textsl textsc textrm textsf texttt textnormal textup emph underline uline sout mbox makebox parbox fbox framebox shorttitle abstract keywords highlight hl foreignlanguage texorpdfstring".split()
)
TEXT_COMMAND.update({"icmltitle", "icmltitlerunning", "icmlkeywords"})
TEXT_COMMAND.update(
    {"IEEEtitleabstractindextext", "tablecaption", "tablehead", "colhead"}
)
OPAQUE_COMMAND = set(
    "author authors affiliation affil address email url path label ref pageref eqref autoref nameref vref cref Cref cite citep citet citealp citeauthor citeyear nocite includegraphics graphicspath input include subfile includeonly bibliography bibliographystyle addbibresource documentclass documentstyle usepackage RequirePackage PassOptionsToPackage newcommand renewcommand providecommand DeclareRobustCommand newenvironment renewenvironment newtheorem newlength setlength addtolength setcounter addtocounter newcounter def edef gdef xdef let newif hypersetup pdfinfo lstset tikzset pgfplotsset color definecolor colorlet multicolumn multirow rule hspace vspace href hyperref".split()
)
OPAQUE_ARGUMENTS = {
    name: 1
    for name in (
        "author authors affiliation affil address email url path label ref pageref eqref autoref nameref vref cref Cref cite citep citet citealp citeauthor citeyear nocite includegraphics input include subfile includeonly bibliography bibliographystyle addbibresource graphicspath documentclass documentstyle usepackage RequirePackage hypersetup pdfinfo lstset tikzset pgfplotsset color pagestyle thispagestyle"
    ).split()
}
OPAQUE_ARGUMENTS["printbibliography"] = 0
STRUCTURAL = set(
    "section subsection subsubsection chapter part paragraph subparagraph caption title subtitle".split()
)
STRUCTURAL.add("icmltitle")
TEXT_AFTER_ARGS = {
    "captionof": 1,
    "parbox": 1,
    "foreignlanguage": 1,
    "href": 1,
    "textcolor": 1,
    "colorbox": 1,
    "fcolorbox": 2,
    "multicolumn": 2,
    "multirow": 2,
    "resizebox": 2,
    "scalebox": 1,
    "rotatebox": 1,
    "raisebox": 1,
}


@dataclass
class Segment:
    start: int
    end: int
    source: str
    masked: str
    protected: list[str]
    role: str = "paragraph"
    literal_macros: dict[str, str] = field(default_factory=dict)

    def literal_value(self, value):
        if named_identifier(value.lstrip("~")):
            return value.lstrip("~")
        if "\\" in value and (
            value[:1].isalpha()
            or value.startswith("{")
            or re.match(r"\\(?:[\"'`^~=.]|[uvHrckbdt](?![A-Za-z@]))", value)
        ):
            from .text_accents import accented_word_text

            if literal := accented_word_text(value):
                return literal
        macro = re.fullmatch(r"~*\\([A-Za-z]+)(?:\{\})?", value.strip())
        return self.literal_macros.get(macro.group(1)) if macro else None

    def is_movable(self, value):
        return movable_token(value) or self.literal_value(value) is not None

    @property
    def key(self):
        material = (
            self.source if self.role == "paragraph" else self.role + "\0" + self.source
        )
        if re.search(r"\\[\"'`^~=.]", self.source):
            material += "\0text-accents-v1"
        if any(
            re.search(r"\\" + name + r"\s*\{", self.source)
            for name in TEXT_DECLARATIONS
        ):
            material += "\0text-declarations-v1"
        # Older caches protected only digits, allowing the model to mistranslate
        # their scale (e.g. billion -> 亿). Invalidate only affected segments.
        if any(
            re.fullmatch(NUMBER + MAGNITUDE, v) or re.fullmatch(NUMBER, v) and "," in v
            for v in self.protected
        ):
            material += "\0quantity-units-v1"
        used = [
            (v, self.literal_value(v))
            for v in self.protected
            if self.literal_value(v) is not None
        ]
        if used:
            material += "\0literal-macros-v1" + repr(used)
        # A source string can acquire a different token layout when a template
        # defines a macro differently. Cached IDs must retain the same meaning.
        material += "\0source-map-v1\0" + repr((self.masked, self.protected))
        return hashlib.sha256(material.encode()).hexdigest()

    def argument_boundaries(self):
        for index, value in enumerate(self.protected[:-1]):
            if value == "]" and self.protected[index + 1] == "{":
                yield index
                continue
            command = COMMAND.match(value)
            if not command or self.protected[index + 1] not in ("{", "["):
                continue
            name = command[0][1:].rstrip("*")
            if name not in FONT_SWITCHES | TEXT_DECLARATIONS | {"item"}:
                yield index

    def whitespace_boundaries(self):
        """Preserve empty groups and table syntax/data cells with no prose."""
        matches = list(MARKER.finditer(self.masked))
        boundaries = set()

        def kind(value):
            command = COMMAND.match(value)
            name = command[0][1:].rstrip("*") if command else ""
            if value == "&":
                return "cell"
            if name in {"\\", "tabularnewline", "cr"}:
                return "row"
            if name in TABLE_RULE_COMMANDS:
                return "rule"
            return ""

        kinds = [kind(value) for value in self.protected]
        for index in range(len(self.protected) - 1):
            if (
                (self.protected[index], self.protected[index + 1])
                in {("{", "}"), ("[", "]")}
                or kinds[index] in {"row", "rule"}
                and kinds[index + 1] == "rule"
            ):
                boundaries.add(index)
        table_edges = [index for index, value in enumerate(kinds) if value]
        for left, right in zip(table_edges, table_edges[1:]):
            cell = self.masked[matches[left].end() : matches[right].start()]
            if not MARKER.sub("", cell).strip():
                # A purely numeric/math/reference cell has no text to translate.
                # This does not constrain math embedded in an actual prose cell.
                boundaries.update(range(left, right))
        for index in sorted(boundaries):
            if not self.masked[
                matches[index].end() : matches[index + 1].start()
            ].strip():
                yield index

    def compact(self, *, arguments_only=False):
        """Treat adjacent syntax as one opaque unit during a repair attempt."""
        protected, expansion = [], {}
        if arguments_only:
            edges = sorted(
                index
                for index in set(self.argument_boundaries())
                | set(self.whitespace_boundaries())
                if re.search(rf"⟪P{index:04d}⟫\s*⟪P{index + 1:04d}⟫", self.masked)
            )
            groups = []
            for edge in edges:
                if groups and edge == groups[-1][-1]:
                    groups[-1].append(edge + 1)
                else:
                    groups.append([edge, edge + 1])
            pairs = [r"\s*".join(f"⟪P{i:04d}⟫" for i in group) for group in groups]
            pattern = re.compile("|".join(pairs + [MARKER.pattern]))
        else:
            pattern = re.compile(r"⟪P\d{4,}⟫(?:\s*⟪P\d{4,}⟫)*")

        def replace(match):
            token = f"⟪P{len(protected):04d}⟫"
            original_tokens = match.group()
            original = MARKER.sub(
                lambda m: self.protected[int(m.group()[2:-1])], original_tokens
            )
            protected.append(original)
            expansion[token] = original_tokens
            return token

        masked = pattern.sub(replace, self.masked)
        return Segment(
            self.start,
            self.end,
            self.source,
            masked,
            protected,
            self.role,
            self.literal_macros,
        ), expansion

    def restore(self, translation: str) -> str:
        translation = normalize_generated_prose(translation.strip())
        expected = [f"⟪P{i:04d}⟫" for i in range(len(self.protected))]
        actual = MARKER.findall(translation)
        if sorted(actual) != sorted(expected):
            raise ValueError("公式或格式标记被修改、遗漏或重复")
        for marker in MARKER.finditer(translation):
            value = self.protected[int(marker[0][2:-1])]
            if not named_identifier(value.lstrip("~")):
                continue
            left, right = translation[: marker.start()], translation[marker.end() :]
            if (
                not value.startswith("~")
                and re.search(r"[A-Za-z0-9_-]\Z", left)
                or re.match(r"[A-Za-z0-9_]|-[A-Z0-9]", right)
            ):
                raise ValueError("命名标识符与相邻文字错误拼接")
        fixed = {
            token
            for token, value in zip(expected, self.protected)
            if not self.is_movable(value)
        }
        if [t for t in actual if t in fixed] != [t for t in expected if t in fixed]:
            raise ValueError("排版结构标记被重排")
        for index in self.argument_boundaries():
            # Prose between \textbf and { changes the actual macro argument.
            adjacent = (
                re.escape(expected[index]) + r"\s*" + re.escape(expected[index + 1])
            )
            if re.search(adjacent, self.masked) and not re.search(
                adjacent, translation
            ):
                raise ValueError("排版命令与文字参数之间不能插入正文")

        def regions(order):
            # Sibling prose before/after an inline group shares the same scope.
            # A citation can move around emphasis, but never into that emphasis,
            # into another table cell, or across a displayed equation.
            frames = [[None, None]]
            cell = block = 0
            places = {}
            for token in order:
                if token not in fixed:
                    places[token] = (
                        cell,
                        block,
                        tuple(tuple(frame) for frame in frames),
                    )
                    continue
                value = self.protected[int(token[2:-1])]
                if value in ("{", "[", r"\begingroup", r"\bgroup"):
                    frames.append([token, None])
                elif value in ("}", "]", r"\endgroup", r"\egroup"):
                    if len(frames) > 1:
                        frames.pop()
                    else:
                        block += 1
                elif value in ("&", r"\\", r"\tabularnewline"):
                    cell += 1
                elif re.match(
                    r"\\(?:tiny|scriptsize|footnotesize|small|normalsize|large|Large|LARGE|huge|Huge|bfseries|mdseries|itshape|slshape|scshape|upshape|normalfont|rmfamily|sffamily|ttfamily|em|bf|it|sc|rm|sf|tt|fontsize|selectfont)\b",
                    value,
                ):
                    frames[-1][1] = token
                elif value.startswith((r"\begin", r"\[", "$$")):
                    block += 1
            return places

        if regions(actual) != regions(expected):
            raise ValueError("数字、公式或引用跨越了原来的格式边界或表格单元格")
        for index in self.whitespace_boundaries():
            adjacent = (
                re.escape(expected[index]) + r"\s*" + re.escape(expected[index + 1])
            )
            if not re.search(adjacent, translation):
                raise ValueError("表格结构、空单元格或空格式组中不能插入正文")
        plain = MARKER.sub("", translation)
        validate_generated_prose(plain)
        if len(plain.strip()) < max(1, len(MARKER.sub("", self.masked).strip()) * 0.10):
            raise ValueError("译文异常短，可能遗漏正文")

        # Escape only generated prose, never the protected original slices.
        def escape(s):
            return "".join(
                {
                    "\\": r"\textbackslash{}",
                    "{": r"\{",
                    "}": r"\}",
                    "$": r"\$",
                    "&": r"\&",
                    "%": r"\%",
                    "#": r"\#",
                    "_": r"\_",
                    "^": r"\textasciicircum{}",
                    "~": r"\textasciitilde{}",
                }.get(c, c)
                for c in s
            )

        out, cursor = [], 0
        for m in MARKER.finditer(translation):
            original = self.protected[int(m.group()[2:-1])]
            out.extend([escape(translation[cursor : m.start()]), original])
            cursor = m.end()
        out.append(escape(translation[cursor:]))
        # A comment token can itself end with a newline. Only restore stripped
        # *prose* whitespace; source whitespace inside tokens is already present.
        lead = re.match(r"\s*", self.masked).group()
        tail = re.search(r"\s*$", self.masked).group()
        return lead + join_tex(out) + tail


def group_end(s: str, pos: int) -> int:
    """Read nested delimiters, escaped delimiters and comments without normalization."""
    if pos >= len(s) or s[pos] not in "[{":
        return pos
    close = {"[": "]", "{": "}"}[s[pos]]
    i = pos + 1
    while i < len(s):
        if s[i] == "\\":
            m = COMMAND.match(s, i)
            i = m.end() if m else i + 2
        elif s[i] == "%":
            j = s.find("\n", i)
            i = len(s) if j < 0 else j + 1
        elif s[i] == "{":
            i = group_end(s, i)
        elif s[i] == close:
            return i + 1
        else:
            i += 1
    return len(s)


def paragraph_break(text: str, pos: int):
    return re.match(r"\n(?:[ \t\r]*\n)+", text[pos:]) if text[pos] == "\n" else None


def skip_tex_space(s: str, pos: int) -> int:
    """Skip TeX argument whitespace, including comments and line breaks."""
    while pos < len(s):
        if s[pos].isspace():
            pos += 1
        elif s[pos] == "%":
            end = s.find("\n", pos)
            pos = len(s) if end < 0 else end + 1
        else:
            break
    return pos


def args_end(s: str, pos: int, required: int | None = None) -> int:
    end = pos
    while True:
        i = skip_tex_space(s, end)
        if required is None and re.search(r"\n[ \t\r]*\n", s[end:i]):
            return end
        if i < len(s) and (s[i] == "[" or s[i] == "{" and required != 0):
            end = group_end(s, i)
            if required is not None and s[i] == "{":
                required -= 1
                if required == 0:
                    return end
        else:
            return end


def math_end(text: str, pos: int, opening: str, aliases: dict[str, str]) -> int:
    """Find the matching math delimiter in TeX tokens, not substring prefixes."""
    environment = re.fullmatch(r"\\begin\{([^}]+)\}", opening)
    closing = (
        r"\end{" + environment[1] + "}"
        if environment
        else {r"\(": r"\)", r"\[": r"\]", "$": "$", "$$": "$$"}[opening]
    )
    depth = 1
    groups = 0
    while pos < len(text):
        if text[pos] == "%":
            pos = skip_tex_space(text, pos)
            continue
        if match := COMMAND.match(text, pos):
            value = match[0]
            pos = match.end()
            name = value[1:]
            if name in ("begin", "end"):
                argument = skip_tex_space(text, pos)
                end = group_end(text, argument)
                if end > argument and text[argument] == "{":
                    value = "\\" + name + text[argument:end]
                    pos = end
            else:
                value = aliases.get(name, value)
            if name in {"bgroup", "begingroup"}:
                groups += 1
                continue
            if name in {"egroup", "endgroup"}:
                groups = max(0, groups - 1)
                continue
            # Text boxes inside math may contain their own $...$ or \(...\).
            # Those mode switches belong to the balanced argument/group, not
            # the surrounding formula. Escaped braces remain control tokens.
            if groups:
                continue
            if value == closing:
                depth -= 1
                if not depth:
                    return pos
            elif environment and value == opening:
                depth += 1
            continue
        if text[pos] == "{":
            groups += 1
        elif text[pos] == "}":
            groups = max(0, groups - 1)
        elif not groups and closing in ("$", "$$") and text.startswith(closing, pos):
            return pos + len(closing)
        pos += 1
    return len(text)


def opaque_environment_end(
    text: str, pos: int, env: str, aliases: dict[str, str]
) -> int:
    # Verbatim-style environments use literal end markers, even inside what
    # looks like a comment. Math uses ordinary TeX comment/token semantics.
    if env in {
        "verbatim",
        "verbatim*",
        "Verbatim",
        "lstlisting",
        "minted",
        "filecontents",
        "filecontents*",
        "comment",
        "CCSXML",
    }:
        ending = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", text[pos:])
        return pos + ending.end() if ending else len(text)
    return math_end(text, pos, r"\begin{" + env + "}", aliases)


def inline_literal_end(text: str, pos: int, name: str) -> int:
    if name == "lstinline":
        pos = args_end(text, pos, required=0)
        pos = skip_tex_space(text, pos)
        if pos < len(text) and text[pos] == "{":
            return group_end(text, pos)
    if pos >= len(text) or text[pos].isspace():
        return pos
    end = text.find(text[pos], pos + 1)
    return len(text) if end < 0 else end + 1


def cmidrule_end(text: str, pos: int) -> int:
    """Read booktabs' [width](trim){column-range} as one syntax unit."""
    end = pos
    opening = skip_tex_space(text, end)
    if opening < len(text) and text[opening] == "[":
        end = group_end(text, opening)
    opening = skip_tex_space(text, end)
    if opening < len(text) and text[opening] == "(":
        cursor = opening + 1
        while cursor < len(text):
            if text[cursor] == "%":
                cursor = skip_tex_space(text, cursor)
            elif command := COMMAND.match(text, cursor):
                cursor = command.end()
            elif text[cursor] == "{":
                cursor = group_end(text, cursor)
            elif text[cursor] == ")":
                end = cursor + 1
                break
            else:
                cursor += 1
        else:
            return len(text)
    opening = skip_tex_space(text, end)
    return (
        group_end(text, opening)
        if opening < len(text) and text[opening] == "{"
        else end
    )


def integer_end(text: str, pos: int) -> int:
    """Keep numeric primitive arguments attached, including TeX radix syntax."""
    start = skip_tex_space(text, pos)
    if start < len(text) and text[start] == "=":
        start = skip_tex_space(text, start + 1)
    while start < len(text) and text[start] in "+-":
        start = skip_tex_space(text, start + 1)
    if text.startswith(r"\numexpr", start):
        cursor = start
        depth = 0
        while cursor < len(text):
            if text[cursor] == "%":
                cursor = skip_tex_space(text, cursor)
            elif command := COMMAND.match(text, cursor):
                cursor = command.end()
                if command[0] == r"\numexpr":
                    depth += 1
                elif command[0] == r"\relax":
                    depth -= 1
                    if not depth:
                        return cursor
            else:
                cursor += 1
    number = re.match(
        r"""(?:\d+|'[0-7]+|"[0-9A-Fa-f]+|`(?:\\(?:[A-Za-z@]+|.)|.))""", text[start:]
    )
    if number:
        return start + number.end()
    command = COMMAND.match(text, start)
    return command.end() if command else pos


def definition_end(text: str, pos: int, name: str) -> int:
    """Consume literal macro definitions without opening their parameter text."""
    pos = skip_tex_space(text, pos)
    if name in {"def", "edef", "gdef", "xdef"}:
        while pos < len(text):
            if text[pos] == "%":
                pos = skip_tex_space(text, pos)
            elif text[pos] == "{":
                return group_end(text, pos)
            else:
                match = COMMAND.match(text, pos)
                pos = match.end() if match else pos + 1
        return pos
    if pos < len(text) and text[pos] == "{":
        pos = group_end(text, pos)
    elif match := COMMAND.match(text, pos):
        pos = match.end()
    else:
        return pos
    return args_end(text, pos, required=2 if "environment" in name else 1)


def dimension_end(text: str, pos: int) -> int:
    """Consume an unbraced TeX length/glue value without exposing its unit."""
    space = r"(?:\s|%[^\n]*(?:\n|$))*"
    number = r"[+-]?\s*(?:\d+(?:\.\d*)?|\.\d+)"
    unit = r"(?:pt|pc|in|bp|cm|mm|dd|cc|sp|ex|em|mu|fil{1,3})(?![A-Za-z])"
    register = r"\\[A-Za-z@]+\d*"
    value = rf"(?:{number}\s*(?:{unit}|{register})|[+-]?\s*{register})"
    expression = re.match(
        space + r"=?" + space + r"\\dimexpr\b[\s\S]*?\\relax\b", text[pos:]
    )
    if expression:
        return pos + expression.end()
    match = re.match(space + r"=?" + space + value, text[pos:])
    if not match:
        return pos
    end = pos + match.end()
    while glue := re.match(space + r"(?:plus|minus)\b" + space + value, text[end:]):
        end += glue.end()
    return end


def collect_text_macros(text: str) -> set[str]:
    from .sources import visible_tex

    visible = visible_tex(text)
    wrappers = set()
    allowed = (
        set(
            "textbf textit textsc emph textrm textsf textnormal smallskip medskip bigskip indent noindent it bf bfseries itshape color textcolor tiny small footnotesize large Large normalsize underline mbox hl".split()
        )
        | FONT_SWITCHES
        | {
            "boldmath",
            "unboldmath",
            "ignorespaces",
            "unskip",
            "hskip",
            "vskip",
            "hspace",
            "vspace",
            "par",
        }
    )
    for m in re.finditer(
        r"\\(?:newcommand|renewcommand|providecommand)\*?\s*(?:\{\\([A-Za-z]+)\}|\\([A-Za-z]+))\s*\[1\]\s*\{",
        visible,
    ):
        a = m.end() - 1
        body = visible[a + 1 : group_end(visible, a) - 1]
        commands = {c.group()[1:] for c in COMMAND.finditer(body)}
        if "#1" in body and not any(c in body for c in "$_^") and commands <= allowed:
            wrappers.add(m.group(1) or m.group(2))
    return wrappers


def collect_math_aliases(text: str) -> dict[str, str]:
    from .sources import visible_tex

    return {
        m.group(1): re.sub(r"(\\(?:begin|end))\s+\{", r"\1{", m.group(2))
        for m in re.finditer(
            r"\\(?:newcommand|renewcommand|def)\s*\{?\\([A-Za-z]+)\}?\s*\{(\\(?:begin|end)\s*\{[^}]+\}|\\[\[\]()])\}",
            visible_tex(text),
        )
    }


def collect_literal_macros(text: str) -> dict[str, str]:
    """Recognize only zero-argument, plain-text names; never infer TeX execution."""
    from .sources import visible_tex

    literals = {}
    for match in re.finditer(
        r"\\(?:newcommand|renewcommand|providecommand|def)\*?\s*(?:\{\\([A-Za-z]+)\}|\\([A-Za-z]+))\s*\{([^{}]*)\}",
        visible_tex(text),
    ):
        value = re.sub(r"\\xspace\b", "", match.group(3)).strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .,:/()+-]*", value):
            literals[match.group(1) or match.group(2)] = value
    return literals


TITLE_COMMANDS = {"title", "subtitle", "icmltitle", "icmltitlerunning", "shorttitle"}
MACRO_DEFINITIONS = {
    "def",
    "gdef",
    "edef",
    "xdef",
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareRobustCommand",
    "newenvironment",
    "renewenvironment",
}


def _title_source_parts(text: str):
    """Locate literal declarations and explicit title arguments without expansion."""
    from .sources import visible_tex

    visible = visible_tex(text)
    aliases = collect_math_aliases(text)
    declarations, titles = [], []
    pos = 0
    while pos < len(visible):
        if visible[pos] == "$":
            delimiter = "$$" if visible.startswith("$$", pos) else "$"
            pos = math_end(visible, pos + len(delimiter), delimiter, aliases)
            continue
        match = COMMAND.match(visible, pos)
        if not match:
            pos += 1
            continue
        name, pos = match[0][1:].rstrip("*"), match.end()
        expansion = aliases.get(name, match[0])
        if expansion in (r"\(", r"\["):
            pos = math_end(visible, pos, expansion, aliases)
            continue
        if aliased_env := re.fullmatch(r"\\begin\{([^}]+)\}", expansion):
            if aliased_env[1] in OPAQUE_ENV:
                pos = math_end(visible, pos, expansion, aliases)
                continue
        if name == "begin":
            opening = skip_tex_space(visible, pos)
            end = group_end(visible, opening)
            env = visible[opening + 1 : end - 1]
            if env in OPAQUE_ENV:
                pos = opaque_environment_end(visible, end, env, aliases)
                continue
        if name in MACRO_DEFINITIONS or name == "let":
            opening = skip_tex_space(visible, pos)
            if opening < len(visible) and visible[opening] == "{":
                end = group_end(visible, opening)
                declared = COMMAND.fullmatch(visible[opening + 1 : end - 1].strip())
            else:
                declared = COMMAND.match(visible, opening)
                end = declared.end() if declared else opening
            body = skip_tex_space(visible, end)
            zero_arg = body < len(visible) and visible[body] == "{"
            if declared:
                body_end = group_end(visible, body) if zero_arg else body
                declarations.append(
                    (
                        declared[0][1:],
                        body + 1,
                        body_end - 1,
                        name in {"def", "newcommand", "renewcommand", "providecommand"}
                        and zero_arg,
                    )
                )
            pos = definition_end(visible, pos, name) if name != "let" else end
            continue
        if name in TITLE_COMMANDS:
            opening = skip_tex_space(visible, pos)
            if opening < len(visible) and visible[opening] == "[":
                opening = skip_tex_space(visible, group_end(visible, opening))
            if opening < len(visible) and visible[opening] == "{":
                pos = group_end(visible, opening)
                titles.append((name, opening + 1, pos - 1))
    return declarations, titles


def collect_title_macros(text: str) -> dict[str, str]:
    """Open only unique plain-text macros used as an entire explicit title.

    The definition is translated once so other title displays keep sharing it.
    Parameterized, nested, computed and conflicting definitions stay opaque.
    """
    from .sources import without_comments

    declarations, titles = _title_source_parts(text)
    referenced = {
        match[0][1:]
        for _, a, b in titles
        if (match := COMMAND.fullmatch(without_comments(text[a:b]).strip()))
    }
    result = {}
    for name in referenced:
        matches = [item for item in declarations if item[0] == name]
        if len(matches) != 1 or not matches[0][3]:
            continue
        _, a, b, _ = matches[0]
        value = without_comments(text[a:b]).strip()
        if re.fullmatch(
            r"[A-Za-z\u3040-\u9fff][A-Za-z0-9\u3040-\u9fff\s.,:;!?/()+–—-]*", value
        ) and (
            re.search(r"[A-Za-z]+\s+[A-Za-z]+", value)
            and re.search(r"[A-Za-z]{2,}", value)
            or re.search(r"[\u3040-\u9fff]{2,}", value)
        ):
            result[name] = text[a:b]
    return result


def extract_paper_title(
    text: str, *, title_macros: dict[str, str] | None = None
) -> str:
    """Read a display title, resolving only explicitly approved literal macros."""
    from .sources import without_comments

    macros = collect_title_macros(text) if title_macros is None else title_macros
    _, titles = _title_source_parts(text)
    for name, a, b in titles:
        if name not in {"title", "icmltitle"}:
            continue
        value = without_comments(text[a:b]).strip()
        if match := COMMAND.fullmatch(value):
            value = macros.get(match[0][1:], "")
        value = re.sub(r"\\[A-Za-z]+|[{}]", "", value.replace(r"\\", " "))
        value = re.sub(r"\s+", " ", without_comments(value)).strip()
        if value:
            return value[:200]
    return ""


def collect_numeric_registers(text: str) -> dict[str, str]:
    from .sources import visible_tex

    return {
        (match[2] or match[3]): "integer" if match[1] == "newcount" else "dimension"
        for match in re.finditer(
            r"\\(newdimen|newlength|newskip|newmuskip|newcount)\s*(?:\{\\([A-Za-z@]+)\}|\\([A-Za-z@]+))",
            visible_tex(text),
        )
    }


def collect_prose_arguments(text: str) -> dict[str, tuple[int, frozenset[int]]]:
    """Infer only unambiguously prose parameters of explicit formatting macros.

    Probe each occurrence through the existing source scanner. A parameter used
    in code, math, syntax or an unknown command remains opaque even if another
    occurrence is prose. No macro is expanded and no names imply prose roles.
    """
    from collections import Counter

    from .sources import visible_tex

    visible = visible_tex(text)
    aliases = collect_math_aliases(text)
    registers = collect_numeric_registers(text)
    constants = set(
        re.findall(
            r"\\(?:newcommand|renewcommand|providecommand|def)\s*\{?\\([A-Za-z@]+)\}?\s*\{",
            visible,
        )
    )
    known = (
        TEXT_COMMAND
        | set(TEXT_AFTER_ARGS)
        | OPAQUE_COMMAND
        | FONT_SWITCHES
        | TEXT_DECLARATIONS
        | DIMENSION_COMMANDS
        | INTEGER_COMMANDS
        | REGISTER_DECLARATIONS
        | CODE_ARGUMENT_COMMANDS
        | constants
        | set(registers)
        | {"begin", "end", "item", "fontsize", "selectfont", "boldmath", "unboldmath"}
    )
    prose_controls = (
        TEXT_COMMAND - CODE_ARGUMENT_COMMANDS
        | TEXT_DECLARATIONS
        | FONT_SWITCHES - {"tt", "ttfamily"}
        | {"item"}
    )
    parameter = re.compile(r"(?<!#)#([1-9])(?!\d)")

    def literal_label_description(body):
        # A literal identifier followed by ': #2' is a description wrapper even
        # without an item/formatting declaration. Keep the exception structural:
        # bare tuples, formulas, dimensions and further code do not qualify.
        def ungroup(value):
            value = value.strip()
            while value.startswith("{") and group_end(value, 0) == len(value):
                value = value[1:-1].strip()
            return value

        body = ungroup(body)
        command = COMMAND.match(body)
        if not command or command[0][1:] not in {"code", "texttt", "url", "path"}:
            return False
        opening = skip_tex_space(body, command.end())
        if opening >= len(body) or body[opening] != "{":
            return False
        end = group_end(body, opening)
        remainder = body[end:].strip()
        return remainder.startswith(":") and bool(
            parameter.fullmatch(ungroup(remainder[1:]))
        )

    pattern = re.compile(
        r"\\(?:newcommand|renewcommand|providecommand)\*?\s*(?:\{\\([A-Za-z@]+)\}|\\([A-Za-z@]+))\s*\[([2-9])\]\s*\{"
    )
    declarations = Counter(
        match[1] or match[2]
        for match in re.finditer(
            r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand|def|gdef|edef|xdef)\*?\s*(?:\{\\([A-Za-z@]+)\}|\\([A-Za-z@]+))",
            visible,
        )
    )
    examined = Counter()
    schemas, ambiguous = {}, set()
    cursor = 0
    while match := pattern.search(visible, cursor):
        end = group_end(visible, match.end() - 1)
        body = visible[match.end() : end - 1]
        cursor = end
        name, count = match[1] or match[2], int(match[3])
        examined[name] += 1
        if name in OPAQUE_COMMAND | TEXT_COMMAND | CODE_ARGUMENT_COMMANDS:
            # Known metadata, file/syntax and standard prose commands already
            # have an explicit contract; a template definition cannot open them.
            ambiguous.add(name)
            continue
        controls = {m[0][1:].rstrip("*") for m in COMMAND.finditer(body)}
        # Control symbols (e.g. escaped %) are literal; unknown control words
        # can consume unbraced operands, so their parameter roles are unknown.
        unknown = {
            word for word in controls - known if re.fullmatch(r"[A-Za-z@]+", word)
        }
        if unknown or not (
            controls & prose_controls or literal_label_description(body)
        ):
            ambiguous.add(name)
            continue
        probes = {
            number: "TeXGlotProseParameter" + chr(64 + number)
            for number in range(1, count + 1)
        }
        blocked = set()
        for occurrence in parameter.finditer(body):
            number = int(occurrence[1])
            if number not in probes:
                blocked.update(probes)
                continue
            before, after = body[: occurrence.start()], body[occurrence.end() :]
            preceding = re.search(r"\\([A-Za-z@]+)\s*$", before)
            if (
                re.search(r"[\w@]$", before)
                and not preceding
                or re.match(r"[\w@]", after)
            ):
                blocked.add(number)
            if preceding and preceding[1] not in FONT_SWITCHES | TEXT_DECLARATIONS | {
                "item"
            }:
                blocked.add(number)
        # Parameter tokens delimit a preceding control word in real TeX. Keep
        # that boundary when replacing #3 with an alphabetic diagnostic probe.
        probed = parameter.sub(lambda m: " " + probes.get(int(m[1]), m[0]) + " ", body)
        exposed = "\n".join(
            MARKER.sub("", item.masked)
            for item in segments(
                probed,
                math_aliases=aliases,
                numeric_registers=registers,
                prose_arguments={},
                literal_code=True,
            )
        )
        safe = frozenset(
            number
            for number, probe in probes.items()
            if number not in blocked
            and probed.count(probe)
            and exposed.count(probe) == probed.count(probe)
        )
        schema = (count, safe)
        if name in schemas and schemas[name] != schema:
            ambiguous.add(name)
        schemas[name] = schema
    return {
        name: schema
        for name, schema in schemas.items()
        if schema[1] and name not in ambiguous and examined[name] == declarations[name]
    }


def input_references(
    text: str, math_aliases: dict[str, str] | None = None
) -> list[tuple[str, bool]]:
    """Read literal input edges together with their TeX math/graphics context.

    Macro definitions and verbatim examples do not execute inputs. Dynamic
    filenames remain the compiler's responsibility; this scanner never expands
    TeX macros or guesses a file's role from its name or prose content.
    """
    from .sources import visible_tex

    visible = visible_tex(text)
    aliases = dict(math_aliases or {}) | collect_math_aliases(text)
    references = []
    pos = opaque_until = 0
    while pos < len(visible):
        start = pos
        opaque = start < opaque_until
        if visible[pos] == "$" and not opaque:
            delimiter = "$$" if visible.startswith("$$", pos) else "$"
            pos += len(delimiter)
            opaque_until = math_end(visible, pos, delimiter, aliases)
            continue
        match = COMMAND.match(visible, pos)
        if not match:
            pos += 1
            continue
        name = match[0][1:].rstrip("*")
        pos = match.end()
        if name in {
            "def",
            "gdef",
            "edef",
            "xdef",
            "newcommand",
            "renewcommand",
            "providecommand",
            "DeclareRobustCommand",
            "newenvironment",
            "renewenvironment",
        }:
            pos = definition_end(visible, pos, name)
            continue
        expansion = aliases.get(name, match[0])
        aliased_env = re.fullmatch(r"\\begin\{([^}]+)\}", expansion)
        if not opaque and (
            expansion in (r"\(", r"\[") or aliased_env and aliased_env[1] in OPAQUE_ENV
        ):
            opaque_until = math_end(visible, pos, expansion, aliases)
        if name in {"begin", "end"}:
            argument = skip_tex_space(visible, pos)
            end = group_end(visible, argument)
            if end > argument and visible[argument] == "{":
                env = visible[argument + 1 : end - 1]
                pos = end
                if name == "begin" and env in OPAQUE_ENV and not opaque:
                    opaque_until = opaque_environment_end(visible, pos, env, aliases)
            continue
        if name not in {"input", "include", "subfile"}:
            continue
        argument = skip_tex_space(visible, pos)
        if argument < len(visible) and visible[argument] == "{":
            pos = group_end(visible, argument)
            filename = visible[argument + 1 : pos - 1].strip()
        elif value := re.match(r'"[^"\n]+"|[^\s\\{}%]+', visible[argument:]):
            pos = argument + value.end()
            filename = value[0]
        else:
            continue
        filename = filename.strip('"')
        if filename and not any(c in filename for c in "\\#{}|\x00"):
            references.append((filename, opaque))
    return references


def classify_source_contexts(
    root, main: str, source_files: list[str], *, math_aliases=None
) -> tuple[set[str], set[str]]:
    """Return opaque-only and mixed-use TeX files in a compiled source graph.

    Descendants inherit an opaque parent's context. Files loaded through a
    dynamic macro (and hence lacking a literal input edge) remain ordinary
    sources unless a definite opaque invocation is observed. Mixed-use files
    must also be preserved: translating one would change its mathematical use.
    """
    from pathlib import Path

    root = Path(root).resolve()
    paths = {
        (root / name).resolve(): name
        for name in source_files
        if (root / name).resolve().is_relative_to(root)
    }
    main_path = (root / main).resolve()
    edges = {}
    for path, name in paths.items():
        references = input_references(path.read_text(encoding="utf-8"), math_aliases)
        edges[name] = []
        for filename, opaque in references:
            relative = Path(filename)
            candidates = [relative]
            if relative.suffix != ".tex":
                candidates.append(Path(filename + ".tex"))
            for base in (main_path.parent, path.parent, root):
                target = next(
                    (
                        (base / name).resolve()
                        for name in candidates
                        if (base / name).resolve() in paths
                    ),
                    None,
                )
                if target is not None:
                    edges[name].append((paths[target], opaque))
                    break
    roles = {name: set() for name in paths.values()}

    def visit(name, opaque):
        pending = [(name, opaque)]
        while pending:
            current, inherited = pending.pop()
            if current not in roles or inherited in roles[current]:
                continue
            roles[current].add(inherited)
            pending.extend(
                (child, inherited or local) for child, local in edges[current]
            )

    visit(main, False)
    for name in roles:
        if not roles[name]:
            visit(name, False)
    return (
        {name for name, contexts in roles.items() if contexts == {True}},
        {name for name, contexts in roles.items() if contexts == {False, True}},
    )


def segments(
    text: str,
    max_chars=4500,
    math_aliases: dict[str, str] | None = None,
    text_macros: set[str] | None = None,
    literal_macros: dict[str, str] | None = None,
    numeric_registers: dict[str, str] | None = None,
    prose_arguments: dict[str, tuple[int, frozenset[int]]] | None = None,
    literal_code: bool = False,
    title_macros: dict[str, str] | None = None,
) -> list[Segment]:
    result = []
    tokens: list[tuple[int, int, bool]] = []
    i = 0
    from .sources import visible_tex, without_comments
    from .text_accents import accented_word_spans

    in_body = not re.search(r"\\begin\s*\{document\}", visible_tex(text))
    prose_macros = collect_text_macros(text) | (text_macros or set())
    aliases = dict(math_aliases or {}) | collect_math_aliases(text)
    literals = dict(literal_macros or {}) | collect_literal_macros(text)
    registers = dict(numeric_registers or {}) | collect_numeric_registers(text)
    argument_roles = (
        collect_prose_arguments(text) if prose_arguments is None else prose_arguments
    )
    accented_words = {start: end for start, end, _ in accented_word_spans(text)}
    title_literals = (
        collect_title_macros(text) if title_macros is None else title_macros
    )
    title_definitions = (
        {
            a: b
            for name, a, b, plain in _title_source_parts(text)[0]
            if plain and name in title_literals and text[a:b] == title_literals[name]
        }
        if title_literals
        else {}
    )
    text_environments = TEXT_ENVIRONMENTS | set(
        re.findall(r"\\newtheorem\*?\s*\{([^}]+)\}", without_comments(text))
    )

    def flush():
        nonlocal tokens
        if not tokens:
            return
        # Keep values together with their literal unit/prefix. Their spelling and
        # association stay immutable while the unit can follow target grammar.
        merged = []
        for x, y, protect in tokens:
            if merged and protect and merged[-1][2] and merged[-1][1] == x:
                a, b, _ = merged[-1]
                left, right = text[a:b], text[x:y]
                number = QUANTITY
                if (
                    (re.fullmatch(number, left) and right == r"\%")
                    or (left == r"\#" and re.fullmatch(number, right))
                    or (left == "~" and movable_token(right))
                ):
                    merged[-1] = (a, y, True)
                    continue
            merged.append((x, y, protect))
        tokens = merged
        a, b = tokens[0][0], tokens[-1][1]
        plain = "".join(text[x:y] for x, y, protected in tokens if not protected)
        if re.search(r"[A-Za-z]{2,}|[\u3040-\u9fff]{2,}", plain):
            protected, parts = [], []
            for x, y, protect in tokens:
                if protect:
                    parts.append(f"⟪P{len(protected):04d}⟫")
                    protected.append(text[x:y])
                else:
                    parts.append(text[x:y])
            result.append(
                Segment(
                    a,
                    b,
                    text[a:b],
                    "".join(parts),
                    protected,
                    role="title"
                    if re.match(r"\s*\\(?:title|icmltitle)\b", text[a:b])
                    else "paragraph",
                    literal_macros=literals,
                )
            )
        tokens = []

    def put(a, b, protect=False):
        if b > a:
            if protect:
                tokens.append((a, b, True))
            else:
                cursor = a
                names = [
                    match
                    for match in NAMED_IDENTIFIER.finditer(text[a:b])
                    if named_identifier(match[0])
                ]
                numbers = [
                    match
                    for match in re.finditer(r"(?<![A-Za-z0-9])" + QUANTITY, text[a:b])
                    if not any(
                        name.start() <= match.start() < name.end() for name in names
                    )
                ]
                for literal in sorted(names + numbers, key=lambda match: match.start()):
                    x, y = a + literal.start(), a + literal.end()
                    if cursor < x:
                        tokens.append((cursor, x, False))
                    tokens.append((x, y, True))
                    cursor = y
                if cursor < b:
                    tokens.append((cursor, b, False))

    while i < len(text):
        start = i
        if in_body and i in accented_words:
            i = accented_words[i]
            put(start, i, True)
            continue
        c = text[i]
        if c == "%":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end + 1
            if in_body:
                put(start, i, True)
                if empty_lines := re.match(r"(?:[ \t\r]*\n)+", text[i:]):
                    flush()
                    i += empty_lines.end()
            continue
        if c == "\\":
            m = COMMAND.match(text, i)
            if not m:
                i += 1
                continue
            name = m.group()[1:].rstrip("*")
            i = m.end()
            if name in MACRO_DEFINITIONS:
                end = definition_end(text, i, name)
                for a, b in title_definitions.items():
                    if i <= a < b < end:
                        flush()
                        for sub in segments(text[a:b], max_chars, title_macros={}):
                            sub.start += a
                            sub.end += a
                            sub.role = "title"
                            result.append(sub)
                        break
                else:
                    if in_body:
                        put(start, end, True)
                i = end
                continue
            if in_body and name in aliases:
                environment = re.fullmatch(r"\\(begin|end)\{([^}]+)\}", aliases[name])
                if environment and environment[2] not in OPAQUE_ENV:
                    # Theorem/proof/list aliases are structural, not mathematics.
                    flush()
                    continue
            if (
                in_body
                and name in aliases
                and (
                    aliases[name].startswith(r"\begin{")
                    or aliases[name] in (r"\[", r"\(")
                )
            ):
                i = math_end(text, i, aliases[name], aliases)
                if in_body:
                    put(start, i, True)
                continue
            if name in ("(", "["):
                i = math_end(text, i, m[0], aliases)
                if in_body:
                    put(start, i, True)
                continue
            if name in ("begin", "end"):
                p = skip_tex_space(text, i)
                e = group_end(text, p)
                env = text[p + 1 : e - 1]
                i = e
                if env == "document":
                    flush()
                    in_body = name == "begin"
                    continue
                if name == "begin" and env in {"abstract", "abstract*"} and not in_body:
                    # Scientific Reports stores its abstract before document;
                    # the environment is still prose, not preamble machinery.
                    closing = re.search(
                        r"\\end\s*\{" + re.escape(env) + r"\}",
                        visible_tex(text[i:]),
                    )
                    if closing:
                        for sub in segments(
                            text[i : i + closing.start()],
                            max_chars,
                            math_aliases=aliases,
                            text_macros=prose_macros,
                            literal_macros=literals,
                            numeric_registers=registers,
                            prose_arguments=argument_roles,
                            literal_code=literal_code,
                        ):
                            sub.start += i
                            sub.end += i
                            result.append(sub)
                        i += closing.end()
                    continue
                if name == "begin" and env in OPAQUE_ENV:
                    i = opaque_environment_end(text, i, env, aliases)
                    if in_body:
                        put(start, i, True)
                    continue
                if in_body:
                    flush()
                    if name == "begin":
                        i = args_end(
                            text,
                            i,
                            required=0
                            if env in text_environments
                            else ENVIRONMENT_ARGS.get(env),
                        )
                    # begin/end and environment parameters remain outside segments.
                continue
            if not in_body:
                if name in (
                    "title",
                    "subtitle",
                    "abstract",
                    "keywords",
                    "author",
                    "icmltitle",
                    "icmltitlerunning",
                    "icmlkeywords",
                    "IEEEtitleabstractindextext",
                ):
                    p = skip_tex_space(text, i)
                    if p < len(text) and text[p] == "[":
                        p = skip_tex_space(text, group_end(text, p))
                    e = group_end(text, p)
                    if e > p and text[p] == "{":
                        ranges = [(p + 1, e - 1)]
                        if name == "author":
                            ranges = []
                            for thanks in re.finditer(
                                r"\\thanks\s*\{", text[p + 1 : e - 1]
                            ):
                                opening = p + 1 + thanks.end() - 1
                                ranges.append(
                                    (opening + 1, group_end(text, opening) - 1)
                                )
                        for a, b in ranges:
                            for sub in segments(
                                text[a:b],
                                max_chars,
                                math_aliases=aliases,
                                text_macros=prose_macros,
                                literal_macros=literals,
                                numeric_registers=registers,
                                prose_arguments=argument_roles,
                                literal_code=literal_code,
                            ):
                                sub.start += a
                                sub.end += a
                                if name in (
                                    "title",
                                    "subtitle",
                                    "icmltitle",
                                    "icmltitlerunning",
                                ):
                                    sub.role = (
                                        "subtitle" if name == "subtitle" else "title"
                                    )
                                result.append(sub)
                    i = e
                else:
                    i = args_end(text, i)
                continue
            if name in STRUCTURAL:
                flush()
            if name in ("verb", "lstinline"):
                i = inline_literal_end(text, i, name)
                put(start, i, True)
            elif name == "cmidrule":
                i = cmidrule_end(text, i)
                put(start, i, True)
            elif name == "texttt" or literal_code and name in CODE_ARGUMENT_COMMANDS:
                i = args_end(text, i, required=1)
                put(start, i, True)
            elif name in argument_roles:
                count, prose_positions = argument_roles[name]
                cursor, arguments = i, []
                for _ in range(count):
                    opening = skip_tex_space(text, cursor)
                    if opening >= len(text) or text[opening] != "{":
                        break
                    cursor = group_end(text, opening)
                    arguments.append((opening + 1, cursor - 1))
                if len(arguments) != count:
                    i = args_end(text, i)
                    put(start, i, True)
                else:
                    flush()
                    for position, (a, b) in enumerate(arguments, 1):
                        if position not in prose_positions:
                            continue
                        for sub in segments(
                            text[a:b],
                            max_chars,
                            math_aliases=aliases,
                            literal_macros=literals,
                            numeric_registers=registers,
                            prose_arguments=argument_roles,
                            literal_code=True,
                        ):
                            sub.start += a
                            sub.end += a
                            result.append(sub)
                    i = cursor
            elif name in REGISTER_DECLARATIONS:
                p = skip_tex_space(text, i)
                if p < len(text) and text[p] == "{":
                    i = group_end(text, p)
                elif declared := COMMAND.match(text, p):
                    i = declared.end()
                put(start, i, True)
            elif name in {"setlength", "addtolength"}:
                p = skip_tex_space(text, i)
                if p < len(text) and text[p] == "{":
                    i = group_end(text, p)
                elif register := COMMAND.match(text, p):
                    i = register.end()
                p = skip_tex_space(text, i)
                if p < len(text) and text[p] == "{":
                    i = group_end(text, p)
                else:
                    i = dimension_end(text, i)
                put(start, i, True)
            elif (
                name in TEXT_COMMAND
                or name in TEXT_AFTER_ARGS
                or name in prose_macros
                or name == "hyperref"
            ):
                # Optional numeric/layout arguments and language names are syntax.
                skip = TEXT_AFTER_ARGS.get(name, 0)
                p = i
                while p < len(text):
                    q = skip_tex_space(text, p)
                    if q < len(text) and text[q] == "[" and name not in STRUCTURAL:
                        p = group_end(text, q)
                    elif skip and q < len(text) and text[q] == "{":
                        p = group_end(text, q)
                        skip -= 1
                    else:
                        if q < len(text) and text[q] == "{":
                            p = q
                        break
                i = p
                put(start, i, True)
                # Plain text and groups will be scanned in place.
            elif name in TEXT_ACCENTS:
                # A TeX accent consumes one token, even without braces (K\"oppen).
                p = i
                while p < len(text) and text[p].isspace():
                    p += 1
                i = (
                    group_end(text, p)
                    if p < len(text) and text[p] == "{"
                    else min(p + 1, len(text))
                )
                put(start, i, True)
            elif name == "twocolumn":
                flush()
                # ICML places its title and author block inside \twocolumn[...].
                # Scan that block normally, preserving the surrounding brackets.
                put(start, i, True)
            elif name in DIMENSION_COMMANDS or registers.get(name) == "dimension":
                i = dimension_end(text, i)
                put(start, i, True)
            elif name in INTEGER_COMMANDS or registers.get(name) == "integer":
                i = integer_end(text, i)
                put(start, i, True)
            elif name == "input":
                p = skip_tex_space(text, i)
                if p < len(text) and text[p] == "{":
                    i = group_end(text, p)
                elif filename := re.match(r'"[^"\n]+"|[^\s\\{}%]+', text[p:]):
                    i = p + filename.end()
                put(start, i, True)
            elif name in FONT_SWITCHES or name in TEXT_DECLARATIONS:
                # Declarations do not consume the following group as an opaque
                # argument: \small{caption text} still contains prose.
                put(start, i, True)
            elif name in NULLARY_COMMANDS:
                put(start, i, True)
            elif name == "item":
                flush()
                i = args_end(text, i, required=0)
                put(start, i, True)
            else:
                i = args_end(text, i, required=OPAQUE_ARGUMENTS.get(name))
                put(start, i, True)
            continue
        if not in_body:
            i += 1
            continue
        if c == "$":
            delim = "$$" if text.startswith("$$", i) else "$"
            i = math_end(text, i + len(delim), delim, aliases)
            put(start, i, True)
        elif c in "{}[]&#_^~":
            i += 1
            put(start, i, True)
        elif break_match := paragraph_break(text, i):
            flush()
            i += break_match.end()
        else:
            i += 1
            while (
                i < len(text)
                and i not in accented_words
                and text[i] not in "\\%${}[]&#_^~"
                and not paragraph_break(text, i)
            ):
                if (
                    i - start >= max_chars
                    and text[i - 1] in ".!?"
                    and text[i].isspace()
                ):
                    break
                i += 1
            put(start, i)
            if tokens and i - tokens[0][0] >= max_chars:
                flush()
    flush()
    return result


def apply_translations(
    text: str, items: list[Segment], translated: dict[str, str]
) -> str:
    for item in reversed(items):
        if item.key in translated:
            text = text[: item.start] + translated[item.key] + text[item.end :]
    return text
