/**
 * Agent Builder API — Phase 3.2 Glass Box Agent client helpers.
 */

import type { PipelineJSON } from "./types";

const BASE = "/api/agent/build";

export interface AgentStreamEventChat {
  type: "chat";
  data: { content: string; highlight_nodes?: string[]; ts: number };
}

export interface AgentStreamEventOperation {
  type: "operation";
  data: {
    op: string;
    args: Record<string, unknown>;
    result: Record<string, unknown>;
    elapsed_ms: number;
    ts: number;
  };
}

export interface AgentStreamEventError {
  type: "error";
  data: { op: string; message: string; hint?: string; ts: number };
}

export interface AgentStreamEventDone {
  type: "done";
  data: {
    status: "finished" | "failed" | "cancelled";
    pipeline_json: PipelineJSON;
    summary?: string | null;
  };
}

/** PR-E3b: structured proposal (Apply / Dismiss UI on frontend). */
export interface SuggestionAction {
  tool: "add_node" | "connect" | "set_param" | "rename_node" | "remove_node";
  args: Record<string, unknown>;
}

export interface AgentStreamEventSuggestionCard {
  type: "suggestion_card";
  data: {
    summary: string;
    rationale?: string | null;
    actions: SuggestionAction[];
    ts: number;
  };
}

export type AgentStreamEvent =
  | AgentStreamEventChat
  | AgentStreamEventOperation
  | AgentStreamEventError
  | AgentStreamEventDone
  | AgentStreamEventSuggestionCard;

export async function createAgentSession(payload: {
  prompt: string;
  base_pipeline_id?: number;
}): Promise<{ session_id: string }> {
  // Java cutover v2: backend now uses {instruction, pipelineId, pipelineSnapshot}.
  // Callers still hand us the old shape — translate here so no other caller breaks.
  const wireBody: Record<string, unknown> = { instruction: payload.prompt };
  if (payload.base_pipeline_id != null) wireBody.pipelineId = payload.base_pipeline_id;
  const res = await fetch(`${BASE}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(wireBody),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`createAgentSession failed (${res.status}): ${text}`);
  }
  return res.json();
}

export async function cancelAgentSession(sessionId: string): Promise<void> {
  await fetch(`${BASE}/${encodeURIComponent(sessionId)}/cancel`, { method: "POST" });
}

export async function fetchAgentSession(sessionId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BASE}/${encodeURIComponent(sessionId)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`fetchAgentSession failed (${res.status})`);
  return res.json();
}

/** URL for EventSource streaming (relative). */
export function agentStreamUrl(sessionId: string): string {
  return `${BASE}/stream/${encodeURIComponent(sessionId)}`;
}
