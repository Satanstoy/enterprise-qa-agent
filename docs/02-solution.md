# 02 方案说明

## 1. 目标与不变量

目标：给员工一个有原文依据的回答，冲突时暴露冲突而不是压平。

不变量：

1. 回答必须来自读过的原文，引用片段必须逐字存在。
2. 未解决冲突时不能输出单一答案，必须追问。
3. 只有文档明确写了 `supersedes`，才允许用新文档覆盖旧文档。
4. 检索无结果或工具失败时，不生成肯定回答。
5. `answered` 必须有引用；`insufficient` / `tool_error` 不带引用。

## 2. 执行流程

```text
QARequest
  -> contextual_query / expand_query
  -> search_docs
       无结果 -> 改写检索一次
  -> read_doc（命中前 3 份）
  -> 冲突检测（结构化 claims + supersedes）
       -> 未解决 -> finish(needs_clarification)
       -> 已解决 -> 采用 authoritative doc
       -> 无冲突 -> 按意图/排名选文档
  -> finish(answered / insufficient / tool_error)
  -> report
```

## 3. 检索

检索分三层：

- 中文 2/3-gram、英文/数字 token。
- 标题、标签、正文的加权词面匹配。
- 文档 `intents` 的意图词加权，帮助“多久/之后/发票怎么提交”这类问题选到正确文档。

这不是向量检索，适合 7 份合成文档的可解释 demo。语料扩大后应换 BM25 + embedding 混合召回，再保留原文读取和引用校验。

## 4. 冲突模型

文档在 `data/docs.json` 里带结构化声明：

```json
{"key": "报销期限", "value": "30天", "quote": "员工应在费用发生后 30 天内提交报销申请，逾期需部门负责人审批。"}
```

`Session.conflicts` 按 `key` 分组：

- 同一 key 的值全部相同：无冲突。
- 值不同，且没有 `supersedes` 关系：未解决冲突，要求用户确认适用制度。
- 值不同，但某文档的 `supersedes` 指向另一份：已解决，采用 superseding 文档，并记录被废止的声明。

版本日期不参与优先级。D02 比 D01 新，但 D02 没有废止 D01，也没有适用范围，所以仍然冲突。

## 5. 引用护栏

`finish` 在写入结果前检查：

1. 引用的文档存在，且已经 `read_doc`。
2. `quote` 是原文的逐字子串。
3. `answered` 没有未解决冲突，且最近一次检索有命中。
4. `needs_clarification` 至少引用两份文档并带追问。
5. `insufficient` 不带引用，必须有缺口。

任何一条失败返回结构化错误，循环继续。报告里的 `citations` 来自 `finish` payload，不采用模型自由文本。

## 6. 上下文与失败

- 问题短或含“那/这个/之后”时，`contextual_query` 追加上一轮用户问题，并去掉疑问词，避免旧问题意图压过当前问题。
- 检索失败重试一次，仍失败 `tool_error`。
- 读取原文失败重试一次，仍失败 `tool_error`，不凭摘要回答。
- 两次检索无命中 `insufficient`，说明资料缺口。

## 7. 评估

12 个测试覆盖明确答案、冲突、改写问题、资料外、上下文、工具失败、瞬时恢复、废止关系、文档替换、非法引用、未解决冲突、单份制度可答。10 组示例有 input/output/trace/manifest，`scripts/build_examples.py` 可重建。

替换文档实验见 `examples/08-doc-updated`：同一问题在 D03 改为 30 天后回答 30 天，证明答案跟着原文走。
