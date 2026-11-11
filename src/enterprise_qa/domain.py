from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class RequestError(ValueError):
    pass


@dataclass(frozen=True)
class QARequest:
    request_id: str
    question: str
    history: tuple[dict[str, str], ...] = ()
    user_scope: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "QARequest":
        if not isinstance(data, dict):
            raise RequestError("input must be a JSON object")
        request_id = str(data.get("request_id") or "").strip()
        if not request_id:
            raise RequestError("request_id is required")
        question = str(data.get("question") or "").strip()
        raw_history = data.get("history") or []
        if not isinstance(raw_history, list):
            raise RequestError("history must be a list")
        history: list[dict[str, str]] = []
        for item in raw_history:
            if not isinstance(item, dict):
                raise RequestError("each history item must be an object")
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                raise RequestError("history items need role=user/assistant and content")
            history.append({"role": role, "content": content})
        return cls(
            request_id=request_id,
            question=question,
            history=tuple(history),
            user_scope=str(data.get("user_scope") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "question": self.question,
            "history": list(self.history),
            "user_scope": self.user_scope,
        }


def load_request(path: str | Path) -> QARequest:
    return QARequest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _tokens(text: str) -> set[str]:
    text = text.lower()
    tokens: set[str] = set(re.findall(r"[a-z0-9_]+", text))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) == 1:
            tokens.add(run)
        for size in (2, 3):
            for index in range(0, len(run) - size + 1):
                tokens.add(run[index : index + size])
    return tokens


SYNONYMS = {
    "出差": ["差旅"],
    "回来": ["发生后"],
    "多久": ["期限", "天内"],
    "几天": ["期限", "天内"],
    "之后": ["结束"],
    "以后": ["结束"],
    "提交": ["上传", "提交"],
    "发票": ["发票", "报销"],
}


def expand_query(query: str) -> str:
    additions: list[str] = []
    for key, values in SYNONYMS.items():
        if key in query:
            additions.extend(values)
    if not additions:
        return query
    return query + " " + " ".join(dict.fromkeys(additions))


def contextual_query(request: QARequest) -> str:
    question = request.question
    if not request.history:
        return question
    if len(question) <= 8 or any(word in question for word in ("那", "这个", "它", "之后", "然后")):
        last_user = next(
            (item["content"] for item in reversed(request.history) if item["role"] == "user"),
            "",
        )
        if last_user:
            topic = re.sub(r"(多久|多长|怎么|如何|什么|多少|几天|吗|呢|[？?])", " ", last_user)
            topic = " ".join(topic.split())
            return f"{question} {topic}".strip()
    return question


@dataclass
class DocStore:
    docs: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, data_dir: str | Path) -> "DocStore":
        raw = json.loads((Path(data_dir) / "docs.json").read_text(encoding="utf-8"))
        docs = raw.get("docs") if isinstance(raw, dict) else raw
        if not isinstance(docs, list):
            raise RequestError("docs.json must contain a docs list")
        return cls(docs=docs)

    def get(self, doc_id: str) -> dict[str, Any] | None:
        return next((doc for doc in self.docs if doc.get("doc_id") == doc_id), None)

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        hits: list[dict[str, Any]] = []
        for doc in self.docs:
            title_tokens = _tokens(str(doc.get("title") or ""))
            text_tokens = _tokens(str(doc.get("text") or ""))
            tag_tokens: set[str] = set()
            for tag in doc.get("tags", []):
                tag_tokens |= _tokens(str(tag))
            intent_tokens: set[str] = set()
            for intent in doc.get("intents", []):
                intent_tokens |= _tokens(str(intent))
            score = (
                len(query_tokens & text_tokens)
                + 2 * len(query_tokens & title_tokens)
                + 2 * len(query_tokens & tag_tokens)
                + 4 * len(query_tokens & intent_tokens)
            )
            if score <= 0:
                continue
            hits.append(
                {
                    "doc_id": doc["doc_id"],
                    "title": doc.get("title"),
                    "version_date": doc.get("version_date"),
                    "score": score,
                    "snippet": _snippet(str(doc.get("text") or ""), query_tokens),
                }
            )
        hits.sort(key=lambda item: (-item["score"], item["doc_id"]))
        if hits:
            # Drop weak lexical matches so a query about one policy does not
            # pull every document that shares a generic word like "天内".
            cutoff = max(1.0, hits[0]["score"] * 0.6)
            hits = [hit for hit in hits if hit["score"] >= cutoff]
        return hits[: max(1, min(int(top_k), 10))]


def _snippet(text: str, query_tokens: set[str]) -> str:
    positions = [text.find(token) for token in query_tokens if len(token) >= 2 and token in text]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return text[:80]
    start = max(0, min(positions) - 18)
    return text[start : start + 90]
