"""Orchestrator tests: compliance is mandatory and the plan survives model failures."""
from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_intake.agents.orchestrator import plan_workstreams
from data.pipelines.rfp_intake.config import DEPARTMENTS

DOC = "# RFP\nOn-site occupational health for 800 employees. Budget USD 500,000."


def fake_llm(monkeypatch, payload=None, error=None):
    def _fake(system, user, **kwargs):
        if error:
            raise error
        return payload

    monkeypatch.setattr(llm, "chat_json", _fake)


def test_compliance_is_added_when_the_model_forgets_it(monkeypatch):
    fake_llm(monkeypatch, {"workstreams": [{"department": "revenue", "section_refs": ["Pricing"], "prompt_context": "budget"}]})
    workstreams, unknown = plan_workstreams(DOC, {})
    departments = [w["department"] for w in workstreams]
    assert departments == ["revenue", "compliance"]
    assert next(w for w in workstreams if w["department"] == "compliance")["prompt_context"]
    assert unknown == []


def test_model_failure_falls_back_to_every_department(monkeypatch):
    fake_llm(monkeypatch, error=llm.LLMError("down"))
    workstreams, _ = plan_workstreams(DOC, {})
    assert {w["department"] for w in workstreams} == set(DEPARTMENTS)


def test_unknown_departments_are_reported_and_never_run(monkeypatch):
    fake_llm(monkeypatch, {"workstreams": [
        {"department": "marketing", "section_refs": [], "prompt_context": "x"},
        {"department": "clinical", "section_refs": [], "prompt_context": "y"},
    ]})
    workstreams, unknown = plan_workstreams(DOC, {})
    assert unknown == ["marketing"]
    assert "marketing" not in {w["department"] for w in workstreams}
    assert "compliance" in {w["department"] for w in workstreams}


def test_duplicate_departments_are_ignored(monkeypatch):
    fake_llm(monkeypatch, {"workstreams": [
        {"department": "clinical", "section_refs": [], "prompt_context": "a"},
        {"department": "clinical", "section_refs": [], "prompt_context": "b"},
    ]})
    workstreams, _ = plan_workstreams(DOC, {})
    assert [w["department"] for w in workstreams].count("clinical") == 1
