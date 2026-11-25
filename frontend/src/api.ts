import type { GenerateRequest, JobEvent, JobStatus } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : (body.detail ?? []).map((d: { msg: string }) => d.msg).join("; ") || detail;
    } catch {
      // keep statusText
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; mode: string; model: string; max_samples_per_job: number }>("/api/health"),

  departments: () => request<string[]>("/api/departments"),

  conditions: (department: string) =>
    request<{ department: string; source: "seed" | "llm"; conditions: string[] }>(
      `/api/departments/${encodeURIComponent(department)}/conditions`,
    ),

  generate: (body: GenerateRequest) =>
    request<JobStatus>("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

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
