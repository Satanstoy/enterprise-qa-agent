from __future__ import annotations

from typing import Any

from .miniagent import RunStatus
from .session import Session


def build_report(
    *,
    session: Session,
    exchanges: list[Any],
    run_status: RunStatus,
    run_id: str,
    engine: str,
    model: str,
    mode_note: str,
    limits: dict[str, int],
) -> dict[str, Any]:
    finish = session.finish_payload or {}
    failed = [item for item in exchanges if not item.result.ok]
    outcome = finish.get("status") if run_status.status == "completed" else (
        "failed" if run_status.status == "failed" else "incomplete"
    )
    queries = []
    for exchange in exchanges:
        if exchange.call.name == "search_docs":
            queries.append(
                {
                    "query": exchange.call.arguments.get("query"),
                    "ok": exchange.result.ok,
                    "hit_count": (exchange.result.data or {}).get("hit_count"),
                    "hits": (exchange.result.data or {}).get("hits", []),
                }
            )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "request_id": session.request.request_id,
        "engine": engine,
        "model": model,
        "mode_note": mode_note,
        "status": run_status.status,
        "outcome": outcome,
        "answer_status": outcome,
        "stop_reason": run_status.stop_reason,
        "limits": {
            **limits,
            "used_steps": run_status.steps,
            "used_tool_calls": run_status.tool_calls,
        },
        "request": session.request.to_dict(),
        "question": session.request.question,
        "answer": finish.get("answer", ""),
        "citations": finish.get("citations", []),
        "gaps": finish.get("gaps", []),
        "followup_question": finish.get("followup_question", ""),
        "conflict": finish.get("conflict", {"detected": False, "resolved": False}),
        "retrieval": {
            "queries": queries,
            "documents_read": list(session.docs_read),
        },
        "plan_steps": [
            {
                "step": index,
                "tool": exchange.call.name,
                "status": "succeeded" if exchange.result.ok else "failed",
                "code": exchange.result.code,
                "summary": exchange.result.summary,
                "arguments": exchange.call.arguments,
                "decision_basis": exchange.call.reason,
            }
            for index, exchange in enumerate(exchanges, start=1)
        ],
        "degraded": bool(failed),
        "failed_tool_calls": [
            {"tool": item.call.name, "code": item.result.code, "summary": item.result.summary}
            for item in failed
        ],
        "decision_basis": {
            "answered": "引用原文片段回答，片段已由 finish 工具校验。",
            "needs_clarification": "检测到字段冲突且无适用范围/优先级，向用户追问。",
            "insufficient": "两次检索无命中，说明资料缺口。",
            "tool_error": "工具连续失败，未生成无依据答案。",
            "needs_input": "缺少问题文本。",
        }.get(outcome, "任务未完成。"),
        "summary": {
            "tools_succeeded": sum(1 for item in exchanges if item.result.ok),
            "tools_failed": len(failed),
            "documents_read": len(session.docs_read),
            "citations": len(finish.get("citations", [])),
        },
    }
