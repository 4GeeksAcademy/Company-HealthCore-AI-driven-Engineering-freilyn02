# HealthCore — Telemetry Plan (Phase 1)

**Status:** Design document — no instrumentation implemented yet.
**Owner:** Engineering (response to Tech Lead's RFI on operational visibility)
**Scope:** Inventory management system (clinical supplies) + backoffice sections that support it.

---

## 1. Executive Summary

HealthCore's inventory system has been running in production for weeks across all 12 clinics (Texas, Florida, Georgia — US; London, Manchester — UK). It correctly enforces the business rule that stock can only change through a traceable `InboundOrder` or `OutboundOrder`, but today the system is a black box to the operations team. We cannot currently answer basic operational questions:

- How many outbound orders are registered per day, and by which clinic/department?
- Which supplies accumulate the most validation errors when staff try to register an order?
- Are staff attempting to bypass supply traceability by editing stock directly, and where?
- When do minimum stock threshold alerts fire the most, and for which supplies?
- Beyond inventory: how many failed login attempts happen per day? Which backoffice sections do operators actually use? Are there flows staff start and abandon?

This plan is the answer to that RFI. It defines, before any instrumentation is written, what data is worth capturing today (the mandatory metrics required by HealthCore from day one) and what is worth capturing as an identified opportunity — technical and business signals that don't have a fully defined business question yet, but that another team (compliance, network operations) will need later.

Every event in this plan exists because it completes the golden-rule sentence: *"We capture `[event_type]` because we need to know `[hypothesis]`, which allows us to make the decision `[decision]`."* If it doesn't complete that sentence, it isn't in this plan.

**Regulatory constraint that shapes every design decision below:** HealthCore is subject to HIPAA (US) and UK GDPR (UK). No event in this system describes a patient. Events describe *supplies and stock*. No `properties` field may ever contain a patient name, medical record identifier, diagnosis, or any data — real or simulated — that could be interpreted as protected health information (PHI). Where a clinical context is needed, only `department` (e.g. `general_consultation`, `chronic_care`) is used, never a patient identifier.

---

## 2. Mandatory Metrics (from `CONTEXT-healthcore.md`)

These five events are the floor of this plan — required by HealthCore regardless of anything else identified below. They will later feed Dr. Okonkwo's network operations dashboard and Claire's compliance alerts, so they are designed to be aggregated by clinic and by country (`US`/`UK`) from day one.

### Mandatory: `inbound_order_created`

- **Class:** mandatory (from CONTEXT)
- **Definition:** fires when a clinic registers the receipt of supplies from a vendor.
- **Data components:** order id, clinic, country, product, product category, quantity, vendor.
- **System touchpoints:** inventory module → "Register inbound order" action.
- **Hypothesis → decision:** We capture `inbound_order_created` because we need to know **how much and what supply is being purchased, by clinic and vendor**, which allows us to decide **how to consolidate purchasing across clinics and negotiate better vendor terms**.

### Mandatory: `outbound_order_created`

- **Class:** mandatory (from CONTEXT)
- **Definition:** fires when a clinic registers the consumption of a supply during a department's care activity.
- **Data components:** order id, clinic, country, product, product category, quantity, department (never a patient).
- **System touchpoints:** inventory module → "Register outbound order" action.
- **Hypothesis → decision:** We capture `outbound_order_created` because we need to know **which supplies are consumed most, and at what rate, by clinic and department**, which allows us to decide **how to adjust automatic replenishment of critical supplies per clinic**.

### Mandatory: `stock_threshold_triggered`

- **Class:** mandatory (from CONTEXT)
- **Definition:** fires when a supply's stock at a clinic falls below its configured minimum threshold.
- **Data components:** clinic, country, product, product category, current stock, threshold.
- **System touchpoints:** stock recalculation triggered after every outbound order.
- **Hypothesis → decision:** We capture `stock_threshold_triggered` because we need to know **how often a clinic runs short of a critical supply (e.g. PPE, medication)**, which allows us to decide **to prioritise urgent restocking and escalate to Marcus (Clinical Operations)**.

### Mandatory: `direct_stock_edit_rejected`

- **Class:** mandatory (from CONTEXT)
- **Definition:** fires when a user attempts to modify stock directly, outside an order, and the system rejects it.
- **Data components:** clinic, country, product, attempted action.
- **System touchpoints:** stock write path — any request that bypasses `InboundOrder`/`OutboundOrder`.
- **Hypothesis → decision:** We capture `direct_stock_edit_rejected` because we need to know **whether staff are attempting to bypass supply traceability controls**, which allows us to decide **to reinforce training or permissions at the clinic where this happens most**.

### Mandatory: `supply_expiry_flagged`

- **Class:** mandatory (from CONTEXT)
- **Definition:** fires when a supply batch (medication or material) approaches its expiry date (within 30 days).
- **Data components:** clinic, country, product, product category, batch id, expiry date, days until expiry.
- **System touchpoints:** scheduled daily expiry-scan job over the `Product` model (expiry date must live on the product/batch, not only on the order, for this to be computable consistently).
- **Hypothesis → decision:** We capture `supply_expiry_flagged` because we need to know **which supplies are about to expire before they become waste or a compliance risk**, which allows us to decide **to prioritise use or controlled disposal of that batch before expiry**.

---

## 3. Flow Mapping — Inventory Management Path

Mapping the path from authenticated access through order completion, including rejected paths and threshold triggers, surfaces **6 instrumentation points** (above the required minimum of 5):

| # | Step in the flow | Event fired | Class |
|---|---|---|---|
| 1 | Authenticated staff member opens the inventory module at their clinic | `inventory_module_accessed` | identified opportunity |
| 2 | Staff registers a vendor shipment | `inbound_order_created` | mandatory |
| 3 | Staff registers supply consumption for a department | `outbound_order_created` | mandatory |
| 4 | Staff submits an order with invalid/missing data (bad quantity, unknown product) | `order_validation_failed` | identified opportunity |
| 5 | Staff (or a script) attempts to edit stock directly instead of through an order | `direct_stock_edit_rejected` | mandatory |
| 6 | Stock recalculation after an outbound order crosses the configured minimum | `stock_threshold_triggered` | mandatory |

`supply_expiry_flagged` is intentionally not in this table — it is not triggered by a user action in this flow, but by a scheduled background scan (see Section 6).

---

## 4. Broad Opportunity Catalogue

The mandatory metrics above only cover the inventory happy/rejected paths. HealthCore's tech lead was explicit: *"it's not just the inventory... any part of the application a user or a process touches is a data opportunity."* The following opportunities were identified across the rest of the backoffice, each validated against the golden-rule sentence before being included.

| Category | Event | Class |
|---|---|---|
| Inventory | `order_validation_failed` | identified opportunity |
| Navigation | `inventory_module_accessed` | identified opportunity |
| Navigation | `section_viewed` | identified opportunity |
| Navigation | `order_flow_abandoned` | identified opportunity |
| Business / Navigation | `product_search_performed` | identified opportunity |
| Authentication | `login_failed` | identified opportunity |
| Authentication | `session_expired` | identified opportunity |
| Authentication / Security | `permission_denied` | identified opportunity |
| Performance | `api_latency_recorded` | identified opportunity |
| Errors | `frontend_error_caught` | identified opportunity |

That's 10 identified-opportunity events across 6 categories (Inventory, Navigation, Business, Authentication, Performance, Errors), on top of the 5 mandatory events — well beyond the minimum of 8 additional events across 3 categories.

Opportunities that were considered and explicitly **not** included are documented in Section 8 (Risks and Exclusions), together with the reasoning for excluding them.

---

## 5. Event Envelope

Every event emitted by HealthCore's systems — regardless of category — shares this envelope. No event is valid without every one of these fields.

| Field | Type | Required | Notes |
|---|---|---|---|
| `eventId` | string (UUID) | yes | Idempotency and deduplication. |
| `timestamp` | string (ISO 8601) | yes | UTC. Clinics span US and UK time zones; normalising to UTC at capture time avoids ambiguity when aggregating across countries. |
| `sessionId` | string | yes | Browser or API session. |
| `userId` | string | yes | Authenticated staff member. This identifies **staff**, never a patient, so it is not PHI — no hashing is required by the current CONTEXT, but the field is designed so a hash can be substituted later without changing the schema, if security policy tightens. |
| `event_type` | string | yes | `entity_action` taxonomy (e.g. `inbound_order_created`). |
| `schemaVersion` | string | yes | e.g. `1.0.0`. |
| `requestId` | string | yes | Correlates frontend, API, and logs for the same operation. |
| `properties` | object | yes | Event-specific payload. Allowlisted per event — see Section 6. |

---

## 6. Event Catalog

Every event below follows the golden-rule sentence, has a defined property allowlist, and documents whether it carries PII/PHI risk and how that risk is handled. `M` = mandatory, `O` = identified opportunity.

### Inventory (business)

#### `inbound_order_created` — M — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `orderId` | string | yes | yes | no |
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `product_id` | string | yes | yes | no |
| `product_category` | enum (`medication`,`ppe`,`consumable`,`equipment`) | yes | yes | no |
| `quantity` | integer | yes | yes | no |
| `vendor_id` | string | yes | yes | no |

- **Stream vs batch:** batch — vendor consolidation and contract negotiation are weekly/monthly decisions, not minute-by-minute ones.
- **Sanitisation:** none needed; no patient-related field exists on a purchase receipt.

#### `outbound_order_created` — M — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `orderId` | string | yes | yes | no |
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `product_id` | string | yes | yes | no |
| `product_category` | enum (`medication`,`ppe`,`consumable`,`equipment`) | yes | yes | no |
| `quantity` | integer | yes | yes | no |
| `department` | string | no | yes | **no — by design.** `department` identifies a clinical area (e.g. `chronic_care`), never a patient. It must never be replaced with a patient identifier. |

- **Stream vs batch:** batch — used for daily replenishment-planning dashboards; sub-minute latency is not required for a restocking decision made once a day.
- **Sanitisation:** `department` is validated against a fixed enum of known departments at write time, so free text can never leak into this field.

#### `stock_threshold_triggered` — M — stream

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `product_id` | string | yes | yes | no |
| `product_category` | enum (`medication`,`ppe`,`consumable`,`equipment`) | yes | yes | no |
| `current_stock` | integer | yes | yes | no |
| `threshold` | integer | yes | yes | no |

- **Stream vs batch:** stream — a critical-supply shortage (PPE, medication) needs same-day escalation to Marcus, not a next-day report.
- **Throttle:** debounce repeated triggers for the same `clinic_id` + `product_id` within a 15-minute window, so one supply staying under threshold doesn't flood the stream with duplicate alerts.

#### `direct_stock_edit_rejected` — M — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `product_id` | string | yes | yes | no |
| `attempted_action` | string | yes | yes | no |
| `attempted_quantity` | integer | no | yes | no |

- **Stream vs batch:** batch — the decision this feeds (retrain staff, tighten permissions at a clinic) is reviewed weekly by compliance/operations, not acted on within minutes of a single attempt. If the frequency for a given clinic crosses an internal alert threshold, that aggregation — not the raw event — is what would justify a stream-based escalation; that aggregation is out of scope for this design phase.
- **Sanitisation:** none needed; `userId` (envelope) already identifies the staff member responsibly, no patient data is involved in a stock-field edit attempt.

#### `supply_expiry_flagged` — M — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `product_id` | string | yes | yes | no |
| `product_category` | enum (`medication`,`ppe`,`consumable`,`equipment`) | yes | yes | no |
| `batch_id` | string | yes | yes | no |
| `expiry_date` | string (date) | yes | yes | no |
| `days_until_expiry` | integer | yes | yes | no |

- **Stream vs batch:** batch — this is produced by a scheduled daily scan job, not a live user action; a once-a-day cadence is sufficient to act before a 30-day expiry window closes.

#### `order_validation_failed` — O — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `order_type` | enum (`inbound`,`outbound`) | yes | yes | no |
| `product_id` | string | no (nullable — the failure may be that no valid product was selected) | yes | no |
| `validation_error_code` | string | yes | yes | no |
| `field` | string | yes | yes | no |

- **Hypothesis → decision:** We capture `order_validation_failed` because we need to know **which products and clinics accumulate the most validation errors when registering an order**, which allows us to decide **whether to fix the form's UX or provide targeted training at specific clinics**.
- **Stream vs batch:** batch — reviewed as part of a weekly UX/quality report.

### Navigation

#### `inventory_module_accessed` — O — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `role` | string | yes | yes | no |

- **Hypothesis → decision:** We capture `inventory_module_accessed` because we need to know **which clinics and roles actually use the inventory module, and when**, which allows us to decide **how to plan support coverage and training by shift and clinic**.
- **Stream vs batch:** batch.

#### `section_viewed` — O — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `section_name` | string | yes | yes | no |
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |

- **Hypothesis → decision:** We capture `section_viewed` because we need to know **which backoffice sections operators actually visit, and which are ignored**, which allows us to decide **where to invest further UX work, or which underused-but-important sections need better discoverability**.
- **Stream vs batch:** batch.

#### `order_flow_abandoned` — O — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `order_type` | enum (`inbound`,`outbound`) | yes | yes | no |
| `step_reached` | string | yes | yes | no |

- **Hypothesis → decision:** We capture `order_flow_abandoned` because we need to know **whether the order-creation flow is too complex or slow, causing staff to abandon it partway through**, which allows us to decide **whether to redesign the form or shorten the flow**.
- **Stream vs batch:** batch.

### Business / Navigation

#### `product_search_performed` — O — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `search_term_hash` | string | yes | yes | **potential — mitigated.** |
| `result_count` | integer | yes | yes | no |

- **Hypothesis → decision:** We capture `product_search_performed` because we need to know **what supplies staff search for that are hard to find, or where the product catalog has gaps**, which allows us to decide **whether to improve catalog searchability or add missing products**.
- **PII/PHI note:** a free-text search box is the one place in this system where a staff member could accidentally type something PHI-adjacent (e.g. referencing a patient while searching). The raw search string is **never captured** — only a one-way hash of the normalised term, so we can still count repeated searches for the same term without ever storing the literal text.
- **Stream vs batch:** batch.

### Authentication

#### `login_failed` — O — stream

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `clinic_id` | string | no (may be unknown before authentication resolves) | yes | no |
| `failure_reason` | enum (`invalid_credentials`,`account_locked`,`mfa_failed`) | yes | yes | no |
| `attempt_number` | integer | no | yes | no |

- **Hypothesis → decision:** We capture `login_failed` because we need to know **how many failed login attempts happen per day, and whether they concentrate around specific accounts or clinics**, which allows us to decide **whether to escalate a possible credential-stuffing/brute-force attempt to security**.
- **Stream vs batch:** stream — repeated failures against the same account need near-real-time detection to lock an account or alert security before a breach, not a next-day report.
- **Throttle:** aggregate repeated failures for the same account within a short window (e.g. emit one `login_failed` per attempt up to a cap, then switch to a rate-limited summary) so a scripted attack doesn't flood the pipeline with one event per millisecond.

#### `session_expired` — O — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `session_duration_seconds` | integer | yes | yes | no |

- **Hypothesis → decision:** We capture `session_expired` because we need to know **how often sessions time out mid-task, forcing staff to redo work**, which allows us to decide **whether to extend the timeout or add a session-refresh warning**.
- **Stream vs batch:** batch.

#### `permission_denied` — O — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `clinic_id` | string | yes | yes | no |
| `country` | enum (`US`, `UK`) | yes | yes | no |
| `attempted_action` | string | yes | yes | no |
| `required_role` | string | yes | yes | no |

- **Hypothesis → decision:** We capture `permission_denied` because we need to know **whether roles and permissions are misconfigured, or whether staff regularly need access beyond their assigned role**, which allows us to decide **whether to adjust role definitions or introduce a formal access-request process**.
- **Stream vs batch:** batch.

### Performance

#### `api_latency_recorded` — O — stream

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `endpoint` | string | yes | yes | no |
| `method` | enum (`GET`,`POST`,`PUT`,`PATCH`,`DELETE`) | yes | yes | no |
| `status_code` | integer | yes | yes | no |
| `duration_ms` | integer | yes | yes | no |
| `clinic_id` | string | no | yes | no |

- **Hypothesis → decision:** We capture `api_latency_recorded` because we need to know **which endpoints are slow, and whether that degradation is concentrated in a specific clinic or time window**, which allows us to decide **whether to prioritise backend optimisation or scale infrastructure**.
- **Stream vs batch:** stream — a live latency spike needs near-real-time detection so on-call engineering can react before it affects clinical operations.
- **Throttle:** sample high-traffic endpoints (e.g. 1 in 10 requests) rather than emitting one event per call, and/or pre-aggregate into per-minute p50/p95 buckets before emitting, to keep stream volume manageable.

### Errors

#### `frontend_error_caught` — O — batch

| Property | Type | Required | Allowlist | PII/PHI |
|---|---|---|---|---|
| `page` | string | yes | yes | no |
| `error_type` | string | yes | yes | no |
| `error_message` | string | yes | yes | **potential — mitigated.** |

- **Hypothesis → decision:** We capture `frontend_error_caught` because we need to know **how frequently uncaught errors occur, and on which screens**, which allows us to decide **which bugs to prioritise fixing first**.
- **PII/PHI note:** `error_message` is sanitised before capture — stack traces and any interpolated form values are stripped, so a JS error thrown while a department/product field is populated can never leak that value verbatim.
- **Stream vs batch:** batch, aggregated into a daily quality report. If the error rate for a given page crosses an internal threshold, that would justify escalating to a stream-based alert — out of scope for this design phase.

---

## 7. High-Frequency Strategy

Three events in this catalog can realistically spike in volume and need explicit throttling, beyond what's already noted per-event above:

- **`stock_threshold_triggered`** — debounced per `clinic_id` + `product_id` within a 15-minute window, so a supply sitting under threshold for hours doesn't generate a stream of duplicate alerts.
- **`login_failed`** — aggregated per account within a short window during a suspected brute-force attempt, rather than emitting one event per failed attempt.
- **`api_latency_recorded`** — sampled (not every request) for high-traffic endpoints, and/or pre-aggregated into per-minute percentile buckets before being sent to the stream, to avoid overwhelming the pipeline with one event per API call across 12 clinics.

Lower-frequency identified-opportunity events (`section_viewed`, `product_search_performed`, `order_flow_abandoned`) do not need throttling at this stage — their expected volume is bounded by the number of active staff sessions, not by automated or repeated actions.

---

## 8. Risks and Exclusions

Deliberate scope cuts made while designing this plan, and why:

- **Raw search query text is never captured.** `product_search_performed` only stores a hash of the search term. A free-text search box is the highest-risk surface in this system for an accidental PHI leak (e.g. a staff member typing a patient reference while searching for a supply), so the raw string is excluded by design — only the hashed token and result count are kept.
- **No patient-related field of any kind, anywhere.** This isn't a per-event decision — it's a hard constraint across the entire catalog, driven directly by HIPAA and UK GDPR. `department` is validated against a closed enum precisely so free text describing a patient can never enter that field.
- **Vendor pricing/contract terms are excluded from `inbound_order_created`.** Only `vendor_id` and `quantity` are captured. Unit costs and contract terms are commercially sensitive and are not needed to answer the current business question (consolidating purchase volume); if procurement later needs cost data, that belongs in a dedicated, access-controlled reporting pipeline, not general-purpose telemetry.
- **`product_viewed` (viewing an individual product's detail page) was considered and discarded.** At current usage volume, this is a very high-frequency, low-actionability event relative to `product_search_performed` and `section_viewed`, which already answer the "what are staff looking for" question at a coarser, sufficient grain. It can be revisited if catalog UX becomes a dedicated priority.
- **Scroll depth / mouse-movement tracking was considered and discarded.** For a clinical operations backoffice, this kind of granular UI-interaction data has a poor cost-to-signal ratio and was excluded on cost grounds — it would multiply event volume without feeding any decision identified in this plan.
- **Raw IP addresses are excluded from `login_failed`.** `clinic_id` and `failure_reason` are sufficient to detect a concentration of failed attempts; storing raw IPs would add a personal-data field under UK GDPR without adding decision-relevant value at this stage.

---

## 9. Summary for Delivery

- **Total events designed:** 15
  - **Mandatory (from CONTEXT):** 5 — `inbound_order_created`, `outbound_order_created`, `stock_threshold_triggered`, `direct_stock_edit_rejected`, `supply_expiry_flagged`
  - **Identified opportunities:** 10 — `order_validation_failed`, `inventory_module_accessed`, `section_viewed`, `order_flow_abandoned`, `product_search_performed`, `login_failed`, `session_expired`, `permission_denied`, `api_latency_recorded`, `frontend_error_caught`
- **Categories covered:** Inventory (business), Navigation, Business, Authentication, Performance, Errors — 6 categories, above the required minimum of 3.
- **Hardest design decision:** deciding what to do with the one genuinely open text field in the whole system — the product search box — without either losing the signal entirely or risking a PHI leak; the resolution was to hash the search term instead of excluding the event outright.
