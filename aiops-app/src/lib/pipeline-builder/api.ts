/**
 * Pipeline Builder — fetch wrappers against /api/pipeline-builder/* proxy routes.
 */

import type {
  BlockSpec,
  ExecuteResponse,
  PipelineJSON,
  PipelineRecord,
  PipelineStatus,
  PipelineSummary,
  ValidationErrorItem,
} from "./types";

const BASE = "/api/pipeline-builder";

async function unwrap<T>(res: Response): Promise<T> {
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    // Java envelope: {ok:false, data:null, error:{message,...}}
    let msg = `HTTP ${res.status}`;
    if (data && typeof data === "object") {
      const obj = data as Record<string, unknown>;
      if ("error" in obj && obj.error && typeof obj.error === "object") {
        const err = obj.error as Record<string, unknown>;
        msg = (typeof err.message === "string" ? err.message : null) ?? JSON.stringify(err);
      } else if ("detail" in obj || "error" in obj) {
        msg = JSON.stringify(data);
      }
    }
    throw new Error(msg);
  }
  // Java envelope: {ok:true, data:{...}, error:null, timestamp:"..."} —
  // unwrap to inner `.data` so callers see the actual record.
  if (
    data &&
    typeof data === "object" &&
    "ok" in (data as Record<string, unknown>) &&
    "data" in (data as Record<string, unknown>)
  ) {
    return (data as { data: T }).data;
  }
  return data as T;
}

export async function listBlocks(category?: string): Promise<BlockSpec[]> {
  const q = category ? `?category=${encodeURIComponent(category)}` : "";
  const res = await fetch(`${BASE}/blocks${q}`, { cache: "no-store" });
  return unwrap<BlockSpec[]>(res);
}

export async function listPipelines(status?: PipelineStatus): Promise<PipelineSummary[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await fetch(`${BASE}/pipelines${q}`, { cache: "no-store" });
  return unwrap<PipelineSummary[]>(res);
}

// 2026-04-27 fix — Java's PipelineEntity.pipelineJson is a `text` column
// mapped to String, so the JSON ships across the wire as a JSON-encoded
// string ("{\"version\":\"1.0\",...}") instead of a nested object. Frontend
// code assumes it's already an object (and calls .nodes / .edges / .inputs
// directly), so BuilderLayout's edit page crashed with
// "Cannot read properties of undefined (reading 'length')". This helper
// hydrates pipeline_json into the typed shape on every PipelineRecord
// response so downstream consumers (BuilderContext, validators, save UI)
// don't have to know about the wire format.
function hydratePipelineJson(rec: PipelineRecord): PipelineRecord {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const raw = rec as any;
  if (typeof raw?.pipeline_json === "string") {
    try {
      raw.pipeline_json = JSON.parse(raw.pipeline_json);
    } catch {
      raw.pipeline_json = { version: "1.0", name: raw.name ?? "Broken Pipeline", nodes: [], edges: [], metadata: {} };
    }
  }
  return rec;
}

export async function getPipeline(id: number): Promise<PipelineRecord> {
  const res = await fetch(`${BASE}/pipelines/${id}`, { cache: "no-store" });
  return hydratePipelineJson(await unwrap<PipelineRecord>(res));
}

export async function createPipeline(payload: {
  name: string;
  description?: string;
  /** Phase 5-UX-7: 3-kind classification. */
  pipeline_kind?: "auto_patrol" | "auto_check" | "skill";
  pipeline_json: PipelineJSON;
}): Promise<PipelineRecord> {
  // Symmetric to hydratePipelineJson on read: Java's PipelineController
  // CreateRequest.pipelineJson is typed as String (text column), so we send
  // the nested PipelineJSON object as a JSON-encoded string. Without this,
  // Jackson rejects with HttpMessageNotReadableException → 500.
  const wirePayload = {
    ...payload,
    pipeline_json: payload.pipeline_json
      ? (typeof payload.pipeline_json === "string"
          ? payload.pipeline_json
          : JSON.stringify(payload.pipeline_json))
      : undefined,
  };
  const res = await fetch(`${BASE}/pipelines`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(wirePayload),
  });
  return hydratePipelineJson(await unwrap<PipelineRecord>(res));
}

export async function updatePipeline(
  id: number,
  payload: { name?: string; description?: string; pipeline_json?: PipelineJSON }
): Promise<PipelineRecord> {
  const wirePayload = {
    ...payload,
    pipeline_json: payload.pipeline_json
      ? (typeof payload.pipeline_json === "string"
          ? payload.pipeline_json
          : JSON.stringify(payload.pipeline_json))
      : undefined,
  };
  const res = await fetch(`${BASE}/pipelines/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(wirePayload),
  });
  return hydratePipelineJson(await unwrap<PipelineRecord>(res));
}

/** Legacy wrapper — prefer transitionPipeline(). Kept for older UI paths. */
export async function promotePipeline(
  id: number,
  target: "pi_run" | "production"
): Promise<PipelineSummary> {
  const res = await fetch(`${BASE}/pipelines/${id}/promote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_status: target }),
  });
  return unwrap<PipelineSummary>(res);
}

/** PR-B unified 5-stage transition. Throws on invalid move / failed gate. */
export async function transitionPipeline(
  id: number,
  to: PipelineStatus,
  notes?: string,
): Promise<PipelineSummary> {
  const res = await fetch(`${BASE}/pipelines/${id}/transition`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, ...(notes ? { notes } : {}) }),
  });
  return unwrap<PipelineSummary>(res);
}

/** Clone & Edit — create a draft copy of any non-draft pipeline. */
export async function clonePipeline(id: number): Promise<PipelineRecord> {
  return forkPipeline(id);
}

// Phase A — pb_pipeline_runs read API.

export interface PipelineRunSummary {
  id: number;
  pipeline_id: number | null;
  pipeline_version: string;
  triggered_by: string;
  /** running | success | failed | skipped | validation_error */
  status: string;
  /** JSON text — for auto_patrol fires it carries
   *  {patrol_id, fanout_count, triggered_count, targets:[{tool_id, status, triggered}]}.
   *  Caller can JSON.parse if it needs to drill in. */
  node_results: string | null;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
}

export async function listPipelineRuns(
  pipelineId: number,
  limit = 20,
): Promise<PipelineRunSummary[]> {
  const res = await fetch(
    `${BASE}/pipelines/${pipelineId}/runs?limit=${limit}`,
    { cache: "no-store" },
  );
  return unwrap<PipelineRunSummary[]>(res);
}

// PR-C — Publishing + Registry

export interface DraftDoc {
  slug: string;
  name: string;
  use_case: string;
  when_to_use: string[];
  inputs_schema: Array<{ name: string; type: string; required?: boolean; description?: string; example?: unknown }>;
  outputs_schema: Record<string, unknown>;
  example_invocation?: { inputs: Record<string, unknown> } | null;
  tags: string[];
}

export async function getDraftDoc(pipelineId: number): Promise<DraftDoc> {
  const res = await fetch(`${BASE}/pipelines/${pipelineId}/publish/draft-doc`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return unwrap<DraftDoc>(res);
}

export async function publishPipeline(
  pipelineId: number,
  reviewedDoc: DraftDoc,
  publishedBy?: string,
): Promise<PipelineSummary & { published_slug?: string }> {
  const res = await fetch(`${BASE}/pipelines/${pipelineId}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewed_doc: reviewedDoc, published_by: publishedBy ?? null }),
  });
  return unwrap(res);
}

export interface PublishedSkillRecord {
  id: number;
  pipeline_id: number;
  pipeline_version: string;
  slug: string;
  name: string;
  use_case: string;
  when_to_use: string[];
  inputs_schema: Array<Record<string, unknown>>;
  outputs_schema: Record<string, unknown>;
  tags: string[];
  status: string;
  published_by?: string | null;
  published_at?: string | null;
}

export async function listPublishedSkills(includeRetired = false): Promise<PublishedSkillRecord[]> {
  const res = await fetch(`${BASE}/published-skills?include_retired=${includeRetired}`, {
    cache: "no-store",
  });
  return unwrap<PublishedSkillRecord[]>(res);
}

export async function searchPublishedSkills(query: string, topK = 10): Promise<PublishedSkillRecord[]> {
  const res = await fetch(`${BASE}/published-skills/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK }),
  });
  return unwrap<PublishedSkillRecord[]>(res);
}

export async function retirePublishedSkill(skillId: number): Promise<PublishedSkillRecord> {
  const res = await fetch(`${BASE}/published-skills/${skillId}/retire`, {
    method: "POST",
  });
  return unwrap<PublishedSkillRecord>(res);
}

export async function forkPipeline(id: number): Promise<PipelineRecord> {
  const res = await fetch(`${BASE}/pipelines/${id}/fork`, { method: "POST" });
  return unwrap<PipelineRecord>(res);
}

export async function deletePipeline(id: number): Promise<void> {
  const res = await fetch(`${BASE}/pipelines/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    const body = await res.text();
    throw new Error(`DELETE pipeline ${id} failed: ${res.status} ${body}`);
  }
}

export async function deprecatePipeline(id: number): Promise<PipelineSummary> {
  const res = await fetch(`${BASE}/pipelines/${id}/deprecate`, { method: "POST" });
  return unwrap<PipelineSummary>(res);
}

export async function validatePipeline(
  pipeline_json: PipelineJSON
): Promise<{ valid: boolean; errors: ValidationErrorItem[] }> {
  const res = await fetch(`${BASE}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(pipeline_json),
  });
  return unwrap(res);
}

export async function executePipeline(
  pipeline_json: PipelineJSON,
  inputs?: Record<string, unknown>,
): Promise<ExecuteResponse> {
  const res = await fetch(`${BASE}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pipeline_json, triggered_by: "user", inputs: inputs ?? {} }),
  });
  return unwrap<ExecuteResponse>(res);
}

export async function fetchSuggestions(field: string): Promise<string[]> {
  try {
    const res = await fetch(`${BASE}/suggestions/${encodeURIComponent(field)}`, { cache: "no-store" });
    if (!res.ok) return [];
    const data = (await res.json()) as unknown;
    if (Array.isArray(data)) return data.filter((x): x is string => typeof x === "string");
    return [];
  } catch {
    return [];
  }
}

export async function previewNode(payload: {
  pipeline_json: PipelineJSON;
  node_id: string;
  sample_size?: number;
}): Promise<{
  status: string;
  target?: string;
  node_result?: {
    status: string;
    rows: number | null;
    duration_ms: number | null;
    error: string | null;
    preview: Record<string, unknown> | null;
  } | null;
  /** v1.3 C: per-node results for all ancestors that executed. */
  all_node_results?: Record<
    string,
    {
      status: string;
      rows: number | null;
      duration_ms: number | null;
      error: string | null;
      preview: Record<string, unknown> | null;
    }
  >;
  errors?: ValidationErrorItem[];
  error_message?: string | null;
  /** v3.2: pipeline-level summary (triggered + charts) */
  result_summary?: import("./types").PipelineResultSummary | null;
}> {
  const res = await fetch(`${BASE}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return unwrap(res);
}
