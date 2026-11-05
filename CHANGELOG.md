# Changelog

## Unreleased

- Strip explicit leading reasoning/answer envelopes from LLM responses while preserving authored tags, JSON string contents and slot-boundary whitespace. Retry incomplete answers and persist validated cleanup of older LLM caches. / 清理 LLM 响应中明确的前置推理及答案封装，保留原文标签、JSON 字符串内容与分段边界空格；不完整回答进入有限重试，旧 LLM 缓存清理并校验后写回。
- Resolve the known Libertinus math font filename mismatch in acmart templates, preserving project fonts, explicit lookup rules and code examples. Refresh older prepared sources on retry while retaining valid translations. / 修复 acmart 模板中已知的 Libertinus 数学字体文件名不匹配，保护工程自带字体、自定义查找规则和代码示例；重试时更新旧预处理源码并复用有效译文。
- Recover confirmed amssymb / unicode-math conflicts using compiler load records and a conditional package load. Preserve cross-file code examples, package order/options and the author's non-Unicode-math branch. / 根据实际编译加载记录确认 amssymb 与 unicode-math 的冲突，以条件加载恢复编译，保留跨文件代码示例、宏包顺序与选项及作者的传统数学分支。

## 1.2.4 — 2026-11-04

- Recover compiler failures caused by unused minted package loads without enabling shell escape; retain used/frozen minted sources and provide actionable diagnostics. / 无需开放 shell escape 即可恢复未使用 minted 宏包造成的编译失败；保留实际使用或冻结缓存的源码，并提供明确的处理提示。
- Repair compiler-diagnosed PDF figure cross-reference corruption with original-file backups and page-content checks; distinguish missing, unreadable and unrecoverable figures instead of hiding or replacing them. / 对编译器确认的 PDF 插图索引损坏进行修复，保留原文件并核对页面内容；区分缺失、无法读取及不可修复的图片，不隐藏或替换插图。

[Release notes](docs/releases/v1.2.4.md) · [中文版本说明](docs/releases/v1.2.4_CN.md)

## 1.2.3 — 2026-10-28

- Translate prose inside explicitly defined robust formatting commands and their aliases, nested callouts, and custom icon-label descriptions; preserve code, math and ambiguous redefinitions. Protect TeX spacing units adjacent to title text. / 修复稳健格式命令及其别名、嵌套提示框和图标说明中的正文漏译，继续保护代码、公式及存在歧义的重定义，并保护紧贴标题文字的 TeX 间距单位。

[Release notes](docs/releases/v1.2.3.md) · [中文版本说明](docs/releases/v1.2.3_CN.md)

## 1.2.2 — 2026-10-23

- Recognize explicitly declared verbatim/listing environments across source files, preserving code and prompt examples through segmentation, compiler preparation and layout adjustments. Keep printed commands out of dependency and abstract extraction, and refresh prepared sources when retrying older tasks. / 跨文件识别显式声明的原样代码环境，在分段、编译预处理及排版调整中完整保留代码与提示词示例，避免示例命令干扰依赖和摘要提取；重试旧任务时更新预处理源码。

[Release notes](docs/releases/v1.2.2.md) · [中文版本说明](docs/releases/v1.2.2_CN.md)

## 1.2.1 — 2026-10-08

- Use locally bundled Qwen, DeepSeek and DeepL brand icons in translation settings. / 翻译设置改用随应用打包的 Qwen、DeepSeek 和 DeepL 品牌图标。
- Add DeepL as an independent translation engine with validated XML protection, bounded retries, native glossary support, character usage and engine-specific caches; shared by App, CLI and Zotero. / 新增独立 DeepL 翻译引擎，支持 XML 结构保护、有限重试、原生术语表、字符用量和独立缓存，App、CLI 与 Zotero 共用。

[Release notes](docs/releases/v1.2.1.md) · [中文版本说明](docs/releases/v1.2.1_CN.md)

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
- Discard stale TeX auxiliary files before a new compilation. / 新一轮编译前清理旧 TeX 辅助文件。
- Preserve macOS compiler isolation for data directories outside the home directory. / 自定义数据目录位于用户主目录之外时，仍保持 macOS 编译器的数据隔离。
- Export final repaired sources, report only final-pass reference warnings, and detect unsupported PSTricks drawing operations. / 导出最终修复源码，仅报告最后一遍引用警告，识别不支持的 PSTricks 绘图操作。

[Release notes](docs/releases/v1.0.2.md) · [中文版本说明](docs/releases/v1.0.2_CN.md)

## 1.0.1 — 2026-09-10

- Validate generated LaTeX and formatting before accepting repair slots; retry only invalid slots once, preserving accepted text and existing caches. / 在接收修复片段前校验新增 LaTeX 与格式，只重试不合规片段一次，保留已通过文字及已有缓存。
- Bound the local frontend build during source installation to 10 minutes and stop its process tree on timeout or cancellation; leave dependency downloads unrestricted by this build timeout. / 源码安装的本地前端构建最多等待 10 分钟，超时或取消时清理相关子进程；依赖下载不受该构建超时限制。
- Preserve Windows console progress and errors during source installation, including batch entry points. / 源码安装在 Windows 上保留控制台进度与错误输出，覆盖批处理入口。

[Release notes](docs/releases/v1.0.1.md) · [中文版本说明](docs/releases/v1.0.1_CN.md)

## 1.0.0

- Hardened the translation pipeline with compiler-recorded source dependencies, context-aware protection for math/graphics fragments, and recoverable job/API/cache failures. / 深度加固核心翻译流程，按编译器实际依赖确定正文范围，保护继承公式或绘图上下文的子文件，并完善任务、API 与缓存异常恢复。
- Expanded compatibility for author-supplied styles, legacy minted caches, pixel dimensions and float/comment syntax; ambiguous EPS paths are rejected before they can silently select the wrong image. / 改善作者自带模板、旧 minted 缓存、像素单位、浮动位置及注释环境兼容；不确定的 EPS 路径提前明确报错，防止静默替错图。
- Strengthened lossless LaTeX boundaries across comments, nested mathematics, table rules, numeric registers and pre-document abstracts; preserve complete accented words and code identifiers. / 加强跨注释、嵌套数学、表格规则、数值寄存器及导言区摘要的无损保护与提取，完整保留重音单词和代码标识符。
- Improved bounded translation repair with exact text-span context, isolated retries for invalid entries, and a structured fallback for failed lines. / 翻译修复使用明确的原文片段位置，只重试无效条目，并为失败的行补充有界结构化恢复。
- Repair now preserves complete sentences and permits validated value reordering within formatting scopes; supported title macros also populate paper titles. / 修复优先保留完整句子，允许数值在原有格式作用域内按语义调整顺序，并支持明确标题宏的翻译与文献命名。
- Fit oversized figures and tables using their actual complete boxes, retaining every panel, caption and label; preserve normal-size floats and report any remaining overflow. / 按实际完整图表尺寸处理超高内容，保留子图、说明与标签；正常图表保持原样，未消除的溢出明确提示。
- Preserve complete alphanumeric model identifiers and provide the unmasked source paragraph for factual context. Allow up to one minute for an owned CLI service to become ready, while rejecting conflicting services immediately. / 完整保护含数字的模型标识符，并提供同段未遮盖原文核对事实关系；CLI 自行启动服务时最多等待一分钟就绪，冲突服务仍立即拒绝。

- Expanded real-paper compatibility: legacy CJK/encoding packages, pdfTeX metadata and math-font setup; EPS figures can be converted with an optional external Ghostscript installation. / 改善旧式中文宏包、编码、pdfTeX 元信息和数学字体兼容性，支持使用外部 Ghostscript 转换 EPS 插图。
- Fixed missed ICML titles and theorem aliases, protected unbraced TeX dimensions and accented letters, and tightened formatting-argument validation. Dense proof repairs retain complete clauses and exact source math. / 修复 ICML 标题与定理宏漏译，保护无括号排版尺寸和重音字符，加强格式参数检查，长证明按完整语句修复并保持公式绑定。

- Retained upstream Electron/Chromium notices in desktop bundles and corrected Windows test fixtures for native ACLs, line endings and environment limits. / 桌面包保留 Electron／Chromium 原始许可，修正 Windows 权限、换行与环境变量限制相关测试。

- Added native desktop packaging: macOS DMG and Windows per-user EXE installer, with an isolated Electron window, bundled Python engine, Tectonic and retained third-party licenses. / 新增 macOS DMG 与 Windows 当前用户安装器，内置独立桌面窗口、Python 引擎、Tectonic 和第三方许可。
- Desktop startup handles existing services and port conflicts; quitting cleans up translation workers and preserves saved tasks. Added native frozen-engine and installer verification. / 桌面启动处理已有服务与端口冲突，退出时清理进程并保留任务，增加冻结引擎及安装包验证。

- Standardized launchers as `start-texglot.command`, `start-texglot.cmd` and `install-texglot.cmd`; the default example now translates Attention Is All You Need with the selected language and guidance. / 安装启动入口统一英文名，默认示例改为按所选语言与引导模式翻译 Attention Is All You Need。

- Unified all four documentation screenshots at 2560 × 1800 with Chrome-native Retina PNG captures and aligned Attention prose, translation and experimental results; updated bilingual acknowledgements. / 四张文档截图统一为 Chrome 原生 2560 × 1800 Retina PNG，首页收窄，对照截图展示位置接近的 Attention 正文、译文与实验结果，同步更新双语致谢。

- First public release materials: English and Chinese README, contributor guides, CLI and platform documentation. / 首个公开版本材料，提供中英文 README、贡献指南、CLI 与平台说明。
- Reproducible Attention Is All You Need walkthrough with a pinned arXiv version and verified Qwen run. / 固定版本 Attention 案例及 Qwen 实测结果。
- Clean release export with source ZIP, wheel, sdist, checksums, retained licenses and bilingual release notes. / 干净源码导出、安装包、校验和、完整第三方许可及双语发布说明。
- Existing translation and reading features retained; no task-data migration. Native Windows installer and frozen-engine checks now pass; interactive Windows client verification remains pending. / 翻译与阅读能力保持，无数据迁移；Windows 原生安装与冻结引擎验证通过，客户端交互验收仍待补充。

## 0.5.0 — 2026-09-09

- 新增 Windows 原生安装与启动入口，macOS/Linux 与 Windows 共用 Python 安装流程；自动准备 Python 3.13 和校验过的 Tectonic 0.17.0 便携编译器。
- 服务锁分别使用 Windows 字节锁与 POSIX 文件锁；适配后台进程、端口独占及编译进程树的取消与超时处理。
- 配置、缓存、源码、日志和 CLI 输出统一 UTF-8；修复 macOS 沙箱对中文目录的转义，并补充 Windows 文件名限制提示。
- 补充独立原生平台自测脚本与三平台 CI 模板。macOS 实机完整验证通过；Windows 原生运行尚待实机验收。

## 0.4.0 — 2026-09-09

- 新增阿里云百炼 Qwen 服务预设，默认模型为 `qwen3.7-plus`，支持业务空间专属地址及现有 DashScope 地址。翻译默认关闭深度思考，复杂片段修复支持 JSON 输出。
- 模型设置整合 Qwen、DeepSeek 和自定义服务；分别记忆连接信息与密钥，切换时按完整地址恢复，避免将密钥传给其他服务。
- 更新中英文设置界面、移动端按钮和表单布局，加入键盘焦点循环；文献列表显示每篇实际使用的模型。
- CLI 新增 `--configure --provider qwen|deepseek|custom`，支持 `DASHSCOPE_API_KEY`，保留原有单篇和批量翻译流程。
- 补充百炼新格式密钥脱敏，并将新增的连接存储文件纳入编译器隔离。
- Qwen 真实翻译 YOLOv10 全部 112 个片段，生成 20 页中文 PDF；本地 LaTeX 示例和结构化修复验证通过。

## 0.3.6 — 2026-09-09

- 实测 YOLOv10、ResNet、ViT、LoRA、DDPM 的 arXiv 源码翻译；修复后 5 篇均完整生成中文 PDF，650 个片段通过检查。
- 修复 LaTeX 命令与中英文译文粘连引起的编译失败，改进数字、百分号、引用及格式作用域检查。
- 数字与数量级单位共同保护，避免 billion 等单位翻译导致数值含义改变；复杂片段增加按文字片段重组结构的修复方式。
- 补译字号命令和自定义标题宏中的文字；识别纯文本名称宏，防止为保持宏顺序而交换模型和数据集的语义。
- 缺少 .bib 时使用源码随附的 .bbl，并读取最终 TeX 日志检查引用问题。
- 清理文献标题中的源码换行标记，新增只读翻译审计脚本和五篇论文验证记录。

## 0.3.5 — 2026-09-09

- 新建翻译中的上下文引导改为语言选择右侧的紧凑开关，移除独立说明区。
- 名称后新增问号浮层，支持悬停、点按、键盘聚焦、Esc 关闭及点按外部关闭；浮层保持在窗口范围内。
- 窄窗口按可用宽度自动换行，翻译按钮独占一行；检查中文与英文布局。

## 0.3.4 — 2026-09-09

- 新增默认开启的「上下文引导」开关。新建翻译可单次切换，模型设置可保存默认值，任务详情可选择下次重新处理的模式；中英文界面同步支持。
- CLI 支持 `--context-guidance` / `--no-context-guidance`，适用于单篇、批量与恢复任务；搭配 `--configure` 保存默认值。
- 关闭时跳过摘要提取，模型请求不发送 `paper_context` 或摘要引导指令。任务保留自己的模式，开关状态参与缓存区分，修改全局默认值不会改变已有任务。

## 0.3.3 — 2026-09-09

- `paper_context` 改为源码摘要，按主文件引用顺序识别，支持常见摘要环境、命令与多文件摘要；不再取路径排序后的前四个片段。
- 摘要背景最多 6000 字符，保留数字、公式及原文措辞；超长时优先在句末截断，无可读摘要时留空，结构校验重试仍保留摘要。
- 提示词明确摘要只用于理解背景，模型仅翻译指定段落；摘要内容纳入缓存标识，旧策略与不同摘要的缓存隔离，旧缓存文件保留。

## 0.3.2 — 2026-09-09

- 最近翻译和文献库的详情改为在对应条目下方就地展开；展开状态通过箭头和无障碍属性明确呈现。
- 切换展开条目时保持所点击文献的位置；收起详情后将键盘焦点返回对应条目。
- 筛选后不再显示已被过滤文献的详情，不同任务的主文件选择和日志展开状态也不再串用。

## 0.3.1 — 2026-09-08

- 仓库重命名为 `texglot-dev`，作为内部早期开发与调试仓库；正式开源版本另行整理。
- 修复对照阅读按整篇滚动比例同步造成的累计错位，改用章节、图表等内容定位点。
- 识别原译文中内容相同的插图，补充浮动图跨章节重排时的区域对应；页码跳转以实际可见内容同步。
- 重新开启同步时，以译文当前位置重新对齐原文。
- 修复单侧与对照视图往返切换、缩放、批注侧栏和窗口尺寸变化时的定位；保留当前内容与视口位置。
- 修复页码输入框未编辑时失焦仍跳到页首的问题，补充切换规则、页面几何和版本匹配回归测试。

## 0.3.0 — 2026-09-08

- 阅读器改为连续纵向阅读，按需渲染相邻页面，并记录上次阅读位置、缩放及对照设置。
- 原文与译文支持可切换的同步滚动，按文档进度跟随，也可分别滚动或按页码跳转。
- 新增五色高亮、下划线、页面便签、文字批注、搜索、跳转、改色、删除和撤销。
- 批注自动保存至本地，与具体 PDF 版本绑定；未发出的文字草稿可在刷新后恢复，并防止多个窗口静默覆盖同一批注。
- 所有批注独立于 PDF 和源码导出，中英文界面同步支持新功能。
- 将现有 TeXGlot 项目接入 GitHub，保留 Apache 2.0 许可证，提供自动构建和测试模板；当前授权缺少 `workflow` 权限，暂未启用。

## 0.2.0 — 2026-09-08

- 新增中英文界面切换、TG 折页 Logo、CLI 与批量处理，支持从终端恢复任务和导出结果。

## 0.1.0 — 2026-09-08

- 本地 arXiv / LaTeX 源码翻译、可配置模型 API、结构保护、缓存恢复、原文与译文 PDF 导出。
