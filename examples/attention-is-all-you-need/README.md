# Attention Is All You Need

**English** · [简体中文](README_CN.md) · [TeXGlot](../../README.md)

A reproducible real-paper walkthrough using **Attention Is All You Need**, Ashish Vaswani et al., NeurIPS 2017. Input is pinned to [arXiv:1706.03762v7](https://arxiv.org/abs/1706.03762v7), so a future arXiv revision does not silently change the example.

## Run it

First install TeXGlot and test your model connection. This walkthrough uses your configured API and incurs provider usage charges.

**GUI:** paste `https://arxiv.org/abs/1706.03762v7` into the arXiv field, choose Simplified Chinese, leave context guidance enabled and click Translate. After completion, open the side-by-side reader.

**CLI:** from any directory:

```bash
texglot https://arxiv.org/abs/1706.03762v7 --language zh --context-guidance -o ./translated
```

Or, from the repository root, use the supplied batch file:

```bash
texglot --batch examples/attention-is-all-you-need/papers.txt --language zh --context-guidance -o ./translated
```

Expect a task-specific folder with `translated.pdf`, `original.pdf`, `translated-source.zip` and `compile.log`, plus a batch JSON summary. The GUI library includes the same task. If interrupted, run `texglot --resume TASK_ID`.

## Check your result

Open the original and translated PDFs and inspect the title, abstract, formulas, captions, numeric results and cross-references. The translated source ZIP should retain the project's figures and resources. Review any task warnings and resume the task if failed segments remain.

Try switching reader modes and re-enabling synchronized scrolling at a later section. The two documents can have different page counts because translation changes text length; synchronization follows shared content landmarks where available.

Model output and usage can vary between runs. Automatic checks cover structural integrity; they do not prove the semantic accuracy of every sentence.

## What is included

This directory contains instructions and the arXiv input list. The source and full translated paper are downloaded/generated locally when you run the example; they are not bundled with TeXGlot.

The paper's [arXiv distribution license](https://arxiv.org/licenses/nonexclusive-distrib/1.0/license.html) records a grant to arXiv, not a general redistribution license for this project. The paper is not covered by TeXGlot's Apache 2.0 license. The README reader images show excerpts of the original prose, their TeXGlot-generated Chinese translation and experimental results, with attribution to the paper.

## Reference

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
