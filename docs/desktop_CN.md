# 桌面应用

[English](desktop.md) · **简体中文** · [返回 README](../README_CN.md)

桌面安装包已经包含网页界面、Python 服务和 Tectonic 0.17.0。普通用户无需安装 Python、Node.js、uv 或完整 TeX 发行版，安装后即可打开独立窗口。模型配置、翻译功能与浏览器版共用同一套实现。

## 安装与首次使用

- **Apple Silicon Mac：**下载 `TeXGlot-1.0.4-macOS-arm64.dmg`，打开后将 TeXGlot 拖入 Applications，再打开应用。
- **Intel Mac：**使用 Release 附件中的 `TeXGlot-1.0.4-macOS-x64.dmg`。
- **Windows x64：**使用 Release 附件中的 `TeXGlot-1.0.4-Windows-x64-Setup.exe`。安装器为当前用户安装，并建立开始菜单和桌面快捷方式，不需要管理员权限。

只有实际附加且验证过的文件才作为下载包提供。当前验证结果见[平台说明](platforms.md)。首批安装包尚无 Apple Developer ID 签名及公证，也没有 Windows 发布者证书，系统可能提示发布者未知。发布校验和用于验证文件完整性，不代表发布者身份认证；请勿为安装应用而关闭系统安全设置。

第一次打开后，进入**模型设置**，配置 Qwen、DeepSeek 或自定义 API，测试连接后保存。首次编译仍需联网获取 TeX 宏包与字体，之后会复用缓存。安装包中不包含任何模型密钥。

## 含 EPS 插图的论文

这类论文需要另行安装 **Ghostscript**，它没有随 TeXGlot 安装包捆绑。macOS 可执行 `brew install ghostscript`；Windows 从 [Ghostscript 官网](https://www.ghostscript.com/releases/gsdnld.html)安装 64 位版本，TeXGlot 会检测其标准安装目录。Linux 可使用发行版的软件包管理器安装 `ghostscript`。

安装后继续原任务即可。程序保留原始 EPS，在任务的预处理副本中生成 PDF 插图，并更新引用。转换启用 Ghostscript 的受限模式，macOS 仍沿用编译沙箱；不会为处理图片开启 LaTeX shell escape。需要重新分发转换程序时，应单独遵守 Ghostscript 的许可。

## 日常使用与升级

**文件**菜单可以打开主窗口、浏览器界面或数据文件夹。macOS 关闭窗口后应用仍会运行，使用**退出 TeXGlot**或 `Cmd+Q` 才会退出。翻译过程中退出会询问是否继续运行，中断的任务可以从文献库恢复。

设置、论文、段落缓存和批注保存在 `~/.texglot`，Windows 对应 `%USERPROFILE%\.texglot`。内置浏览器的数据保存在其中的 `desktop-profile` 子目录。更新只替换应用文件；Windows 卸载也会保留文献库。升级前请备份数据。

源码版默认使用仓库中的 `data/`。迁移时先停止两个服务，将该目录内容复制到**空的** `~/.texglot`，或在启动前设置 `TEXGLOT_DATA_DIR`。不要直接合并两个已有内容的文献库。桌面版不会自动搬动原来的源码任务。

桌面服务仅监听本机，在 8765 附近选择可用端口；只有数据目录和版本均相同才复用已有服务；升级后若旧版服务仍在使用同一资料库，需要先退出旧版服务。如 8765 被占用，可通过**文件 → 在浏览器中打开**进入正确地址。服务故障日志保存在数据目录的 `desktop-service.log`。

## 更新提醒

桌面版会在启动后及每 12 小时检查正式版本，发现更新时显示轻量提示。也可以使用**帮助 → 检查更新**或**模型设置 → 检查更新**，并在更新窗口关闭自动检查。检查本身不会下载或安装软件。

点击**下载更新**后，应用从正式 GitHub 仓库获取适合本机系统和架构的安装包，验证文件大小和 SHA-256。可以取消下载，重新打开应用后也能复用已经校验的安装包。下载期间可继续阅读和翻译。校验通过后，点击**退出并打开安装包**；需要先完成或停止仍在运行的翻译任务，阅读器中的批注和位置会先保存。

macOS 需要将打开的 DMG 中的 TeXGlot 拖入 Applications 并确认替换；Windows 按打开的安装程序完成更新。当前采用引导安装流程，尚未签名的安装包不会静默替换自身。macOS 标准自动更新需要应用签名，见 [Electron 官方说明](https://www.electronjs.org/docs/latest/api/auto-updater#macos)。

只有包含此功能的桌面版本才提供这些入口；旧版本需要先手动升级一次。源码和浏览器版本继续使用原来的安装流程。检查更新只向 GitHub 请求版本信息，不发送论文、模型密钥或资料库路径。GitHub API 限流时会回退到正式 Release 地址；网络或校验失败不会改变已经安装的应用。

## 安装包中的 CLI

安装包同时包含完整 CLI 引擎。可以打开 TeXGlot 并指定实际端口共用服务，也可以独立运行引擎。macOS 默认安装路径下：

```bash
"/Applications/TeXGlot.app/Contents/Resources/engine/texglot-engine" --help
"/Applications/TeXGlot.app/Contents/Resources/engine/texglot-engine" 1706.03762v7 --language zh
```

Windows 对应安装目录中的 `resources\engine\texglot-engine.exe`。引擎接受相同的 [CLI 参数](cli.md)，支持批量与任务恢复。桌面安装器不会修改终端 PATH；源码或 wheel 安装仍可以提供简短的 `texglot` 命令。

## 从源码构建安装包

需要在目标操作系统及对应架构上构建，不能在 Mac 上直接冻结 Windows Python 程序。准备 Node.js 22.12+ 与 uv 后：

```bash
cd frontend
npm ci
npm test
npm run build
cd ..
uv sync --locked --group desktop --python 3.13.11
cd desktop
npm ci
npm test
cd ..
uv run python scripts/build_desktop.py
```

安装包输出到 `desktop/out`。PyInstaller 冻结服务，electron-builder 打包原生窗口与安装器，编译器固定版本并验证下载校验和。可执行引擎位于 `desktop/engine-dist/texglot-engine`，验证命令：

```bash
# Windows 可执行文件名为 texglot-engine.exe。
uv run python scripts/smoke_platform.py --engine desktop/engine-dist/texglot-engine/texglot-engine --output output/desktop-smoke
```

检查会从 PATH 去除开发工具，通过本地模型桩翻译 `.tex` 与含中文目录的多文件 ZIP，验证中文 PDF 内容和父进程退出清理。不消耗模型额度，也不代表任意论文的语义质量已验证。

[原生构建工作流](../.github/workflows/desktop.yml)使用 GitHub 的 Windows x64 和 Intel macOS 主机，验证冻结引擎并执行 Windows 静默安装。手动触发，只上传构建产物，不自动发布 Release。正式签名版本需要另行配置可信签名凭据。第三方许可随应用附带，可从**帮助 → 第三方许可**查看。
