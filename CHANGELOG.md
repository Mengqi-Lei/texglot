# Changelog

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
