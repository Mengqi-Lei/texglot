# 参与 TeXGlot 开发

[English](CONTRIBUTING.md) · **简体中文** · [项目首页](README_CN.md)

欢迎提交问题修复、模板适配、界面翻译、文档改进和 Windows/macOS 原生测试结果。较大的功能变更建议先通过 Issue 说明问题和预期行为；小型修复可以直接提交 Pull Request。

## 搭建开发环境

Fork [Mengqi-Lei/texglot](https://github.com/Mengqi-Lei/texglot)，克隆自己的仓库并创建分支。分支名可以使用 `fix/reader-position`、`feat/provider-name` 等描述性名称。

先安装 **uv** 和 **Node.js 22.12+**，然后在项目根目录执行：

```bash
cd frontend
npm ci
npm run build
cd ..
uv sync --locked --python 3.13
uv run python scripts/install_compiler.py --if-missing
```

请**先构建前端，再安装 Python 项目**：wheel 会打包 `frontend/dist`。运行时支持 Python 3.11+，安装脚本使用 Python 3.13。以上开发流程不会替换全局 `texglot` 命令。

已在日常使用 TeXGlot 时，开发服务请使用独立数据目录：

```bash
# macOS / Linux，后端终端
export TEXGLOT_DATA_DIR="$PWD/output/dev-data"
uv run python -m app.server
```

```powershell
# Windows PowerShell，后端终端
$env:TEXGLOT_DATA_DIR = Join-Path $PWD 'output/dev-data'
uv run python -m app.server
```

在另一个终端运行前端：

```bash
cd frontend
npm run dev
```

打开 Vite 输出的网址。开发代理的 `/api` 指向 **8765** 端口；请先停止其他 TeXGlot 服务，或改用其他后端端口并相应修改本次开发使用的 `frontend/vite.config.ts`。后端不会自动重载，修改 Python 后请在没有运行中任务时重启。开发 CLI 使用 `uv run python -m app.cli`，与服务设置相同的数据目录和端口。

## 目录结构

| 路径 | 职责 |
| :--- | :--- |
| `app/main.py`、`app/server.py` | HTTP 接口、回环地址服务和进程所有权锁 |
| `app/cli.py` | CLI 配置、批量提交、状态等待和导出 |
| `app/sources.py`、`app/jobs.py` | 输入校验、源码识别和任务生命周期 |
| `app/latex.py`、`app/paper_context.py`、`app/llm.py` | 文本提取、摘要背景、提示词、译文校验和缓存 |
| `app/compiler.py`、`app/pdf.py`、`app/alignment.py` | TeX 编译、PDF 处理和阅读定位点 |
| `app/providers.py`、`app/config.py`、`app/platforms.py` | 服务商行为、设置持久化和平台差异 |
| `frontend/src/` | React 界面、PDF.js 阅读器、几何计算与批注 |
| `tests/`、`frontend/tests/` | 后端与前端回归测试 |
| `examples/` | 可复用的小型源码工程和 Attention 案例 |
| `scripts/` | 安装、启动、编译器准备、原生检查和发布导出 |

新增服务商时，同步检查后端识别与预设、前端预设以及双语文案，以服务商文档中的接口约定为依据，不仅根据模型名判断行为。修改翻译提示词时，检查校验与缓存指纹，避免旧译文绕过新规则。

## 应保持的行为

- **源码完整性：** 保留受保护的 LaTeX 语法、公式、引用和资源文件。段落校验失败必须可见，不将含失败段落的结果标为全部完成。
- **阅读器：** 同步使用共同内容定位点和局部插值。开启同步以译文为基准，进入对照跟随此前可见文档，退出对照保留所选侧位置；缩放和布局变化时保留阅读锚点，只渲染附近页面画布。
- **批注：** `reader.json` 使用归一化页面坐标及 PDF 的 SHA-256 版本。保留修订冲突检查和可撤销删除，不把批注写入导出 PDF 或源码包。
- **隐私：** 不记录密钥，不向其他地址转发已有服务的凭据。配置、任务、PDF、缓存和批注不能成为提交内容或测试数据；自动化测试使用合成输入与模型桩。
- **双语与平台：** 保持中英文界面同步更新，界面语言独立于翻译语言；显式使用 UTF-8，通过平台辅助函数处理路径、文件锁与子进程，避免引入特定 shell 的运行假设。

## 验证改动

从项目根目录按顺序运行：

```bash
cd frontend
npm ci
npm test
npm run build
cd ..
uv sync --locked
uv run ruff check app tests scripts
uv run python -m pytest -q
uv build
```

这些测试无需付费模型密钥。行为变更应补充有针对性的回归覆盖；纯文档修改通常只需检查链接和内容。涉及界面布局时，检查中英文及窄窗口显示。

安装、编译器或进程管理的变更，还应在受影响的操作系统运行：

```bash
uv run python scripts/smoke_platform.py --portable-compiler
```

脚本下载固定版本编译器，使用本地模型桩和隔离的临时服务，结果保存在 `output/platform-smoke/`。它验证原生处理流程，**不验证真实模型翻译质量**。macOS 上执行 Windows 分支测试不等于 Windows 实机测试；请在 PR 中说明实际执行的系统和检查。

[持续集成](.github/workflows/verify.yml) 在 `main` 推送及 Pull Request 时执行 Linux、macOS、Windows 的源码、前端与原生流程检查。[桌面构建工作流](.github/workflows/desktop.yml) 由维护者手动触发。两个工作流均不发布 Release，也不需要模型密钥；平台覆盖以实际运行结果为准。

## Commit 与 Pull Request

1. 每次提交聚焦一个问题，说明问题、改后行为及相关验证。
2. 推荐提交标题：`fix(reader): preserve position when switching views`、`feat(provider): add endpoint support`、`docs: clarify Windows setup`。提交标题建议英文，Issue 和 PR 讨论可使用中文或英文。
3. 同步修改受影响的中英文文档和界面文本，用户可感知的变化写入 `CHANGELOG.md`。
4. 依赖变化时才更新锁文件。不提交 `.venv`、`node_modules`、构建产物、本地配置、模型密钥、任务数据或下载的研究论文。
5. 向 `main` 提交 PR。视觉变更附截图，问题修复附最小复现，说明仍有的限制；未运行的测试不要写为通过。等待审查再合并，避免混入无关格式化。

仓库提供 [PR 模板](.github/pull_request_template.md) 和 [Issue 模板](.github/ISSUE_TEMPLATE)。附日志前，请移除密钥、个人路径及无权分享的论文内容。

## 二次分发与发布

项目采用 [Apache 2.0](LICENSE)。二次分发时保留许可和第三方声明，并说明实质修改。提交贡献即表示同意以项目 Apache 2.0 许可分发该贡献，并确认有权提交；没有另行要求签署 CLA 或强制 DCO sign-off。

发布内容应包含源码 ZIP、wheel、sdist、校验和及双语说明。[发布准备说明](docs/releasing_CN.md) 介绍干净导出和验证流程。不要发布私有数据，也不要将论文可在 arXiv 下载视为可自由重新分发的许可。

## 桌面安装包

桌面窗口位于 `desktop/`，打包脚本为 `scripts/build_desktop.py`。构建流程、包内引擎验证和原生工作流见[桌面开发说明](docs/desktop_CN.md#从源码构建安装包)。修改桌面服务启动与退出逻辑后，运行 `npm test --prefix desktop`，并用对应系统上的实际安装包验证。
