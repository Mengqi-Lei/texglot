"""Localize service messages on output; source content and persisted jobs are untouched."""

import re

MESSAGES = {
    "命名标识符与相邻文字错误拼接": "A named identifier was incorrectly joined to adjacent text",
    "部分图表超出页高，已整体缩放以保留全部内容、标签和图表说明": "Some figures or tables exceeded the page height and were scaled together to preserve all content, labels, and captions.",
    "存在超出页高的浮动体，内容可能被裁切；请检查图表及编译日志": "Some floats still exceed the page height and may be clipped. Check the figures, tables, and compilation log.",
    "检查 EPS 插图的实际源码依赖": "Checking actual source dependencies for EPS figures",
    "编译依赖探测未生成有效记录，请检查源码工程": "Compiler dependency discovery produced no valid record. Check the source project.",
    "表格结构、空单元格或空格式组中不能插入正文": "Text cannot be inserted into table structure, empty cells, or empty formatting groups",
    "论文含 EPS 插图，需要安装 Ghostscript 后继续；macOS 可运行 brew install ghostscript，Windows 请安装 Ghostscript 64 位版": "This paper contains EPS figures. Install Ghostscript and resume; use brew install ghostscript on macOS or the 64-bit Ghostscript installer on Windows.",
    "EPS 插图路径包含重定义或作用域不明确的宏，无法安全确定图片；请改为明确的工程内相对路径": "An EPS figure path uses a reassigned or locally scoped macro. Specify an explicit relative path within the project so the correct figure can be selected safely.",
    "EPS 插图在不同 graphicspath 下指向不同文件，无法安全转换；请为图片指定明确的工程内相对路径": "An EPS figure resolves to different files under different graphicspath settings. Specify an explicit relative path within the project to convert the correct figure safely.",
    "EPS 转换文件名与源码文件冲突，请检查重复的插图文件": "The EPS conversion filename conflicts with a source file. Check duplicate figure files.",
    "排版命令与文字参数之间不能插入正文": "Text cannot be inserted between a formatting command and its argument",
    "未安装 LaTeX 编译器。请运行项目安装脚本，或安装 Tectonic / TeX Live 后重试": "No LaTeX compiler found. Run the project setup script or install Tectonic / TeX Live, then retry.",
    "源码包包含 Windows 不支持的文件名，请修改文件名及对应引用": "The source contains filenames unsupported by Windows. Rename them and update the corresponding references.",
    "源码包有重复或仅大小写不同的文件名，Windows 无法区分": "The source contains duplicate or case-only filenames that Windows cannot distinguish.",
    "不支持的模型服务商": "Unsupported model provider",
    "请填写百炼控制台提供的 OpenAI 兼容地址": "Enter the OpenAI-compatible URL from the Bailian console",
    "批注位置超出页面": "Annotation is outside the page",
    "批注数据已达容量上限": "Annotation storage limit reached",
    "批注数量已达上限": "Annotation count limit reached",
    "批注页码无效": "Invalid annotation page",
    "批注已存在，请刷新后重试": "Annotation already exists. Refresh and retry",
    "PDF 已更新，请重新打开阅读器": "This PDF has changed. Reopen the reader",
    "批注已在其他窗口修改，请重新加载后再保存": "This annotation changed in another window. Reload it before saving",
    "批注不存在": "Annotation not found",
    "只接受本地页面发起的请求": "Only same-origin local requests are accepted",
    "禁止跨站请求": "Cross-site requests are not allowed",
    "任务不存在": "Task not found",
    "支持 .tex、.zip、.tar、.tar.gz 和 .tgz 源码文件": "Choose a .tex, .zip, .tar, .tar.gz, .tgz, or .gz source file",
    "文件为空或超过 80 MB": "File is empty or exceeds 80 MB",
    "任务正在处理": "Task is already running",
    "主文件无效": "Invalid main file",
    "文件尚未生成": "Artifact is not available yet",
    "请输入有效的 API Base URL，不要包含密钥或查询参数": "Enter a valid API base URL without credentials or query parameters",
    "远程 API 请使用 HTTPS；本地模型可使用 HTTP": "Use HTTPS for remote APIs; HTTP is allowed for local models",
    "请输入模型名称": "Enter a valid model name",
    "暂不支持该目标语言": "Unsupported target language",
    "无效编译器": "Invalid compiler",
    "模型未将正文翻译为目标中文，请翻译完整正文而不是复制英文": "The model did not translate the body into the requested Chinese language",
    "译文仍保留了大部分英文正文，请完整翻译": "Most of the body remains in English; a complete translation is required",
    "[密钥已隐藏]": "[key redacted]",
    "API 认证失败，请在模型设置中检查 key 和模型权限": "API authentication failed. Check the key and model permissions in settings",
    "模型账户余额不足，请充值或切换 API": "Insufficient provider balance. Top up or switch your API provider",
    "API 地址或模型不存在，请检查 Base URL 和模型名称": "API endpoint or model not found. Check the base URL and model name",
    "模型输出被截断": "Model output was truncated",
    "模型没有返回有效文本": "The model returned no valid text",
    "API 连接超时或网络不可达，请检查网络和 Base URL": "API timed out or is unreachable. Check your network and base URL",
    "API 返回格式不兼容，需要 Chat Completions 接口": "Incompatible API response. A Chat Completions endpoint is required",
    "模型请求失败": "Model request failed",
    "上次服务停止，译文已保存，点击继续即可恢复": "Service stopped previously. Translations are saved; resume to continue",
    "等待开始": "Waiting to start",
    "任务已在运行": "Task is already running",
    "等待处理": "Queued for processing",
    "任务已停止，已完成段落会在继续时复用": "Task stopped. Completed paragraphs will be reused when resumed",
    "任务已暂停，已完成段落已保存": "Task paused. Completed paragraphs are saved",
    "正在从 arXiv 获取 LaTeX 源码": "Fetching LaTeX source from arXiv",
    "解压源码并识别主文件": "Extracting source and detecting the main file",
    "这篇论文的 arXiv 源码只是 PDF 包装文件，没有可翻译的 LaTeX 正文。请上传作者提供的真实 LaTeX 工程": "The arXiv source only wraps a PDF and has no translatable LaTeX body. Upload the author's actual LaTeX project",
    "检查目标语言字体与论文模板的兼容性": "Checking target-language fonts against the paper template",
    "没有找到可翻译的正文，请检查主文件或自定义宏": "No translatable body found. Check the main file or custom macros",
    "未识别到论文摘要，本次不附加论文背景": "No abstract detected; proceeding without paper context",
    "上下文引导已关闭，仅翻译当前段落": "Context guidance is off; translating each paragraph without abstract context",
    "任务正在处理，无法切换上下文引导；请停止后重试": "Cannot change context guidance while a task is running. Stop it before retrying",
    "任务正在处理，无法切换主文件或上下文引导；请停止后重试": "Cannot change the main file or context guidance while a task is running. Stop it before retrying",
    "翻译缓存无法读取，已保留副本；本次重新翻译相关段落": "The translation cache could not be read. A copy was preserved; affected paragraphs will be translated again",
    "模型服务要求较长的重试等待，可稍后继续任务": "The model service requested a long retry delay. Resume the task later",
    "编译依赖记录不可用，已按静态引用识别正文；请检查是否存在遗漏": "Compiler dependency records are unavailable. Source files were identified from static includes; check for omitted content",
    "arXiv 暂时繁忙，已保留任务；请稍后重试": "arXiv is temporarily busy. Your task was preserved; retry later",
    "译文已保存，正在编译 PDF 并解析交叉引用": "Translation saved. Building PDF and resolving cross-references",
    "输出 PDF 没有页面": "Output PDF has no pages",
    "翻译完成": "Translation complete",
    "已完成，部分段落保留原文": "Completed with some paragraphs left in the original language",
    "未安装 LaTeX 编译器。macOS 可执行 brew install tectonic，然后重试": "No LaTeX compiler installed. On macOS, run brew install tectonic, then retry",
    "源码包含外部命令输入，当前本地编译不支持": "Source includes external command input, which local compilation does not support",
    "编译超时，任务和译文已保存；可重试以复用已下载的宏包": "Build timed out. Progress is saved; retry to reuse downloaded packages",
    "参考文献编译超时": "Bibliography build timed out",
    "参考文献编译失败，请检查 .bib 和 .bst 文件": "Bibliography build failed. Check the .bib and .bst files",
    "编译器未生成有效 PDF": "The compiler did not produce a valid PDF",
    "编译日志报告缺失字形，请检查 PDF 中的特殊字符": "The build reports missing glyphs. Check special characters in the PDF",
    "存在未解析的引用，请检查参考文献文件": "Unresolved citations remain. Check your bibliography files",
    "请输入 arxiv.org 论文链接或 arXiv ID": "Enter an arxiv.org paper link or an arXiv ID",
    "arXiv 地址格式不正确，例如 https://arxiv.org/abs/1706.03762": "Invalid arXiv address. Example: https://arxiv.org/abs/1706.03762",
    "压缩包包含不安全的文件路径": "Archive contains an unsafe file path",
    "文件路径超出工程目录": "File path is outside the project directory",
    "源码包过大（最多 4000 个文件，解压后 300 MB）": "Source archive is too large (up to 4,000 files and 300 MB extracted)",
    "压缩包内容长度异常": "Invalid archive content length",
    "源码包最多包含 4000 个文件或目录": "Source archive may contain at most 4,000 files or directories",
    "源码包不能包含符号链接": "Source archive cannot contain symbolic links",
    "源码包只能包含普通文件": "Source archive may contain regular files only",
    "源码文件过大": "Source file is too large",
    "该论文未提供可用 LaTeX 源码；请上传作者提供的源码包": "No usable LaTeX source is available. Upload the author's source archive",
    "文件不是有效的 LaTeX 源码": "File is not valid LaTeX source",
    "压缩包中没有 .tex 文件": "Archive contains no .tex files",
    "无法识别源码编码": "Could not identify the source encoding",
    "未找到包含 documentclass 和 begin{document} 的主文件": "No main file with documentclass and begin{document} found",
    "指定的主文件不存在或不是完整文档": "The selected main file is missing or is not a complete document",
    "arXiv 暂时繁忙，稍后自动重试": "arXiv is busy. Retrying shortly",
    "arXiv 未找到这篇论文或其源码，请检查 ID": "Paper or source not found on arXiv. Check the ID",
    "arXiv 源码超过 80 MB，请手动精简后上传": "arXiv source exceeds 80 MB. Reduce the archive and upload it manually",
    "arXiv 下载超时；已保留任务，可重试或上传源码包": "arXiv download timed out. Task is saved; retry or upload the source archive",
    "下载连接中断，正在重试": "Download interrupted. Retrying",
    "公式或格式标记被修改、遗漏或重复": "Math or formatting markers were changed, omitted, or repeated",
    "排版结构标记被重排": "Layout structure markers were reordered",
    "数字、公式或引用跨越了原来的格式边界或表格单元格": "A number, equation, or citation crossed a formatting boundary or table cell",
    "模型生成了额外的 LaTeX 指令": "The model generated extra LaTeX commands",
    "模型返回了无效格式": "The model returned an invalid format",
    "译文异常短，可能遗漏正文": "Translation is unusually short and may omit content",
}
RULES = [
    (r"正在转换 EPS 插图 · (\d+) / (\d+)", r"Converting EPS figures · \1 / \2"),
    (r"EPS 插图转换超时：(.+)", r"EPS conversion timed out: \1"),
    (r"EPS 插图转换失败：([\s\S]+)", r"EPS conversion failed: \1"),
    (
        r"EPS 插图转换页数异常：(.+)",
        r"EPS conversion produced an unexpected page count: \1",
    ),
    (
        r"使用论文摘要作为翻译背景（(\d+) 字符）",
        r"Using the paper abstract as translation context (\1 characters)",
    ),
    (
        r"模型服务暂时不可用（HTTP (\d+)），可稍后继续任务",
        r"Model service unavailable (HTTP \1). Resume later",
    ),
    (
        r"模型拒绝请求（HTTP (\d+)），请检查模型设置",
        r"Model rejected the request (HTTP \1). Check model settings",
    ),
    (
        r"检测到 (\d+) 个主文件，使用 (.+)；可在任务中切换后重新编译",
        r"Found \1 main files. Using \2; select another in task details to rebuild",
    ),
    (
        r"主文件 (.+) · 使用 (.+) 检查原文编译",
        r"Main file \1 · Checking original with \2",
    ),
    (
        r"已提取 (\d+) 个段落，公式、引用和排版指令已保护",
        r"Extracted \1 paragraphs; equations, citations, and layout commands are protected",
    ),
    (
        r"已保留 (\d+) 个图形或公式源码文件的原始内容",
        r"Preserved the original content of \1 figure or equation source files",
    ),
    (
        r"以下源码同时用于正文和图形或公式，已保留原样：(.+)",
        r"These source files are used as both prose and figure or equation code and were preserved unchanged: \1",
    ),
    (
        r"有一段译文未通过结构检查，保留原文：(.+)",
        r"A paragraph failed structural validation; keeping the original: \1",
    ),
    (
        r"结构修复片段 (\d+) 返回了非字符串",
        r"Structure repair slot \1 returned a non-string value",
    ),
    (
        r"结构修复片段 (\d+) 返回了空白正文",
        r"Structure repair slot \1 returned empty text",
    ),
    (
        r"结构修复片段 (\d+) 包含保护标记",
        r"Structure repair slot \1 included a protected token",
    ),
    (
        r"结构修复片段 (\d+) 包含无效的 LaTeX 或格式",
        r"Structure repair slot \1 included invalid LaTeX or formatting",
    ),
    (
        r"结构修复片段 (\d+) 未返回",
        r"Structure repair slot \1 was missing",
    ),
    (r"正在翻译 · (\d+) / (\d+) 段落", r"Translating · \1 / \2 paragraphs"),
    (
        r"为 (\d+) 个表格设置页宽上限，避免译文溢出页边距",
        r"Constrained \1 tables to page width to prevent overflow",
    ),
    (
        r"(\d+) / (\d+) 段落未通过翻译检查，PDF 对应位置保留了原文，可点击继续重试",
        r"\1 / \2 paragraphs failed validation and remain in the original language. Resume to retry",
    ),
    (r"PDF 已生成 · (\d+) 页 · ([\d,]+) tokens", r"PDF ready · \1 pages · \2 tokens"),
    (
        r"未安装 (.+)，请安装后重试或切换编译器",
        r"\1 is not installed. Install it or choose another compiler",
    ),
    (
        r"(.+) 引用了工程目录外的路径，请将依赖文件放入源码包并使用相对路径",
        r"\1 references a path outside the project. Include the dependency and use a relative path",
    ),
    (
        r"首次使用的宏包正在缓存到本机 · 已下载 (\d+) 项",
        r"Caching new TeX packages locally · \1 downloaded",
    ),
    (r"LaTeX 编译未通过：([\s\S]+)", r"LaTeX build failed: \1"),
]


def english(message: str) -> str:
    if message in MESSAGES:
        return MESSAGES[message]
    # Replace complete dynamic messages first, then any nested validation reason.
    for pattern, replacement in RULES:
        message = re.sub(pattern, replacement, message)
    for source, target in MESSAGES.items():
        message = message.replace(source, target)
    return re.sub(
        r"(?<!\d)1 (pages|tables|paragraphs|main files)\b",
        lambda match: match.group(0)[:-1],
        message,
    )


def localize_payload(value, field=""):
    if isinstance(value, dict):
        return {key: localize_payload(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [localize_payload(item, field) for item in value]
    if isinstance(value, str) and field in {
        "message",
        "error",
        "detail",
        "msg",
        "warnings",
    }:
        return english(value)
    return value
