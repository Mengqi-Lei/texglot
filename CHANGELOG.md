# Changelog

## Unreleased

- Validate generated LaTeX and formatting before accepting repair slots; retry only invalid slots once, preserving accepted text and existing caches. / 在接收修复片段前校验新增 LaTeX 与格式，只重试不合规片段一次，保留已通过文字及已有缓存。
- Bound the local frontend build during source installation to 10 minutes and stop its process tree on timeout or cancellation; leave dependency downloads unrestricted by this build timeout. / 源码安装的本地前端构建最多等待 10 分钟，超时或取消时清理相关子进程；依赖下载不受该构建超时限制。

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
