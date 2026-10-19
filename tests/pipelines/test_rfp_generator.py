"""Unit tests for the department generators. The LLM is faked: no network."""
import pytest

from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_response import generators

from .rfp_helpers import make_handoff


def fake_llm(monkeypatch, payload):
    calls = []

    def _fake(system, user, **kwargs):
        calls.append({"system": system, "user": user})
        return payload

    monkeypatch.setattr(llm, "chat_json", _fake)
    return calls


def test_generator_returns_the_markdown_section(monkeypatch):
    fake_llm(monkeypatch, {"content": "## Revenue Cycle\nAll amounts are in USD."})
    content = generators.generate_section("revenue", make_handoff())
    assert content.startswith("## Revenue Cycle")


def test_prompt_uses_the_handoff_currency_and_forbids_inventing(monkeypatch):
    calls = fake_llm(monkeypatch, {"content": "## Revenue Cycle\ntext"})
    generators.generate_section("revenue", make_handoff(country="UK", currency="GBP"))
    assert "GBP" in calls[0]["system"]
    assert "NEVER invent" in calls[0]["system"]
    assert "<rfp_findings>" in calls[0]["user"]


def test_compliance_generator_gets_the_legal_instrument(monkeypatch):
    calls = fake_llm(monkeypatch, {"content": "## Compliance\ntext"})
    generators.generate_section("compliance", make_handoff("compliance", "US", "USD"))
    assert "Business Associate Agreement" in calls[0]["system"]


def test_feedback_and_previous_draft_are_sent_on_regeneration(monkeypatch):
    calls = fake_llm(monkeypatch, {"content": "## Revenue Cycle\nfixed"})
    generators.generate_section(
        "revenue", make_handoff(), feedback="Compliance [X]: add the currency", previous_draft="old draft"
    )
    assert "<evaluator_feedback>" in calls[0]["user"]
    assert "add the currency" in calls[0]["user"]
    assert "old draft" in calls[0]["user"]


def test_empty_draft_raises(monkeypatch):
    fake_llm(monkeypatch, {"content": "   "})
    with pytest.raises(ValueError):
        generators.generate_section("revenue", make_handoff())


def test_unknown_department_raises_without_calling_the_llm(monkeypatch):
    calls = fake_llm(monkeypatch, {})
    with pytest.raises(ValueError):
        generators.generate_section("not_a_department", make_handoff())
    assert calls == []
