# 02 目标设计（企业知识问答）

这份文档描述目标状态，不代表当前实现。当前实现见 `02-solution.md`，差距和落地顺序在本文第 2、10 节。

## 1. 目标与不变量

目标：员工问制度或产品问题，Agent 给出有原文依据的回答；资料冲突时暴露冲突，不替用户选一个版本。

不变量：

1. 回答只来自已经 `read_doc` 的原文，引用必须能逐字核验。
2. 引用必须绑定到具体 claim，不能只证明“这句话在文档里”。
3. 有未解决冲突时不能输出单一答案，必须列出冲突并追问。
4. 只有文档明确写了 `supersedes`，才允许用新文档覆盖旧文档；版本日期不参与优先级。
5. 只剩被废止文档时，返回资料缺口，不能回退到旧文档回答。
6. 检索无结果或工具失败时，不生成肯定回答。
7. 所有状态、工具调用、证据和失败都进入 report 与 trace。

## 2. 当前实现与目标差距

| 维度 | 当前实现 | 目标设计 |
| --- | --- | --- |
| 召回范围 | `search_docs` 默认 `top_k=3`，只读前 3 份 | 先扩大召回，再按 claim key 补读同字段文档，总读取设上限 |
| 冲突状态 | 只有 `unresolved` / `resolved` | 增加 `stale_only`：只剩被废止文档 |
| 多冲突 | `policy` 只取 `unresolved[0]` | 汇总所有与问题相关的冲突，无关冲突只记录 |
| 冲突范围 | 比较所有已读文档的 claim | 按 query token 与 claim key 筛相关冲突 |
| 引用校验 | `quote in doc.text` | `doc_id + claim_key + quote`，校验 claim 与原文 |
| 读取失败 | 任一份连续失败就 `tool_error` | 先判断失败文档是否相关，再决定停止或降级 |
| 评估 | 12 个离线测试、10 组示例 | 增加 stale chain、漏检、多冲突、部分读取和 live 评测 |

## 3. 目标流水线

```text
QARequest
  -> contextual_query / expand_query
  -> search_docs(top_k=8)
  -> 选前 3 份高相关文档
  -> read_doc（每份失败重试一次）
  -> claim 补读
       用已读文档的 claim key 反查同 key 文档
       只补读 active 文档，总读取不超过 6 份
  -> 冲突检测
       unresolved  -> needs_clarification
       resolved    -> answered（authoritative doc）
       stale_only  -> insufficient + STALE_ONLY
       none        -> 按 intent/rank 选文档
  -> finish 校验 citation
  -> report + trace
```

补读和冲突检测分开：`DocStore` 负责“哪些文档有同一个 claim”，`policy` 负责“这个 claim 是否和当前问题相关”。不要把索引逻辑写进 policy，也不要在检索阶段就做冲突判断。

## 4. 状态机

| 状态 | 触发 | 输出约束 |
| --- | --- | --- |
| `answered` | 有已读原文、引用绑定 claim、无未解决冲突 | 必须有 citations；不能引用未读文档 |
| `needs_clarification` | 多个 active claim 值不同且无 supersedes | 至少两条引用；必须带 `followup_question` |
| `insufficient` | 两次检索无命中，或只剩被废止文档 | 不带 citations；必须有 gaps |
| `tool_error` | 检索或读取连续失败且无法降级 | 不带 citations；必须说明失败工具 |
| `needs_input` | 缺问题文本 | 不检索、不回答；列出缺失字段 |

顶层 `status` 表示循环是否跑完，业务状态看 `answer_status`。两者不要混用：循环正常结束但业务未完成，是 `completed` + `insufficient`，不是 `failed`。

## 5. 数据模型

### 5.1 文档与声明

```json
{
  "doc_id": "D01",
  "version_date": "2025-01-01",
  "scope": null,
  "supersedes": [],
  "claims": [
    {
      "key": "报销期限",
      "value": "30天",
      "quote": "员工应在费用发生后 30 天内提交报销申请，逾期需部门负责人审批。"
    }
  ]
}
```

`claims` 是冲突检测和引用绑定的共同依据。没有结构化 claim 的长文本，需要先做条款抽取，不能直接进入当前冲突模型。

### 5.2 冲突结果

```python
{
    "unresolved": [{"key": "报销期限", "claims": [...]}],
    "resolved": [{"key": "发票提交方式", "authoritative": {...}, "superseded": [...]}],
    "stale_only": [{"key": "报销期限", "removed": [...]}],
    "noted_conflicts": [{"key": "无关字段", "claims": [...]}],
}
```

`unresolved`：同一 key 至少有两个不同的 active 值，且没有废止关系。

`resolved`：同一 key 只剩一个 active 值，并且有文档被明确废止。

`stale_only`：同一 key 的 active 集合为空，removed 非空。说明只找到了已废止文档，最新制度没有覆盖这个字段。这个分支不能静默回退到旧文档。

`noted_conflicts`：检测到但与当前问题无关的冲突，只记录，不阻断回答。

### 5.3 引用

```python
{
    "doc_id": "D01",
    "claim_key": "报销期限",
    "quote": "员工应在费用发生后 30 天内提交报销申请，逾期需部门负责人审批。",
}
```

`finish` 按 `doc_id + claim_key` 找到 claim，要求 `quote == claim.quote`，或者严格落在 `claim.quote` 内。`needs_clarification` 的每条引用也要带 `claim_key`，否则冲突引用仍可能引用文档里与冲突无关的句子。

没有 claims 的文档使用 `evidence_span`：

```python
{"doc_id": "D07", "start": 0, "end": 24, "quote": "会议室需提前 2 小时预订"}
```

服务端用 `text[start:end] == quote` 校验，不用自由文本。

### 5.4 claim 索引

`DocStore.load` 时建立：

```python
claim_index: dict[str, list[str]]  # claim key -> doc_id
```

提供 `docs_for_claim(key)`。索引只解决“找得到”，是否补读由 policy 决定。补读时按 `scope`、版本和 active 状态过滤，并设总读取上限，避免 key 泛化时把整个库拖进来。

## 6. 冲突检测规则

按 claim key 分组：

1. 计算所有 `supersedes` 指向的文档，得到 `superseded_ids`。
2. `active = claims` 中 `doc_id` 不在 `superseded_ids` 的声明。
3. `removed = claims` 中 `doc_id` 在 `superseded_ids` 的声明。
4. `active` 有多个不同值：`unresolved`。
5. `active` 只有一个值，且 `removed` 非空：`resolved`，采用 active 文档。
6. `active` 为空，且 `removed` 非空：`stale_only`。
7. `active` 有多个相同值：无冲突；`removed` 存在时也不阻断。

冲突相关性：

- claim key 或 claim quote 与 query token 有重叠，算相关。
- 相关冲突全部返回；多个冲突按 key 分点列出。
- 无关冲突进入 `noted_conflicts`，不阻断回答。

## 7. 引用校验

`finish` 在写入结果前检查：

1. 引用文档存在，且已经 `read_doc`。
2. `claim_key` 在文档 claims 中存在。
3. `quote` 等于该 claim 的 quote，或严格落在 claim quote 内。
4. `answered` 的引用必须绑定回答所依据的 claim。
5. `needs_clarification` 的每条引用必须绑定冲突中的 claim。
6. `insufficient` / `tool_error` 不带 citations。
7. `answered` 有未解决冲突时拒绝；有 `stale_only` 时也拒绝。

校验失败返回结构化错误码，循环继续：

- `DOC_NOT_READ`
- `UNKNOWN_CLAIM`
- `INVALID_CITATION`
- `UNRESOLVED_CONFLICT`
- `STALE_ONLY`
- `CITATION_REQUIRED`

## 8. 失败与降级

检索：

- 第一次失败，扩展同义词重试一次。
- 连续失败，`tool_error` + `SEARCH_FAILED`。
- 两次无命中，`insufficient` + `NO_DOC`。

读取：

- 单份文档失败重试一次。
- 仍失败时先判断相关性：
  - 失败文档与问题或已读文档共享 claim key，或可能包含 `supersedes` 关系：停止，`tool_error` + `READ_FAILED`。
  - 失败文档与当前问题无关：继续回答可读文档，report 里记 `unverified_docs`，并标记 `degraded=true`。
- 所有候选都读不到：`tool_error`，不回答。

步数或工具调用达到上限：

- 顶层 `status=incomplete`，`stop_reason=step_limit` 或 `tool_limit`。
- 不生成肯定回答；trace 保留已完成步骤。

## 9. 评估

离线测试覆盖：

- 明确答案、冲突、废止、stale_only、无资料、工具失败、瞬时恢复、部分读取、多冲突、无 claim 文档、非法引用。

live 评估：

- 固定 10 组用例，每组跑 3 次。
- 指标：引用绑定通过率、冲突召回率、状态正确率、语义支持抽检、工具失败处理。
- `finish` 拦住的非法引用是护栏指标，不能当成模型回答正确率。
- 记录失败样本和方差；10 组样本只说明链路跑通，不做统计显著性结论。

## 10. 实施顺序

1. `session.py`：增加 `stale_only`，补多冲突和相关性过滤的单元测试。
2. `tools.py`：`finish` 增加 `claim_key` 校验；放开 `insufficient` 的“最近检索有命中”限制，条件是 `stale_only` 非空且无 active claim。
3. `domain.py`：建立 claim 索引和 `docs_for_claim`。
4. `policy.py`：`top_k=8`、claim 补读、相关冲突聚合、读取失败按相关性降级。
5. `report.py`：输出 `stale_only`、`noted_conflicts`、`unverified_docs`、citation 的 `claim_key`。
6. `tests/` 与 `examples/`：补 stale chain、漏检冲突、多冲突、部分读取、错误 claim 引用五组用例。
7. live 评估脚本与文档。

## 11. 已知边界

- 冲突检测依赖结构化 `claims`；长文本需要先做条款抽取。
- 检索仍是关键词 + 标签 + 意图词，不是 BM25 或向量检索；语料扩大后要换混合召回。
- 没有接企业权限，`user_scope` 当前未参与过滤。
- 没有确认后的续跑状态机：用户回复“按 D02”后需要重新发起请求。
- `supersedes` 关系只能从已读文档里发现；未读文档的废止边仍可能漏。
- live 模型的语义支持需要人工抽检，工具校验只保证引用格式和原文匹配。
