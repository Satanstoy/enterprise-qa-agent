# Live 运行记录

这些记录用本机 OpenCode CLI 的 `opencode-local` 引擎生成，模型是 `opencode-go/deepseek-v4.1-flash`。它不是离线策略，模型在每一步根据工具观察决定下一步。

| 用例 | 路径 | 结果 |
| --- | --- | --- |
| 明确答案 | `01-clear` | `search_docs -> read_doc(D03) -> read_doc(D04) -> finish(answered)` |
| 文档冲突 | `02-conflict` | `search_docs -> read_doc(D01) -> read_doc(D02) -> finish(needs_clarification)` |
| 改写后的相似问题 | `03-paraphrase` | 同一路径，识别出 D01/D02 冲突 |
| 资料外问题 | `04-out-of-corpus` | `search_docs -> search_docs(rewrite) -> finish(insufficient)` |
| 上下文追问 | `05-followup` | `search_docs -> read_doc(D04) -> finish(answered)` |
| 工具失败 | `06-tool-failure` | `search_docs(failed) -> search_docs(failed) -> finish(tool_error)` |
| 已解决冲突 | `07-resolved-conflict` | 读取 D06 和 D05，按 supersedes 采用 D06 |
| 替换文档内容 | `08-doc-updated` | 同一问题在变体数据上回答 30 天 |

每组包含 `input.json`、`output.json`、`trace.json`、`manifest.json`。`trace.json` 记录模型决策、工具参数和结果。模型返回理由时会写入 `decision_basis`。

重新生成：

```bash
scripts/run_live_examples.sh
```

脚本默认使用本机 OpenCode CLI，不读取项目内的密钥。不要把 API key 写进仓库。
