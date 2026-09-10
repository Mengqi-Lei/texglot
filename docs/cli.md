# TeXGlot CLI

[English](cli.en.md) · **简体中文** · [返回首页](../README_CN.md)

CLI 与网页共用本机模型设置、任务队列、缓存和文献库。无需打开浏览器；服务未运行时，CLI 会自动在后台启动它，后续命令复用同一进程。

## 安装与启动

macOS / Linux 完整安装：

```bash
./scripts/setup.sh
uv tool update-shell
```

Windows 双击仓库中的 `install-texglot.cmd`；原生 PowerShell 和 CMD 均可使用，不需要 WSL。安装依赖与平台验证状态见 [跨平台说明](platforms.md)。

重开终端即可从任意目录运行 `texglot`。已经构建好界面的源码仓库，也可以直接 `uv tool install --editable .` 安装命令；使用 `uv run python -m app.cli` 可在仓库内运行。

## 单篇翻译

```bash
texglot https://arxiv.org/abs/1706.03762
texglot 1706.03762 -o ~/Documents/Papers
texglot ./paper.tex
texglot ./project.zip --main main.tex --language zh
```

支持 arXiv 摘要链接、PDF 链接、ID，以及 `.tex`、`.zip`、`.tar`、`.tar.gz`、`.tgz`、`.gz` 文件。多文件项目请将图片、参考文献、模板一起打包。文件名包含空格时使用引号。Windows 示例：`texglot "C:\Papers\论文.tex" -o "D:\Translated Papers"`。

翻译目标使用已保存的设置；`--language zh` / `zh-TW` / `en` 可指定简体中文、繁体中文或英文。`--locale en` 仅改变 CLI 提示语言。

## 上下文引导

初始默认开启，使用论文原文摘要作为翻译背景。不传参数时，新任务沿用已保存的默认值。下列参数只覆盖本次命令创建的任务，批量处理的每一篇均使用相同选择：

```bash
texglot 1706.03762 --context-guidance
texglot ./paper.tex --no-context-guidance
texglot --batch papers.txt --no-context-guidance
```

关闭时不提取摘要，请求不包含摘要背景或摘要引导指令；正常翻译提示词、术语表和 LaTeX 结构保护仍有效。设置长期默认值：

```bash
texglot --configure --no-context-guidance
texglot --configure --context-guidance
```

默认值与网页模型设置同步，修改后不影响已经创建的任务。恢复任务默认保留该任务的选择；需要改变模式时显式指定：

```bash
texglot --resume TASK_ID --no-context-guidance
```

如果已完成任务的模式与参数不同，该命令会重新处理任务；模式相同则直接导出。运行中的任务不能切换模式，需要先停止。开关状态参与缓存区分，批次 JSON 的每个结果包含 `context_guidance`。

## 批量处理

直接传入多个来源：

```bash
texglot 1706.03762 ./paper.tex ./project.zip -o ./translated
```

也可以使用 UTF-8 文本清单，每行一个来源，空行和以 `#` 开头的行会被忽略：

```text
# papers.txt
https://arxiv.org/abs/1706.03762
./paper.tex
./project.zip
```

```bash
texglot --batch papers.txt -o ./translated
texglot --batch papers.txt --batch more-papers.txt --json
```

清单中的相对文件路径以**清单所在目录**为基准；命令行输入和输出目录以当前工作目录为基准。可使用 [cli-batch.txt](../examples/cli-batch.txt) 运行两份随附示例。

任务顺序处理，每篇内部按模型设置并发翻译段落。单篇失败会记录原因并继续下一篇；加 `--fail-fast` 可遇错停止。按 `Ctrl+C` 停止当前任务并结束本次批次，已完成任务和段落保留，未开始的项目不会被提交。若本地连接也已中断，CLI 会打印任务 ID，恢复连接后可查看或继续。

## 导出与恢复

默认输出在当前目录的 `texglot-output/`。每篇保存到带任务 ID 的独立目录：

```text
texglot-output/
  1706.03762-<task-id>/
    translated.pdf
    original.pdf
    translated-source.zip
    compile.log
  batch-<unique-id>.json
```

失败任务若已有源码或原始 PDF，也会导出已有产物。再次导出不会覆盖原文件，而会添加数字后缀。批次 JSON 记录每项状态、错误、页数、token 用量和文件路径；token 用量来自模型响应，恢复后反映该任务累计记录。

```bash
texglot --list
texglot --status TASK_ID
texglot --resume TASK_ID -o ./translated
texglot --resume FIRST_ID --resume SECOND_ID
```

未显式改变上下文引导时，`--resume` 对正在运行的任务等待结果，对中断或失败任务继续处理，对已完成任务直接导出。目标语言沿用原任务；改变翻译方向应提交新任务。恢复后复用有效的段落缓存。`partial` 表示部分段落未通过检查而保留原文，需要查看警告，可再次恢复重试。

退出码：`0` 全部成功，`1` 有失败、部分译文需检查或服务错误，`2` 命令参数错误，`130` 用户中断。`--json` 将可解析结果写入标准输出，进度写入标准错误，适合脚本调用。

## 模型配置

网页保存的模型配置可直接使用。终端也支持配置：

```bash
texglot --configure
texglot --configure --provider qwen \
  --base-url https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1 \
  --key-env DASHSCOPE_API_KEY --test
texglot --configure --provider deepseek --key-env DEEPSEEK_API_KEY --test
# 已分别保存过连接后，可直接切换：
texglot --configure --provider qwen
texglot --show-config
```

无参数的 `--configure` 会交互式询问地址、模型和隐藏输入的密钥。脚本可用 `--key-env` 从已设置的环境变量读取密钥，避免把密钥写进命令参数。`--show-config` 只显示密钥是否存在。`--provider` 可选 `qwen`、`deepseek`、`custom`，仅用于 `--configure`。Qwen 预设模型为 `qwen3.7-plus`，首次配置必须填写百炼控制台提供的 OpenAI 兼容地址；以上工作空间 ID 需要替换为实际值。更换 API 地址时不会沿用旧服务密钥；已保存的相同地址可恢复自己的密钥，同地址留空保留。`--configure --clear-key` 清除当前地址保存的密钥，其他服务的配置不受影响。本地无鉴权模型可以留空。

## 本地服务与安装包

```bash
texglot --serve                # 在当前终端运行服务，Ctrl+C 停止
texglot --no-start --list      # 只连接已运行的服务
texglot --port 8877 paper.tex  # 自定义端口
```

自动启动的服务在 CLI 退出后继续运行，网页可通过 `http://127.0.0.1:8765` 使用。若需要随终端退出而停止服务，可先在终端运行 `texglot --serve`，再在另一个终端提交翻译。若服务已在运行，`--serve` 会显示其地址。

源码安装默认读取仓库的 `data/`。独立 wheel 安装默认使用 `~/.texglot/`；用 `TEXGLOT_DATA_DIR` 可指定已有数据目录，`TEXGLOT_PORT` 可指定端口。同一数据目录只能由一个服务进程管理；CLI 检测到端口属于其他目录或应用时会报错，避免操作错误的文献库。

发布 wheel 前先 `cd frontend && npm ci && npm run build`，然后在仓库根目录运行 `uv build`。界面、PDF 阅读资源、字体与示例会按 [Hatch 的文件包含配置](https://hatch.pypa.io/latest/config/build/#forced-inclusion) 一起打包，私有配置和任务不会进入安装包。Windows 提供原生预览支持，无需 WSL；验证范围见 [平台说明](platforms.md)。
