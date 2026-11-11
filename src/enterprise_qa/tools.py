from __future__ import annotations

from typing import Any

from .miniagent import Tool, ToolError, ToolResult, ToolRegistry
from .session import Session


def _search(session: Session, query: str, top_k: int = 3) -> dict[str, Any]:
    if not query.strip():
        raise ToolError("EMPTY_QUERY", "检索词不能为空")
    hits = session.store.search(query, top_k)
    payload = {"query": query, "hits": hits, "hit_count": len(hits)}
    session.searches.append(payload)
    return payload


def _read(session: Session, doc_id: str) -> dict[str, Any]:
    doc = session.store.get(doc_id)
    if doc is None:
        raise ToolError("DOC_NOT_FOUND", f"文档 {doc_id} 不存在")
    session.docs_read[doc_id] = doc
    return doc


def _finish(
    session: Session,
    status: str,
    answer: str = "",
    citations: list[dict[str, str]] | None = None,
    gaps: list[Any] | None = None,
    followup_question: str = "",
    conflict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allowed = {"answered", "needs_clarification", "insufficient", "tool_error", "needs_input"}
    if status not in allowed:
        raise ToolError("INVALID_STATUS", f"status 必须是 {sorted(allowed)} 之一")
    answer = answer or ""
    citations = citations or []
    gaps = gaps or []
    followup_question = followup_question or ""
    if conflict is not None and not isinstance(conflict, dict):
        conflict = None
    unresolved = session.conflicts()["unresolved"]

    if status == "needs_input":
        if session.request.question:
            raise ToolError("EVIDENCE_MISMATCH", "问题不为空，不能标记 needs_input")
    if status in {"answered", "needs_clarification"} and not answer.strip():
        raise ToolError("ANSWER_REQUIRED", "该状态必须有回答或冲突说明")
    if status == "answered":
        if not citations:
            raise ToolError("CITATION_REQUIRED", "answered 必须带引用")
        if unresolved:
            raise ToolError("UNRESOLVED_CONFLICT", "存在未解决冲突，不能给出单一答案")
        if not session.searches or not session.searches[-1].get("hits"):
            raise ToolError("NO_EVIDENCE", "没有成功检索到资料，不能回答")
    if status == "needs_clarification":
        if not unresolved:
            raise ToolError("NO_CONFLICT", "没有检测到未解决冲突，不能要求澄清")
        if len(citations) < 2:
            raise ToolError("CITATION_REQUIRED", "冲突说明需要引用至少两份资料")
        if not followup_question.strip():
            raise ToolError("FOLLOWUP_REQUIRED", "冲突时必须向用户追问")
    if status == "insufficient":
        if citations:
            raise ToolError("EVIDENCE_MISMATCH", "资料不足时不应带引用")
        if not gaps:
            raise ToolError("GAP_REQUIRED", "资料不足时必须说明缺口")
        # 命中可能全部与问题无关，不能只凭“最近一次检索有 hits”拒绝缺口状态。
    if status == "tool_error":
        if citations:
            raise ToolError("EVIDENCE_MISMATCH", "工具失败时不应带引用")

    for citation in citations:
        doc_id = str(citation.get("doc_id") or "")
        quote = str(citation.get("quote") or "")
        doc = session.docs_read.get(doc_id) or session.store.get(doc_id)
        if doc is None:
            raise ToolError("UNKNOWN_DOC", f"引用文档 {doc_id} 不存在")
        if doc_id not in session.docs_read:
            raise ToolError("DOC_NOT_READ", f"引用前必须读取 {doc_id} 原文")
        if not quote or quote not in str(doc.get("text") or ""):
            raise ToolError("INVALID_CITATION", f"引用片段不在文档 {doc_id} 原文中")

    computed = session.conflicts()
    canonical_conflict = {
        "detected": bool(computed["unresolved"] or computed["resolved"]),
        "resolved": bool(computed["resolved"]) and not computed["unresolved"],
        "unresolved_items": computed["unresolved"],
        "resolved_items": computed["resolved"],
    }
    if canonical_conflict["resolved"] and computed["resolved"]:
        canonical_conflict["authoritative_doc_id"] = computed["resolved"][0]["authoritative"]["doc_id"]
    if isinstance(conflict, dict):
        note = conflict.get("note") or conflict.get("summary")
        if note:
            canonical_conflict["note"] = str(note)
    payload = {
        "status": status,
        "answer": answer.strip(),
        "citations": citations,
        "gaps": gaps,
        "followup_question": followup_question.strip(),
        "conflict": canonical_conflict,
    }
    session.finish_payload = payload
    return payload


def build_tools(session: Session, faults: dict[str, int] | None = None) -> ToolRegistry:
    search_tool = Tool(
        name="search_docs",
        description="按问题检索制度或 FAQ，返回文档 ID、版本日期、相关度和片段。",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词；无结果时可改写后重试"},
                "top_k": {"type": "integer", "description": "返回条数，默认 3"},
            },
            "required": ["query"],
        },
        handler=lambda query, top_k=3: ToolResult.success("检索完成", _search(session, query, top_k)),
    )
    read_tool = Tool(
        name="read_doc",
        description="读取指定文档的原文、版本日期、结构化声明和废止关系。引用前必须读取原文。",
        parameters={
            "type": "object",
            "properties": {"doc_id": {"type": "string"}},
            "required": ["doc_id"],
        },
        handler=lambda doc_id: ToolResult.success("读取完成", _read(session, doc_id)),
    )
    finish_tool = Tool(
        name="finish",
        description="提交最终回答。answered 必须带原文引用；发现未解决冲突时必须追问，不能选一个答案。",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["answered", "needs_clarification", "insufficient", "tool_error", "needs_input"],
                },
                "answer": {"type": "string"},
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"doc_id": {"type": "string"}, "quote": {"type": "string"}},
                        "required": ["doc_id", "quote"],
                    },
                },
                "gaps": {"type": "array"},
                "followup_question": {"type": "string"},
                "conflict": {"type": "object"},
            },
            "required": ["status"],
        },
        handler=lambda status, answer="", citations=None, gaps=None, followup_question="", conflict=None: ToolResult.success(
            "任务结束", _finish(session, status, answer, citations, gaps, followup_question, conflict)
        ),
    )
    return ToolRegistry([search_tool, read_tool, finish_tool], faults=faults)
