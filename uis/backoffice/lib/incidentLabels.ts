import {
    IncidentBranch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
  } from "../types/incident";
  
  export const CATEGORY_LABELS: Record<IncidentCategory, string> = {
    clinical_equipment: "Clinical Equipment",
    it_system: "IT System",
    billing_error: "Billing Error",
    compliance_breach: "Compliance Breach",
    patient_experience: "Patient Experience",
    staff_issue: "Staff Issue",
    facility_issue: "Facility Issue",
    referral_issue: "Referral Issue",
    other: "Other",
  };
  
  export const STATUS_LABELS: Record<IncidentStatus, string> = {
    open: "Open",
    in_progress: "In Progress",
    resolved: "Resolved",
    discarded: "Discarded",
  };
  
  export const ORIGIN_LABELS: Record<IncidentOrigin, string> = {
    customer: "Customer",
    branch: "Branch",
    internal: "Internal",
  };
  
  export const BRANCH_LABELS: Record<IncidentBranch, string> = {
    central: "Central — Austin Main Clinic",
    austin_north: "Austin — North",
    dallas_uptown: "Dallas Uptown",
    houston_med_center: "Houston Medical Center",
    san_antonio_west: "San Antonio West",
    miami_brickell: "Miami Brickell",
    miami_doral: "Miami Doral",
    orlando_east: "Orlando East",
    tampa_bay: "Tampa Bay",
    atlanta_midtown: "Atlanta Midtown",
    savannah: "Savannah",
    london_city: "London City",
    london_west: "London West End",
    manchester_central: "Manchester Central",
  };