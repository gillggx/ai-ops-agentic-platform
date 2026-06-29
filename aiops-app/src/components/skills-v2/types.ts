/**
 * Skills v2 wire types — mirror SkillV2Service.SkillDto exactly.
 *
 * Note Jackson SNAKE_CASE convention (feedback_jackson_snake_case_wire):
 * record field {@code pipelineNodes} serialises as {@code pipeline_nodes}
 * on the wire. So this interface uses snake_case throughout.
 */

export type Role = "tool" | "patrol" | "datacheck";
export type TriggerKind = "schedule" | "event";

export interface Trigger {
  kind: TriggerKind;
  schedule?: string;
  target?: string;
  source?: string;       // event-driven: upstream patrol slug (alarm-driven)
  event?: string;        // event-driven: raw simulator event name (e.g. "OOC")
}

export interface EventType {
  name: string;
  description: string;
}

export interface PipelineNode {
  k: string;
  t: string;
  s: string;
  isVerdict?: boolean;
}

export interface Skill {
  id: number;
  slug: string;
  name: string;
  sub: string;
  nl: string;
  pipeline_id: number | null;
  pipeline_nodes: string;   // JSON-encoded PipelineNode[]
  has_alarm: boolean;
  in_type: string;
  out_type: string;
  role: Role;
  trigger_config: string | null;   // JSON-encoded Trigger
  alarm_gate: string | null;
  outcome: string | null;
  status: string;
  test_cases: string;
}

export interface AlarmSource {
  slug: string;
  name: string;
  sub: string;
}

// ── Catalogs from spec §2.2 ────────────────────────────────────────────────

export const SCHEDULES = ["每 30 分鐘", "每 1 小時", "每 2 小時", "每日 08:00"] as const;
export const TARGETS   = ["所有機台", "特定機台群 (Etch)", "單一機台"] as const;
export const GATES     = ["任一符合 → alarm", "全部符合 → alarm", "5 取 2 達標 → alarm"] as const;
export const OUTCOMES  = ["raise alarm · 可被下游接", "advisory only · 只通知", "接 action / workflow"] as const;

// ── Helpers ───────────────────────────────────────────────────────────────

export function parsePipelineNodes(raw: string): PipelineNode[] {
  if (!raw) return [];
  try { return JSON.parse(raw) as PipelineNode[]; } catch { return []; }
}

export function parseTrigger(raw: string | null): Trigger | null {
  if (!raw) return null;
  try { return JSON.parse(raw) as Trigger; } catch { return null; }
}

export function summarizeTrigger(t: Trigger | null): string {
  if (!t) return "— 未綁定 trigger";
  if (t.kind === "schedule") {
    return `⏱ ${t.schedule ?? "—"} · ${t.target ?? "—"}`;
  }
  if (t.event) return `⚡ on event ${t.event}`;
  return `⚡ on ${t.source ?? "—"} · alarm`;
}

export function roleLabel(role: Role): string {
  switch (role) {
    case "patrol":    return "Auto Patrol";
    case "datacheck": return "Data Check";
    case "tool":      return "工具 · 未啟動";
  }
}
