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
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });

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