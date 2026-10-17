"""Unit tests for the evaluators. The LLM is faked: no network."""
from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_response import config, evaluators
from data.pipelines.rfp_response.guidelines import check_guidelines

from .rfp_helpers import make_handoff

LONG_SIMPLE_TEXT = "The clinic will provide care to employees every week. " * 15  # ~150 words


def fake_llm(monkeypatch, payload):
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kwargs: payload)


def llm_down(monkeypatch):
    def boom(system, user, **kwargs):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "chat_json", boom)
    monkeypatch.setattr(config, "LLM_RETRY_BASE_DELAY", 0)  # no waiting in tests


# --- readability --------------------------------------------------------------
def test_readability_passes_for_simple_text():
    result = evaluators.evaluate_readability(LONG_SIMPLE_TEXT)
    assert result["pass"] is True
    assert result["score"] is not None


def test_readability_fails_when_grade_is_above_the_limit(monkeypatch):
    monkeypatch.setattr(config, "READABILITY_MAX_GRADE", 0.5)
    result = evaluators.evaluate_readability(LONG_SIMPLE_TEXT)
    assert result["pass"] is False
    assert "shorter sentences" in result["details"]["message"]


def test_readability_is_skipped_for_very_short_text():
    result = evaluators.evaluate_readability("Too short.")
    assert result["pass"] is True
    assert result["score"] is None


# --- relevance ---------------------------------------------------------------
def test_relevance_fails_with_missing_aspects(monkeypatch):
    fake_llm(monkeypatch, {"missing_aspects": ["Pricing per employee"]})
    result = evaluators.evaluate_relevance("some draft", make_handoff())
    assert result == {"pass": False, "missing_aspects": ["Pricing per employee"]}


def test_relevance_fails_closed_and_is_marked_unavailable_when_the_llm_is_down(monkeypatch):
    llm_down(monkeypatch)
    result = evaluators.evaluate_relevance("draft", make_handoff())
    assert result["pass"] is False
    assert result["unavailable"] is True
    assert "LLMError" in result["error"]


# --- compliance, anchored to the CONTEXT rules --------------------------------
def test_compliance_fails_on_wrong_currency_invented_figure_and_guarantee():
    handoff = make_handoff(country="UK", currency="GBP")
    draft = "## Revenue Cycle\nTotal price is $99,999, guaranteed."
    result = check_guidelines("revenue", draft, handoff)
    assert result["pass"] is False
    assert "GUIDELINE_CURRENCY_MATCHES_COUNTRY" in result["rule_ids"]
    assert "GUIDELINE_NO_INVENTED_FIGURES" in result["rule_ids"]
    assert "GUIDELINE_NO_UNVERIFIED_GUARANTEES" in result["rule_ids"]
    assert len(result["rule_ids"]) == len(result["violations"])


def test_compliance_passes_for_a_clean_revenue_draft():
    draft = "## Revenue Cycle\nPricing is quoted in USD. The budget range is 50,000-75,000."
    assert check_guidelines("revenue", draft, make_handoff())["pass"] is True


def test_us_compliance_section_needs_a_baa():
    handoff = make_handoff("compliance", "US", "USD")
    failing = check_guidelines("compliance", "## Compliance\nWe follow HIPAA.", handoff)
    assert failing["rule_ids"] == ["GUIDELINE_LEGAL_INSTRUMENT_BY_COUNTRY"]
    ok = check_guidelines("compliance", "## Compliance\nA Business Associate Agreement (BAA) applies.", handoff)
    assert ok["pass"] is True


def test_uk_compliance_section_needs_a_dpa_with_uk_gdpr():
    handoff = make_handoff("compliance", "UK", "GBP")
    ok = check_guidelines("compliance", "## Compliance\nA DPA under UK GDPR applies.", handoff)
    assert ok["pass"] is True


# --- the three evaluators merged ----------------------------------------------
def test_evaluate_section_passes_when_all_three_pass(monkeypatch):
    fake_llm(monkeypatch, {"missing_aspects": []})
    result = evaluators.evaluate_section("clinical", LONG_SIMPLE_TEXT, make_handoff("clinical"))
    assert result["overall_pass"] is True
    assert result["evaluator_unavailable"] is False
    assert result["feedback_for_generator"] == ""


def test_evaluate_section_fails_with_concrete_feedback(monkeypatch):
    fake_llm(monkeypatch, {"missing_aspects": ["Pricing per employee"]})
    handoff = make_handoff(country="UK", currency="GBP")
    result = evaluators.evaluate_section("revenue", "## Revenue Cycle\nPrice is $99,999.", handoff)
    assert result["overall_pass"] is False
    assert "Pricing per employee" in result["feedback_for_generator"]
    assert "GUIDELINE_CURRENCY_MATCHES_COUNTRY" in result["feedback_for_generator"]


def test_unavailable_evaluator_blocks_approval_but_gives_no_useless_feedback(monkeypatch):
    llm_down(monkeypatch)
    result = evaluators.evaluate_section("clinical", LONG_SIMPLE_TEXT, make_handoff("clinical"))
    assert result["overall_pass"] is False
    assert result["evaluator_unavailable"] is True
    assert result["feedback_for_generator"] == ""
