from __future__ import annotations

from typing import Any

from .domain import contextual_query, expand_query
from .miniagent import OFFLINE_NOTE, EngineFailure, TextOnly, ToolCall, ToolCalls
from .session import Session


def _results(state: Any, name: str) -> list[Any]:
    return [exchange for exchange in state.transcript if exchange.call.name == name]


def _select_doc(session: Session, question: str, top_hits: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, hit in enumerate(top_hits):
        doc = session.docs_read.get(hit["doc_id"])
        if doc is None:
            continue
        intent_score = sum(len(str(intent)) for intent in doc.get("intents", []) if str(intent) in question)
        ranked.append((intent_score, -index, doc))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def _citation(doc: dict[str, Any], claim: dict[str, Any] | None = None) -> dict[str, str]:
    quote = (claim or {}).get("quote") or (doc.get("claims") or [{}])[0].get("quote") or doc.get("text", "")
    return {
        "doc_id": doc["doc_id"],
        "title": doc.get("title", ""),
        "version_date": doc.get("version_date", ""),
        "quote": quote,
    }


class OfflineEngine:
    name = "offline-reference"
    model = "reference-policy"
    mode_note = OFFLINE_NOTE
    prompt_hash = "offline-reference-policy"

    def __init__(self, session: Session):
        self.session = session

    def _call(self, name: str, arguments: dict[str, Any], reason: str) -> ToolCalls:
        return ToolCalls([ToolCall(name=name, arguments=arguments, reason=reason)])

    def next_action(self, state: Any) -> ToolCalls | TextOnly | EngineFailure:
        request = state.request
        if not request.question:
            return self._call(
                "finish",
                {
                    "status": "needs_input",
                    "answer": "",
                    "gaps": [{"code": "MISSING_QUESTION", "message": "缺少问题文本"}],
                },
                "没有问题，先返回缺口。",
            )

        searches = _results(state, "search_docs")
        contextual = contextual_query(request)
        if not searches:
            return self._call(
                "search_docs",
                {"query": expand_query(contextual), "top_k": 3},
                "先检索相关制度或 FAQ；必要时扩展同义词。",
            )

        last_search = searches[-1]
        if not last_search.result.ok:
            if len(searches) == 1:
                return self._call(
                    "search_docs",
                    {"query": f"{expand_query(contextual)} 制度", "top_k": 3},
                    "检索失败，扩展同义词后重试一次。",
                )
            return self._call(
                "finish",
                {
                    "status": "tool_error",
                    "answer": "",
                    "gaps": [{"code": "SEARCH_FAILED", "message": "检索工具连续失败，未生成答案"}],
                },
                "连续检索失败，停止并说明工具故障。",
            )

        hits = last_search.result.data.get("hits") or []
        if not hits:
            if len(searches) == 1:
                return self._call(
                    "search_docs",
                    {"query": f"{expand_query(contextual)} 资料", "top_k": 3},
                    "无结果，改写检索词后重试。",
                )
            return self._call(
                "finish",
                {
                    "status": "insufficient",
                    "answer": f"现有资料没有覆盖“{request.question}”，无法给出有依据的回答。",
                    "gaps": [
                        {
                            "code": "NO_DOC",
                            "message": "两次检索均未命中任何文档",
                            "queries": [item.call.arguments.get("query") for item in searches],
                        }
                    ],
                },
                "资料库没有覆盖问题，明确说明缺口。",
            )

        top_hits = hits[:3]
        for hit in top_hits:
            doc_id = hit["doc_id"]
            reads = [
                item
                for item in _results(state, "read_doc")
                if item.call.arguments.get("doc_id") == doc_id
            ]
            if not reads:
                return self._call(
                    "read_doc",
                    {"doc_id": doc_id},
                    f"读取 {doc_id} 原文，核对引用和冲突。",
                )
            if not reads[-1].result.ok:
                if len(reads) == 1:
                    return self._call(
                        "read_doc",
                        {"doc_id": doc_id},
                        f"读取 {doc_id} 失败，重试一次。",
                    )
                return self._call(
                    "finish",
                    {
                        "status": "tool_error",
                        "answer": "",
                        "gaps": [
                            {
                                "code": "READ_FAILED",
                                "message": f"读取 {doc_id} 连续失败，已有检索结果保留，但无法核验原文",
                            }
                        ],
                    },
                    "原文读取失败，不能只凭摘要回答。",
                )

        conflicts = self.session.conflicts()
        unresolved = conflicts["unresolved"]
        if unresolved:
            item = unresolved[0]
            claims = sorted(item["claims"], key=lambda claim: claim["doc_id"])
            descriptions = "；".join(
                f"{claim['doc_id']}（{claim['version_date']}）规定 {claim['value']}" for claim in claims
            )
            answer = (
                f"检索到关于“{item['key']}”的冲突：{descriptions}。"
                "这些文档都没有给出适用范围或优先级，不能判断哪一份适用。"
            )
            doc_options = "、".join(f"{claim['doc_id']}（{claim['version_date']}）" for claim in claims)
            return self._call(
                "finish",
                {
                    "status": "needs_clarification",
                    "answer": answer,
                    "citations": [
                        {
                            "doc_id": claim["doc_id"],
                            "title": self.session.docs_read[claim["doc_id"]].get("title", ""),
                            "version_date": claim["version_date"],
                            "quote": claim["quote"],
                        }
                        for claim in claims
                    ],
                    "followup_question": f"请确认适用哪份制度：{doc_options}？",
                    "conflict": {
                        "detected": True,
                        "resolved": False,
                        "field": item["key"],
                        "claims": claims,
                        "note": "未提供适用范围或优先级，不擅自选择版本。",
                    },
                },
                "发现未解决冲突，列出双方原文并追问适用制度。",
            )

        resolved = conflicts["resolved"]
        if resolved:
            item = resolved[0]
            authoritative = item["authoritative"]
            doc = self.session.docs_read[authoritative["doc_id"]]
            return self._call(
                "finish",
                {
                    "status": "answered",
                    "answer": doc.get("answer") or doc.get("text", ""),
                    "citations": [_citation(doc, authoritative)],
                    "conflict": {
                        "detected": True,
                        "resolved": True,
                        "field": item["key"],
                        "authoritative_doc_id": authoritative["doc_id"],
                        "superseded": item["superseded"],
                        "note": item["note"],
                    },
                },
                "发现版本冲突，依据文档中的废止关系采用新制度。",
            )

        doc = _select_doc(self.session, request.question, top_hits)
        if doc is None:
            return self._call(
                "finish",
                {
                    "status": "tool_error",
                    "answer": "",
                    "gaps": [{"code": "NO_READABLE_DOC", "message": "命中文档均未能读取原文"}],
                },
                "没有可核验的原文，停止。",
            )
        claim = (doc.get("claims") or [None])[0]
        return self._call(
            "finish",
            {
                "status": "answered",
                "answer": doc.get("answer") or doc.get("text", ""),
                "citations": [_citation(doc, claim)],
                "conflict": {"detected": False, "resolved": False},
            },
            f"依据 {doc['doc_id']} 的原文回答。",
        )

    def record_tool_results(self, exchanges: list[Any]) -> None:
        return None

    def record_nudge(self, message: str) -> None:
        return None
