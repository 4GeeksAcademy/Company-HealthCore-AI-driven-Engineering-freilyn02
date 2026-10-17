"""Unit tests for the bounded generator <-> evaluator loop. Everything is faked."""
from data.pipelines.rfp_response import evaluators, generators
from data.pipelines.rfp_response.loop import run_section_loop

from .rfp_helpers import make_handoff


def evaluation(passed: bool, feedback: str = "") -> dict:
    return {
        "section_id": "revenue",
        "department_id": "revenue",
        "readability": {"pass": True, "score": 8.0, "details": {}},
        "relevance": {"pass": passed, "missing_aspects": [] if passed else ["Pricing"]},
        "compliance": {"pass": True, "rule_ids": [], "violations": []},
        "overall_pass": passed,
        "feedback_for_generator": feedback,
    }


def test_passes_on_the_first_iteration(monkeypatch):
    monkeypatch.setattr(generators, "generate_section", lambda d, h, feedback=None, previous_draft=None: "draft v1")
    monkeypatch.setattr(evaluators, "evaluate_section", lambda d, c, h: evaluation(True))
    result = run_section_loop("revenue", make_handoff())
    assert result["iterations"] == 1
    assert result["needs_human_review"] is False
    assert result["content"] == "draft v1"


def test_failure_goes_back_to_the_generator_with_feedback(monkeypatch):
    seen = []

    def gen(department, handoff, feedback=None, previous_draft=None):
        seen.append({"feedback": feedback, "previous": previous_draft})
        return f"draft v{len(seen)}"

    results = iter([evaluation(False, "Add the pricing"), evaluation(True)])
    monkeypatch.setattr(generators, "generate_section", gen)
    monkeypatch.setattr(evaluators, "evaluate_section", lambda d, c, h: next(results))

    result = run_section_loop("revenue", make_handoff())
    assert seen[0] == {"feedback": None, "previous": None}
    assert seen[1] == {"feedback": "Add the pricing", "previous": "draft v1"}
    assert result["iterations"] == 2
    assert result["needs_human_review"] is False


def test_iteration_limit_keeps_the_last_draft_and_flags_review(monkeypatch):
    calls = []

    def gen(department, handoff, feedback=None, previous_draft=None):
        calls.append(1)
        return f"draft v{len(calls)}"

    monkeypatch.setattr(generators, "generate_section", gen)
    monkeypatch.setattr(evaluators, "evaluate_section", lambda d, c, h: evaluation(False, "Still missing pricing"))

    result = run_section_loop("revenue", make_handoff(), max_iterations=2)
    assert len(calls) == 2  # hard limit
    assert result["needs_human_review"] is True
    assert result["content"] == "draft v2"  # last draft is kept
    assert result["evaluation"]["overall_pass"] is False
    assert result["evaluation"]["iterations"] == 2


def test_a_failing_generator_does_not_crash_the_loop(monkeypatch):
    def boom(department, handoff, feedback=None, previous_draft=None):
        raise RuntimeError("llm down")

    monkeypatch.setattr(generators, "generate_section", boom)
    result = run_section_loop("revenue", make_handoff())
    assert result["needs_human_review"] is True
    assert result["content"] == ""
    assert "Generation failed" in result["evaluation"]["feedback_for_generator"]


def test_on_phase_reports_drafting_then_evaluating(monkeypatch):
    monkeypatch.setattr(generators, "generate_section", lambda d, h, feedback=None, previous_draft=None: "x")
    monkeypatch.setattr(evaluators, "evaluate_section", lambda d, c, h: evaluation(True))
    phases = []
    run_section_loop("revenue", make_handoff(), on_phase=lambda dept, phase: phases.append(phase))
    assert phases == ["drafting", "evaluating"]


def test_loop_stops_early_when_only_an_evaluator_is_unavailable(monkeypatch):
    calls = []

    def gen(department, handoff, feedback=None, previous_draft=None):
        calls.append(1)
        return "draft v1"

    def broken_evaluator(department, content, handoff):
        result = evaluation(False)
        result["evaluator_unavailable"] = True
        return result

    monkeypatch.setattr(generators, "generate_section", gen)
    monkeypatch.setattr(evaluators, "evaluate_section", broken_evaluator)

    result = run_section_loop("revenue", make_handoff(), max_iterations=3)
    assert len(calls) == 1  # regenerating cannot fix a broken evaluator
    assert result["needs_human_review"] is True
    assert result["content"] == "draft v1"
