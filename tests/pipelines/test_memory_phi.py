"""MEM-092: the HealthCore memory CONTEXT, as tests.

  - patient information (HIPAA / UK GDPR) NEVER enters memory, and a request to remember it
    is refused out loud, audited without the patient data, and never reaches the model;
  - the facts the CONTEXT calls worth remembering are accepted (staff names are fine);
  - consolidation re-checks every stored entry and deletes the ones that fail.

The model and retrieval are fakes; memory uses the in-memory backends (no Redis, no Qdrant).
"""

import json

import pytest

from agent import nodes, tracing
from agent.graph import run_agent
from agent.harness import observability
from agent.memory import llm, runtime
from agent.memory.audit import REDACTED, InMemoryAuditLog
from agent.memory.consolidate import consolidate
from agent.memory.flow import (
    PHI_NOTICE,
    propose,
    refuse_phi_request,
    resolve_pending,
    wants_to_remember,
)
from agent.memory.policy import (
    FRAMEWORK_COVERAGE,
    MEMORABLE_KINDS,
    PHI_CATEGORIES,
    SENSITIVE_PATTERNS,
    inspect,
    validate_fact,
)
from agent.memory.proposal import InMemoryPendingStore
from agent.memory.store import InMemoryMemoryStore, MemoryEntry
from agent.memory.turn import MEMORY_RULES, ProposedMemory

SESSION = "session-phi-01"
PHI_REQUEST = "Patient Johnson cancelled tomorrow's appointment, note that down."

# The three examples the CONTEXT says SHOULD generate a proposal (as the facts they become),
# plus the incident-pattern example.
MEMORABLE_FACTS = [
    "At the Manchester clinic, internal referrals now go through the coordinator before the specialist.",
    "The high no-show alert at the Austin clinic was caused by a road closure that week, not by a problem with the reminder programme.",
    "The weekly report for Diane Foster needs vacancies broken down by role, not just by clinic.",
    "The referral system fails on Monday mornings because of the overnight batch job.",
]


# ------------------------------------------------------------------ what IS worth remembering
@pytest.mark.parametrize("fact", MEMORABLE_FACTS)
def test_the_contexts_memorable_facts_pass_the_policy(fact):
    assert validate_fact(fact, ["clinic", "operations"]).allowed


def test_a_staff_members_name_is_allowed_in_a_presentation_preference():
    assert inspect(MEMORABLE_FACTS[2]).violation is None


def test_the_three_memorable_kinds_come_from_the_context():
    assert set(MEMORABLE_KINDS) == {
        "clinic_operational_correction", "incident_pattern", "staff_presentation_preference",
    }


# ------------------------------------------------------------------ what must NEVER enter memory
@pytest.mark.parametrize(
    "text, category",
    [
        ("Patient Johnson cancelled tomorrow's appointment.", "patient_name"),
        ("Patient John Smith has an open balance.", "patient_name"),
        ("The patient's name is on the referral form.", "patient_name"),
        ("A patient named Maria missed the visit.", "patient_name"),
        ("Pt Garcia was moved to Tuesday.", "patient_name"),
        ("The record for MRN 4471 is wrong.", "medical_record"),
        ("Patient #5521 failed the referral.", "medical_record"),
        ("Her date of birth is in the system.", "date_of_birth"),
        ("The insurance number is AB-4455.", "insurance_id"),
        ("Medicare ID 1EG4 was rejected.", "insurance_id"),
        ("The NHS number 943 476 5919 was rejected.", "nhs_number"),
        ("National Insurance AB 12 34 56 C was used.", "national_insurance"),
        ("She was diagnosed last week.", "clinical_content"),
        ("The lab results for that visit were normal.", "clinical_content"),
        ("The clinical notes mention a new prescription.", "clinical_content"),
        ("Her blood pressure reading was high.", "clinical_content"),
        ("The patient has diabetes and needs a longer slot.", "patient_condition"),
        ("The patient lives at 12 Baker Street.", "patient_address"),
        ("The patient arrived on 12/03/2026 for a check.", "patient_date"),
        ("Call 305-555-0142 for approvals.", "phone"),
        ("Contact jane.doe@example.com for refunds.", "email"),
    ],
)
def test_patient_information_is_rejected_and_marked_as_phi(text, category):
    result = validate_fact(text)
    assert result.allowed is False
    assert result.reason == f"forbidden:{category}"
    assert result.sensitive is True and result.phi is True


def test_credentials_are_rejected_but_are_not_patient_information():
    result = validate_fact("The api key for the billing system is abc123.")
    assert result.allowed is False and result.sensitive is True and result.phi is False


@pytest.mark.parametrize(
    "text",
    [
        "Patient Safety reviews every incident on Mondays.",
        "Patient Portal logins fail after the overnight batch job.",
        "Patient no-show alerts are sent at 8am.",
        "Patients are asked to arrive 10 minutes early at the Austin clinic.",
        "Medicare patients are not charged a no-show fee.",
        "No-show fees do not apply to Medicare patients.",
        "A patient cancelled and the slot was reassigned.",
    ],
)
def test_ordinary_operational_sentences_are_not_blocked(text):
    assert validate_fact(text).allowed


def test_the_keywords_of_a_proposal_must_pass_the_policy_too():
    result = validate_fact("Referrals go through the coordinator.", ["Patient Johnson", "referral"])
    assert result.allowed is False and result.reason == "key_forbidden:patient_name" and result.phi


# ------------------------------------------------------------------ HIPAA and UK GDPR coverage
def test_every_rule_is_mapped_to_both_frameworks():
    assert set(FRAMEWORK_COVERAGE) == set(SENSITIVE_PATTERNS)
    for category in PHI_CATEGORIES:
        assert "HIPAA" in FRAMEWORK_COVERAGE[category] and "UK GDPR" in FRAMEWORK_COVERAGE[category]


# ------------------------------------------------------------------ refusing out loud
@pytest.mark.parametrize(
    "message, expected",
    [
        (PHI_REQUEST, True),
        ("Please remember this.", True),
        ("Keep that in mind for next week.", True),
        ("Don't forget that the Austin clinic closes at 5.", True),
        ("Can you save that?", True),
        ("What's this week's no-show rate?", False),
        ("Thanks, that settles my report.", False),
    ],
)
def test_wants_to_remember(message, expected):
    assert wants_to_remember(message) is expected


def test_a_request_to_remember_a_patient_is_refused_audited_and_redacted():
    audit = InMemoryAuditLog()
    notice = refuse_phi_request(SESSION, PHI_REQUEST, audit=audit)
    assert notice == PHI_NOTICE
    assert "HIPAA" in notice and "UK GDPR" in notice and "Nothing was saved" in notice
    [record] = audit.list()
    assert record.decision == "policy_rejected" and record.written is False
    assert "forbidden:patient_name" in record.reason
    assert record.user_message == REDACTED
    assert "Johnson" not in json.dumps(record.__dict__)  # the patient name never reaches the log


def test_no_refusal_when_there_is_no_patient_information():
    audit = InMemoryAuditLog()
    message = "Please remember that internal referrals at Manchester go through the coordinator first."
    assert refuse_phi_request(SESSION, message, audit=audit) is None and audit.list() == []


def test_no_refusal_when_nobody_asks_to_remember():
    audit = InMemoryAuditLog()
    assert refuse_phi_request(SESSION, "What is the status for Patient Johnson?", audit=audit) is None
    assert audit.list() == []


def test_resolve_pending_refuses_the_request_and_passes_nothing_on():
    store, pending, audit = InMemoryMemoryStore(), InMemoryPendingStore(), InMemoryAuditLog()
    result = resolve_pending(SESSION, PHI_REQUEST, pending=pending, store=store, audit=audit)
    assert result.decision == "phi_refused" and result.question == "" and result.notice == PHI_NOTICE
    assert store.list() == [] and pending.get(SESSION) is None


def test_a_patient_request_that_answers_a_pending_proposal_discards_it_and_is_refused(monkeypatch):
    store, pending, audit = InMemoryMemoryStore(), InMemoryPendingStore(), InMemoryAuditLog()
    fact = "Internal referrals at Manchester go through the coordinator first."
    propose(SESSION, ProposedMemory(fact=fact, keys=["referrals"], reason="fix"), "m", pending=pending, audit=audit)
    monkeypatch.setattr(llm, "chat_text", lambda *a, **k: pytest.fail("the classifier must not see patient data"))
    result = resolve_pending(SESSION, PHI_REQUEST, pending=pending, store=store, audit=audit)
    assert result.decision == "phi_refused" and result.question == ""
    assert store.list() == [] and pending.get(SESSION) is None
    assert [r.decision for r in audit.list()] == ["proposed", "unclear", "policy_rejected"]


def test_a_model_proposal_that_contains_a_patient_is_never_pending():
    pending, audit = InMemoryPendingStore(), InMemoryAuditLog()
    proposed = ProposedMemory(fact="Patient Johnson cancelled tomorrow's appointment.", keys=["x"], reason="r")
    assert propose(SESSION, proposed, PHI_REQUEST, pending=pending, audit=audit) is None
    assert pending.get(SESSION) is None
    [record] = audit.list()
    assert record.decision == "policy_rejected" and record.proposed_fact == REDACTED


def test_the_prompt_tells_the_model_about_patients_and_the_three_kinds():
    assert "ABSOLUTELY NEVER propose anything that contains or is about a patient" in MEMORY_RULES
    assert "staff member" in MEMORY_RULES and "incident pattern" in MEMORY_RULES


# ------------------------------------------------------------------ consolidation re-checks the PHI
def test_consolidation_deletes_stored_entries_that_fail_the_policy_today():
    store = InMemoryMemoryStore()
    good = MemoryEntry.new(MEMORABLE_FACTS[0], ["manchester", "referrals"], "mem-1")
    bad = MemoryEntry.new("Patient Johnson cancelled tomorrow's appointment.", ["cancellation"], "mem-2")
    bad_key = MemoryEntry.new("Referrals go through the coordinator.", ["Patient Johnson"], "mem-3")
    for entry in (good, bad, bad_key):
        store.write(entry)

    report = consolidate(store)

    assert sorted(report.policy_removed) == sorted([(bad.id, "forbidden:patient_name"),
                                                    (bad_key.id, "key_forbidden:patient_name")])
    assert [e.id for e in store.list()] == [good.id]
    assert report.kept == 1


# ------------------------------------------------------------------ end to end (run_agent)
CHUNKS = [{"text": "Internal referrals are handled by the specialist.", "score": 0.9}]


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACE_DIR", tmp_path)
    monkeypatch.setattr(nodes, "retrieve", lambda question: CHUNKS)
    monkeypatch.setattr(nodes, "casual_reply", lambda question: "Sure.")
    observability.reset()
    backends = runtime.use_in_memory()
    queue, calls = [], []

    def fake(messages, temperature=0.0, timeout=60.0):
        calls.append(messages)
        item = queue.pop(0)
        return item if isinstance(item, str) else json.dumps(item)

    monkeypatch.setattr(llm, "chat_text", fake)
    yield backends, queue, calls
    observability.reset()
    runtime.use_in_memory()


def test_agent_refuses_to_remember_a_patient_and_never_calls_the_model(agent_env):
    (store, pending, audit), _, calls = agent_env
    _, state = run_agent(PHI_REQUEST, session_id=SESSION)
    assert PHI_NOTICE in state["answer"]
    assert calls == [] and store.list() == [] and pending.get(SESSION) is None
    assert [r.decision for r in audit.list()] == ["policy_rejected"]
    assert "Johnson" not in json.dumps([r.__dict__ for r in audit.list()])


def test_agent_explains_when_the_model_itself_proposes_patient_information(agent_env):
    (store, pending, audit), queue, _ = agent_env
    queue.append({
        "reply": "Thanks for letting me know.",
        "memory_proposal": {"fact": "Patient Johnson had a failed referral on Monday.", "keys": ["referral"], "reason": "r"},
    })
    _, state = run_agent("Referrals fail on Monday mornings and Patient Johnson had one.", session_id=SESSION)
    assert "Thanks for letting me know." in state["answer"] and PHI_NOTICE in state["answer"]
    assert store.list() == [] and pending.get(SESSION) is None
    assert [r.decision for r in audit.list()] == ["policy_rejected"]


def test_agent_accepts_a_de_identified_pattern_from_a_message_that_mentions_a_patient(agent_env):
    (store, pending, audit), queue, _ = agent_env
    fact = "Referrals fail on Monday mornings."
    queue.append({"reply": "Thanks.", "memory_proposal": {"fact": fact, "keys": ["referrals", "monday"], "reason": "r"}})
    _, state = run_agent("Referrals fail on Monday mornings and Patient Johnson had one.", session_id=SESSION)
    assert fact in state["answer"] and PHI_NOTICE not in state["answer"]
    assert pending.get(SESSION).fact == fact
    assert "Johnson" not in json.dumps([r.__dict__ for r in audit.list()])  # message redacted in the audit
