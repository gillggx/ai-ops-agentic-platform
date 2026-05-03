/**
 * Topology Workbench v2 — shared types.
 *
 * The data model is a list of RUNS (each run = one completed process step).
 * All views derive from this stream: per-kind objects, co-occurrence links,
 * timeline density, focus neighbours.
 */

export type Kind = "tool" | "lot" | "recipe" | "apc" | "step" | "fdc" | "spc";
export type RunStatus = "ok" | "warn" | "alarm";

export const KIND_ORDER: Kind[] = ["tool", "lot", "recipe", "apc", "step", "fdc", "spc"];

export const KIND_COLOR: Record<Kind, string> = {
  tool:   "#e0245e",
  lot:    "#2563eb",
  recipe: "#16a34a",
  apc:    "#c026d3",
  step:   "#475569",
  fdc:    "#ea580c",
  spc:    "#0891b2",
};

export const KIND_LABEL: Record<Kind, string> = {
  tool: "TOOL", lot: "LOT", recipe: "RECIPE", apc: "APC",
  step: "STEP", fdc: "FDC", spc: "SPC",
};

export interface RunRecord {
  id:        string;
  eventTime: string;            // ISO
  lotID:     string;
  toolID:    string;
  step:      string;
  recipeID:  string;
  apcID:     string;
  fdcID:     string;
  spcID:     string;
  status:    RunStatus;
}

export interface RunsResponse {
  runs:      RunRecord[];
  window:    { from: string; to: string };
  kindStats: Record<Kind, number>;
  truncated: boolean;
}

/** A node in the derived ontology — one per (kind, id) pair appearing in runs. */
export interface ObjNode {
  id:      string;
  kind:    Kind;
  name:    string;
  runs:    number;
  alarms:  number;
  lastT:   number;            // epoch ms
}

/** A link = two object IDs that co-occurred in ≥1 run. */
export interface Link {
  a:        string;
  b:        string;
  count:    number;
  lastT:    number;
  anyAlarm: boolean;
}

export interface FocusRef {
  kind: Kind;
  id:   string;
}

export interface TweaksState {
  anomalyEmph: "none" | "subtle" | "strong";
  linkStyle:   "underline" | "border" | "tint";   // TraceView lane styling
}

export const DEFAULT_TWEAKS: TweaksState = {
  anomalyEmph: "subtle",
  linkStyle:   "underline",
};
