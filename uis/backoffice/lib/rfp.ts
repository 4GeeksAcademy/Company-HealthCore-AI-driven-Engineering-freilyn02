// lib/rfp.ts
//
// Centralized module for all /rfp API calls ("no fetch in components").
// Upload uses FormData, so it cannot reuse apiFetch (which forces a JSON
// Content-Type header); it keeps the same 401 / error-shape handling.

import { getToken, clearToken } from "./auth";
import { ApiError, apiFetch } from "./api";
import type { RfpTicket, RfpUploadResponse } from "@/types/rfp";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export function listRfpTickets(): Promise<RfpTicket[]> {
  return apiFetch<RfpTicket[]>("/rfp/tickets");
}

export function getRfpTicket(ticketId: number): Promise<RfpTicket> {
  return apiFetch<RfpTicket>(`/rfp/tickets/${ticketId}`);
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
