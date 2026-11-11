from __future__ import annotations

from typing import Any

from .context import ContextBuilder
from .miniagent import ToolRegistry
from .session import Session


def _recent_failures(transcript: list[Any]) -> list[dict[str, Any]]:
    return [
        {"tool": exchange.call.name, "code": exchange.result.code}
        for exchange in transcript[-8:]
        if not exchange.result.ok
    ]


def render_state(session: Session, state: Any) -> dict[str, Any]:
    conflicts = session.conflicts()
    return {
        "search_runs": [
            {
                "query": item.get("query"),
                "hit_count": item.get("hit_count"),
                "doc_ids": [hit["doc_id"] for hit in item.get("hits", [])],
            }
            for item in session.searches
        ],
        "documents_read": [
            {
                "doc_id": doc.get("doc_id"),
                "title": doc.get("title"),
                "version_date": doc.get("version_date"),
                "claim_keys": [claim.get("key") for claim in doc.get("claims", [])],
            }
            for doc in session.docs_read.values()
        ],
        "conflicts": {
            "unresolved": [item.get("key") for item in conflicts["unresolved"]],
            "resolved": [item.get("key") for item in conflicts["resolved"]],
        },
        "finish": session.finish_payload,
        "recent_failures": _recent_failures(state.transcript),
    }


def build_context(
    session: Session,
    system_prompt: str,
    registry: ToolRegistry,
    max_chars: int = 14000,
) -> ContextBuilder:
    return ContextBuilder(
        system_prompt=system_prompt,
        tools=registry.schemas(),
        request_renderer=lambda state: state.request.to_dict(),
        state_renderer=lambda state: render_state(session, state),
        output_contract=(
            '只输出一个 JSON 对象，格式：{"tool":"工具名","arguments":{...},"reason":"一句话依据"}。'
            "reason 必填。不要 Markdown、解释或思维过程。每次只推进一个工具调用。"
            "finish 的 status 只能是 answered / needs_clarification / insufficient / tool_error / needs_input；"
            "answered 和 needs_clarification 必须带 citations（doc_id + quote），不要传 null。"
        ),
        max_chars=max_chars,
        recent_observations=6,
    )
