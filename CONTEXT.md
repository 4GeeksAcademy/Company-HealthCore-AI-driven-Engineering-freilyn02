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

### Supplier (Supplier Directory)

- name, country, categories (list), rate, updated_at, status
- country: US / UK
- categories: Medical Equipment, Pharmaceuticals, PPE & Medical Consumables, Lab Supplies, IT & Telehealth Equipment, Facility & Maintenance, Office & Administrative Supplies
- status: active / suspended