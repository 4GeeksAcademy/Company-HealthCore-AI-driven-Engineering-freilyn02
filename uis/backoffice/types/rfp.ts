// types/rfp.ts - mirrors the /rfp/tickets API (Milestone 9, Part 1).

export type RfpStatus = "analyzing" | "discarded" | "intake_complete";

export interface RfpSynthesisDepartment {
  department: string;
  label: string;
  needs: string[];
  open_questions: string[];
  contact: string | null;
  failed: boolean;
}

export interface RfpSynthesis {
  ticket_id: number;
  summary: string;
  currency: string | null;
  by_department: RfpSynthesisDepartment[];
  unknown_departments: string[];
  readability_estimate: string;
  requires_compliance_review: boolean;
  compliance_flags: string[];
  departments_needed: string[];
  routing_next: string;
}

export interface RfpMetadata {
  client_name?: string | null;
  client_country?: "US" | "UK" | null;
  program_type?: string | null;
  covered_population?: number | null;
  deadline?: string | null;
  budget_range?: string | null;
  currency?: string | null;
  departments_needed?: string[];
}

export interface RfpTicket {
  id: number;
  status: RfpStatus;
  original_filename: string;
  is_rfp: boolean | null;
  classifier_confidence: number | null;
  classifier_reason: string | null;
  contains_phi: boolean;
  phi_findings: Record<string, number> | null;
  summary: string | null;
  synthesis: RfpSynthesis | null;
  routing_status: string;
  error_message: string | null;
  rfp_metadata: RfpMetadata | null;
  readability: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface RfpUploadResponse {
  ticket_id: number;
  status: RfpStatus;
}
