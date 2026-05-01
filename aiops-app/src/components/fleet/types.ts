/** Mirror of FleetDtos in the Java backend.
 *  Wire format is snake_case (Jackson PropertyNamingStrategy.SNAKE_CASE). */

export interface FleetEquipment {
  id: string;
  name: string;
  health: "crit" | "warn" | "healthy";
  score: number;
  ooc: number;             // %
  ooc_count: number;
  alarms: number;
  fdc: number;
  lots24h: number;
  trend: "up" | "down" | "flat";
  note: string;
  hourly: number[];        // 24 buckets, oldest → newest
}

export interface FleetEquipmentResponse {
  since: string;
  as_of: string;
  total: number;
  equipment: FleetEquipment[];
}

export interface FleetConcern {
  id: string;
  rule_id: string;
  severity: "crit" | "warn";
  confidence: number;
  title: string;
  detail: string;
  tools: string[];
  steps: string[];
  evidence: number;
  actions: string[];
}

export interface FleetConcernResponse {
  since: string;
  as_of: string;
  concerns: FleetConcern[];
}

export interface FleetStats {
  fleet_ooc_rate: number;
  ooc_events: number;
  total_events: number;
  fdc_alerts: number;
  open_alarms: number;
  affected_lots: number;
  crit_count: number;
  warn_count: number;
  as_of: string;
}
