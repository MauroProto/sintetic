import type {
  ArtifactsResponse,
  CreateJobInput,
  CreateJobResponse,
  DashboardExamplesResponse,
  ExamplePatch,
  ExamplesResponse,
  JobRecord,
  MetricsResponse,
  PdfListResponse,
  ProjectConfig,
  ProvidersInfo,
  SourceModeResult,
} from "./types";

async function request<T>(
  input: string,
  init: RequestInit = {},
  { parse = "json" }: { parse?: "json" | "text" | "none" } = {},
): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
      else if (body?.error) detail = body.error;
      else if (body?.message) detail = body.message;
    } catch {
      // ignore parse error
    }
    throw new ApiError(detail, response.status);
  }
  if (parse === "none") return undefined as T;
  if (parse === "text") return (await response.text()) as unknown as T;
  return (await response.json()) as T;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export const api = {
  getJobs(limit = 20): Promise<JobRecord[]> {
    return request<JobRecord[]>(`/api/jobs?limit=${limit}`);
  },
  getJob(jobId: string): Promise<JobRecord> {
    return request<JobRecord>(`/api/jobs/${jobId}`);
  },
  createJob(input: CreateJobInput): Promise<CreateJobResponse> {
    const body = new FormData();
    body.append("source_dir", input.source_dir);
    body.append("generate_eval", String(input.generate_eval));
    body.append("parser_mode", input.parser_mode);
    body.append("resource_profile", input.resource_profile);
    body.append("generation_workers", String(input.generation_workers));
    body.append("judge_workers", String(input.judge_workers));
    body.append("page_batch_size", String(input.page_batch_size));
    body.append("batch_pause_seconds", String(input.batch_pause_seconds));
    body.append("targets_per_chunk", String(input.targets_per_chunk));
    if (input.max_pdfs != null) {
      body.append("max_pdfs", String(input.max_pdfs));
    }
    if (input.max_pages_per_chunk != null) {
      body.append("max_pages_per_chunk", String(input.max_pages_per_chunk));
    }
    if (input.quality_preset) {
      body.append("quality_preset", input.quality_preset);
    }
    if (input.min_groundedness_score != null) {
      body.append("min_groundedness_score", String(input.min_groundedness_score));
    }
    if (input.min_overall_score != null) {
      body.append("min_overall_score", String(input.min_overall_score));
    }
    if (input.included_files && input.included_files.length > 0) {
      body.append("included_files", JSON.stringify(input.included_files));
    }
    return request<CreateJobResponse>("/api/jobs", { method: "POST", body });
  },
  listPdfs(sourceDir: string): Promise<PdfListResponse> {
    const url = `/api/pdfs?source_dir=${encodeURIComponent(sourceDir)}`;
    return request<PdfListResponse>(url);
  },
  controlJob(jobId: string, action: "pause" | "resume" | "cancel"): Promise<void> {
    return request<void>(`/api/jobs/${jobId}/${action}`, { method: "POST" }, { parse: "none" });
  },
  pickFolder(): Promise<{ path: string }> {
    return request<{ path: string }>("/api/pick-folder", { method: "POST" });
  },
  saveProviderKey(provider: string, apiKey: string): Promise<{ stored: boolean; provider: string }> {
    const body = new FormData();
    body.append("provider_name", provider);
    body.append("api_key", apiKey);
    return request("/api/provider/key", { method: "POST", body });
  },
  getSourceMode(sourceDir: string): Promise<SourceModeResult> {
    const url = `/api/source-mode?source_dir=${encodeURIComponent(sourceDir)}`;
    return request<SourceModeResult>(url);
  },
  getProviders(): Promise<ProvidersInfo> {
    return request<ProvidersInfo>("/api/providers");
  },
  setActiveProvider(provider: string): Promise<{ active: string }> {
    const body = new FormData();
    body.append("provider", provider);
    return request<{ active: string }>("/api/provider/active", { method: "POST", body });
  },
  getConfig(): Promise<{ yaml: string; config: ProjectConfig }> {
    return request<{ yaml: string; config: ProjectConfig }>("/api/config");
  },
  saveConfig(payload: { yaml?: string; config?: ProjectConfig }): Promise<{ yaml: string; config: ProjectConfig }> {
    return request<{ yaml: string; config: ProjectConfig }>("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },
  getExamples(
    jobId: string,
    params: {
      split?: string;
      accepted?: boolean | null;
      kind?: string;
      score_min?: number;
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<ExamplesResponse> {
    const search = new URLSearchParams();
    if (params.split) search.set("split", params.split);
    if (params.accepted != null) search.set("accepted", String(params.accepted));
    if (params.kind) search.set("kind", params.kind);
    if (params.score_min != null) search.set("score_min", String(params.score_min));
    search.set("limit", String(params.limit ?? 50));
    search.set("offset", String(params.offset ?? 0));
    return request<ExamplesResponse>(`/api/jobs/${jobId}/examples?${search.toString()}`);
  },
  getMetrics(jobId: string): Promise<MetricsResponse> {
    return request<MetricsResponse>(`/api/jobs/${jobId}/metrics`);
  },
  getDashboardExamples(params: {
    accepted?: boolean | null;
    kind?: string;
    score_min?: number;
    search?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<DashboardExamplesResponse> {
    const search = new URLSearchParams();
    if (params.accepted != null) search.set("accepted", String(params.accepted));
    if (params.kind) search.set("kind", params.kind);
    if (params.score_min != null) search.set("score_min", String(params.score_min));
    if (params.search) search.set("search", params.search);
    search.set("limit", String(params.limit ?? 100));
    search.set("offset", String(params.offset ?? 0));
    return request<DashboardExamplesResponse>(`/api/examples?${search.toString()}`);
  },
  patchExample(jobId: string, exampleId: string, split: string, patch: ExamplePatch) {
    return request(`/api/jobs/${jobId}/examples/${exampleId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ split, patch }),
    });
  },
  deleteExample(jobId: string, exampleId: string, split: string) {
    return request(
      `/api/jobs/${jobId}/examples/${exampleId}?split=${encodeURIComponent(split)}`,
      { method: "DELETE" },
    );
  },
  acceptExample(jobId: string, exampleId: string, split: string) {
    const body = new FormData();
    body.append("split", split);
    return request(`/api/jobs/${jobId}/examples/${exampleId}/accept`, {
      method: "POST",
      body,
    });
  },
  rejectExample(jobId: string, exampleId: string, split: string, reason = "manual_rejection") {
    const body = new FormData();
    body.append("split", split);
    body.append("reason", reason);
    return request(`/api/jobs/${jobId}/examples/${exampleId}/reject`, {
      method: "POST",
      body,
    });
  },
  getArtifacts(jobId: string): Promise<ArtifactsResponse> {
    return request<ArtifactsResponse>(`/api/jobs/${jobId}/artifacts`);
  },
  artifactDownloadUrl(jobId: string, relativePath: string): string {
    return `/api/jobs/${jobId}/artifacts/file?path=${encodeURIComponent(relativePath)}`;
  },
};
