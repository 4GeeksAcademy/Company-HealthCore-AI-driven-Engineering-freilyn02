"""Bounded generator <-> evaluators loop for ONE department section.

    generate -> evaluate (3 in parallel) --pass--> done
                    +--fail + feedback--> generate again ... up to max_iterations

If the limit is exhausted the LAST draft and its EvaluationResult are kept and the
section is flagged `needs_human_review`. It is never dropped.
"""
from typing import Any, Callable

from . import evaluators, generators
from .config import MAX_ITERATIONS


def _failed_evaluation(department: str, message: str) -> dict[str, Any]:
    return {
        "section_id": department,
        "department_id": department,
        "readability": {"pass": False, "score": None, "details": {"message": message}},
        "relevance": {"pass": False, "missing_aspects": []},
        "compliance": {"pass": False, "rule_ids": [], "violations": [message]},
        "overall_pass": False,
        "feedback_for_generator": message,
    }


def run_section_loop(
    department: str,
    handoff: dict[str, Any],
    *,
    max_iterations: int = MAX_ITERATIONS,
    on_phase: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    draft = ""
    evaluation: dict[str, Any] | None = None
    feedback: str | None = None
    failure: str | None = None
    iterations = 0

    for _ in range(max_iterations):
        iterations += 1
        if on_phase:
            on_phase(department, "drafting")
        try:
            draft = generators.generate_section(
                department, handoff, feedback=feedback, previous_draft=draft or None
            )
        except Exception as exc:  # a failing generator must not kill the ticket
            failure = f"Generation failed ({type(exc).__name__}): needs manual review."
            break

        if on_phase:
            on_phase(department, "evaluating")
        evaluation = evaluators.evaluate_section(department, draft, handoff)
        if evaluation["overall_pass"]:
            evaluation["iterations"] = iterations
            return {
                "department": department,
                "content": draft,
                "evaluation": evaluation,
                "iterations": iterations,
                "needs_human_review": False,
            }
        feedback = evaluation["feedback_for_generator"]

    if evaluation is None:
        evaluation = _failed_evaluation(department, failure or "No evaluation was produced.")
    evaluation["iterations"] = iterations
    return {
        "department": department,
        "content": draft,
        "evaluation": evaluation,
        "iterations": iterations,
        "needs_human_review": True,
    }
