# 企业知识问答 Agent（项目题 3 · 小 demo）

员工问制度或产品问题，Agent 先检索文档、再读取原文，回答时带文档 ID 和原文片段。两份制度冲突且没有适用范围或优先级时，它列出双方并追问，不擅自选一个版本。

默认 `offline` 是确定性参考策略，用来复现验收路径；`opencode-local` 用本机 OpenCode CLI 跑真实模型，`live` 走 OpenAI-compatible function calling。离线结果不代表真实模型效果。live 记录见 `examples/live/`。

## 评审入口

- 离线测试：`python3 -m pytest -q`，12 个测试。
- 离线示例：`examples/01-clear` 到 `examples/10-single-policy`。
- live 示例：`examples/live/` 下 8 组，覆盖明确答案、未解决冲突、改写、资料外、上下文追问、工具失败、已解决冲突和文档替换。
- 复现 live：`scripts/run_live_examples.sh`，需要本机 OpenCode CLI。

详细评估见 [`docs/03-evaluation.md`](docs/03-evaluation.md)。

## 快速开始

需要 Python 3.12+。

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
```

明确答案：

```bash
python3 run.py run \
  --input examples/01-clear/input.json \
  --state-dir .runs/clear \
  --now 2026-11-10T09:00:00+08:00
```

冲突问题：

```bash
python3 run.py run \
  --input examples/02-conflict/input.json \
  --state-dir .runs/conflict \
  --now 2026-11-10T09:00:00+08:00
```

注入检索连续失败：

```bash
python3 run.py run \
  --input examples/06-tool-failure/input.json \
  --state-dir .runs/fail \
  --now 2026-11-10T09:00:00+08:00 \
  --fault search_docs:2
```

## 验收场景

| 场景 | 入口 | 实际结果 |
| --- | --- | --- |
| 明确答案 | `examples/01-clear` | `answered`，引用 D03 原文 |
| 文档冲突 | `examples/02-conflict` | D01 说 30 天、D02 说 15 天，`needs_clarification`，两份都引用 |
| 改写后的相似问题 | `examples/03-paraphrase` | “出差回来多久内要报销”仍检索到 D01/D02，返回冲突 |
| 资料外问题 | `examples/04-out-of-corpus` | 两次检索无命中，`insufficient`，无引用 |
| 上下文追问 | `examples/05-followup` | “那之后呢”结合历史定位到 D04，回答续费/只读 |
| 工具失败 | `examples/06-tool-failure` | 两次检索失败，`tool_error`，不生成答案 |
| 可查证的冲突 | `examples/07-resolved-conflict` | D06 明确废止 D05，采用 D06，冲突标记 resolved |
| 替换文档内容 | `examples/08-doc-updated` | 同一问题在变体数据上回答 30 天，证明答案跟着原文走 |
| 瞬时失败恢复 | `examples/09-tool-recovery` | 第一次检索失败，重试成功，Trace 保留失败步骤 |
| 单份制度可答 | `examples/10-single-policy` | 只命中 D07，直接回答会议室预订规则，不制造冲突 |

每个示例目录有 `input.json`、`output.json`、`trace.json`、`manifest.json`；`08-doc-updated` 另带一份 `data/docs.json` 变体。

## 冲突实例

`examples/02-conflict` 的实际输出：

```json
{
  "answer_status": "needs_clarification",
  "answer": "检索到关于“报销期限”的冲突：D01（2025-01-01）规定 30天；D02（2026-01-01）规定 15天。这些文档都没有给出适用范围或优先级，不能判断哪一份适用。",
  "citations": [
    {"doc_id": "D01", "quote": "员工应在费用发生后 30 天内提交报销申请，逾期需部门负责人审批。"},
    {"doc_id": "D02", "quote": "报销申请须在费用发生后 15 天内提交，逾期不予受理。"}
  ],
  "followup_question": "请确认适用哪份制度：D01（2025-01-01）、D02（2026-01-01）？",
  "conflict": {"detected": true, "resolved": false, "field": "报销期限"}
}
```

版本日期更新不等于自动废止。D02 比 D01 新，但它没有写“废止 D01”，也没有写适用范围，所以不能直接答 15 天。

`examples/07-resolved-conflict` 是另一种情况：D06 明确写了“原 2024 版同时废止”，`supersedes` 指向 D05，Agent 才采用 D06。

## 工具与校验

| 工具 | 作用 | 关键校验 |
| --- | --- | --- |
| `search_docs` | 关键词检索文档，返回 ID、版本、片段 | 空查询拒绝；无结果由策略改写一次 |
| `read_doc` | 读取原文、结构化声明、废止关系 | 文档必须存在；引用前必须读原文 |
| `finish` | 提交回答、引用、缺口、追问 | 引用片段必须逐字出现在原文；有未解决冲突时拒绝 `answered` |

冲突检测不靠模型自由判断。Agent 读原文后比较结构化 `claims`：同一个 `key` 出现不同 `value` 就是冲突。如果某份文档的 `supersedes` 明确指向另一份，才把它判为已解决。见 `src/enterprise_qa/session.py` 的 `conflicts`。

## 输出口径

- `status`：循环是否跑完（`completed` / `incomplete` / `failed`）。
- `answer_status`：业务状态（`answered` / `needs_clarification` / `insufficient` / `tool_error` / `needs_input`）。
- `answer`：给用户的回答或冲突说明；资料不足和工具失败时不编答案。
- `citations`：文档 ID、标题、版本日期、原文片段。
- `gaps`：资料缺口。
- `followup_question`：冲突时向用户追问的问题。
- `conflict`：是否检测到冲突、是否解决、字段和双方声明。

## 目录

```text
src/enterprise_qa/
  miniagent.py   # 手写工具循环、Trace、OpenAI 适配器
  context.py     # ContextBuilder：按预算重建上下文
  context_adapter.py # 把会话状态渲染成模型上下文
  local_engine.py # 本机 OpenCode CLI 的模型入口
  domain.py      # 请求、文档加载、检索、查询改写
  session.py     # 会话状态、冲突检测
  tools.py       # 检索、读原文、finish 校验
  policy.py      # 离线参考策略
  report.py      # 输出组装
  runner.py      # 组装与执行
  cli.py         # 命令行
tests/           # 12 个测试
data/            # 7 份合成制度/FAQ
examples/        # 10 组离线验收 + 8 组 live
examples/live/   # 本机 OpenCode CLI 的 live 运行记录
docs/00-grill.md # 设计追问与回答
docs/02-design.md # 目标设计
docs/03-evaluation.md # 离线与 live 评估记录
scripts/         # 示例生成脚本
```

## 真实模型（可选）

默认离线模式不需要网络。两种 live 入口：

- `--engine opencode-local`：调用本机 OpenCode CLI，默认 `opencode-go/deepseek-v4.1-flash`，不需要项目内 API key。`scripts/run_live_examples.sh` 用这个入口。
- `--engine live`：OpenAI-compatible function calling。复制 `.env.example` 为 `.env`，填 `OPENAI_API_KEY`、`OPENAI_MODEL`，运行命令加 `--engine live`。

## 已知边界

- 检索是关键词 + 标签 + 意图词，不是向量检索；语料扩大后需要 embedding 或混合检索。
- 冲突检测依赖文档里的结构化 `claims`；纯自然语言长文需要先抽取声明。
- 只处理单轮或简单多轮；没有真正的对话状态机。
- 不接企业权限系统，所有合成文档对所有用户可见。
- 仓库保留 8 组 live 单次运行记录。`09-tool-recovery` 和 `10-single-policy` 有离线覆盖。

实现细节见 [`docs/02-solution.md`](docs/02-solution.md)，目标设计见 [`docs/02-design.md`](docs/02-design.md)，评估记录见 [`docs/03-evaluation.md`](docs/03-evaluation.md)，设计追问见 [`docs/00-grill.md`](docs/00-grill.md)。
