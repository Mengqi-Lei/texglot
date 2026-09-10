# Attention Is All You Need

[English](README.md) · **简体中文** · [TeXGlot](../../README_CN.md)

本案例使用 Ashish Vaswani 等人发表于 NeurIPS 2017 的 **Attention Is All You Need**，输入固定为 [arXiv:1706.03762v7](https://arxiv.org/abs/1706.03762v7)，避免论文后续修订影响复现输入。

## 运行

先完成 TeXGlot 安装并测试模型连接。案例使用你配置的 API，会产生服务商计费的用量。

**网页：** 将 `https://arxiv.org/abs/1706.03762v7` 粘贴到 arXiv 输入框，选择简体中文，保持上下文引导开启，点击开始翻译。完成后打开对照阅读器。

**CLI：** 可以在任意目录运行：

```bash
texglot https://arxiv.org/abs/1706.03762v7 --language zh --context-guidance -o ./translated
```

或在项目根目录使用随附批量清单：

```bash
texglot --batch examples/attention-is-all-you-need/papers.txt --language zh --context-guidance -o ./translated
```

完成后，独立任务目录应包含 `translated.pdf`、`original.pdf`、`translated-source.zip` 和 `compile.log`，另有批次 JSON 结果。同一任务也会显示在网页文献库。中断时可以用 `texglot --resume TASK_ID` 继续。

## 检查结果

打开原文和译文 PDF，对照标题、摘要、公式、图表标题、数字结果及交叉引用。译后源码 ZIP 应保留工程中的图片和资源。检查任务警告，仍有失败段落时恢复任务重试。

在靠后章节尝试切换阅读模式并重新开启同步。翻译改变文字长度，两份文档的页数可能不同；存在共同内容定位点时，阅读器据此同步位置。

模型输出和用量可能随运行变化。自动检查覆盖结构完整性，不能证明每一句译文的语义准确性。

## 案例内容

本目录提供说明和 arXiv 输入清单，原始源码及完整译文在运行时下载、生成到本机，不随 TeXGlot 分发。

论文的 [arXiv 分发许可](https://arxiv.org/licenses/nonexclusive-distrib/1.0/license.html) 记录的是授予 arXiv 的分发权，不是对本项目的通用重新分发许可。论文不属于 TeXGlot 的 Apache 2.0 许可范围。README 阅读器截图展示英文正文节选、TeXGlot 生成的中文译文及实验结果，并标明论文出处。

## 文献引用

```bibtex
@inproceedings{vaswani2017attention,
  title={Attention Is All You Need},
  author={Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and
          Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N. and
          Kaiser, Lukasz and Polosukhin, Illia},
  booktitle={Advances in Neural Information Processing Systems},
  volume={30},
  year={2017},
  url={https://arxiv.org/abs/1706.03762}
}
```
