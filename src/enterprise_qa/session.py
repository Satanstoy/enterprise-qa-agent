from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .domain import DocStore, QARequest

TZ = timezone(timedelta(hours=8))


@dataclass
class Session:
    request: QARequest
    store: DocStore
    state_dir: Path
    now: datetime
    searches: list[dict[str, Any]] = field(default_factory=list)
    docs_read: dict[str, dict[str, Any]] = field(default_factory=dict)
    finish_payload: dict[str, Any] | None = None

    def search_hits(self) -> list[dict[str, Any]]:
        if not self.searches:
            return []
        return list(self.searches[-1].get("hits") or [])

    def conflicts(self) -> dict[str, Any]:
        claims_by_key: dict[str, list[dict[str, Any]]] = {}
        supersedes: dict[str, set[str]] = {}
        for doc_id, doc in self.docs_read.items():
            supersedes[doc_id] = set(doc.get("supersedes") or [])
            for claim in doc.get("claims", []):
                claims_by_key.setdefault(str(claim.get("key")), []).append(
                    {
                        "doc_id": doc_id,
                        "value": claim.get("value"),
                        "quote": claim.get("quote"),
                        "version_date": doc.get("version_date"),
                    }
                )
        unresolved: list[dict[str, Any]] = []
        resolved: list[dict[str, Any]] = []
        superseded_ids: set[str] = set()
        for doc_id, targets in supersedes.items():
            superseded_ids |= targets
        for key, claims in claims_by_key.items():
            if len({str(claim["value"]) for claim in claims}) <= 1:
                continue
            active = [claim for claim in claims if claim["doc_id"] not in superseded_ids]
            removed = [claim for claim in claims if claim["doc_id"] in superseded_ids]
            if len({str(claim["value"]) for claim in active}) > 1:
                unresolved.append({"key": key, "claims": claims})
            elif active and removed:
                resolved.append(
                    {
                        "key": key,
                        "authoritative": active[0],
                        "superseded": removed,
                        "note": f"{active[0]['doc_id']} 明确废止 {removed[0]['doc_id']}，采用前者。",
                    }
                )
        return {"unresolved": unresolved, "resolved": resolved}

    def authoritative_doc_ids(self) -> list[str]:
        return [item["authoritative"]["doc_id"] for item in self.conflicts()["resolved"]]


def parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(TZ)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)
