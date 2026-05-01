"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pill, StatusDot } from "../primitives";
import { ModuleStatusRow } from "./ModuleStatusRow";
import { HealthTimeline } from "./HealthTimeline";
import { SpcChart } from "./SpcChart";
import type {
  ModuleStatus, ModulesResponse,
  TimelineEvent, TimelineResponse,
  SpcTrace, SpcTraceResponse,
} from "../eqp-types";
import type { FleetConcern, FleetEquipment } from "../types";

const FONT_LINK = "https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap";

/** Phase 2: per-equipment detail view. Lays the handoff `eqp-detail.jsx`
 *  shape over the Mode B URL (?toolId=XX) of /dashboard. Reuses the
 *  fleet-overview tokens so visual continuity with Mode A is preserved. */
export function EqpDetail({ toolId, onBack }: { toolId: string; onBack?: () => void }) {
  const [equipment, setEquipment] = useState<FleetEquipment | null>(null);
  const [concerns, setConcerns] = useState<FleetConcern[]>([]);
  const [modules, setModules] = useState<ModuleStatus[]>([]);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [traces, setTraces] = useState<SpcTrace[]>([]);
  const [activeChart, setActiveChart] = useState<string>("c_chart");

  // Lazy-load fonts (same as Mode A).
  useEffect(() => {
    const id = "fleet-overview-fonts";
    if (document.getElementById(id)) return;
    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = FONT_LINK;
    document.head.appendChild(link);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [eqRes, cnRes, modRes, tlRes, trRes] = await Promise.all([
        fetch("/api/admin/fleet/equipment?since_hours=24"),
        fetch("/api/admin/fleet/concerns?since_hours=24"),
        fetch(`/api/admin/fleet/equipment/${toolId}/modules?since_hours=24`),
        fetch(`/api/admin/fleet/equipment/${toolId}/timeline?since_hours=24`),
        fetch(`/api/admin/fleet/equipment/${toolId}/spc-trace?limit=100`),
      ]);
      if (eqRes.ok) {
        const j = await eqRes.json();
        const me = (j.equipment ?? []).find((e: FleetEquipment) => e.id === toolId) ?? null;
        setEquipment(me);
      }
      if (cnRes.ok) {
        const j = await cnRes.json();
        setConcerns((j.concerns ?? []).filter((c: FleetConcern) => c.tools.includes(toolId)));
      }
      if (modRes.ok) {
        const j: ModulesResponse = await modRes.json();
        setModules(j.modules ?? []);
      }
      if (tlRes.ok) {
        const j: TimelineResponse = await tlRes.json();
        setTimeline(j);
      }
      if (trRes.ok) {
        const j: SpcTraceResponse = await trRes.json();
        setTraces(j.charts ?? []);
        if (j.charts && j.charts.length > 0 && !j.charts.some(c => c.chart === activeChart)) {
          setActiveChart(j.charts[0].chart);
        }
      }
    } catch { /* swallow — empty state shows */ }
  }, [toolId, activeChart]);

  useEffect(() => { refresh(); }, [toolId]); // eslint-disable-line

  const concern = concerns[0];
  const trace = useMemo(
    () => traces.find(t => t.chart === activeChart) ?? null,
    [traces, activeChart],
  );

  if (!equipment) {
    return (
      <div className="fleet-overview" style={{ padding: 40, color: "var(--c-ink-3)" }}>
        載入 {toolId}…
      </div>
    );
  }

  return (
    <div className="fleet-overview" style={{ paddingTop: 16 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 2 }}>
            {onBack && (
              <button className="btn btn-ghost" style={{ height: 24, padding: "0 8px" }} onClick={onBack}>
                ← 全廠總覽
              </button>
            )}
            <StatusDot status={equipment.health} size={10} />
            <div className="mono" style={{ fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em" }}>
              {equipment.id}
            </div>
            <Pill kind={equipment.health === "healthy" ? "ok" : equipment.health}>
              {equipment.score}/100
            </Pill>
          </div>
          {equipment.note && (
            <div className="small" style={{ color: "var(--c-ink-2)", marginTop: 4 }}>{equipment.note}</div>
          )}
        </div>
      </div>

      {/* AI banner */}
      {concern && (
        <div className={`surface stripe-${concern.severity}`} style={{ padding: "10px 14px", display: "flex", gap: 12, alignItems: "flex-start" }}>
          <span style={{ fontSize: 14, marginTop: 2 }}>✦</span>
          <div style={{ flex: 1 }}>
            <div className="h3" style={{ marginBottom: 2 }}>{concern.title}</div>
            <div className="small" style={{ color: "var(--c-ink-2)" }}>{concern.detail}</div>
          </div>
          <span className="micro mono" style={{ color: "var(--c-ink-3)" }}>
            {Math.round(concern.confidence * 100)}% conf.
          </span>
        </div>
      )}

      {/* Module status row */}
      <ModuleStatusRow modules={modules} />

      {/* Health timeline */}
      {timeline && <HealthTimeline events={timeline.events} since={timeline.since} asOf={timeline.as_of} />}

      {/* Trend drill-down */}
      <div className="surface" style={{ padding: "14px 16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
          <div className="h2">趨勢</div>
          <div style={{ display: "flex", gap: 4 }}>
            {(traces.length === 0 ? ["c_chart", "p_chart", "r_chart"] : traces.map(t => t.chart)).map(k => (
              <button
                key={k}
                onClick={() => setActiveChart(k)}
                className={`btn ${activeChart === k ? "btn-primary" : "btn-ghost"}`}
                style={{ height: 24, padding: "0 8px", fontSize: 11 }}
              >
                {k.replace("_chart", "").toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        {trace ? (
          <SpcChart trace={trace} />
        ) : (
          <div className="micro" style={{ color: "var(--c-ink-3)", padding: 16 }}>
            (此 chart 沒 trace；切換上方 tab 看其他)
          </div>
        )}
      </div>
    </div>
  );
}
