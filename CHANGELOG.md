# Changelog

## 1.2.0 — 2026-09-25

- Handle pdfTeX-only PDF date and file-ID settings consistently in source templates and diagnosed packages under XeTeX, preserving paper content, literal examples and malformed-source diagnostics. / 在 XeTeX 下统一处理模板及已定位宏包中的 pdfTeX 专用日期与文件标识设置，保留正文、代码示例及异常源码的报错边界。
- Refuse task submission to older cores without library reuse instead of silently falling back to the legacy create endpoint and retranslating an existing paper. / 连接不支持文献库复用的旧核心时明确提示更新，不再静默回退到旧的新建接口而重复翻译。
- Resolve arXiv versions from the selected PDF's first-page stamp, attachment metadata and saved file bindings, so ordinary Zotero records do not need a manually entered `vN`. When a local PDF cannot be verified, offer the official version with its paired original while preserving existing files and annotations. / 自动从 PDF 首页、附件信息和已保存的文件对应关系识别 arXiv 版本，无需手填 vN；本地版本无法确认时，提供使用官方版本及配套原文的继续选项，并保留已有文件与批注。
- Keep deterministic target-font probes separate from model-translation validation, preventing mixed word/number compounds from blocking translation before model requests. / 将确定性的目标字体预检与模型译文校验分开，修复字母、数字组合在调用模型前触发错误还原检查的问题。
- Reuse matching translations and active jobs from the local TeXGlot library before creating a Zotero translation, validate saved PDFs, recover missing Zotero files, and offer an explicit retranslation command that keeps existing results. / Zotero 翻译前先复用 TeXGlot 文献库中的同版本、同语言译文或正在执行的任务，检查 PDF 有效性并恢复丢失的 Zotero 译文文件；新增保留旧译文的重新翻译入口。
- Add a compact TeXGlot status-icon column beside Title, with language/version tooltips, native show/hide controls, and automatic updates from translation tasks and child PDF attachments. / 在标题旁新增紧凑的 TeXGlot 状态图标列，悬停显示语言与版本，支持原生列显示开关，并随翻译任务及译文附件变化自动刷新。
- Use the desktop TG logo for the add-on, status-column header and TeXGlot context-menu commands. / 插件图标、状态列表头及 TeXGlot 右键菜单选项统一使用桌面版 TG 标识。
- Repair Zotero PDF double-clicks blocked by readers left behind after closing split tabs or windows, and prevent delayed split restoration from reviving an unloaded add-on. / 清理分屏标签或窗口关闭后残留的 Zotero 阅读器，修复被失效标签拦截的 PDF 双击；插件卸载时取消尚未执行的分屏恢复。
- Open uniquely matched TeXGlot translations in split view by default when double-clicking a paper, with a saved context-menu toggle to restore single-PDF opening; PDF child attachments keep their single-document behavior. / 双击具有唯一对应译文的文献时默认进入左右对照；右键菜单可关闭并保存此行为，PDF 子附件仍分别打开单篇。

[Release notes](docs/releases/v1.2.0.md) · [中文版本说明](docs/releases/v1.2.0_CN.md)

## 1.1.3 — 2026-09-16

- Resolve compiler diagnostics that omit an included file's `.tex` suffix, allowing package-option conflicts in split preambles to recover while retaining the requested options. / 修复编译日志省略被引用文件 `.tex` 后缀时的路径识别，使分文件导言区的宏包选项冲突能够自动恢复，并保留原有选项。
- Prefer cached official arXiv titles, repair existing placeholder titles in the background, and fall back to local source metadata when offline. / 优先使用并缓存 arXiv 官方标题，后台修复已有占位标题，离线时回退到源码标题。
- Preserve full original titles and unsupported LaTeX expressions, render supported mathematical symbols and wordmarks, and show complete titles on hover without truncating stored metadata. / 保留完整原始标题及无法转换的 LaTeX 写法，改善数学符号和文字标志的显示；悬浮可查看完整标题，存储时不再截断。

[Release notes](docs/releases/v1.1.3.md) · [中文版本说明](docs/releases/v1.1.3_CN.md)

## 1.1.2 — 2026-09-15

- Allow up to 12 concurrent paragraph translations in model settings, shared by the GUI and CLI. / 模型设置中的段落翻译并发上限扩展至 12，网页与 CLI 共用该设置。
- Fix missing paper titles when templates redefine font and layout declarations; refresh existing task titles without retranslating or changing reading data. / 修复模板重定义字号、字体等排版声明导致的标题缺失；自动刷新已有任务标题，无需重新翻译，也不改变阅读数据。

[Release notes](docs/releases/v1.1.2.md) · [中文版本说明](docs/releases/v1.1.2_CN.md)

## 1.1.1 — 2026-09-14

- Add full-document PDF search with Cmd/Ctrl+F, highlighted matches and previous/next navigation; dismiss selection tools on lost selection or outside interaction, with restrained transitions. / 新增 Cmd/Ctrl+F 全文 PDF 搜索、高亮与匹配跳转；选区取消或点击别处后自动收起批注工具框，并加入克制的过渡动画。
- Prevent translated paragraphs from overlapping when figures or tables move to another page: neutralize literal negative spacing outside movable floats while retaining their internal layout and the original PDF. / 修复图表换页后译文段落重叠：消除可移动浮动图表外侧的固定负间距，保留图表内部布局与原文 PDF。

[Release notes](docs/releases/v1.1.1.md) · [中文版本说明](docs/releases/v1.1.1_CN.md)

## 1.1.0 — 2026-09-13

- Add restrained selection, switch, dialog and content transitions while preserving the existing visual style, reading anchors and reduced-motion preferences. / 保留现有外观，为选项、开关、弹窗和内容切换增加克制的过渡动画，保留阅读定位并适配减少动态效果偏好。
- Refresh model presets to Qwen 3.8 Flash (`qwen3.8-flash`) and DeepSeek V4.1 Flash (`deepseek-flash`) across the interface and CLI; keep saved model selections and connections. / 界面与 CLI 预设更新为 Qwen 3.8 Flash 和 DeepSeek V4.1 Flash，保留已保存的模型选择与连接。

[Release notes](docs/releases/v1.1.0.md) · [中文版本说明](docs/releases/v1.1.0_CN.md)

## 1.0.5 — 2026-09-12

- Fit complete table measurement containers at runtime, including containers inserted by journal classes; preserve captions and notes without nesting incompatible fitting boxes. / 在实际排版时缩放完整的表格测量容器，覆盖期刊模板内部插入的包装，保留标题与注释，避免不兼容的嵌套缩放导致编译失败。

[Release notes](docs/releases/v1.0.5.md) · [中文版本说明](docs/releases/v1.0.5_CN.md)

## 1.0.4 — 2026-09-11

- Keep successful automatic figure/table fitting in processing logs, including existing tasks, while retaining warnings for unresolved layout problems. / 自动完成的图表缩放只记录到处理日志，兼容已有任务；未解决的排版问题仍会提示。
- Add side-by-side pane swapping with saved order, independent document positions and unchanged annotation ownership. / 对照阅读新增左右互换，保存显示顺序，保留两侧阅读位置及批注所属文档。
- Add desktop update reminders, architecture-matched installer downloads, integrity verification, cancellation and verified download reuse; require explicit installation and preserve pending reader writes. / 桌面版新增更新提醒、按系统架构选择安装包、完整性校验、取消下载和已验证下载复用；确认后打开安装器，并先保存阅读器中的待写入内容。
- Recover diagnosed pdfTeX-only output settings in external Tectonic packages using task-local copies from the same bundle; retain the original package, license and accessibility code. / 根据编译诊断，使用同一 Tectonic 宏包库中的任务内副本适配 pdfTeX 专用输出设置，保留原始宏包、许可及无障碍代码。
- Carry original-compilation repairs into target-language preflight, translation, source exports and cached retries. / 将原文编译阶段的修复完整带入目标语言预检、翻译、源码导出和缓存重试。

[Release notes](docs/releases/v1.0.4.md) · [中文版本说明](docs/releases/v1.0.4_CN.md)

## 1.0.3 — 2026-09-11

- Fix reader loading for large raster images while preserving section and figure alignment. / 修复大位图导致的阅读器加载失败，保留章节与插图同步。
- Add Ctrl + mouse wheel PDF zoom, retaining the reading position and visible page until the sharper frame is ready. / 新增 Ctrl＋滚轮 PDF 缩放，保持阅读位置和已显示画面，避免缩放时闪出排版提示。
- Resolve bounded text macros in display titles and refresh existing task metadata without retranslation. / 有界解析标题文本宏，自动修正已有任务标题，无需重新翻译。
- Use white native desktop icon backgrounds on macOS and Windows. / macOS 与 Windows 桌面图标改为白底。

[Release notes](docs/releases/v1.0.3.md) · [中文版本说明](docs/releases/v1.0.3_CN.md)

## 1.0.2 — 2026-09-11

- Validate source reconstruction and target-language layout before model requests. / 在模型请求前验证源码还原及目标语言排版。
- Repair diagnosed template, package, bibliography and font incompatibilities; retain prepared sources across retries. / 修复诊断明确的模板、宏包、参考文献及字体兼容问题，重试时复用预处理源码。
- Convert compiler-selected EPS assets without confusing scoped paths or duplicate filenames; preserve complete table wrappers. / 按编译器实际选择转换 EPS，避免局部路径和同名文件混淆，保留完整表格边界。
- Protect source identifiers, drawing regions and custom delimited math; render generated Unicode math with standard TeX encodings. / 保护源码标识符、绘图区域与自定义分隔符公式，以标准 TeX 编码显示生成的 Unicode 数学符号。
- Preserve macOS compiler isolation for data directories outside the home directory. / 自定义数据目录位于用户主目录之外时，仍保持 macOS 编译器的数据隔离。
- Discard stale TeX auxiliary files before a new compilation. / 新一轮编译前清理旧 TeX 辅助文件。
- Export final repaired sources, report only final-pass reference warnings, and detect unsupported PSTricks drawing operations. / 导出最终修复源码，仅报告最后一遍引用警告，识别不支持的 PSTricks 绘图操作。

[Release notes](docs/releases/v1.0.2.md) · [中文版本说明](docs/releases/v1.0.2_CN.md)

## 1.0.1 — 2026-09-10

- Validate generated LaTeX and formatting before accepting repair slots; retry only invalid slots once, preserving accepted text and existing caches. / 在接收修复片段前校验新增 LaTeX 与格式，只重试不合规片段一次，保留已通过文字及已有缓存。
- Bound the local frontend build during source installation to 10 minutes and stop its process tree on timeout or cancellation; leave dependency downloads unrestricted by this build timeout. / 源码安装的本地前端构建最多等待 10 分钟，超时或取消时清理相关子进程；依赖下载不受该构建超时限制。
- Preserve Windows console progress and errors during source installation, including batch entry points. / 源码安装在 Windows 上保留控制台进度与错误输出，覆盖批处理入口。

[Release notes](docs/releases/v1.0.1.md) · [中文版本说明](docs/releases/v1.0.1_CN.md)

## 1.0.0

First public release. / 首个公开版本。

- Translate arXiv links and local LaTeX projects into PDF and editable source, with source preflight, formula/reference protection, validation and resumable caches. / 将 arXiv 链接和本地 LaTeX 工程翻译为 PDF 与可编辑源码，提供编译预检、公式与引用保护、结果校验和可恢复缓存。
- Configure Qwen, DeepSeek or a compatible model endpoint; optionally use abstract context for each task. / 自行配置 Qwen、DeepSeek 或兼容服务，为每项任务选择是否启用摘要引导。
- Read original and translated PDFs continuously or side by side, synchronize reading positions, and keep highlights, underlines and notes locally. / 连续阅读或对照原译 PDF，同步阅读位置，本地保存高亮、下划线和便签。
- Use the CLI for single papers, batches, task resumption and JSON exports. / 通过 CLI 翻译单篇或批量论文，恢复任务并导出 JSON 结果。
- Support Chinese and English interfaces, with Simplified Chinese, Traditional Chinese and English translation targets. / 提供中英文界面，翻译目标支持简体中文、繁体中文和英文。
- Provide macOS Apple Silicon / Intel DMGs, a Windows x64 installer, and source/Python distributions. / 提供 Apple Silicon 与 Intel Mac DMG、Windows x64 安装器，以及源码和 Python 分发包。
- Include bilingual setup and contribution guides, an Attention Is All You Need walkthrough, automated regression tests and retained third-party licenses. / 提供双语安装与贡献指南、Attention Is All You Need 案例、自动回归测试和完整第三方许可。

[Release notes](docs/releases/v1.0.0.md) · [中文版本说明](docs/releases/v1.0.0_CN.md)
