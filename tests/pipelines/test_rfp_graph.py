"""Graph-level tests: the classifier is a hard gate and workers fan out.

All agents are faked: no network, no database, no real PDF.
"""
from pathlib import Path

from data.pipelines.rfp_intake import graph as graph_module
from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_intake.agents.classifier import ClassifierResult
from data.pipelines.rfp_intake.config import DEPARTMENTS

DEPTS = list(DEPARTMENTS)[:2]


def _patch_common(monkeypatch, is_rfp):
    monkeypatch.setattr(graph_module, "pdf_to_markdown", lambda p: ("# Fake RFP\n" + "text " * 100, Path("fake.md")))
    monkeypatch.setattr(graph_module, "readability_scores", lambda m: {"available": True, "complexity": "low"})
    monkeypatch.setattr(
        graph_module,
        "classify_rfp",
        lambda m: ClassifierResult(
            is_rfp=is_rfp, confidence=0.9, reason="test", detected_departments=DEPTS if is_rfp else []
        ),
    )
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {"summary": "ok"})


def _boom(*args, **kwargs):
    raise AssertionError("must not be called")


def test_non_rfp_stops_before_the_orchestrator(monkeypatch):
    _patch_common(monkeypatch, is_rfp=False)
    monkeypatch.setattr(graph_module, "plan_workstreams", _boom)
    monkeypatch.setattr(graph_module, "run_worker", _boom)

    result = graph_module.run_intake("x.pdf")

    assert result["classification"]["is_rfp"] is False
    assert "synthesis" not in result
    assert not result.get("worker_results")


def _fake_plan(markdown, metadata):
    return [{"department": d, "section_refs": [], "prompt_context": "ctx"} for d in DEPTS], []


def _fake_worker(department, metadata, context):
    return {
        "department": department,
        "key_aspects": [f"{department} aspect"],
        "open_questions": [],
        "suggested_contact_role": "role",
        "failed": False,
    }


def test_rfp_runs_one_worker_per_workstream_and_synthesizes(monkeypatch):
    _patch_common(monkeypatch, is_rfp=True)
    monkeypatch.setattr(graph_module, "plan_workstreams", _fake_plan)
    monkeypatch.setattr(graph_module, "run_worker", _fake_worker)

    result = graph_module.run_intake("x.pdf")

    departments = {d["department"] for d in result["synthesis"]["by_department"]}
    assert departments == set(DEPTS)
    assert result["synthesis"]["summary"] == "ok"


def test_one_failing_worker_does_not_kill_the_ticket(monkeypatch):
    _patch_common(monkeypatch, is_rfp=True)
    monkeypatch.setattr(graph_module, "plan_workstreams", _fake_plan)

    def flaky_worker(department, metadata, context):
        if department == DEPTS[0]:
            raise RuntimeError("LLM down")
        return _fake_worker(department, metadata, context)

    monkeypatch.setattr(graph_module, "run_worker", flaky_worker)

    result = graph_module.run_intake("x.pdf")

    by_dept = {d["department"]: d for d in result["synthesis"]["by_department"]}
    assert by_dept[DEPTS[0]]["failed"] is True
    assert by_dept[DEPTS[1]]["failed"] is False
