# HealthCore — Company Context (Milestone 1)

## About HealthCore
HealthCore is an outpatient healthcare clinic network operating 12 clinics across the United States and the United Kingdom. Founded in 2011 by Dr. Elena Marsh and Raj Whitfield, HealthCore uses a "hub-and-spoke" model connecting small, fully-staffed outpatient clinics through a shared digital backbone.

## Application form fields
The application form on this site collects candidate applications for open positions at HealthCore clinics. Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| full_name | text | yes | Full legal name |
| email | email | yes | Valid email format |
| phone | tel | yes | Valid phone format |
| position | select | yes | One of the open positions listed |
| linkedin_url | url | no | Optional LinkedIn profile |
| cv_url | url | no | Optional link to CV/resume |
| experience_years | number | yes | Years of relevant experience, 0 or more |

## Open positions (example enum for `position`)
- Registered Nurse
- Patient Coordinator
- Clinic Operations Manager
- Executive Assistant

## Brand
- Accent color: #ff6a3d (orange)
- Background: white / warm off-white
- Fonts: Manrope (body), Space Grotesk (headings)