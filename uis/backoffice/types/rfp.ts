// types/rfp.ts - mirrors the /rfp/tickets API (Milestone 9, Part 1).

export type RfpStatus = "analizando" | "descartado" | "analisis_completo";

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
  by_department: RfpSynthesisDepartment[];
  unknown_departments: string[];
  readability_estimate: string;
  routing_next: string;
}

export interface RfpTicket {
  id: number;
  status: RfpStatus;
  original_filename: string;
  is_rfp: boolean | null;
  classifier_confidence: number | null;
  classifier_reason: string | null;
  summary: string | null;
  synthesis: RfpSynthesis | null;
  routing_status: string;
  error_message: string | null;
  rfp_metadata: Record<string, unknown> | null;
  readability: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface RfpUploadResponse {
  ticket_id: number;
  status: RfpStatus;
}
