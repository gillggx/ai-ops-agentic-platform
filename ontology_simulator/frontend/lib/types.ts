export type Stage =
  | "STAGE_IDLE"
  | "STAGE_LOAD"
  | "STAGE_PROCESS"
  | "STAGE_ANALYSIS"
  | "STAGE_DONE_PASS"
  | "STAGE_DONE_OOC";

export interface MachineState {
  id: string;          // EQP-01 … EQP-10
  stage: Stage;
  lotId: string | null;
  recipe: string | null;
  apc: { active: boolean; mode: string };
  dc:  { active: boolean; collectionPlan: string };
  spc: { active: boolean };
  step: string | null;       // e.g. "STEP_088"
  apcId: string | null;      // e.g. "APC-088"
  bias: number | null;
  biasTrend: "UP" | "DOWN" | null;
  biasAlert: boolean;
  reflection: string | null;
  lastEvent: string | null;  // ISO timestamp
  processStartTime: number | null;
  // "EQUIPMENT" = mid-process hold (ACKNOWLEDGE resumes processing)
  // "SPC"       = post-process OOC (ACKNOWLEDGE resets to STANDBY)
  holdType: "EQUIPMENT" | "SPC" | null;
}

export interface EntityLinkEvent {
  type: "ENTITY_LINK";
  machine_id: string;
  data: { lot_id: string; recipe: string; status: string; timestamp: string };
}
export interface ToolLinkEvent {
  type: "TOOL_LINK";
  machine_id: string;
  data: {
    apc: { active: boolean; mode: string };
    dc:  { active: boolean; collection_plan: string };
    spc: { active: boolean };
  };
}
export interface MetricUpdateEvent {
  type: "METRIC_UPDATE";
  machine_id: string;
  target: string;
  data: {
    bias: number;
    unit: string;
    trend: "UP" | "DOWN";
    bias_alert: boolean;
    spc_status: "PASS" | "OOC";
    reflection: string | null;
    step: string;
    lot_id: string;
    timestamp: string;
  };
}
export interface MachineHoldEvent {
  type: "MACHINE_HOLD";
  machine_id: string;
  data: { reason: string; timestamp: string };
}

export type WsEvent = EntityLinkEvent | ToolLinkEvent | MetricUpdateEvent | MachineHoldEvent;
