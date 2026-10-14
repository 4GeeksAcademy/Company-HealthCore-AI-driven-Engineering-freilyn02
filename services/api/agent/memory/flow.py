"""The two operations of the memory flow (MEM-092):

  propose()          validate -> keep ONE pending proposal -> audit -> return the question
  resolve_pending()  classify the user's answer -> write ONLY if approved/edited -> audit

Nothing is written to memory unless resolve_pending() sees an explicit, classified approval
(or an edit that passes the memory policy again).

HealthCore rule: when a user asks the agent to remember patient or personal health information,
the request is REFUSED OUT LOUD (PHI_NOTICE explains why) and audited. It is never ignored
silently, and the message never reaches the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from . import confirm
from .audit import AuditLog
from .grounding import ungrounded_words
from .policy import inspect, validate_fact
from .proposal import MemoryProposal, PendingStore, audit_record, get_active_or_expire
from .store import MemoryEntry, MemoryStore
from .turn import ProposedMemory

PROPOSAL_QUESTION = (
    'Would you like me to remember this for next time? "{fact}" '
    "(Reply yes or no, or tell me how to change it.)"
)
SAVED_NOTICE = 'Saved. I will remember: "{fact}"'
REJECTED_NOTICE = "Okay, I won't remember that."
NOT_SAVED_NOTICE = "I couldn't save that to memory because it doesn't meet the memory policy."
PHI_NOTICE = (
    "I can't remember that. It appears to contain patient or personal health information, and "
    "HealthCore's compliance rules (HIPAA in the US and UK GDPR in the UK) do not allow that in "
    "the agent's memory. Nothing was saved. I can remember operational facts that don't identify "
    "anyone, such as a change in a clinic's procedure or a recurring incident pattern. If you "
    "have another question, please ask it again without the patient details."
)
_REMEMBER_INTENT = re.compile(
    r"\b(?:remember|memori[sz]e|note\s+(?:that|this|it)\b|note\s+down|write\s+(?:that|this|it)\s+down|"
    r"make\s+a\s+note|keep\s+(?:that|this|it)\s+in\s+mind|keep\s+track|don'?t\s+forget|do\s+not\s+forget|"
    r"(?:save|store|log|record|add)\s+(?:that|this|it)\b|add\s+(?:that|this|it)\s+to\s+(?:your\s+)?(?:memory|notes))",
    re.IGNORECASE,
)
_MAX_AUDITED_FACT = 600


@dataclass
class ResolveResult:
    question: str  # what the rest of the agent must still answer ("" = nothing left)
    notice: str | None = None  # memory message to show the user
    decision: str | None = None  # approve | edit | reject | unclear | policy_rejected | phi_refused | None


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def _remaining(message: str, candidate: str | None) -> str:
    """The classifier may only COPY part of the user's message, never invent a question."""
    if not candidate or not candidate.strip():
        return ""
    return candidate.strip() if _squash(candidate) in _squash(message) else message


def wants_to_remember(message: str) -> bool:
    """True when the user asks the agent to remember / note down / save something."""
    return bool(_REMEMBER_INTENT.search(message or ""))


def is_phi(text: str) -> bool:
    """True when the text contains patient or personal health information (HIPAA / UK GDPR)."""
    return inspect(text or "").phi


def refuse_phi_request(session_id: str, message: str, *, audit: AuditLog,
                       now: datetime | None = None) -> str | None:
    """If the user asks to remember something that contains patient information, refuse it
    explicitly. Returns the explanation for the user, or None when the message is fine.
    The audit record keeps the reason and the category, never the patient data itself."""
    if not wants_to_remember(message):
        return None
    inspection = inspect(message)
    if not (inspection.violation and inspection.phi):
        return None
    proposal = MemoryProposal.new(session_id, "(request to remember refused: no proposal created)", [],
                                  "", message, now=now)
    audit.append(audit_record(
        proposal, "policy_rejected", written=False, user_message=message,
        reason=f"request to remember patient or personal information ({inspection.violation})", now=now))
    return PHI_NOTICE


def resolve_pending(session_id: str, message: str, *, pending: PendingStore, store: MemoryStore,
                    audit: AuditLog, now: datetime | None = None) -> ResolveResult:
    """Resolve the pending proposal (if any); then refuse, out loud, any request to remember
    patient information. A refused message is NOT passed on: the model never sees it."""
    result = _resolve_pending(session_id, message, pending=pending, store=store, audit=audit, now=now)
    if not result.question.strip():
        return result
    refusal = refuse_phi_request(session_id, result.question, audit=audit, now=now)
    if refusal is None:
        return result
    notice = f"{result.notice}\n\n{refusal}" if result.notice else refusal
    return ResolveResult(question="", notice=notice, decision="phi_refused")


def _resolve_pending(session_id: str, message: str, *, pending: PendingStore, store: MemoryStore,
                     audit: AuditLog, now: datetime | None = None) -> ResolveResult:
    proposal = get_active_or_expire(pending, audit, session_id, now=now)
    if proposal is None:
        return ResolveResult(question=message)  # nothing pending: normal turn

    result = confirm.classify(proposal, message)
    pending.clear(session_id)  # exactly one resolution per proposal

    if result.decision == "unclear":
        audit.append(audit_record(proposal, "unclear", written=False, user_message=message,
                                  reason="ambiguous answer or topic change: discarded by default", now=now))
        return ResolveResult(question=message, decision="unclear")

    remaining = _remaining(message, result.remaining_question)

    if result.decision == "reject":
        audit.append(audit_record(proposal, "reject", written=False, user_message=message, now=now))
        return ResolveResult(question=remaining, notice=REJECTED_NOTICE, decision="reject")

    fact = proposal.fact if result.decision == "approve" else (result.edited_fact or "").strip()
    check = validate_fact(fact, proposal.keys)  # defense in depth: re-check what is about to be stored
    if not check.allowed:
        audit.append(audit_record(proposal, "policy_rejected", written=False, user_message=message,
                                  reason=check.reason, now=now))
        return ResolveResult(question=remaining, notice=NOT_SAVED_NOTICE, decision="policy_rejected")

    store.write(MemoryEntry.new(fact, proposal.keys, proposal.proposal_id, now=now))
    audit.append(audit_record(
        proposal, result.decision, written=True, user_message=message,
        reason=None if result.decision == "approve" else f"edited to: {fact}", now=now,
    ))
    return ResolveResult(question=remaining, notice=SAVED_NOTICE.format(fact=fact), decision=result.decision)


def propose(session_id: str, proposed: ProposedMemory | None, source_message: str, *,
            pending: PendingStore, audit: AuditLog, now: datetime | None = None,
            grounded_in: str | None = None) -> str | None:
    """Returns the question to append to the reply, or None when nothing is proposed.

    grounded_in: when given, the fact may only use words that appear in this text (the user's
    message). A fact that adds details the user never said is discarded and audited."""
    if proposed is None:
        return None
    fact = proposed.fact.strip()
    check = validate_fact(fact, proposed.keys)
    proposal = MemoryProposal.new(session_id, fact[:_MAX_AUDITED_FACT], proposed.keys, proposed.reason,
                                  source_message, now=now)
    if not check.allowed:
        audit.append(audit_record(proposal, "policy_rejected", written=False, user_message=source_message,
                                  reason=check.reason, now=now))
        return None
    if grounded_in is not None:
        invented = ungrounded_words(fact, grounded_in)
        if invented:
            audit.append(audit_record(
                proposal, "policy_rejected", written=False, user_message=source_message,
                reason=f"fact adds details the user did not state: {', '.join(invented[:5])}", now=now))
            return None
    if not pending.set_if_empty(proposal):  # only ONE pending proposal at a time
        audit.append(audit_record(proposal, "policy_rejected", written=False, user_message=source_message,
                                  reason="another proposal is still pending", now=now))
        return None
    audit.append(audit_record(proposal, "proposed", written=False, user_message=source_message, now=now))
    return PROPOSAL_QUESTION.format(fact=fact)


def read_memories(question: str, store: MemoryStore, limit: int = 3) -> list[MemoryEntry]:
    """Explicit memory READ: relevant approved entries, with their usage counters updated."""
    return [store.touch(entry.id) or entry for entry in store.search(question, limit=limit)]
