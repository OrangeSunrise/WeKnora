# delivery/ 交付内容

本目录是 `dev-qingyang` 分支新增的交付物，不属于 WeKnora 上游代码。
文档在 `document/`，从 `document/文档索引.md` 进入。

## 构成

| 路径 | 说明 |
|---|---|
| `scripts/import_kb.py` | 批量导入脚本，只用 Python 标准库，无需 pip 安装 |
| `kb-corpus/imported-300/` | 实际入库的 300 篇语料，按真实标题命名。`data/files` 下存放的是无意义的 ID 文件名，不适合交付 |
| `kb-corpus/manifest.csv` | 语料清单，共 7 列：`file`、`title`、`knowledge_id`、`bytes`、`parse_status`、`summary_status`、`enable_status`。其中 `title` 列取值与 `file` 列相同，均为带 `.md` 后缀的文件名，并非条目在知识库内的显示标题 |

## 快速使用

前提：服务已按 `document/操作说明.md` 启动，模型已接入，知识库已创建。

```bash
# 取知识库 ID
curl -s http://127.0.0.1:8080/api/v1/knowledge-bases

# 批量导入并等待索引完成
python delivery/scripts/import_kb.py --kb <知识库ID> --dir delivery/kb-corpus/imported-300 --wait
```

导入前**务必确认** `.env.lite` 中 `WEKNORA_MODEL_MAX_CONCURRENCY` 已调小（单机建议 2）。
默认值 32 会把 Ollama 队列堵满，导入期间任何提问都要排队数分钟。

## 脚本已处理的两件事

1. **中文文件名编码**。Windows 命令行按 ANSI 代码页传 argv，直接用 curl 传中文文件名会被
   `ValidateInput` 拒为「文件名包含非法字符」。脚本通过 multipart 的 `fileName` 表单字段
   以显式 UTF-8 传递，服务端 handler 会用它覆盖 header 中的文件名。
2. **索引完成判定**。`--wait` 会轮询到所有文档 `summary_status` 均为 `completed`。
   批量导入期间该字段会短暂出现 `failed`，属可重试中间状态，不必干预。

需要注意 `--wait` 等待的范围是全部知识库，而非仅 `--kb` 指定的那一个。脚本的
`wait_until_indexed` 先取知识库列表再逐库统计未完成条目，因此部署中存在多个知识库
时，其他库的未完成条目也会让它继续等待。只关心单个库的进度时，改用
`document/操作说明.md` 第 6.2 节的 SQL 或界面的运行队列页查看。

`--dir` 可指向任意目录，`--ext` 默认只收 `.md`。更换语料的完整流程，包括清空原库、
批量重新解析、嵌入模型变更时新建知识库这三种情形，见
`document/操作说明.md` 第 6.3 节。

## 语料来源

`kb-corpus/imported-300/` 是从中文维基工业类条目中按概念覆盖抽取的 300 篇，
清洗后的全量语料在 `source/wiki-kb/data/filtered/industrial_wiki_clean.jsonl`（35MB），
重新生成的脚本链在 `source/wiki-kb/scripts/`，详见 `document/操作说明.md` 第 6.4 节。

语料中混有铁路机车、军用雷达等与工业维护无关的内容，这是按概念覆盖抽取所致，
不是缺陷。它对测试有实际影响：无关文档会挤占召回，这也是把 `embedding_top_k`
降到 5 的原因。
