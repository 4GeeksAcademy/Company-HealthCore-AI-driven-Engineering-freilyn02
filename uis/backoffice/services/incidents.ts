import { apiFetch } from "../lib/api";
import {
  Incident,
  IncidentCreatePayload,
  IncidentStatus,
  IncidentSummary,
} from "../types/incident";

export function createIncident(payload: IncidentCreatePayload): Promise<Incident> {
  return apiFetch<Incident>("/api/incidents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export interface IncidentFilters {
  status?: IncidentStatus;
  origin?: string;
  branch?: string;
  category?: string;
}

export function listIncidents(filters: IncidentFilters = {}): Promise<Incident[]> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const query = params.toString();
  return apiFetch<Incident[]>(`/api/incidents${query ? `?${query}` : ""}`);
}

export function getIncident(id: string): Promise<Incident> {
  return apiFetch<Incident>(`/api/incidents/${id}`);
}

export function updateIncidentStatus(id: string, status: IncidentStatus): Promise<Incident> {
  return apiFetch<Incident>(`/api/incidents/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function getIncidentSummary(): Promise<IncidentSummary> {
  return apiFetch<IncidentSummary>("/api/incidents/summary");
}