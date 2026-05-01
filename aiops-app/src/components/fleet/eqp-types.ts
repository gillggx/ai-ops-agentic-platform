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
