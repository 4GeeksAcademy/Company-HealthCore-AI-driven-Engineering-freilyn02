"""Compliance rules are applied in code: BAA for US, DPA + UK GDPR for UK, PHI flag."""
from data.pipelines.rfp_intake import llm
from data.pipelines.rfp_intake.agents.workers import failed_result, run_worker


def fake_llm(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {"key_aspects": ["model aspect"], "open_questions": []})


def test_us_client_requires_a_baa(monkeypatch):
    fake_llm(monkeypatch)
    result = run_worker("compliance", {"client_country": "US"}, "ctx")
    assert any("Business Associate Agreement" in a for a in result["key_aspects"])
    assert not any("UK GDPR" in a for a in result["key_aspects"])


def test_uk_client_requires_a_dpa_referencing_uk_gdpr(monkeypatch):
    fake_llm(monkeypatch)
    result = run_worker("compliance", {"client_country": "UK"}, "ctx")
    assert any("Data Processing Agreement" in a and "UK GDPR" in a for a in result["key_aspects"])
    assert not any("Business Associate" in a for a in result["key_aspects"])


def test_missing_country_becomes_an_open_question_never_a_guess(monkeypatch):
    fake_llm(monkeypatch)
    result = run_worker("compliance", {"client_country": None}, "ctx")
    assert any("country" in q.lower() for q in result["open_questions"])
    assert not any("Business Associate" in a or "Data Processing" in a for a in result["key_aspects"])


def test_phi_detection_is_flagged_for_compliance_review(monkeypatch):
    fake_llm(monkeypatch)
    phi = {"contains_phi": True, "findings": {"patient_name": 1}}
    result = run_worker("compliance", {"client_country": "US"}, "ctx", phi=phi)
    assert any("PHI detected" in a and "human review" in a for a in result["key_aspects"])
    assert "Jane" not in str(result)


def test_other_departments_never_get_compliance_rules(monkeypatch):
    fake_llm(monkeypatch)
    result = run_worker("revenue", {"client_country": "US"}, "ctx")
    assert result["key_aspects"] == ["model aspect"]


def test_failed_compliance_worker_keeps_its_mandatory_rule():
    result = failed_result("compliance", "RuntimeError", {"client_country": "UK"}, None)
    assert result["failed"] is True
    assert any("UK GDPR" in a for a in result["key_aspects"])
