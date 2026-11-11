from __future__ import annotations

from enterprise_qa.domain import DocStore, QARequest
from enterprise_qa.miniagent import ToolResult
from enterprise_qa.session import Session
from enterprise_qa.tools import build_tools
from conftest import ROOT


def test_clear_answer_is_grounded_in_d03(run_case):
    output, _ = run_case("01-clear")
    assert output["answer_status"] == "answered"
    assert output["answer"].startswith("企业版试用期为 14 天")
    assert [item["doc_id"] for item in output["citations"]] == ["D03"]
    quote = output["citations"][0]["quote"]
    doc = DocStore.load(ROOT / "data").get("D03")
    assert quote in doc["text"]


def test_conflict_lists_both_docs_and_asks_user(run_case):
    output, _ = run_case("02-conflict")
    assert output["answer_status"] == "needs_clarification"
    assert output["conflict"]["detected"] is True
    assert output["conflict"]["resolved"] is False
    assert [item["doc_id"] for item in output["citations"]] == ["D01", "D02"]
    assert "30天" in output["answer"] and "15天" in output["answer"]
    assert output["followup_question"].startswith("请确认适用哪份制度")
    # 关键缺陷：不能擅自给出单一期限。
    assert not output["answer"].strip().startswith("15 天")


def test_paraphrased_question_still_hits_both_policies(run_case):
    output, _ = run_case("03-paraphrase")
    assert output["answer_status"] == "needs_clarification"
    assert {item["doc_id"] for item in output["citations"]} == {"D01", "D02"}
    queries = [item["query"] for item in output["retrieval"]["queries"]]
    assert any("报销" in query for query in queries)


def test_out_of_corpus_returns_gap_not_answer(run_case):
    output, _ = run_case("04-out-of-corpus")
    assert output["answer_status"] == "insufficient"
    assert "没有覆盖" in output["answer"]
    assert output["citations"] == []
    assert output["gaps"][0]["code"] == "NO_DOC"


def test_context_followup_uses_history_to_pick_d04(run_case):
    output, _ = run_case("05-followup")
    assert output["answer_status"] == "answered"
    assert output["answer"].startswith("企业版试用期结束后")
    assert [item["doc_id"] for item in output["citations"]] == ["D04"]


def test_search_failure_after_retry_returns_tool_error(run_case):
    output, _ = run_case("06-tool-failure", faults=["search_docs:2"])
    assert output["answer_status"] == "tool_error"
    assert output["answer"] == ""
    assert output["citations"] == []
    assert output["gaps"][0]["code"] == "SEARCH_FAILED"


def test_transient_search_failure_recovers(run_case):
    output, _ = run_case("09-tool-recovery", faults=["search_docs:1"])
    assert output["answer_status"] == "answered"
    assert output["degraded"] is True
    assert output["failed_tool_calls"][0]["code"] == "INJECTED_FAILURE"


def test_explicit_supersedes_resolves_invoice_conflict(run_case):
    output, _ = run_case("07-resolved-conflict")
    assert output["answer_status"] == "answered"
    assert output["conflict"]["resolved"] is True
    assert output["conflict"]["authoritative_doc_id"] == "D06"
    assert output["citations"][0]["doc_id"] == "D06"


def test_changing_document_changes_answer(run_case):
    output, _ = run_case(
        "08-doc-updated",
        data_dir=ROOT / "examples" / "08-doc-updated" / "data",
    )
    assert output["answer_status"] == "answered"
    assert "30 天" in output["answer"]
    assert "14 天" not in output["answer"]


def test_invalid_citation_is_rejected(tmp_path):
    request = QARequest.from_dict({"request_id": "T-1", "question": "企业版试用期多久？"})
    store = DocStore.load(ROOT / "data")
    session = Session(request=request, store=store, state_dir=tmp_path, now=__import__("datetime").datetime.now())
    registry = build_tools(session)
    registry.execute("search_docs", {"query": "企业版试用期"})
    registry.execute("read_doc", {"doc_id": "D03"})
    result = registry.execute(
        "finish",
        {
            "status": "answered",
            "answer": "14 天",
            "citations": [{"doc_id": "D03", "quote": "这句话不在原文里"}],
        },
    )
    assert result.ok is False
    assert result.code == "INVALID_CITATION"


def test_unresolved_conflict_blocks_answered_status(tmp_path):
    request = QARequest.from_dict({"request_id": "T-2", "question": "报销期限多久？"})
    store = DocStore.load(ROOT / "data")
    session = Session(request=request, store=store, state_dir=tmp_path, now=__import__("datetime").datetime.now())
    registry = build_tools(session)
    registry.execute("search_docs", {"query": "报销期限"})
    registry.execute("read_doc", {"doc_id": "D01"})
    registry.execute("read_doc", {"doc_id": "D02"})
    result = registry.execute(
        "finish",
        {
            "status": "answered",
            "answer": "15 天",
            "citations": [
                {"doc_id": "D02", "quote": "报销申请须在费用发生后 15 天内提交，逾期不予受理。"}
            ],
        },
    )
    assert result.ok is False
    assert result.code == "UNRESOLVED_CONFLICT"


def test_single_policy_answers_without_manufacturing_conflict(run_case):
    output, _ = run_case("10-single-policy")
    assert output["answer_status"] == "answered"
    assert [item["doc_id"] for item in output["citations"]] == ["D07"]
    assert output["conflict"]["detected"] is False
    assert "2 小时" in output["answer"]
