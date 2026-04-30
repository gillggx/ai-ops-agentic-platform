/** Mirror of AlarmClusterDtos in the Java backend. Keep field casing
 *  in sync with the actual JSON wire format (snake_case). */

export type Severity = "critical" | "high" | "med" | "low";

export interface Cluster {
  cluster_id: string;
  equipment_id: string;
  bay: string | null;
  severity: Severity;
  title: string;
  summary: string | null;
  trigger_events: string[];
  count: number;
  open_count: number;
  ack_count: number;
  resolved_count: number;
  affected_lots: number;
  first_at: string | null;
  last_at: string | null;
  spark: number[];
  cause: string | null;
  rootcause_confidence: number | null;
  alarm_ids: number[];
}

export interface ClusterListResponse {
  since: string;
  as_of: string;
  total_alarms: number;
  clusters: Cluster[];
}

export interface Kpis {
  active_alarms: number;
  open_clusters: number;
  high_severity_count: number;
  mttr_minutes: number | null;
  auto_check_runs_last_hour: number;
  auto_check_avg_latency_s: number | null;
  health_score: number;
}
