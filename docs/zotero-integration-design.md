# TeXGlot Zotero 集成设计说明

状态：Zotero 9 实验性集成。当前已实现 arXiv/LaTeX 来源识别、本地任务提交、译文附件导入和基础双栏阅读；本文件其余条目是分阶段设计目标，不能视作已经交付的功能。实机验证目前仅覆盖 macOS 上的 Zotero 9。

本文定义 TeXGlot 与 Zotero 桌面客户端的集成边界、仓库结构、运行协议、数据保存规则、测试要求和分阶段实施计划。目标是让用户可以在 Zotero 文献库中发起 TeXGlot 翻译，同时继续使用 TeXGlot 现有的模型配置、缓存、编译恢复、源码导出和对照阅读能力。

## 1. 结论与设计原则

TeXGlot Zotero 插件与 TeXGlot 共享同一个 Git 仓库，但插件是独立的构建产物。插件不内嵌 Python、模型、Tectonic、PDF 解析器或完整翻译流程，而是通过本机回环服务调用 TeXGlot 的任务系统。

最终关系如下：

```text
Zotero 插件（XPI）
    │  本地集成 API
    ▼
TeXGlot 本地服务（JobManager）
    ├── TeXGlot 网页 / 桌面 GUI
    ├── TeXGlot CLI
    ├── 模型服务与 API key 配置
    ├── 段落缓存、任务恢复和编译恢复
    └── PDF、LaTeX 源码和阅读器数据
```

必须遵守以下原则：

1. **同仓库，分包构建。** Zotero 插件代码位于本仓库，但不混入 Python wheel、桌面引擎或公开源码包的运行时依赖。
2. **共享服务，不直接调用 CLI。** Zotero 插件使用稳定的本地 HTTP 协议；不通过 shell 拼接命令调用 `texglot`，避免跨平台路径、转义、权限和进程回收问题。
3. **模型配置只归 TeXGlot。** 插件不保存或读取 Qwen、DeepSeek 等 API key，只请求 TeXGlot 服务执行任务。
4. **原始附件永不覆盖。** 翻译 PDF 和翻译源码作为当前 Zotero 条目的新子附件保存，原文保持不变。
5. **版本严格对应。** 论文来源必须使用可确认的完整 arXiv 版本，例如 `2401.12345v2`。无法确认版本时停止并提示用户，不静默切换到最新版。
6. **阅读器职责分离。** Zotero 负责文献库和附件管理；插件使用 Zotero 原生阅读器承载基础原文/译文分屏和同步定位，TeXGlot 阅读器继续负责完整的搜索、缩放、批注和位置保存能力。
7. **失败可恢复。** 任务提交、轮询、下载、导入和打开阅读器都必须有明确状态、可重试路径和可诊断错误，不把网络超时误报为翻译完成。

## 2. 为什么采用同仓库但独立插件包

Zotero 插件和 TeXGlot 核心的发布节奏、运行环境和兼容约束不同。将它们放在同一仓库可以共享接口合同、测试夹具、文档和版本发布流程；将插件作为独立包则可以避免以下问题：

- Zotero 的 JavaScript/ESM 兼容代码进入 Python 服务或桌面引擎；
- `node_modules`、XPI 构建产物或 Zotero 测试环境进入 Python wheel 和源码分发包；
- Zotero 版本变化迫使整个 TeXGlot 核心同步升级；
- 插件故障影响 CLI 或普通网页使用；
- 用户为了使用 CLI 而被迫安装 Zotero，或为了使用 Zotero 而下载模型和编译器。

仓库内建议使用如下目录：

```text
integrations/
└── zotero/
    ├── README.md
    ├── package.json
    ├── package-lock.json
    ├── tsconfig.json
    ├── zotero-plugin.config.ts
    ├── addon/
    │   ├── manifest.json
    │   ├── bootstrap.js
    │   ├── chrome/
    │   └── locale/
    ├── src/
    │   ├── addon.ts
    │   ├── bridge.ts
    │   ├── item-source.ts
    │   ├── attachment-import.ts
    │   ├── menus.ts
    │   ├── preferences.ts
    │   ├── reader-launch.ts
    │   └── errors.ts
    ├── tests/
    │   ├── item-source.test.ts
    │   ├── bridge-contract.test.ts
    │   ├── attachment-import.test.ts
    │   └── fixtures/
    └── docs/
        └── development.md
```

根目录的前端、后端和桌面测试继续按现有流程运行。插件使用自己的 `package.json` 和锁文件，构建输出只写入 `integrations/zotero/.scaffold/build/` 或临时目录。

插件的构建目录不能加入 Python 的 `sdist`、wheel 或桌面引擎；如果 Release 提供 XPI，Release 脚本单独复制经过检查的 `.xpi` 文件。

## 3. 功能范围

当前插件只有一个文献右键入口，默认译为简体中文。提交与完成会显示短通知，持续进度只记录在 Zotero 调试日志中；Zotero 内的任务面板、取消/重试按钮和翻译选项面板尚未实现。PDF-only 论文目前不能作为翻译输入。下列第一阶段条目描述目标范围，未勾选的能力不应在对外说明中宣称已支持。

### 3.1 第一阶段目标

第一版以 arXiv 和真实 LaTeX 项目为主：

- Zotero 条目右键菜单发起翻译；
- 选中多个条目后批量提交；
- 从父条目、PDF 附件和元数据中识别 arXiv ID；
- 识别并锁定完整版本号；
- 调用本地 TeXGlot 服务创建任务；
- 显示任务状态、段落进度和错误摘要；
- 支持取消、继续和重试；
- 将译文 PDF 自动导入为子附件；
- 可选导入翻译后的 LaTeX 源码包；
- 在同一个 Zotero 标签页中打开原文/译文原生分屏，原文在左、译文在右并作为主窗格；原有 deep link 只作为原生阅读器不可用时的回退；
- 检测同一版本、同一目标语言和同一产物是否已经存在，避免重复导入。

### 3.2 后续支持

以下功能依赖 TeXGlot 对应核心能力成熟后再加入插件：

- Zotero PDF 附件 → TeXGlot PDF 内容解析 → 重排 LaTeX → 翻译；
- 无 arXiv ID 的普通 PDF；
- 扫描件 OCR；
- 从 Zotero 选中文字直接请求段落翻译；
- 将 TeXGlot 批注候选导入 Zotero 笔记；
- 将 TeXGlot 的全部批注、搜索和重排阅读能力完整嵌入 Zotero；基础分屏已经支持，完整能力仍由 TeXGlot 阅读器提供。

### 3.3 明确不做的事情

- 不修改原始 PDF、原始 LaTeX 或父条目标题；
- 不直接写 Zotero SQLite 数据库；
- 不在插件中保存模型 API key；
- 不把 TeXGlot 的 Python 环境、模型或编译器打进 XPI；
- 不通过猜测基础 arXiv ID 自动选择不同版本；
- 不把 TeXGlot 批注嵌入导出的 PDF；
- 不因为 Zotero 插件存在而改变现有 GUI、CLI 的任务语义。

## 4. 用户体验设计

### 4.1 入口

在以下对象的右键菜单中提供入口：

- 普通文献条目；
- 文献条目下的 PDF 附件；
- 可识别为 LaTeX 工程的源码压缩包。

推荐菜单文案：

```text
使用 TeXGlot 翻译并对照阅读
使用 TeXGlot 翻译（仅生成附件）
TeXGlot 设置
```

对多个条目选择时，第一项变为批量任务。没有可识别输入时，菜单项显示但不可用，并在状态提示中说明需要 arXiv ID、LaTeX 源码或支持的 PDF 输入。

### 4.2 提交前确认

单篇任务默认不弹出复杂配置窗口，只在以下情况显示轻量确认面板：

- 发现多个候选 PDF 或多个 arXiv 版本；
- 目标语言与默认值不同；
- 用户启用了“每次提交前确认”；
- 发现已有相同产物；
- 任务需要未来的 PDF 解析管线。

面板包含：

- 原文标题和 arXiv 完整版本；
- 输入来源和选中的附件；
- 目标语言；
- 上下文引导开关；
- 是否导入 translated-source.zip；
- 完成后打开方式：对照阅读、译文 PDF、仅保存在 Zotero；
- 处理已有译文：复用、生成新版本或取消。

### 4.3 任务状态

插件显示状态，但不复制 TeXGlot 的全部任务详情。建议显示：

```text
准备源码
检查排版
段落翻译 42 / 119
生成 PDF
已完成 / 需检查 / 失败 / 已取消
```

对于部分段落未通过校验的任务，插件必须显示“需检查”，不能只显示“已完成”。用户可点击“在 TeXGlot 中继续 / 重试”进入完整任务详情。

### 4.4 完成后的附件

默认导入：

```text
[TeXGlot] 简体中文 · arXiv 2401.12345v2.pdf
```

可选导入：

```text
[TeXGlot] translated-source · arXiv 2401.12345v2.zip
```

附件的 `url` 或 `note` 中可以保存可诊断的本地任务标识，但不能保存 API key、完整本地路径或模型请求正文。建议在附件 note 中记录有限的结构化信息：

```json
{
  "provider": "texglot",
  "arxiv_id": "2401.12345v2",
  "language": "简体中文",
  "task_id": "...",
  "core_version": "1.2.0"
}
```

如果用户选择“译文作为 Zotero 默认 PDF”，插件可以在明确确认后执行；默认不改变 Zotero 的最佳附件选择，避免影响用户已有阅读流程。

## 5. 输入识别与版本锁定

### 5.1 父条目到附件的解析顺序

插件按以下顺序收集候选信息：

1. 用户当前选中的 PDF 附件；
2. 其父条目的 `extra`、`url`、`DOI`、`archiveID` 和自定义 arXiv 字段；
3. 父条目下所有 PDF 附件的文件名和内置元数据；
4. PDF 首页可提取的 arXiv 标识；
5. 通过 arXiv API 对候选 ID 做存在性校验。

优先使用用户直接选中的附件。用户选中父条目且存在多个论文 PDF 时，只能自动选择版本明确且与父条目一致的主论文 PDF；补充材料、幻灯片和附录不参与主论文选择。

### 5.2 完整版本要求

以下值可以作为完整版本：

```text
2401.12345v2
arXiv:2401.12345v2
https://arxiv.org/abs/2401.12345v2
10.48550/arXiv.2401.12345v2
```

只包含 `2401.12345` 时，插件优先读取实际 PDF 首页及附件信息，自动补齐版本。仍无法核实时，核心查询官方完整版本；已有未知版本 PDF 的用户确认后导入该任务的配套原文，已有文件和批注保留。没有本地原文时直接使用配套原文。用户无需手填版本号，任务创建及复用仍要求完整 `vN`。

旧式分类编号和换行版本戳受支持；PDF 的版本优先于滞后的条目版本。不同论文编号冲突时停止，多个无法区分的附件使用原生文件选择框。首页读取失败可使用附件信息；不能把父条目的版本当成未知 PDF 的身份证明。版本选择与操作见[插件指南](../integrations/zotero/README_CN.md#版本与译文复用)。

### 5.3 重复检测

重复检测至少同时比较：

- 完整 arXiv ID；
- 目标语言；
- TeXGlot 核心版本和翻译管线版本；
- 上下文引导状态；
- 翻译 PDF 的 SHA-256（任务完成后）；
- 附件 note 中的任务元数据。

不能只靠附件标题中的“中文翻译”判断重复，因为标题可能被用户手动修改。

## 6. 运行架构

### 6.1 TeXGlot GUI、CLI 和插件的关系

GUI、CLI 和插件都使用 `app/server.py` 提供的本地服务和 `JobManager`。GUI 与 CLI 已经共享设置、任务、缓存和数据目录；插件只新增一个客户端，不新增一套翻译实现。

```text
桌面 GUI ─┐
网页 GUI ─┼─> 127.0.0.1:port ─> FastAPI / JobManager ─> Provider / Compiler
CLI     ─┤
Zotero  ─┘
```

CLI 可以自动启动服务，也可以由用户先执行 `texglot --serve`。Zotero 插件不依赖 CLI 命令是否在 PATH 中，只检查服务健康状态。桌面应用负责在应用启动时拥有服务；插件需要启动桌面应用时，后续可通过 `texglot://` 协议唤起，而不是自行猜测应用安装路径。

### 6.2 服务所有权

插件调用服务前必须检查：

- `name == "TeXGlot"`；
- `ok == true`；
- 数据目录是用户预期的 TeXGlot 数据目录；
- API 协议版本满足插件要求；
- 没有另一份服务正在以不同数据目录占用端口。

现有服务的单所有者锁、端口检查和本地数据目录保护继续有效。插件不能因为端口不可用而自动连接任意其他 HTTP 服务。

## 7. Zotero 集成 API

现有 `/api/jobs/*` 接口可以用于第一版原型。正式插件不应长期依赖面向网页和 CLI 的内部字段，因此增加一个带版本的适配层：

```text
GET  /api/integrations/zotero/health
GET  /api/integrations/zotero/capabilities
POST /api/integrations/zotero/sources/resolve
POST /api/integrations/zotero/jobs
GET  /api/integrations/zotero/jobs/{id}
POST /api/integrations/zotero/jobs/{id}/cancel
POST /api/integrations/zotero/jobs/{id}/retry
GET  /api/integrations/zotero/jobs/{id}/artifacts/{kind}
```

### 7.1 健康和能力

```json
{
  "ok": true,
  "name": "TeXGlot",
  "core_version": "1.1.3",
  "integration_api": "zotero.v1",
  "data_dir": "...",
  "capabilities": {
    "arxiv_latex": true,
    "latex_upload": true,
    "pdf_reflow": false,
    "translated_source": true,
    "reader_deep_link": true,
    "library_reuse": true,
    "arxiv_resolution": true,
    "original_pdf": true
  }
}
```

LaTeX 输入使用 `source.type = "latex"`、`source.filename`、`source.main` 和 base64 编码的 `source.content_base64`。当前请求体最大对应 80 MB 源码；PDF 输入虽然保留在 schema 中，但 capability 为 `false`，服务会返回 `SOURCE_NOT_SUPPORTED`，不会把 PDF 错误地送入 LaTeX 管线。

幂等键可以放在请求体的 `idempotency_key`，也可以放在 HTTP `Idempotency-Key` 请求头；两者同时存在且不一致时请求被拒绝。显式幂等键绑定来源版本、目标语言、上下文引导、配置指纹和复用策略，服务重启后仍返回原任务；修改请求后复用同一键会报冲突。普通菜单操作不需要显式键，而是按下述文献库复用规则查找当前可用的结果。

能力字段必须反映真实可用功能，不能仅根据版本号推断。插件根据能力隐藏或禁用不支持的入口。

提交任务必须确认 `library_reuse` 能力；旧服务缺少该能力，或集成任务接口返回 404/405 时，插件提示更新运行中的 App，不回退到 `/api/jobs/arxiv`。该旧接口会直接新建任务，不能替代带复用语义的提交。健康检查、已有任务查询和产物下载保留只读兼容路径；Zotero 已保存的配对不依赖服务升级即可离线打开。

`POST sources/resolve` 接受 `{"id":"1706.03762"}`，返回完整 `id`、`title`、`evidence`，不创建任务或调用模型。优先查询官方 Atom API，失败后核对官方摘要页的论文身份和版本历史；网络超时、无有效版本或论文不符时返回可重试错误。已完整的版本直接保留，不查询最新版。插件能力检测使旧核心在需要新能力时显示更新提示。

### 7.2 创建任务

arXiv 请求示例：

```json
{
  "source": {
    "type": "arxiv",
    "id": "2401.12345v2"
  },
  "target_language": "简体中文",
  "context_guidance": true,
  "import": {
    "translated_pdf": true,
    "translated_source": true,
    "open": "comparison"
  },
  "client": {
    "name": "zotero",
    "version": "0.1.0",
    "item_key": "ABCD1234",
    "library_id": 1
  },
  "idempotency_key": "sha256:..."
}
```

服务返回：

```json
{
  "id": "task-id",
  "status": "queued",
  "source": {
    "type": "arxiv",
    "id": "2401.12345v2"
  },
  "target_language": "简体中文",
  "context_guidance": true,
  "protocol": "zotero.v1"
}
```

`reuse_existing` 默认为 `true`。服务在同一次请求内查找或新建任务，查找与创建之间不让出事件循环，避免并发请求同时新建。查找范围是当前服务数据目录中的所有任务，包括 App、网页、CLI 创建的任务。

- arXiv 必须完整版本和目标语言一致，不以标题或无版本 ID 猜测匹配。
- 源码上传按原始文件 SHA-256、输入形式（单文件或压缩包）及主文件选择匹配。新任务保存原始主文件选择；旧任务只在可确认时复用。
- 优先无警告的完成结果，其次需检查的有效结果，再次正在执行的任务；同级选较新任务。复用前检查 PDF 存在、可解析、有页面、未加密且位于本任务目录内。失败、取消、重启中断的任务不用于普通复用。
- 普通复用不要求模型或上下文设置相同。主动选择“使用 TeXGlot 重新翻译（保留已有译文）”发送 `reuse_existing: false`，保留旧任务和附件，按当前设置新建任务。
- 新建返回 HTTP 202、`reuse: null`；复用返回 HTTP 200、`reuse: "library"` 或 `"active"`；显式幂等键重放返回 `"replay"`。插件对已完成结果直接导入，对活动任务轮询，并保留质量标记。显式重放可能返回失败或中断状态，不会偷偷新建任务。
- 为从普通任务复用得到的显式幂等请求保存轻量绑定，不改写原任务的来源、模型配置、阅读数据或文献库排序。无显式键的复用是只读操作。

旧核心不声明 `library_reuse` 时维持原提交接口；插件不向旧核心发送新增字段，主动重新翻译会提示更新核心。

### 7.3 状态和产物

插件只依赖稳定字段：

```json
{
  "id": "task-id",
  "status": "translating",
  "progress": {
    "done": 42,
    "total": 119,
    "percent": 35
  },
  "message": "段落翻译",
  "quality": "completed_with_warnings",
  "artifacts": {
    "translated_pdf": true,
    "translated_source": true,
    "original_pdf": true
  },
  "error": null
}
```

状态至少包括：

```text
queued
downloading
preparing
checking_layout
translating
compiling
completed
completed_with_warnings
needs_retry
needs_selection
cancelled
failed
```

插件不能把 `completed_with_warnings` 显示为无条件成功。用户应能看到“需检查”和进入 TeXGlot 任务详情的入口。

### 7.4 错误分类

集成 API 应返回机器可判断的 `code` 和面向用户的 `message`：

```text
SERVICE_UNAVAILABLE
PROTOCOL_UNSUPPORTED
ARXIV_VERSION_REQUIRED
ARXIV_NOT_FOUND
SOURCE_NOT_SUPPORTED
TASK_ALREADY_EXISTS
TASK_RUNNING
MODEL_ERROR
COMPILATION_ERROR
ARTIFACT_NOT_READY
ATTACHMENT_IMPORT_FAILED
```

错误信息不得包含 API key、完整模型请求、用户目录中的隐私路径或论文正文。完整编译日志继续由 TeXGlot 本地任务保存，用户点击后在 TeXGlot 中查看。

## 8. 本地服务安全

服务继续只绑定 `127.0.0.1`，不开放局域网访问。插件请求不应启用通配 CORS，也不应把本地服务改成公开 HTTP API。

建议在集成 API 启用一次性配对机制：

1. TeXGlot 首次启动时在数据目录生成权限受限的桥接 token；
2. 用户在 TeXGlot 设置中点击“连接 Zotero”后短暂显示配对码；
3. 插件通过本机请求完成配对，之后只保存加密或系统安全存储中的 token；
4. 用户可以在 TeXGlot 设置中撤销配对；
5. 未配对的插件只能访问健康状态，不能创建任务或读取附件。

第一版可以先依赖回环地址、数据目录和协议版本检查，但在公开发布 Zotero 插件前必须完成配对或等价的请求认证，不能把“只能本机访问”当作完整授权模型。

模型 API key 只存在 TeXGlot 设置文件或系统密钥存储中。Zotero 插件、Zotero 日志和附件 note 中都不能出现密钥。

## 9. 附件导入和数据一致性

### 9.1 导入流程

1. 从 TeXGlot 下载到 Zotero 临时目录；
2. 检查 HTTP 状态、文件大小上限和 `%PDF-` 文件头；
3. 计算 SHA-256；
4. 查询当前父条目是否已有相同版本和相同哈希的附件；
5. 使用 Zotero 附件 API 导入到父条目；
6. 保存有限的任务元数据；
7. 删除临时文件；
8. 根据用户选择打开原生 Zotero 分屏、单个附件或 TeXGlot 阅读器回退入口。

导入失败时保留 TeXGlot 任务，不把任务标为失败；用户可以重新导入，不需要重新调用模型。

`artifacts/{kind}` 支持 `original`、`translated`、`source`。采用配套原文时，原文附件标记 `artifact: "original"` 及其 SHA-256；译文记录 `source_attachment_key`、`source_fingerprint`、完整 arXiv ID 和目标语言。重新打开沿同一解析流程核验文件指纹，不依赖文件名或把任意唯一附件当作原文。

### 9.2 原文保护

插件不能覆盖原始 PDF，也不能修改原始附件的文件名、URL 或 `dateAdded` 来影响 Zotero 的最佳附件选择。若用户明确选择“将译文设为默认打开”，必须提供可撤销操作，并在设置中保留原始选择。

### 9.3 同步行为

导入到 Zotero 存储区的译文会按照用户现有 Zotero 同步设置同步。插件需要在首次导入前提示可能增加附件同步占用，但不自行改变 Zotero 的同步设置。

TeXGlot 的阅读位置和批注仍保存在 TeXGlot 任务的 `reader.json` 中，不写入 Zotero PDF 批注。两套坐标系统因为译文可能重排，不能直接互相覆盖。

## 10. Zotero 原生分屏阅读与 TeXGlot 阅读器联动

当前插件在译文导入后优先创建一个原生 Zotero 分屏标签页：

- 左侧载入原始 PDF，右侧载入 TeXGlot 译文 PDF；
- 右侧译文默认是主窗格，支持拖动中间分隔条调整宽度；
- 进入分屏时优先继承当前可见阅读器的页码和位置；
- 同步滚动按页码和页内位置映射，避免两个 PDF 页高不同造成逐页累积偏移；
- 通过阅读器上下文菜单可以关闭/开启同步，或切换主窗格；
- Zotero 会话恢复后，插件根据保存的左右附件 ID 重建分屏标签页。

原生分屏只负责两个 Zotero PDF 的并排阅读、基础定位和同步。TeXGlot 自己的阅读器仍然负责完整的全文搜索、批注、重排 PDF 的内容锚点和任务级位置保存。原生阅读器不可用时，插件才回退到本地 TeXGlot deep link。

为了支持该流程，TeXGlot 需要增加受控的 reader deep link，例如：

```text
http://127.0.0.1:8765/?reader=<job-id>
```

或注册：

```text
texglot://reader/<job-id>
```

Deep link 必须只接受本地任务 ID，并检查任务属于当前数据目录；不能接受任意文件路径或远程 URL。

原生分屏实现保持为独立模块，不复制 AGPL 插件的实现代码；需要新增跨 PDF 批注映射或完整内容锚点时，优先复用 TeXGlot 的阅读器合同，而不是把整套阅读逻辑复制到 Zotero。

## 11. CLI 联动规则

CLI 和 Zotero 插件共享服务，但职责不同：

| 能力 | CLI | Zotero 插件 |
| :--- | :--- | :--- |
| 配置模型 API | 支持 | 跳转到 TeXGlot 设置 |
| 提交 arXiv / LaTeX | 支持 | 支持 |
| 批量文件列表 | 支持 | 以 Zotero 多选条目为输入 |
| 任务进度 | 终端输出 | Zotero 状态面板 |
| 导出目录 | 用户指定目录 | Zotero 子附件 |
| PDF 对照阅读 | 打开网页或桌面 GUI | 打开 Zotero 原生分屏；不可用时使用 TeXGlot reader deep link |
| API key | 由 TeXGlot 服务读取 | 不接触 |

插件不直接运行：

```bash
texglot paper.tex --language zh
```

原因是直接启动 CLI 会产生重复服务、无法可靠跟踪后台任务、难以处理 Windows 路径和无法保证退出清理。插件应调用同一服务协议；CLI 也继续调用该协议。

## 12. 版本和发布

代码共用仓库，但插件和核心需要分别声明版本：

```text
TeXGlot core: 1.2.0
Zotero plugin: 0.1.0
integration API: zotero.v1
```

插件 manifest 中声明：

- 支持的 Zotero 主版本范围；
- 最低 `integration_api`；
- 推荐的 TeXGlot 核心版本；
- 插件自身版本和更新地址。

建议 Release 可以同时包含：

```text
TeXGlot-1.2.0-macOS-arm64.dmg
TeXGlot-1.2.0-macOS-x64.dmg
TeXGlot-1.2.0-Windows-x64-Setup.exe
texglot-1.2.0-source.zip
texglot-zotero-0.1.0.xpi
SHA256SUMS.txt
```

插件 XPI 不自动安装到 Zotero。桌面应用可以提供“下载 Zotero 插件”入口，但不能未经用户操作修改 Zotero profile。插件升级通过 Zotero 的更新机制或 GitHub Release 完成。

同仓库 CI 应增加：

1. 插件 TypeScript 类型检查、lint 和单元测试；
2. 集成 API schema 检查；
3. Python/前端/桌面现有测试；
4. 使用模拟 TeXGlot 服务的插件端到端测试；
5. 可选的真实 Zotero 8/9/10 集成测试；
6. XPI 内容审计，禁止包含 API key、用户路径、模型文件、任务 PDF 和 node_modules；
7. XPI、源码包和桌面安装包分别生成 SHA-256。

只有插件测试和核心测试都通过后，才把 XPI 放入公开 Release。

## 13. 测试矩阵

### 13.1 插件单元测试

- DOI、URL、Extra、archiveID 和文件名中的 arXiv ID 提取；
- `v1`、`v2` 与无版本号的区分；
- 旧式分类编号和冲突元数据；
- 多附件中主论文选择；
- 重复附件和哈希去重；
- 非 PDF 响应、截断下载和错误 JSON；
- 非法文件名和 Unicode 标题；
- 任务取消、重试和服务重新连接。

### 13.2 集成 API 测试

使用本地模拟服务验证：

- 健康检查和能力协商；
- arXiv、LaTeX 和未来 PDF 三种输入的能力开关；
- idempotency key 重复提交；
- 排队、源码准备、翻译、编译和完成状态；
- 需检查、失败和取消状态；
- 错误码不泄漏密钥和本地隐私路径；
- 服务重启后任务仍可查询。

### 13.3 Zotero 集成测试

至少覆盖当前使用的 macOS Zotero 9.0.6，并在发布前覆盖 Zotero 8、9 和 Windows 对应版本：

- 父条目和 PDF 附件两个入口；
- 单篇和多篇批量；
- arXiv 完整版本正确匹配；
- 已有译文复用；
- 译文附件导入和 Zotero 数据库重启后仍可打开；
- TeXGlot 服务关闭、端口被占用、版本不兼容；
- TeXGlot 任务部分失败后在 GUI 中继续；
- 原 PDF、原条目字段和已有批注保持不变；
- Zotero 同步开启时不修改同步设置；
- 应用更新或插件更新后旧任务仍能读取。

### 13.4 发布前人工检查

- 中文和英文菜单；
- 320px 级别的配置窗口不产生横向溢出；
- 长标题、中文路径、特殊符号和多版本论文；
- Windows/macOS 文件名和附件导入；
- XPI 安装、禁用、升级和卸载；
- 版本不一致时确实停止而不是静默下载错误译文。

## 14. 分阶段实施

### Phase 0：接口和测试合同

- 确定 `zotero.v1` schema；
- 增加 health、capabilities、idempotency 和错误码；
- 添加模拟服务和 schema 测试；
- 不改变现有 GUI、CLI 任务行为。

验收标准：CLI、GUI 和模拟 Zotero 客户端可以使用同一服务创建并查询任务。

### Phase 1：Zotero arXiv POC

- 建立 `integrations/zotero/`；
- 增加右键菜单；
- 识别完整 arXiv 版本；
- 提交 arXiv 任务并显示进度；
- 完成后导入译文 PDF。

验收标准：在 macOS Zotero 9 中对 Attention Is All You Need 发起任务，原文保持不变，译文作为子附件可打开。

### Phase 2：生产级附件和批处理

- LaTeX ZIP 附件；
- 多条目批处理；
- 去重、重试、取消和服务重启恢复；
- translated-source.zip 导入选项；
- 配置页和插件更新元数据。

验收标准：单篇失败不阻塞其他条目，重复提交不生成重复任务，所有错误均可从 Zotero 回到 TeXGlot 诊断。

### Phase 3：对照阅读联动（已开始）

- Zotero 原生双栏阅读器；
- 完成后自动打开原文/译文分屏，翻译侧为主、原文跟随滚动；
- 进入分屏继承当前页码，滚动按页内位置同步；
- 会话恢复时重建分屏，原生阅读器不可用时回退到 reader deep link。

验收标准：用户不需要手动复制任务 ID，能够从 Zotero 一步进入原文/译文对照阅读；重启 Zotero 后已保存的分屏仍能恢复为双栏。

### Phase 4：PDF 输入

- 等 PDF → 内容结构 → 重排 LaTeX 管线稳定后增加 PDF capability；
- 插件上传 PDF 或通过受控临时文件传递；
- 显示“重排后的原文 PDF”和译文 PDF，而不是承诺还原原始版式；
- 保留 OCR、公式和表格质量警告。

验收标准：普通 PDF 不能走源码接口，不支持时给出清晰提示；支持时任务、缓存和编译状态与 arXiv 路径一致。

## 15. 风险与处理

| 风险 | 处理方式 |
| :--- | :--- |
| Zotero 内部 API 变化 | 使用官方菜单 API和稳定的插件模板；保留 Zotero 8/9 集成测试；不直接依赖 SQLite |
| 服务端口被占用 | 健康检查必须验证服务名、版本和数据目录；不连接任意占用端口的程序 |
| 论文版本错配 | 完整版本锁定，冲突时停止；不自动回退到基础 ID |
| Zotero 附件重复 | 任务元数据 + 完整版本 + SHA-256 三重去重 |
| 大文件导入失败 | 临时文件校验后再导入；导入失败可单独重试，不重复翻译 |
| API key 泄漏 | 插件不接触 key；服务日志和附件 note 做敏感信息过滤 |
| XPI 体积膨胀 | 不包含 Python、模型、编译器、任务和前端构建缓存 |
| PDF 解析质量不稳定 | 通过 capability 明确支持范围；解析失败进入任务错误，不伪装成翻译完成 |
| 许可不兼容 | 借鉴行为和协议，重新实现；不复制 AGPL 插件代码到 Apache 核心 |

## 16. 参考实现

本设计参考了以下公开项目的功能行为，不复制其实现代码：

- [幻觉翻译官网](https://hjfy.top/)：arXiv 和本地文档翻译入口。
- [ANGJustinl/zotero-plugin-hjfy](https://github.com/ANGJustinl/zotero-plugin-hjfy)：一键翻译、批量处理、arXiv 元数据识别和自动附件导入。
- [Infinity4B/zotero-hjfy-split-reader](https://github.com/Infinity4B/zotero-hjfy-split-reader)：完整版本锁定、任务轮询、译文附件复用和分屏阅读。
- [windingwind/zotero-actions-tags 的 HJFY Action](https://github.com/windingwind/zotero-actions-tags/discussions/614)：接口返回校验、PDF 文件头校验、附件导入和默认打开策略示例。
- [Zotero JavaScript API](https://www.zotero.org/support/dev/client_coding/javascript_api)：选中条目、附件和文件操作的官方开发资料。

这些项目的公开插件代码采用 AGPL 许可。TeXGlot 的插件应在实现阶段重新确认上游许可证、模板依赖和分发义务；未完成审查前，不应直接复制代码或将其打进 Apache 2.0 的 TeXGlot 核心。

## 17. 当前决策记录

截至本文档创建时，已经确定：

- 插件与 TeXGlot 核心共享仓库；
- 插件位于 `integrations/zotero/`，独立构建为 XPI；
- 插件通过本地集成 API 使用 TeXGlot 服务；
- GUI、CLI 和 Zotero 共享同一 JobManager、缓存和模型配置；
- 第一版优先支持 arXiv/LaTeX，不承诺立即支持普通 PDF；
- 翻译结果作为 Zotero 子附件保存，原文不覆盖；
- 默认进入 Zotero 原生原文/译文分屏，不默认改变 Zotero 的最佳附件；原生阅读器不可用时回退到 TeXGlot 对照阅读器；
- 不把模型 API key 放入插件；
- 不直接调用 CLI，不直接修改 Zotero SQLite；
- 未完成实现、测试和许可证复核前，不发布 Zotero XPI。

本文档是后续实现和验收的依据。实现过程中若要改变上述边界，必须同时更新本文档、集成 API 合同、测试矩阵和对应的中英文用户说明。
