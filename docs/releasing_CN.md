# 发布准备

[English](releasing.md) · **简体中文**

本指南供维护者重复执行版本发布流程。本地准备不会提交代码、推送仓库、上传 PyPI 或发布 GitHub Release。

## 版本与验证

1. 完成[贡献指南](../CONTRIBUTING_CN.md)中的相关检查及[源码 CI](../.github/workflows/verify.yml)，记录实际验证的系统和范围。
2. 对齐 `pyproject.toml`、`uv.lock`、`app/main.py`、`app/cli.py`、前端与桌面的 `package.json` 及对应锁文件版本，在 `docs/releases/` 添加双语说明，并更新 `CHANGELOG.md`。
3. 按[桌面指南](desktop_CN.md)在目标系统和架构构建安装包。[桌面工作流](../.github/workflows/desktop.yml) 构建并验证 Windows x64 与 Intel Mac 安装包；Apple Silicon 在 ARM Mac 上构建。这些工作流不会发布 Release。

## 准备文件

先构建前端，再从项目根目录导出到新目录：

```bash
uv run python scripts/prepare_release.py --output output/release-1.0.0 --installer desktop/out/TeXGlot-1.0.0-macOS-arm64.dmg
```

每个已验证的 DMG 或 EXE 分别添加一次 `--installer PATH`。输出目录不能已存在。脚本按明确的源码清单导出，检查文档链接和常见凭据、私人路径泄漏，并构建源码 ZIP、wheel、sdist，同时生成 SHA-256 校验和、源码清单及带版本仓库链接的双语发布正文。

| 输出 | 用途 |
| :--- | :--- |
| `repository/` | 不含 Git 元数据、本地数据或构建环境的源码快照 |
| `artifacts/` | 已验证安装包、源码 ZIP、wheel、sdist 和 `SHA256SUMS.txt` |
| `manifest.json` | 源码路径与 SHA-256 哈希 |
| `release-body.md` | 双语 GitHub Release 正文 |

检查导出目录和压缩包，确认字体与第三方许可完整，不包含设置、模型密钥、任务 PDF、批注或本地环境。在隔离环境验证 wheel 安装，在对应平台验证安装器。源码包、wheel 与安装包应使用相同的运行时及前端代码。

## 发布

保留仓库历史，提交已审阅的源码变更。在发布提交创建对应的 `vX.Y.Z` 标签，再使用生成的说明和已验证附件准备 [GitHub Release](https://github.com/Mengqi-Lei/texglot/releases) 草稿。公开前核对附件名称、校验和及文档链接。

安装包和生成的压缩包放在 Release 附件中，不写入 Git 历史。只提供已验证平台的安装包，并准确描述剩余限制。发布者签名和 Apple 公证不同于文件完整性检查，不将未签名的安装包描述为已签名。上传 PyPI 是独立流程。
