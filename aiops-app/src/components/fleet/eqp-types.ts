/** Mirrors FleetDtos Phase 2 records (SNAKE_CASE on the wire). */

export interface TimelineEvent {
  t: string;                    // ISO timestamp
  lane: "ooc" | "apc" | "fdc" | "ec" | "recipe" | "lot";
  severity: "crit" | "warn" | "info" | "ok";
  label: string;
  detail: string;
}

export interface TimelineResponse {
  equipment_id: string;
  since: string;
  as_of: string;
  events: TimelineEvent[];
}

export interface ModuleStatus {
  key: "SPC" | "APC" | "FDC" | "DC" | "EC";
  state: "crit" | "warn" | "ok";
  value: string;
  sub: string;
}

export interface ModulesResponse {
  equipment_id: string;
  as_of: string;
  modules: ModuleStatus[];
}

export interface SpcTrace {
  chart: string;                // e.g. "c_chart"
  values: number[];
  times: string[];
  ucl: number;
  lcl: number;
  target: number;
}

export interface SpcTraceResponse {
  equipment_id: string;
  as_of: string;
  charts: SpcTrace[];
}

// ── Phase 3: lineage view ───────────────────────────────────

export interface LotSummary {
  lot_id: string;
  recipe: string;
  started: string;
  events: number;
  duration_min: number;
  status: "ooc" | "warn" | "ok";
  latest_step: string;
  latest_event_time: string;     // raw simulator eventTime — feed to /topology
}

export interface LineageNode {
  title: string;
  value: string;
  sub: string;
  state: "crit" | "warn" | "ok" | "info" | "neutral";
  highlight: boolean;
}

export interface LineageFlow {
  inputs: LineageNode[];
  process: LineageNode[];
  outcomes: LineageNode[];
}

export interface ParameterRow {
  name: string;
  group: string;
  value: number | null;
  baseline: number;
  delta: string;
  state: "crit" | "warn" | "ok";
  history: number[];
}

export interface SelectedLotDetail {
  lot: LotSummary;
  lineage: LineageFlow;
  parameters: ParameterRow[];
}

export interface LineageResponse {
  equipment_id: string;
  as_of: string;
  lots: LotSummary[];
  selected: SelectedLotDetail | null;
}
