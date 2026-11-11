# 03 评估记录（企业知识问答）

## 1. 评估目标

这份记录回答两件事：

1. 离线测试能证明什么：流程、状态、护栏和确定性输出。
2. live 运行能证明什么：模型是否根据工具结果选择下一步，而不是走预设分支。

离线结果不能替代 live 结果。`finish` 能拦住非法引用，只说明护栏生效，不说明模型回答正确。

## 2. 环境与模型

- 运行方式：`opencode-local`，调用本机 OpenCode CLI 的实验生成接口。
- 模型：`opencode-go/deepseek-v4.1-flash`。
- 时间：2026-11-10T09:00:00+08:00（固定 `--now`）。
- 数据：`data/docs.json`，7 份合成制度/FAQ。
- 生成命令：

```bash
scripts/run_live_examples.sh
```

脚本不读取项目内密钥；API key 不进入仓库。

## 3. 离线测试

```bash
python3 -m pytest -q
```

结果：`12 passed`。

覆盖：明确答案、冲突、改写问题、资料外、上下文追问、工具失败、瞬时恢复、废止关系、文档替换、非法引用、未解决冲突、单份制度可答。

离线测试的作用是锁定状态和护栏，不证明模型决策。`examples/01-clear` 到 `examples/10-single-policy` 是离线参考输出。

## 4. Live 运行结果

| 用例 | 运行 ID | 步骤 | 结果 | 引用 |
| --- | --- | --- | --- | --- |
| 明确答案 | `QA-8DC62B227F` | 4 | `answered` | D03 |
| 文档冲突 | `QA-53A414510E` | 4 | `needs_clarification` | D01、D02 |
| 改写后的相似问题 | `QA-3598575953` | 4 | `needs_clarification` | D01、D02 |
| 资料外问题 | `QA-84FA4837F2` | 3 | `insufficient` | 无 |
| 上下文追问 | `QA-AA16D774AA` | 3 | `answered` | D04 |
| 工具失败 | `QA-18F4680608` | 3 | `tool_error` | 无 |
| 已解决冲突 | `QA-778DF835F9` | 4 | `answered` | D06、D05 |
| 替换文档内容 | `QA-2B4C2D9372` | 4 | `answered` | D03 |

### 代表性路径

- `01-clear`：读 D03 核对试用期，再读 D04 核对续费说明，最后引用 D03 回答。
- `02-conflict`：读取 D01 的 30 天和 D02 的 15 天，未找到可用于裁决的优先级，列出两份原文并追问。
- `06-tool-failure`：注入两次检索失败，模型重试一次后返回 `tool_error`。
- `07-resolved-conflict`：读完 D06 和 D05 后根据明确废止关系采用 D06，保留两份引用。
- `08-doc-updated`：同一个试用期问题在替换语料后回答 30 天，引用变体 D03。

## 5. Live 过程中发现的问题

第一次跑 `01-clear` 时，模型给 `finish` 传了 `followup_question: null`，`tools._finish` 直接调用 `.strip()`，触发 `TOOL_EXCEPTION`。模型随后重读 D04 并重试 `finish`，任务才完成。

修复：`tools._finish` 在入口把 `answer`、`followup_question` 归一化为空字符串，把非 dict 的 `conflict` 置空。修复后 `01-clear` 路径从 5 步降到 4 步，不再出现无效的工具失败。多出的 D04 读取是模型主动核对冲突，属于有效步骤。

同一轮还发现模型可能把 `status` 写成 `error`。在上下文输出协议里补上 `finish` 的合法状态后，`06-tool-failure` 的最终运行一次就提交了 `tool_error`。

`04-out-of-corpus` 第一次跑了 8 步：检索命中发票和差旅文档，模型想提交 `insufficient`，但 `finish` 要求“最近一次检索没有 hits”，于是它被迫读 D06/D05、再检索两次，最后才结束。这还导致输出里出现与年假无关的发票废止冲突。

修复：`insufficient` 只要求不带引用、gaps 非空，不再用“最近一次检索是否有 hits”判断。命中可能全部与问题无关，拒绝缺口状态会逼模型走无关路径。修复后 `04` 变成 3 步，输出也不再带无关冲突。冲突范围过滤（`noted_conflicts`）仍然没有实现，见 `02-design.md`。

`05-followup` 第一次运行的最后一个 `finish` 没有 `reason`，Trace 里 `decision_basis` 为空。已在系统提示和输出协议里写明 `reason` 必填；重跑后三步都有决策依据。

## 6. 当前结论与限制

- 这批 live 路径记录了模型根据检索结果、原文和工具失败调整下一步的过程。
- 冲突和改写路径证明模型会读两份原文并追问，不会只凭版本日期选一个答案。
- 工具失败路径证明模型会重试一次，仍失败就停止，不生成无依据答案。
- 资料外和上下文追问路径证明模型会改写检索、读历史相关文档，并在没有证据时返回缺口。
- 文档替换路径证明答案跟着原文走，不是把 14 天写死在代码里。
- 仓库保留八组 live 单次运行记录。`06-tool-failure`、`08-doc-updated` 各有一步缺少 `decision_basis`。
- `09-tool-recovery`、`10-single-policy` 目前只有离线覆盖。
- 当前 live 依赖本机 OpenCode CLI；这是本地开发入口，不是生产部署方式。
- 目标设计里的 claim 索引、`stale_only`、多冲突聚合、读取失败降级还没有实现，见 `02-design.md`。

## 7. 下一步

1. 补跑 `09-tool-recovery` 和 `10-single-policy` 的 live 用例。
2. 现有八组用例各跑 3 次，记录失败样本和差异。
3. 对冲突和工具失败路径做人工抽检：引用是否支持结论、追问是否覆盖两份制度。
4. 实现目标设计里的 claim 索引、`stale_only`、多冲突 scope 和读取失败降级。
5. live 结果稳定后，再决定是否把 `opencode-local` 作为默认评审入口，还是保留 `offline` 作为可复现基线。
