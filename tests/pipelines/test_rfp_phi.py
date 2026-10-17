"""Unit tests for the deterministic PHI guard. All inputs are obviously synthetic."""
import json

from data.pipelines.rfp_intake.phi import redact_text, scan_and_redact, scrub_obj

CLEAN = (
    "Meridian Manufacturing (Austin, TX) requests a proposal for on-site occupational health "
    "for 800 employees. Patient experience metrics will be reported quarterly. "
    "Diagnostic imaging is out of scope. Contact: Jordan Lee."
)


def test_patient_name_and_diagnosis_are_redacted():
    text = "Case summary. Patient name: Jane Testpatient. Diagnosis: synthetic test condition. Please advise."
    clean, phi = scan_and_redact(text)
    assert "Testpatient" not in clean
    assert "synthetic test condition" not in clean
    assert phi["contains_phi"] is True
    assert phi["findings"]["patient_name"] == 1
    assert phi["findings"]["diagnosis"] == 1


def test_dob_mrn_ssn_and_nhs_number_are_redacted():
    text = "DOB: 04/12/1975. MRN: TP-448291. SSN 123-45-6789. NHS number: 943 476 5919."
    clean, phi = scan_and_redact(text)
    for leaked in ("04/12/1975", "TP-448291", "123-45-6789", "943 476 5919"):
        assert leaked not in clean
    assert set(phi["findings"]) == {"dob", "record_id", "ssn", "nhs_number"}


def test_person_described_by_age_is_redacted():
    clean, phi = scan_and_redact("Jane Testpatient, a 54-year-old employee, was treated last year.")
    assert "Testpatient" not in clean
    assert phi["findings"]["patient_name"] == 1


def test_clean_rfp_is_left_untouched():
    clean, phi = scan_and_redact(CLEAN)
    assert clean == CLEAN
    assert phi == {"contains_phi": False, "findings": {}}


def test_findings_never_contain_the_detected_values():
    _, phi = scan_and_redact("Patient name: Jane Testpatient. MRN: TP-448291.")
    dumped = json.dumps(phi)
    assert "Jane" not in dumped and "TP-448291" not in dumped


def test_redaction_is_idempotent():
    once = redact_text("Patient name: Jane Testpatient. Diagnosis: synthetic test condition.")
    assert redact_text(once) == once


def test_scrub_obj_cleans_nested_structures_and_keeps_other_types():
    data = {"a": ["Patient: Jane Testpatient"], "b": {"c": "ok"}, "n": 5, "flag": True}
    cleaned = scrub_obj(data)
    assert "Testpatient" not in json.dumps(cleaned)
    assert cleaned["b"] == {"c": "ok"} and cleaned["n"] == 5 and cleaned["flag"] is True
