import { getToken, clearToken } from "./auth";
import { track } from "@/services/telemetry";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export class ApiError extends Error {
  status: number;
  field?: string;
  constructor(message: string, status: number, field?: string) {
    super(message);
    this.status = status;
    this.field = field;
  }
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options?.headers,
  };

  const method = options?.method ?? "GET";
  const startedAt = performance.now();
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  // Technical baseline: performance. Captured for every request through this
  // shared client, regardless of success/failure status.
  track("api_latency_recorded", {
    endpoint: path,
    method,
    status_code: res.status,
    duration_ms: Math.round(performance.now() - startedAt),
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
      const body = await res.json();
      if (body.field && body.message) {
        // Business-rule validation error: { field, message }
        field = body.field;
        message = body.message;
      } else if (body.detail) {
        // Not found / generic HTTPException: { detail }
        message = body.detail;
      }
    } catch {
      // response had no JSON body
    }
    throw new ApiError(message, res.status, field);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}