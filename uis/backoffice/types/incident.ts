export type IncidentCategory =
  | "clinical_equipment"
  | "it_system"
  | "billing_error"
  | "compliance_breach"
  | "patient_experience"
  | "staff_issue"
  | "facility_issue"
  | "referral_issue"
  | "other";

export type IncidentStatus = "open" | "in_progress" | "resolved" | "discarded";

export type IncidentOrigin = "customer" | "branch" | "internal";

export type IncidentBranch =
  | "central"
  | "austin_north"
  | "dallas_uptown"
  | "houston_med_center"
  | "san_antonio_west"
  | "miami_brickell"
  | "miami_doral"
  | "orlando_east"
  | "tampa_bay"
  | "atlanta_midtown"
  | "savannah"
  | "london_city"
  | "london_west"
  | "manchester_central";

export interface Incident {
  id: string;
  title: string;
  description: string;
  category: IncidentCategory;
  status: IncidentStatus;
  origin: IncidentOrigin;
  branch: IncidentBranch;
  created_at: string;
  updated_at: string;
}

export interface IncidentCreatePayload {
  title: string;
  description: string;
  category: IncidentCategory;
  origin: IncidentOrigin;
  branch: IncidentBranch;
}

export interface IncidentSummary {
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_origin: Record<string, number>;
  by_branch: Record<string, number>;
}

export const INCIDENT_CATEGORIES: IncidentCategory[] = [
  "clinical_equipment",
  "it_system",
  "billing_error",
  "compliance_breach",
  "patient_experience",
  "staff_issue",
  "facility_issue",
  "referral_issue",
  "other",
];

export const INCIDENT_STATUSES: IncidentStatus[] = ["open", "in_progress", "resolved", "discarded"];

export const INCIDENT_ORIGINS: IncidentOrigin[] = ["customer", "branch", "internal"];

export const INCIDENT_BRANCHES: IncidentBranch[] = [
  "central",
  "austin_north",
  "dallas_uptown",
  "houston_med_center",
  "san_antonio_west",
  "miami_brickell",
  "miami_doral",
  "orlando_east",
  "tampa_bay",
  "atlanta_midtown",
  "savannah",
  "london_city",
  "london_west",
  "manchester_central",
];

// Valid lifecycle transitions — mirrors services/api/models.py exactly.
// The UI uses this to only offer valid next-status options.
export const VALID_STATUS_TRANSITIONS: Record<IncidentStatus, IncidentStatus[]> = {
  open: ["in_progress", "discarded"],
  in_progress: ["resolved", "discarded"],
  resolved: [],
  discarded: [],
};