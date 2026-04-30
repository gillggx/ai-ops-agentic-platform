"use client";

import type { Kpis } from "./types";

/** AI 戰況 — auto_check throughput strip. Tier 1 placeholder uses live
 *  KPI counts; future versions can stream auto_check completions via SSE. */
export function PulseStrip({ kpis }: { kpis: Kpis | null }) {
  const runs = kpis?.auto_check_runs_last_hour ?? 0;
  const lat = kpis?.auto_check_avg_latency_s ?? null;
  const high = kpis?.high_severity_count ?? 0;
  return (
    <div className="alarm-center__pulse-strip">
      <span className={"pulse-dot" + (high > 0 ? " pulse-dot--high" : "")} />
      <span style={{ fontWeight: 600, color: "var(--text)" }}>AI 戰況</span>
      <span className="pulse-divider" />
      <span className="pulse-stat">
        Auto-check <strong>{runs}</strong> runs/hr
      </span>
      <span className="pulse-divider" />
      <span className="pulse-stat">
        Avg latency <strong>{lat != null ? `${Math.max(0, lat).toFixed(1)}s` : "—"}</strong>
      </span>
      <span className="pulse-divider" />
      <span className="pulse-stat">
        High <strong>{high}</strong>
      </span>
      <div style={{ flex: 1 }} />
      <span style={{ color: "var(--text-3)" }}>last hour · refreshed every 60s</span>
    </div>
  );
}
