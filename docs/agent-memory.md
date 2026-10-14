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
   |
   v
input_guard -> memory_read -> route -> retrieve / tools -> answer (ONE structured model call)
   |
   v
memory_finalize  appends the "remember this?" question, keeps ONE pending proposal, audits "proposed"
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
| What may never be stored | `services/api/agent/memory/policy.py` |
| Code-level guards on proposals and replies | `services/api/agent/memory/grounding.py` |
| Reply + `memory_proposal` in one structured call | `services/api/agent/memory/turn.py` |
| Intent classifier (approve / reject / edit / unclear) | `services/api/agent/memory/confirm.py` |
| Propose / resolve flow | `services/api/agent/memory/flow.py` |
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

**What must never enter memory, whoever asks?**

- Patient-identifying data (names, dates of birth, record numbers, contact details). This comes from
  the regulatory constraint in `CONTEXT.md`. It is blocked when a fact is proposed and when it is
  edited, and it is redacted in the audit log.
- Credentials, API keys and tokens.
- Live data (ticket status, stock levels): it changes and has its own tools.
- Instructions to the agent disguised as facts ("from now on always answer in...").
- Opinions and anything about a specific person.

These checks are deterministic (`policy.py`), so a model mistake or a fake "approval" cannot get past them.

**How does the agent decide what to forget, and what happens to a pending proposal nobody answers?**

- A proposal not answered within 30 minutes is discarded. If the same conversation continues, the
  discard is audited as `timeout`. If the user never comes back, the audit keeps the `proposed`
  record without an outcome, and Redis deletes the pending key after 24 hours.
- Approved memories are cleaned by `scripts/memory_consolidate.py` (it has a `--dry-run` mode):
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

Memorable (a `memory_proposal` is created):

| Example | Status |
| --- | --- |
| The user corrects the late-cancellation and no-show fee to 75 USD (the knowledge base says 50 USD). | Verified with the real model (section 6). |
| The user corrects a stated escalation window in the referral process. | Design example. |
| The user confirms a stable, reusable company-level rule that is not in the knowledge base. | Design example. |

Not memorable (`memory_proposal` stays `null`):

| Example | Status |
| --- | --- |
| The user "corrects" something the knowledge base already says (cancelling 24 hours ahead is free). The agent answers that this is correct and proposes nothing. | Observed with the real model in an earlier run (that transcript was not kept). |
| Greetings, thanks and small talk. | Design example. |
| Live-data questions such as "what is the status of ticket 482?" or "how many gloves are in stock?". | Design example. A proposal only comes from the knowledge route. |
| A message that contains patient data or credentials. | Verified by tests (the policy rejects it). |

## 5. Audit log

Every proposal and every outcome is recorded, whether approved or not:

~~~
timestamp, proposal_id, session_id, proposed_fact, user_message, decision, written, reason
decision: proposed | approve | edit | reject | unclear | timeout | policy_rejected
~~~

- It is append-only (the interface has no delete, clear or update method).
- Patient data and credentials are redacted before they are logged.
- It is capped at 20,000 records. In production it would be rotated to durable storage first.

## 6. Evidence

`scripts/memory_evidence.py` runs the two required cycles with the real model, real Qdrant and real
Redis, and prints the transcript and the audit trail. The transcript is attached to the PR.

- **Rejected cycle:** the agent proposes the 75 USD correction, the user says no, nothing is stored,
  the audit shows `proposed` then `reject`, and a later conversation still answers with the official 50 USD.
- **Approved cycle:** the agent proposes the same correction, the user says yes, exactly one entry is
  stored, the audit shows `proposed` then `approve`, and in a new conversation the agent uses the
  memory and presents it as a user-approved correction that is not yet verified.

The behavior is also covered by deterministic tests with a fake model and no external services:
`tests/pipelines/test_memory_store.py`, `test_memory_flow.py`, `test_memory_agent.py` and
`test_memory_guards.py`.

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
- **No automatic scheduling** of the cleanup yet: run `scripts/memory_consolidate.py` by hand or schedule it.
