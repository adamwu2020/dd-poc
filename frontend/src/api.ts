import type {
  Account,
  GenerateRequest,
  JobEvent,
  JobStatus,
  JobSummary,
  OrderView,
  Quote,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Called whenever the server says the session is gone, so the app can show the sign-in page. */
let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { credentials: "same-origin", ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : (body.detail ?? []).map((d: { msg: string }) => d.msg.replace(/^Value error, /, "")).join("; ") ||
            detail;
    } catch {
      // keep statusText
    }
    if (res.status === 401 && !url.startsWith("/api/auth/")) onUnauthorized();
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T>(url: string, body?: unknown) =>
  request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  health: () =>
    request<{ status: string; mode: string; model: string; max_samples_per_job: number; payment_mode: string }>(
      "/api/health",
    ),

  me: () => request<Account>("/api/auth/me"),
  account: () => request<Account>("/api/account"),
  register: (email: string, password: string) => post<Account>("/api/auth/register", { email, password }),
  login: (email: string, password: string) => post<Account>("/api/auth/login", { email, password }),
  logout: () => post<void>("/api/auth/logout"),

  departments: () => request<string[]>("/api/departments"),

  conditions: (department: string) =>
    request<{ department: string; source: "seed" | "llm"; conditions: string[] }>(
      `/api/departments/${encodeURIComponent(department)}/conditions`,
    ),

  quote: (body: GenerateRequest) => post<Quote>("/api/orders/quote", body),
  createOrder: (body: GenerateRequest) => post<OrderView>("/api/orders", body),
  order: (orderId: string) => request<OrderView>(`/api/orders/${orderId}`),
  cancelOrder: (orderId: string) => post<OrderView>(`/api/orders/${orderId}/cancel`),
  mockPay: (orderId: string) => post<OrderView>(`/api/orders/${orderId}/mock-pay`),

  jobs: () => request<JobSummary[]>("/api/jobs"),
  cancel: (jobId: string) => request<JobStatus>(`/api/jobs/${jobId}`, { method: "DELETE" }),

  exportUrl: (jobId: string, format: string, part: string) =>
    `/api/jobs/${jobId}/export?format=${format}&part=${part}`,

  /** Subscribe to job events. The server replays history on (re)connect, so handlers must be idempotent. */
  stream(jobId: string, onEvent: (e: JobEvent) => void): () => void {
    const source = new EventSource(`/api/jobs/${jobId}/stream`);
    const handle = (msg: MessageEvent) => {
      const event = JSON.parse(msg.data) as JobEvent;
      onEvent(event);
      if (event.type === "done") source.close();
    };
    for (const type of ["status", "sample", "sample_error", "done"]) {
      source.addEventListener(type, handle as EventListener);
    }
    return () => source.close();
  },
};

export function formatUsd(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}
