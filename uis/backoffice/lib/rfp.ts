// lib/rfp.ts
//
// Centralized module for all /rfp API calls ("no fetch in components").
// Upload uses FormData, so it cannot reuse apiFetch (which forces a JSON
// Content-Type header); it keeps the same 401 / error-shape handling.
// The Part 3 calls (approvals) share one small helper with the same behavior.

import { getToken, clearToken } from "./auth";
import { ApiError, apiFetch } from "./api";
import type {
  RfpApprovalBoard,
  RfpApprovalStatus,
  RfpApproverIdentity,
  RfpDecisionInput,
  RfpTicket,
  RfpTicketCreatedEvent,
  RfpTraceEvent,
  RfpUploadResponse,
} from "@/types/rfp";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export function listRfpTickets(): Promise<RfpTicket[]> {
  return apiFetch<RfpTicket[]>("/rfp/tickets");
}

// --- Real-time (SSE) -----------------------------------------------------------

export const RFP_EVENTS_PATH = "/events/stream";
export const RFP_TICKET_CREATED_EVENT = "rfp_ticket_created";

// Validates the untrusted JSON of an SSE frame. Returns null for anything that is not a usable event.
export function parseRfpTicketCreated(data: unknown): RfpTicketCreatedEvent | null {
  if (!data || typeof data !== "object") return null;
  const event = data as Partial<RfpTicketCreatedEvent>;
  if (
    typeof event.id !== "number" ||
    typeof event.status !== "string" ||
    typeof event.original_filename !== "string" ||
    typeof event.created_at !== "string"
  ) {
    return null;
  }
  return event as RfpTicketCreatedEvent;
}

// The event only carries part of a ticket. The row is completed with the neutral values a
// brand-new ticket has; the next normal refresh of the list replaces it with the full record.
export function ticketFromCreatedEvent(event: RfpTicketCreatedEvent): RfpTicket {
  return {
    id: event.id,
    status: event.status,
    original_filename: event.original_filename,
    is_rfp: null,
    classifier_confidence: null,
    classifier_reason: null,
    contains_phi: false,
    phi_findings: null,
    summary: null,
    synthesis: null,
    routing_status: "pending",
    error_message: null,
    rfp_metadata: null,
    readability: null,
    created_at: event.created_at,
    updated_at: event.created_at,
  };
}

// Merges ticket lists by `id`, so the same ticket never appears twice. `incoming` wins over
// `current` for the same id when `preferIncoming` is true (a server refetch is authoritative);
// otherwise the record already shown is kept (an event must not overwrite a full record with
// its partial copy). Result is newest first, like GET /rfp/tickets.
export function mergeRfpTickets(
  current: RfpTicket[],
  incoming: RfpTicket[],
  { preferIncoming }: { preferIncoming: boolean },
): RfpTicket[] {
  const byId = new Map<number, RfpTicket>();
  for (const ticket of current) byId.set(ticket.id, ticket);
  for (const ticket of incoming) {
    if (preferIncoming || !byId.has(ticket.id)) byId.set(ticket.id, ticket);
  }
  return [...byId.values()].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime() || b.id - a.id,
  );
}

export function getRfpTicket(ticketId: number): Promise<RfpTicket> {
  return apiFetch<RfpTicket>(`/rfp/tickets/${ticketId}`);
}

// Turns FastAPI error bodies ({detail: string | {message} | [{msg}]}) into one readable message.
function extractMessage(data: unknown, fallback: string): { message: string; field?: string } {
  if (!data || typeof data !== "object") return { message: fallback };
  const body = data as { field?: string; message?: string; detail?: unknown };
  if (body.field && body.message) return { message: body.message, field: body.field };
  const detail = body.detail;
  if (typeof detail === "string") return { message: detail };
  if (Array.isArray(detail)) {
    const text = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String((item as { msg: unknown }).msg) : ""))
      .filter(Boolean)
      .join("; ");
    return { message: text || fallback };
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return { message: String((detail as { message: unknown }).message) };
  }
  return { message: fallback };
}

async function rawRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(init.body ? { "Content-Type": "application/json" } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (res.status === 401) {
    clearToken();
    window.location.assign("/login");
    throw new ApiError("Unauthorized", 401);
  }
  if (!res.ok) {
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      // response had no JSON body
    }
    const { message, field } = extractMessage(data, res.statusText);
    throw new ApiError(message, res.status, field);
  }
  return res;
}

async function jsonRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await rawRequest(path, init);
  return res.json() as Promise<T>;
}

export async function uploadRfp(file: File): Promise<RfpUploadResponse> {
  const token = getToken();
  const body = new FormData();
  body.append("file", file);

  // No Content-Type here: the browser must set the multipart boundary itself.
  const res = await fetch(`${API_URL}/rfp/tickets`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  });

  if (res.status === 401) {
    clearToken();
    window.location.assign("/login");
    throw new ApiError("Unauthorized", 401);
  }

  if (!res.ok) {
    let message = res.statusText;
    let field: string | undefined;
    try {
      const data = await res.json();
      if (data.field && data.message) {
        field = data.field;
        message = data.message;
      } else if (data.detail) {
        message = data.detail;
      }
    } catch {
      // response had no JSON body
    }
    throw new ApiError(message, res.status, field);
  }

  return res.json() as Promise<RfpUploadResponse>;
}

// --- Part 2 ------------------------------------------------------------------

export function generateRfpResponse(ticketId: number): Promise<{ ticket_id: number; status: string }> {
  return jsonRequest(`/rfp/tickets/${ticketId}/generate`, { method: "POST" });
}

// --- Part 3: approval and completion ------------------------------------------

export function getMyApprover(): Promise<RfpApproverIdentity> {
  return jsonRequest<RfpApproverIdentity>("/rfp/approver/me");
}

export function startRfpApprovals(ticketId: number): Promise<RfpApprovalStatus> {
  return jsonRequest<RfpApprovalStatus>(`/rfp/tickets/${ticketId}/approvals/start`, { method: "POST" });
}

export function getRfpApprovals(ticketId: number): Promise<RfpApprovalBoard> {
  return jsonRequest<RfpApprovalBoard>(`/rfp/tickets/${ticketId}/approvals`);
}

export function submitRfpDecision(ticketId: number, decision: RfpDecisionInput): Promise<RfpApprovalStatus> {
  return jsonRequest<RfpApprovalStatus>(`/rfp/tickets/${ticketId}/approvals/resume`, {
    method: "POST",
    body: JSON.stringify(decision),
  });
}

export function getRfpTrace(ticketId: number): Promise<RfpTraceEvent[]> {
  return jsonRequest<RfpTraceEvent[]>(`/rfp/tickets/${ticketId}/trace`);
}

export async function getRfpFinalDocument(ticketId: number): Promise<string> {
  const res = await rawRequest(`/rfp/tickets/${ticketId}/final-document`);
  return res.text();
}
