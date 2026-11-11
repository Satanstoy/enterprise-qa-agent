from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .context_adapter import build_context
from .domain import DocStore, QARequest, load_request
from .miniagent import (
    Limits,
    OpenAIEngine,
    ToolExchange,
    TraceRecorder,
    new_run_id,
    parse_faults,
    run_loop,
    write_json,
)
from .local_engine import OpenCodeLocalEngine
from .policy import OfflineEngine
from .report import build_report
from .session import Session, parse_now
from .tools import build_tools

SYSTEM_PROMPT = """你是企业知识问答 Agent，服务员工查找制度和产品问题的可靠答案。
规则：
1. 必须先用 search_docs 检索，再 read_doc 读取原文；回答必须带文档 ID 和原文片段。
2. 只能依据读到的原文回答，不得使用常识补全，也不得编造文档或数字。
3. 多份文档对同一字段给出不同值时，说明冲突并请求用户确认适用制度；除非文档明确写了废止/优先级。发现废止声明时必须读取被废止文档核对。
4. 检索无结果，或命中均与问题无关时，改写查询一次；仍无相关结果就说明资料缺口，不要猜。
5. 工具失败时重试一次；仍失败就如实报告，不能只凭摘要回答。
6. 只能通过 finish 提交最终结果。
7. 每次调用工具前，先用一句中文说明这一步要做什么、为什么；reason 字段必填，不要输出长篇推理。
8. finish 的 status 只能是 answered / needs_clarification / insufficient / tool_error / needs_input；answered 和 needs_clarification 必须带 citations。

输出协议：每次只输出一个 JSON 对象，格式为
{"tool":"工具名","arguments":{...},"reason":"一句话依据"}。
不要输出 Markdown、解释或思维过程。"""


def build_user_prompt(request: QARequest) -> str:
    return (
        "请回答以下问题。若有对话历史，请结合上下文理解指代。\n"
        + json.dumps(request.to_dict(), ensure_ascii=False, indent=2)
        + "\n可用工具：search_docs, read_doc, finish。"
    )


@dataclass
class AgentState:
    request: QARequest
    transcript: list[ToolExchange] = field(default_factory=list)
    steps: int = 0
    tool_calls: int = 0
    finished: bool = False


def run_agent(
    *,
    input_path: str | Path,
    data_dir: str | Path,
    state_dir: str | Path,
    engine_name: str = "offline",
    now: str | None = None,
    faults: list[str] | None = None,
    max_steps: int = 12,
    max_tool_calls: int = 20,
    run_id: str | None = None,
    provider: str = "opencode-go",
    model: str = "deepseek-v4.1-flash",
    cli_path: str | None = None,
    max_context_chars: int = 14000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = load_request(input_path)
    store = DocStore.load(data_dir)
    state_path = Path(state_dir)
    state_path.mkdir(parents=True, exist_ok=True)
    session = Session(request=request, store=store, state_dir=state_path, now=parse_now(now))
    registry = build_tools(session, faults=parse_faults(faults))
    limits = Limits(max_steps=max_steps, max_tool_calls=max_tool_calls)
    run_id = run_id or new_run_id("QA")

    if engine_name == "offline":
        engine: Any = OfflineEngine(session)
    elif engine_name == "live":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        api_key = os.getenv("OPENAI_API_KEY")
        openai_model = os.getenv("OPENAI_MODEL")
        if not api_key or not openai_model:
            raise RuntimeError("live 模式需要 OPENAI_API_KEY 和 OPENAI_MODEL")
        engine = OpenAIEngine(
            api_key=api_key,
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            model=openai_model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_user_prompt(request),
            registry=registry,
        )
    elif engine_name == "opencode-local":
        builder = build_context(session, SYSTEM_PROMPT, registry, max_chars=max_context_chars)
        engine = OpenCodeLocalEngine(
            context_builder=builder,
            cli_path=cli_path,
            provider=provider,
            model=model,
        )
    else:
        raise RuntimeError(f"未知 engine：{engine_name}")

    trace = TraceRecorder(
        run_id=run_id,
        engine=engine.name,
        model=engine.model,
        request=request.to_dict(),
        limits=limits.to_dict(),
        mode_note=engine.mode_note,
        prompt_hash=engine.prompt_hash,
    )
    state = AgentState(request=request)
    run_status = run_loop(
        engine=engine,
        registry=registry,
        state=state,
        trace=trace,
        limits=limits,
    )
    output = build_report(
        session=session,
        exchanges=state.transcript,
        run_status=run_status,
        run_id=run_id,
        engine=engine.name,
        model=engine.model,
        mode_note=engine.mode_note,
        limits=limits.to_dict(),
    )
    if engine_name == "opencode-local":
        trace.note("context_stats", **builder.last_stats.to_dict())
    trace.finalize(output)
    trace_data = trace.to_dict()
    write_json(state_path / "output.json", output)
    write_json(state_path / "trace.json", trace_data)
    return output, trace_data
