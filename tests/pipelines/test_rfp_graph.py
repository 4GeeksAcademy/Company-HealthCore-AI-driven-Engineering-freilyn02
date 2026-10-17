"""Graph-level tests: PHI guard first, classifier is a hard gate, workers fan out.

All agents are faked: no network, no database, no real PDF.
"""
from pathlib import Path

from data.pipelines.rfp_intake import graph as graph_module
from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_intake.agents.classifier import ClassifierResult
from data.pipelines.rfp_intake.config import DEPARTMENTS

DEPTS = list(DEPARTMENTS)  # revenue, clinical, compliance
CLEAN_TEXT = "# Fake RFP\n" + "text " * 100
PHI_TEXT = (
    "# Fake RFP\nAttached case summary. Patient name: Jane Testpatient. "
    "Diagnosis: synthetic test condition. " + "text " * 100
)
US_FIELDS = {
    "client_name": "Acme", "client_country": "US", "program_type": "occupational_health",
    "covered_population": 100, "deadline": None, "budget_range": None,
}


def _patch_common(monkeypatch, is_rfp, text=CLEAN_TEXT):
    seen = {}
    monkeypatch.setattr(graph_module, "pdf_to_markdown", lambda p: text)

    def fake_write(path, content):
        seen["written"] = content
        return Path("fake.md")

    def fake_classify(markdown):
        seen["classified"] = markdown
        return ClassifierResult(
            is_rfp=is_rfp, confidence=0.9, reason="test", detected_departments=DEPTS if is_rfp else []
        )

    monkeypatch.setattr(graph_module, "write_markdown", fake_write)
    monkeypatch.setattr(graph_module, "readability_scores", lambda m: {"available": True, "complexity": "low"})
    monkeypatch.setattr(graph_module, "classify_rfp", fake_classify)
    monkeypatch.setattr(graph_module, "extract_rfp_metadata", lambda m: dict(US_FIELDS))
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {"summary": "ok"})
    return seen


def _boom(*args, **kwargs):
    raise AssertionError("must not be called")


def _fake_plan(markdown, metadata):
    return [{"department": d, "section_refs": [], "prompt_context": "ctx"} for d in DEPTS], []


def _fake_worker(department, metadata, context, phi=None):
    return {
        "department": department,
        "key_aspects": [f"{department} aspect"],
        "open_questions": [],
        "suggested_contact_role": "role",
        "failed": False,
    }


def test_non_rfp_stops_before_the_orchestrator(monkeypatch):
    _patch_common(monkeypatch, is_rfp=False)
    monkeypatch.setattr(graph_module, "plan_workstreams", _boom)
    monkeypatch.setattr(graph_module, "run_worker", _boom)

    result = graph_module.run_intake("x.pdf")

    assert result["classification"]["is_rfp"] is False
    assert "synthesis" not in result
    assert not result.get("worker_results")


def test_rfp_runs_one_worker_per_workstream_and_synthesizes(monkeypatch):
    _patch_common(monkeypatch, is_rfp=True)
    monkeypatch.setattr(graph_module, "plan_workstreams", _fake_plan)
    monkeypatch.setattr(graph_module, "run_worker", _fake_worker)

    result = graph_module.run_intake("x.pdf")

    departments = {d["department"] for d in result["synthesis"]["by_department"]}
    assert departments == set(DEPTS)
    assert result["synthesis"]["summary"] == "ok"
    assert result["synthesis"]["currency"] == "USD"  # decided by client_country, not by the model
    assert result["synthesis"]["requires_compliance_review"] is False


def test_phi_is_redacted_before_any_agent_or_file_sees_it(monkeypatch):
    seen = _patch_common(monkeypatch, is_rfp=True, text=PHI_TEXT)
    monkeypatch.setattr(graph_module, "plan_workstreams", _fake_plan)
    monkeypatch.setattr(graph_module, "run_worker", _fake_worker)

    result = graph_module.run_intake("x.pdf")

    assert "Testpatient" not in seen["classified"]
    assert "synthetic test condition" not in seen["classified"]
    assert "Testpatient" not in seen["written"]  # the .md artifact is redacted too
    assert result["phi"]["contains_phi"] is True
    assert result["synthesis"]["requires_compliance_review"] is True
    assert "phi_detected" in result["synthesis"]["compliance_flags"]


def test_one_failing_worker_does_not_kill_the_ticket(monkeypatch):
    _patch_common(monkeypatch, is_rfp=True)
    monkeypatch.setattr(graph_module, "plan_workstreams", _fake_plan)

    def flaky_worker(department, metadata, context, phi=None):
        if department in ("revenue", "compliance"):
            raise RuntimeError("LLM down")
        return _fake_worker(department, metadata, context, phi)

    monkeypatch.setattr(graph_module, "run_worker", flaky_worker)

    result = graph_module.run_intake("x.pdf")

    by_dept = {d["department"]: d for d in result["synthesis"]["by_department"]}
    assert by_dept["revenue"]["failed"] is True
    assert by_dept["clinical"]["failed"] is False
    # Compliance keeps its mandatory rule even when its worker fails (US client -> BAA).
    assert by_dept["compliance"]["failed"] is True
    assert any("Business Associate Agreement" in need for need in by_dept["compliance"]["needs"])
