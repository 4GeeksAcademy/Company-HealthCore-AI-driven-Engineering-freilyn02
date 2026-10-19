// types/rfp.ts - mirrors the /rfp API (Milestone 9, Parts 1, 2 and 3).

export type RfpStatus =
  | "analyzing"
  | "discarded"
  | "intake_complete"
  | "drafting"
  | "under_evaluation"
  | "needs_human_review"
  | "waiting_for_approval"
  | "done";

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

// --- Real-time: GET /events/stream, event "rfp_ticket_created" ---------------

// Payload published by the API right after a ticket is saved. A subset of RfpTicket,
// with the same field names (`id` is the ticket identifier).
export interface RfpTicketCreatedEvent {
  id: number;
  status: RfpStatus;
  original_filename: string;
  created_at: string;
}

// --- Part 3: approval and completion ----------------------------------------

export type ApprovalStatus = "pending" | "approved" | "rejected" | "changes_requested";
export type ApprovalDecision = "approve" | "reject" | "request_changes";

export interface RfpDepartmentApproval {
  approval_status: ApprovalStatus;
  approver: string | null;
  revision_count: number;
}

export interface RfpArbitrationResolution {
  conflict_id: string;
  departments: string[];
  arbiter: string;
  rule: string;
  deferred: boolean;
  resolution: string;
}

export interface RfpApprovalStatus {
  ticket_id: string;
  status: RfpStatus;
  departments: Record<string, RfpDepartmentApproval>;
  pending_approvals: string[];
  blocked: boolean;
  final_document: string | null;
  closing_outcome?: string;
  resolutions?: RfpArbitrationResolution[];
}

export interface RfpPendingApproval {
  ticket_id: string;
  department: string;
  owner: string;
  section_summary: string;
  evaluation_snapshot: { passed?: boolean | null; iterations?: number | null; contains_phi?: boolean };
  draft_hash: string;
  revision: number;
  actions: ApprovalDecision[];
}

export interface RfpApprovalBoard {
  approvals: RfpApprovalStatus;
  pending: RfpPendingApproval[];
}

export interface RfpApproverIdentity {
  actor: string | null;
  department: string | null;
}

export interface RfpDecisionInput {
  department: string;
  decision: ApprovalDecision;
  actor: string;
  comment?: string;
  requested_changes?: string;
}

export interface RfpTraceEvent {
  ts: string;
  ticket_id: string;
  agent: string;
  department: string | null;
  input_ref: string;
  output_ref: string;
}
