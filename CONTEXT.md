# HealthCore — Company Context

## About HealthCore
HealthCore was founded in 2011 by Dr. Elena Marsh, a former NHS general practitioner, and Raj Whitfield, a healthcare operations consultant, after they identified a shared problem on both sides of the Atlantic: patients in mid-sized towns had to travel long distances or wait weeks for routine specialist care. Starting with a single clinic in Bristol, UK, and a sister clinic in Tampa, Florida, HealthCore grew through a "hub-and-spoke" model — small, fully-staffed outpatient clinics connected by a shared digital backbone, rather than large centralized hospitals.

Today HealthCore operates 12 outpatient clinics across the US and UK. HealthCore Digital is the internal technology unit responsible for building and maintaining every software tool used across the network — from clinical operations to patient-facing services and internal hiring.

## Differentiator
HealthCore's core bet is "continuity over convenience": instead of competing on same-day urgent care, HealthCore builds long-term patient-provider relationships by keeping patient records, referrals, and follow-ups tightly connected across every clinic in the network — a patient seen in Bristol can have their history instantly available if they later visit the Tampa clinic. This connective-tissue approach is why internal tooling (like the Talent Pipeline Tracker) matters so much: HealthCore's advantage lives in how well its systems talk to each other, not just in its clinics.

## Business domain
- Ambulatory / outpatient care (no hospital admissions)
- Operations span two regions: US and UK, each with local regulatory and staffing considerations
- Internal focus areas include: talent acquisition & HR (People & Talent), clinic operations, and patient-facing services

## Key entities & field names
### Candidate (Talent Pipeline Tracker)
- full_name, email, phone, position, linkedin_url, cv_url, experience_years
- status: received / in_progress / selected / discarded
- stage: pending / review / personal_interview / technical_interview / offer_presented
- notes: internal notes attached to a candidate record

### Supplier (Supplier Directory)

- name, country, categories (list), rate, updated_at, status
- country: US / UK
- categories: Medical Equipment, Pharmaceuticals, PPE & Medical Consumables, Lab Supplies, IT & Telehealth Equipment, Facility & Maintenance, Office & Administrative Supplies
- status: active / suspended

## Constraints
- UI must always show human-readable labels, never raw API values (e.g. "Personal interview", not "personal_interview")
- Terminology across apps should reflect HealthCore branding — not a generic implementation