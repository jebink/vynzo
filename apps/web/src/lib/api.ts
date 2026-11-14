// Base client for the VYNZO API (services/api). Typed endpoints will come from packages/api-client.
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * A non-2xx response from the API. `status` lets callers tell a 404 from other failures;
 * `detail` is the API's own message (FastAPI `{"detail": "..."}`) when it sent one.
 */
export class ApiError extends Error {
  constructor(
    readonly method: string,
    readonly path: string,
    readonly status: number,
    readonly detail: string | null = null,
  ) {
    super(detail ?? `${method} ${path} failed: ${status}`);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, method });
  if (!response.ok) {
    throw new ApiError(method, path, response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

/** The string `detail` of a FastAPI error body, if there is one. */
async function readDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" ? detail : null;
  } catch {
    return null;
  }
}

export function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return request("GET", path, init);
}

export function apiPut<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  return request("PUT", path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    body: JSON.stringify(body),
  });
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}
