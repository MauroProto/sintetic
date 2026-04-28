export type JobStatus =
  | "queued"
  | "running"
  | "paused"
  | "pausing"
  | "resuming"
  | "completed"
  | "failed"
  | "cancelled";

export interface JobRecord {
  job_id: string;
  source_dir: string;
  provider: string;
  model: string;
  status: JobStatus | string;
  stage: string;
  percent: number;
  current_file: string | null;
  message: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  config: Record<string, unknown> & {
    dataset_mode?: "single_document" | "multi_document";
    dataset_mode_note?: string;
    parser_mode?: string;
    resource_profile?: string;
    generation_workers?: number;
    judge_workers?: number;
    page_batch_size?: number;
    batch_pause_seconds?: number;
    max_pdfs?: number;
    max_pages_per_chunk?: number;
    generate_eval?: boolean;
    quality_preset?: "strict" | "balanced" | "permissive";
    min_groundedness_score?: number;
    min_overall_score?: number;
  };
  stats: Record<string, unknown> & {
    pages_processed?: number;
    total_pages?: number;
    current_batch?: number;
    total_batches?: number;
    requests?: number;
    accepted?: number;
    rejected?: number;
    eta_seconds?: number;
    math_expressions?: number;
  };
  artifacts_dir: string;
  events?: JobEvent[];
}

export interface JobEvent {
  event_id: number;
  job_id: string;
  stage: string;
  status: string;
  percent: number;
  message: string | null;
  current_file: string | null;
  created_at: string;
  stats?: Record<string, unknown>;
}

export interface SourceModeResult {
  ok: boolean;
  pdf_count: number;
  dataset_mode: "single_document" | "multi_document" | null;
  label: string | null;
  message: string | null;
  note?: string | null;
}

export interface ProviderProfile {
  api_key_env: string;
  base_url: string;
  model: string;
  max_tokens: number;
  temperature: number;
  concurrency: number;
  extra_headers?: Record<string, string>;
}

export interface ProvidersInfo {
  active: string;
  profiles: Record<string, ProviderProfile>;
  keys_present: Record<string, boolean>;
}

export interface ProjectConfig {
  providers: {
    active: string;
    profiles: Record<string, ProviderProfile>;
  };
  parsing: {
    primary_parser: string;
    fallback_parser: string;
    default_language: string;
    enable_ocr: boolean;
    ocr_text_min_chars: number;
    render_page_images: boolean;
    page_image_dpi: number;
    multimodal_max_pages_per_chunk: number;
  };
  chunking: {
    strategy: string;
    target_tokens: number;
    overlap: number;
    max_pages_per_chunk: number | null;
  };
  generation: {
    resource_profile: string;
    generation_workers: number | null;
    judge_workers: number | null;
    prompt_version: string;
    backend: string;
    retries: number;
    max_generation_attempts_per_target: number;
    page_batch_size: number;
    batch_pause_seconds: number;
    mix: Record<string, number>;
    refusal_text: string;
  };
  filters: {
    preset: string;
    groundedness_threshold: number | null;
    overall_threshold: number | null;
  };
  review: {
    sample_size: number;
  };
  export: {
    require_eval_split: boolean;
  };
}

export interface JudgeScore {
  relevance: number;
  groundedness: number;
  format: number;
  difficulty: number;
  overall: number;
  rationale: string;
}

export interface GeneratedExample {
  example_id: string;
  doc_id: string;
  source_doc: string;
  chunk_ids: string[];
  page_range: [number, number];
  question_type: string;
  difficulty: string;
  language: string;
  is_answerable: boolean;
  question: string;
  answer: string;
  evidence: string[];
  reasoning: string | null;
  supporting_facts: string[];
  prompt_version: string;
  teacher_model: string;
  requested_kind: string | null;
  context_image_paths: string[];
  judge_score: JudgeScore | null;
  raw_response?: Record<string, unknown>;
}

export interface ExampleWithMeta extends GeneratedExample {
  split: "train" | "eval";
  accepted: boolean;
  reason?: string | null;
}

export interface ExamplesResponse {
  total: number;
  limit: number;
  offset: number;
  items: ExampleWithMeta[];
  filters: {
    split: string | null;
    accepted: boolean | null;
    kind: string | null;
    score_min: number | null;
  };
  available_splits: string[];
}

export interface DashboardExampleItem extends ExampleWithMeta {
  job_id: string;
}

export interface DashboardExamplesResponse {
  total: number;
  limit: number;
  offset: number;
  items: DashboardExampleItem[];
  aggregate: {
    types: Record<string, number>;
    avg_score: number;
    per_job: Record<string, { accepted: number; rejected: number }>;
  };
  filters: {
    accepted: boolean | null;
    kind: string | null;
    score_min: number | null;
    search: string | null;
  };
}

export interface ExamplePatch {
  question?: string;
  answer?: string;
  evidence?: string[];
  reasoning?: string | null;
  question_type?: string;
  difficulty?: string;
  is_answerable?: boolean;
}

export interface CuratedSummary {
  total_input: number;
  accepted: number;
  rejected: number;
  rejected_by_reason: Record<string, number>;
}

export interface MetricsResponse {
  job_id: string;
  progress: Record<string, unknown>;
  summaries: {
    train?: CuratedSummary;
    eval?: CuratedSummary;
  };
  type_distribution: {
    train: Record<string, number>;
    eval: Record<string, number>;
  };
  score_distribution: {
    train: { relevance: number[]; groundedness: number[]; overall: number[] };
    eval: { relevance: number[]; groundedness: number[]; overall: number[] };
  };
  acceptance: {
    train: { accepted: number; rejected: number };
    eval: { accepted: number; rejected: number };
  };
}

export interface ArtifactEntry {
  path: string;
  size: number;
  modified_at: string;
}

export interface ArtifactsResponse {
  job_id: string;
  root: string;
  items: ArtifactEntry[];
}

export interface CreateJobInput {
  source_dir: string;
  generate_eval: boolean;
  parser_mode: "auto" | "fast" | "ocr_safe";
  resource_profile: "low" | "balanced" | "throughput";
  generation_workers: number;
  judge_workers: number;
  page_batch_size: number;
  batch_pause_seconds: number;
  targets_per_chunk: number;
  max_pdfs?: number | null;
  max_pages_per_chunk?: number | null;
  quality_preset?: "strict" | "balanced" | "permissive" | null;
  min_groundedness_score?: number | null;
  min_overall_score?: number | null;
  included_files?: string[] | null;
}

export interface PdfEntry {
  path: string;
  size: number;
  modified_at: string;
}

export interface PdfListResponse {
  ok: boolean;
  root: string;
  count: number;
  items: PdfEntry[];
}

export interface CreateJobResponse {
  job_id: string;
  status: string;
  stage: string;
  dataset_mode: string;
  dataset_mode_label: string;
  note: string;
}
