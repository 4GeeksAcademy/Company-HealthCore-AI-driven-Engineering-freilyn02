# Agent memory and self-improvement (MEM-092)

The HealthCore support agent remembers corrections across conversations, under strict
control: it **proposes** what to remember, the **user decides**, and every decision is
**audited**. This document explains the architecture, the design decisions, the evidence
and the known limits.

## 1. How it works

~~~
user message
   |
   v
memory_resolve   a proposal is pending? classify the message
                 approve / edit -> policy check -> write -> audit
                 reject / unclear -> discard -> audit
                 then: "remember this" + patient information? -> REFUSE out loud, audit,
                 and stop (the message never reaches the model)
   |
   v
input_guard -> memory_read -> route -> retrieve / tools -> answer (ONE structured model call)
   |
   v
memory_finalize  appends the "remember this?" question, keeps ONE pending proposal, audits "proposed";
                 a model proposal that contains patient information is dropped and explained
   |
   v
output_guard -> reply
~~~

- **Propose is not write.** Nothing reaches the store until a later user message is classified as
  an approval (or as an edit that passes the memory policy again).
- **Same conversation.** The question is appended to the agent's own reply.
- **One pending proposal per session.** While one is open, a second one is refused.
- **Silence or ambiguity is a rejection.** A topic change, a hedge ("maybe"), a classifier failure
  or an unanswered proposal (30 minutes) discards the proposal. It is never approved by default.
- **Explicit interface.** Memory is read and written through `MemoryStore`
  (`write`, `read`, `delete`, `list`, `search`, `touch`). It is never appended to the system prompt;
  approved memories reach the model as data in the user role, inside `<approved_memory>` tags.
- **Opt-in per conversation.** The client sends a `session_id` (8-64 chars) on every message of a
  conversation. Without it the agent behaves exactly as before.
- **Fails safe.** If the memory backend is down, the agent still answers (without memory) and
  nothing is written.

| Piece | File |
| --- | --- |
| Store (Redis / in-memory) | `services/api/agent/memory/store.py` |
| Pending proposal + audit records | `services/api/agent/memory/proposal.py` |
| Append-only audit log | `services/api/agent/memory/audit.py` |
| What may never be stored (HIPAA / UK GDPR rules) | `services/api/agent/memory/policy.py` |
| Code-level guards on proposals and replies | `services/api/agent/memory/grounding.py` |
| Reply + `memory_proposal` in one structured call | `services/api/agent/memory/turn.py` |
| Intent classifier (approve / reject / edit / unclear) | `services/api/agent/memory/confirm.py` |
| Propose / resolve flow + explicit refusal of patient information | `services/api/agent/memory/flow.py` |
| Cleanup policy | `services/api/agent/memory/consolidate.py`, `scripts/memory_consolidate.py` |
| Graph wiring | `services/api/agent/state.py`, `graph.py`, `nodes.py`, `services/api/routers/agent.py` |

## 2. Memory architecture and why

**Choice: episodic key-value memory in Redis** (one JSON entry per approved fact, with keywords),
in its own Redis database (`/1`) and key prefix (`agent_memory:`).

What the agent needs to remember is short, discrete company facts: a corrected fee, a corrected
SLA, a reusable resolution note. Each one is a sentence with a few keywords. Key-value storage
handles that well: cheap writes, exact deletes, simple expiry, and a retrieval that is easy to
explain and test.

| Option | Decision |
| --- | --- |
| Context window | Not enough: it disappears when the conversation ends. |
| Episodic key-value (Redis) | **Chosen.** Short facts, exact delete, TTL and caps, trivial to audit. |
| Vector database | Rejected for now. The memory is tiny (capped at 200 entries) and facts are short, so keyword matching is enough and easier to test. A vector index would add embedding cost and a second thing to keep consistent. |
| Knowledge graph | Rejected. Nothing here needs explicit relations (dependency, hierarchy). |
| Fine-tuning | Rejected. It cannot forget a single wrong fact, and it is slow and costly to update. |

**Never the company RAG.** Memory is not written to `healthcore_knowledge` or to any `*_knowledge`
collection. The RAG stays a read-only tool: mixing user-approved facts with curated documents would
break the retrieval evals and the poisoning controls. Redis DB `/1` is also separate from the Celery
queue on DB `/0`.

## 3. Design decisions

**What types of memory, and what was discarded?** Episodic facts only (see above). Vector and graph
memory were left out because the data is small and has no relational structure.

**What must never enter memory, whoever asks?** This comes straight from the HealthCore memory
CONTEXT. It is a compliance requirement with no exceptions, so it is enforced in code (`policy.py`),
not left to the model:

- **Any patient identifier:** name, medical record number, date of birth, diagnosis, insurance
  number, NHS or National Insurance number, a patient's address or dates, or any combination that
  could re-identify a person.
- **Any clinical content:** clinical notes, lab or test results, medication, symptoms, anything from a
  medical visit, even if the user mentions it while asking the agent to remember something else.
- Credentials, API keys and tokens.
- Live data (ticket status, stock levels, this week's no-show rate): it changes and has its own tools.
- Instructions to the agent disguised as facts ("from now on always answer in...").
- Opinions.

A **staff member's name is allowed** when it is part of an operational presentation preference
("the weekly report for Diane Foster needs vacancies by role"). That is not patient data.

The patient-information check runs **at every stage**, not only at the first one:

1. **Before the model sees the message:** if the user asks to remember something ("note that down",
   "remember this") and the message contains patient information, the agent **refuses out loud**:
   it explains that it cannot remember it and why (HIPAA and UK GDPR), says nothing was saved, and
   suggests what it can remember instead. The message is not sent to the model. The audit log records
   the refusal (`policy_rejected`) with the user message and the fact **redacted**.
2. **When the model proposes a fact:** every proposal is validated *before* the user sees it. If it
   contains patient information it is discarded, audited, and the user gets the same explanation.
   The prompt also tells the model to leave patients out and propose a de-identified pattern or nothing.
3. **When the user edits a proposal:** the edited fact is validated again before it is stored.
4. **When the memory is consolidated:** every stored entry is re-checked and deleted if it fails.
5. **The proposal keywords** are validated too, because they are stored and searched.

**How the validation covers both HIPAA (US) and UK GDPR (UK).** HealthCore operates under both at
the same time, so each rule in `policy.py` is mapped to both frameworks in `FRAMEWORK_COVERAGE`
(a test fails if a rule has no mapping):

| Rule | HIPAA (US) | UK GDPR (UK) |
| --- | --- | --- |
| `patient_name`, `patient_address`, `patient_date` | Identifiers: names, geographic data smaller than a state, dates related to an individual | Personal data of an identifiable person |
| `email`, `phone`, `ssn`, `long_number`, `medical_record`, `insurance_id`, `date_of_birth` | Identifiers: contact data, SSN, record, health plan and account numbers, dates | Personal data and identification numbers |
| `nhs_number`, `national_insurance` | "Any other unique identifier" | Identifiers linked to a person (NHS number, National Insurance number) |
| `clinical_content`, `patient_condition` | Protected health information | Special category data: health (Art. 9) |

The rule is the stricter of the two: if either framework would treat it as protected, it is blocked.
The same checks apply to US and UK clinics, so a UK-only identifier is blocked everywhere.

**How does the agent decide what to forget, and what happens to a pending proposal nobody answers?**

- A proposal not answered within 30 minutes is discarded. If the same conversation continues, the
  discard is audited as `timeout`. If the user never comes back, the audit keeps the `proposed`
  record without an outcome, and Redis deletes the pending key after 24 hours.
- Approved memories are cleaned by `scripts/memory_consolidate.py` (it has a `--dry-run` mode):
  0. **Re-check the policy** on every stored entry and **delete** any that contains patient
     information or other forbidden data (and audit the deletion without logging the text).
     Consolidation never rewrites or summarizes a fact, so it can never write new patient data.
  1. **Expire** entries not used for 90 days (stale facts are worse than none).
  2. **Supersede**: an older entry with the same keywords, or the same text, loses to the newer one.
  3. **Cap** at 200 entries, evicting the least used first. Redis runs with `noeviction`, so the cap is ours.

**How is poisoning prevented?**

- No write without an explicit, classified approval.
- The classifier reads the user message as data. A message that contains patient data or an
  injection attempt is never treated as a decision.
- A proposed fact may only use words the user actually said (`ungrounded_words`). A proposal that adds
  details is discarded and audited as `policy_rejected`.
- The model cannot invent the part of the message that is still to be answered: it can only copy
  text that is really in the user message.
- An edited fact is validated again before it is stored.
- A stored memory never overrides the knowledge base. If they conflict, the agent answers with the
  official value and says a user-approved correction exists that is not yet verified.
- Approved memories travel in the user role, wrapped in tags, never in the system prompt.
- Rejections and injection attempts stay in the audit log, so repeated attempts are visible.

**Why is no multi-agent architecture needed?** The self-evaluation adds zero model calls: the same
single call that writes the answer also returns an optional `memory_proposal` field
(`{"reply": ..., "memory_proposal": ...}`). There is no second agent, no tools and no extra graph.
The only extra call is the small intent classifier, and it only runs when a proposal is pending.

## 4. What is and is not memorable

What is worth remembering (from the HealthCore memory CONTEXT): recurring operational corrections per
clinic (schedule changes, local front-desk protocols, administrative exceptions by country), known
incident patterns **with no patient data**, and how a staff member wants operational (not clinical)
information presented.

Memorable (a `memory_proposal` is created):

| Example | Kind |
| --- | --- |
| "At the Manchester clinic, internal referrals now go through the coordinator before the specialist; that changed last quarter." | Clinic operational correction (UK) |
| "That high no-show alert at the Austin clinic was because of a road closure that week, not a real problem with the reminder programme." | Incident pattern, no patient data |
| "The weekly report for Diane Foster needs vacancies broken down by role, not just by clinic; she asked for that two weeks ago." | Staff presentation preference |
| The user corrects the late-cancellation and no-show fee to 75 USD (the knowledge base says 50 USD). | Administrative exception by country. Used in the real-model evidence (section 6). |

Not memorable (`memory_proposal` stays `null`):

| Example | Why | Behavior |
| --- | --- | --- |
| "What's this week's no-show rate?" | One-off query; the data lives in the dashboard. | No proposal. |
| "Patient Johnson cancelled tomorrow's appointment, note that down." | An attempt to store patient information. | **Refused out loud** with an explanation, audited and redacted, never sent to the model. |
| "Thanks, that settles my report." | The conversation is closing; nothing new. | No proposal. |
| The user "corrects" something the knowledge base already says (cancelling 24 hours ahead is free). | Nothing new. | The agent answers that this is correct. Observed with the real model in an earlier run (that transcript was not kept). |
| Live-data questions such as "what is the status of ticket 482?". | Live data has its own tools. | No proposal. |

These examples are also tests (`tests/pipelines/test_memory_phi.py`).

## 5. Audit log

Every proposal and every outcome is recorded, whether approved or not:

~~~
timestamp, proposal_id, session_id, proposed_fact, user_message, decision, written, reason
decision: proposed | approve | edit | reject | unclear | timeout | policy_rejected
~~~

- It is append-only (the interface has no delete, clear or update method).
- Patient data and credentials are redacted before they are logged. A refused request to remember a
  patient is recorded with its reason (for example `forbidden:patient_name`) and a redacted message.
- It is capped at 20,000 records. In production it would be rotated to durable storage first.

## 6. Evidence

`scripts/memory_evidence.py` runs the two required cycles, plus the patient-information refusal, with the
real model, real Qdrant and real Redis, and prints the transcript and the audit trail. The transcript is
attached to the PR.

- **Rejected cycle:** the agent proposes the 75 USD correction, the user says no, nothing is stored,
  the audit shows `proposed` then `reject`, and a later conversation still answers with the official 50 USD.
- **Approved cycle:** the agent proposes the same correction, the user says yes, exactly one entry is
  stored, the audit shows `proposed` then `approve`, and in a new conversation the agent uses the
  memory and presents it as a user-approved correction that is not yet verified.
- **Patient-information cycle (HealthCore CONTEXT):** the user asks the agent to note that "Patient
  Johnson cancelled tomorrow's appointment". The agent refuses out loud and explains why, nothing is
  stored, and the audit shows a single `policy_rejected` record with the message redacted.

The behavior is also covered by deterministic tests with a fake model and no external services:
`tests/pipelines/test_memory_store.py`, `test_memory_flow.py`, `test_memory_agent.py`,
`test_memory_guards.py` and `test_memory_phi.py` (patient information, HIPAA / UK GDPR coverage, the
explicit refusal, and the consolidation re-check).

**What the real model got wrong, and the fix.** Running the real evidence showed problems the fake
model could not:

1. The proposed fact added a detail the user never said ("for private-pay patients").
2. The reply claimed things the system had not done ("I have noted...", "for review...",
   "This note will be considered").

Rules in the prompt were not enough: the model ignored them in later runs. Both are now enforced in
code (`grounding.py`): a proposal that adds unstated details is discarded and audited, and sentences
that claim a save or promise a follow-up are removed from the reply. The prompt rules remain as a first
line of defense.

## 7. Limits (known and accepted for this milestone)

- **Shared memory, no ownership.** An approved memory affects answers for every user, and the endpoint
  has no authentication. In production, writes to core memory go through change tickets reviewed by a
  dedicated team; the milestone brief skips that governance on purpose.
- **Keyword retrieval.** Memory search matches keywords. It is simple and testable, but it will miss a
  memory phrased with different words.
- **The code guards are lexical.** The grounding check compares words, so it can discard a legitimate
  fact that is phrased with different words (the safe direction). The reply filter is a list of
  patterns, so a new phrasing of a false promise could get through until it is added.
- **`session_id` is chosen by the client.** It identifies a conversation, not a user.
- **The patient-information checks are lexical.** They are regular expressions: they catch names written as
  "Patient Johnson" (capitalized), identifiers with a recognizable shape, and clinical vocabulary. They
  can miss a lowercase name ("patient johnson"), a misspelled identifier or an indirect description, and
  they can reject a harmless sentence that uses a clinical word (the safe direction). They are one
  layer of defense, not a replacement for the compliance review that HealthCore requires.
- **Biometrics, photos and free-text descriptions** (HIPAA identifiers that are not text patterns) are out
  of scope for a text-only agent.
- **No automatic scheduling** of the cleanup yet: run `scripts/memory_consolidate.py` by hand or schedule it.
