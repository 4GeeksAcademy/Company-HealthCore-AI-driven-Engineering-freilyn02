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

### Incident (Centralized Incident Manager)

- title, description, category, status, origin, branch, created_at, updated_at
- category: clinical_equipment, it_system, billing_error, compliance_breach, patient_experience, staff_issue, facility_issue, referral_issue, other
- status: open / in_progress / resolved / discarded
  - valid transitions: open → in_progress, open → discarded, in_progress → resolved, in_progress → discarded (resolved and discarded are final)
- origin: customer (reported by a patient or representative), branch (reported by clinic staff), internal (detected by tech, compliance or corporate leadership)
- branch — must be one of these 14 values:

| Value              | Display label                |
| ------------------ | ----------------------------- |
| central             | Central — Austin Main Clinic |
| austin_north        | Austin — North                |
| dallas_uptown       | Dallas Uptown                 |
| houston_med_center  | Houston Medical Center        |
| san_antonio_west    | San Antonio West               |
| miami_brickell      | Miami Brickell                 |
| miami_doral         | Miami Doral                    |
| orlando_east        | Orlando East                   |
| tampa_bay           | Tampa Bay                      |
| atlanta_midtown     | Atlanta Midtown                |
| savannah            | Savannah                       |
| london_city         | London City                    |
| london_west         | London West End                |
| manchester_central  | Manchester Central             |

  Use `central` when the incident isn't tied to a specific clinic (e.g. internal corporate reports or customer complaints that can't be linked to one branch).

> ⚠️ **Regulatory constraint:** this manager must NOT store patient-identifying data (name, date of birth, medical record number, contact info). If an incident involves a patient, reference them only by an internal opaque identifier. Any free-text field must show a visible warning against entering patient personal data.

## Constraints
- UI must always show human-readable labels, never raw API values (e.g. "Personal interview", not "personal_interview")
- Terminology across apps should reflect HealthCore branding — not a generic implementation