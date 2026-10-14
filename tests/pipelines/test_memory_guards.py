"""MEM-092: code-level guards against what the real model got wrong in the evidence run:
facts that add details the user never said, and replies that claim a save or promise a review."""

import json

import pytest

from agent.memory.audit import InMemoryAuditLog
from agent.memory.flow import propose
from agent.memory.grounding import FALLBACK_REPLY, scrub_reply, ungrounded_words
from agent.memory.proposal import InMemoryPendingStore
from agent.memory.turn import ProposedMemory, parse_turn

MESSAGE = "Correction: the late-cancellation and no-show fee in the United States is now 75 USD, not 50 USD."
GOOD_FACT = "The late-cancellation and no-show fee in the United States is 75 USD."
INVENTED_FACT = "HealthCore's late-cancellation and no-show fee for private-pay patients in the United States is 75 USD."


# ------------------------------------------------------------------ grounding
def test_a_fact_that_only_uses_the_users_words_is_grounded():
    assert ungrounded_words(GOOD_FACT, MESSAGE) == []


def test_a_fact_with_invented_details_is_not_grounded():
    missing = ungrounded_words(INVENTED_FACT, MESSAGE)
    assert {"private", "pay", "patients"} <= set(missing)


def test_an_invented_number_is_not_grounded():
    assert ungrounded_words("The late-cancellation and no-show fee in the United States is 90 USD.", MESSAGE) == ["90"]


def test_singular_and_plural_are_the_same_word():
    assert ungrounded_words("No-show fees apply.", "The no-show fee applies.") == []


# ------------------------------------------------------------------ scrubbing the reply
@pytest.mark.parametrize(
    "reply, expected",
    [
        ("Thank you for the correction. I have noted this update for review.", "Thank you for the correction."),
        ("Our records show 50 USD. This change will be reviewed by our team.", "Our records show 50 USD."),
        ("Thank you. I will use 75 USD as the current fee.", "Thank you."),
        ("I have noted this update.", FALLBACK_REPLY),
    ],
)
def test_false_claims_and_promises_are_removed(reply, expected):
    assert scrub_reply(reply) == expected


@pytest.mark.parametrize(
    "reply",
    [
        "Medicare patients are not charged a no-show fee.",
        "Our records show 50 USD, and we note your update that it is now 75 USD.",
        "Line one.\n- item A\n- item B",
    ],
)
def test_honest_replies_are_left_untouched(reply):
    assert scrub_reply(reply) == reply


def test_parse_turn_scrubs_the_reply_but_keeps_the_proposal():
    text = json.dumps({
        "reply": "Thanks. I have noted this for review.",
        "memory_proposal": {"fact": GOOD_FACT, "keys": ["fee"], "reason": "correction"},
    })
    turn = parse_turn(text)
    assert turn.reply == "Thanks."
    assert turn.memory_proposal.fact == GOOD_FACT


# ------------------------------------------------------------------ propose + grounding
def test_propose_discards_a_fact_that_adds_unstated_details_and_audits_it():
    pending, audit = InMemoryPendingStore(), InMemoryAuditLog()
    proposed = ProposedMemory(fact=INVENTED_FACT, keys=["fee"], reason="correction")
    assert propose("s1", proposed, MESSAGE, pending=pending, audit=audit, grounded_in=MESSAGE) is None
    assert pending.get("s1") is None
    record = audit.list()[0]
    assert record.decision == "policy_rejected" and "did not state" in record.reason and "private" in record.reason


def test_propose_accepts_a_grounded_fact():
    pending, audit = InMemoryPendingStore(), InMemoryAuditLog()
    proposed = ProposedMemory(fact=GOOD_FACT, keys=["fee"], reason="correction")
    question = propose("s1", proposed, MESSAGE, pending=pending, audit=audit, grounded_in=MESSAGE)
    assert GOOD_FACT in question and pending.get("s1").fact == GOOD_FACT
    assert [r.decision for r in audit.list()] == ["proposed"]
