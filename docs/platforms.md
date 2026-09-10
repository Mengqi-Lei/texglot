# 平台支持

[English](platforms.en.md) · **简体中文** · [返回首页](../README_CN.md)

各平台共用 Python 服务、网页、CLI 和数据格式。桌面安装包自带运行环境，也可以继续使用源码启动入口，无需 WSL。

| 平台 | 安装 / 启动入口 | 1.0.0 验证范围 |
| :--- | :--- | :--- |
| macOS Apple Silicon | ARM64 DMG，也可源码安装 | macOS 26.6.2 实测 DMG 完整性、桌面窗口、服务启动与退出、安装后引擎和 PDF 生成。 |
| macOS Intel | x64 DMG，也可源码安装 | Intel 原生 GitHub 主机构建成功，包内引擎翻译与 PDF 生成通过；交互式 Intel 桌面验收待补充。 |
| Windows 10/11 x64 | x64 EXE，也可使用源码脚本 | 原生 GitHub Windows Server 2025 主机通过 EXE 安装、安装后引擎、中文路径多文件输入和中文 PDF 生成；Windows 10/11 客户端交互验收待补充。 |
| Linux x64 / ARM64 | `bash scripts/setup.sh` / `uv run python scripts/start.py` | 已配置安装资源，本次发布尚无 Linux 原生验收结果。 |

Windows ARM64 暂无专用便携编译器。以上 macOS 版本是实际测试环境，不代表已经确定的最低系统版本。

## 依赖

- **桌面版：**无需另装 Python、Node.js 或 uv，DMG／EXE 自带应用运行环境。详见[桌面指南](desktop_CN.md)。
- **源码版：**安装前准备 uv 和 **Node.js 22.12+**。安装脚本管理 **Python 3.13**，应用元数据允许 Python 3.11+。
- 安装及首次下载 TeX 宏包和字体需要联网；翻译需要访问所选模型接口，arXiv 输入还需要连接 arXiv。
- 可用模型接口，以及该服务要求的 API key。模型费用由服务商收取，TeXGlot 不收取 API 费用。
- 未安装 Tectonic 时，会在数据目录内准备独立编译器，固定为 0.17.0 并校验 SHA-256。自行安装 XeLaTeX/LuaLaTeX 后，也可以在设置中选择。

Windows 建议使用 `D:\TeXGlot` 等较短路径。源码和数据可以迁移；`.venv`、`node_modules` 应在新操作系统重新安装，不跨平台复制使用。

## 自检与自定义启动

```bash
# macOS
bash start-texglot.command --check
bash start-texglot.command --no-browser --port 8877
```

```powershell
# Windows
.\start-texglot.cmd --check
.\start-texglot.cmd --no-browser --port 8877
```

`--check` 检查 Python、前端和编译器，不启动服务。也支持 `TEXGLOT_PORT`、`TEXGLOT_DATA_DIR`、`TEXGLOT_NO_BROWSER=1`。全局命令无法找到时，运行 `uv tool update-shell` 并重开终端；源码目录可使用 `uv run python -m app.cli`。

## 隔离与验证

服务采用对应系统的单进程所有权锁、子进程清理与显式 UTF-8 读写，仅监听回环地址。macOS 有额外的编译沙箱，Windows/Linux 尚无同等级的 OS 文件隔离，请使用可信源码。

帮助验证平台时，可运行 `uv run python scripts/smoke_platform.py --portable-compiler`，将脱敏结果附到 Issue。测试使用本地模型桩，验证原生 CLI 和 PDF 生成，不消耗模型额度。[桌面构建工作流](../.github/workflows/desktop.yml) 构建安装包并检查其中的引擎；[源码 CI](../.github/workflows/verify.yml) 覆盖 Linux、macOS 和 Windows。工作流配置本身不代表平台已获验证，上表记录本次发布实际完成的检查。
