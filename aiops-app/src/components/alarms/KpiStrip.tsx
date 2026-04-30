"use client";

import type { Kpis } from "./types";

export function KpiStrip({ kpis }: { kpis: Kpis | null }) {
  if (!kpis) return <div className="alarm-center__kpi-strip" />;
  const cards: { label: string; value: string; tone?: "high" | "accent" }[] = [
    { label: "Active alarms", value: String(kpis.active_alarms) },
    { label: "Open clusters", value: String(kpis.open_clusters) },
    { label: "High severity", value: String(kpis.high_severity_count), tone: "high" },
    { label: "Health score", value: String(kpis.health_score), tone: kpis.health_score < 40 ? "high" : "accent" },
    { label: "MTTR (min)", value: kpis.mttr_minutes != null ? String(kpis.mttr_minutes) : "—" },
  ];
  return (
    <div className="alarm-center__kpi-strip" role="status" aria-label="alarm KPI summary">
      {cards.map(c => (
        <div key={c.label} className={"kpi-card" + (c.tone === "high" ? " kpi-card--high" : c.tone === "accent" ? " kpi-card--accent" : "")}>
          <div className="kpi-card__label">{c.label}</div>
          <div className="kpi-card__value">{c.value}</div>
        </div>
      ))}
      <div style={{ flex: 1 }} />
      <div className="kpi-card">
        <div className="kpi-card__label">As of</div>
        <div className="kpi-card__value" style={{ fontSize: 12, fontWeight: 500, color: "var(--text-3)" }}>
          {new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit" })}
        </div>
      </div>
    </div>
  );
}
