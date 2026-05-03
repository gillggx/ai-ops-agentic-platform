"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pill, StatusDot } from "../primitives";
import { ModuleStatusRow } from "./ModuleStatusRow";
import { HealthTimeline } from "./HealthTimeline";
import { SpcChart } from "./SpcChart";
import { LineageView } from "./lineage/LineageView";
import { TopologyTab } from "./lineage/TopologyTab";
import type {
  ModuleStatus, ModulesResponse,
  TimelineResponse,
  SpcTrace, SpcTraceResponse,
} from "../eqp-types";
import type { FleetConcern, FleetEquipment } from "../types";

type TopTab = "trend" | "lineage";
type LineageSubTab = "topology" | "flow" | "params";

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
  const [topTab, setTopTab] = useState<TopTab>("trend");
  const [lineageSub, setLineageSub] = useState<LineageSubTab>("flow");

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

      {/* Top-level tabs */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--c-line)", gap: 0 }}>
        {([
          ["trend", "📈 健康趨勢"],
          ["lineage", "🔍 製程溯源"],
        ] as const).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTopTab(k as TopTab)}
            style={{
              padding: "10px 18px", fontSize: 13,
              fontWeight: topTab === k ? 600 : 400,
              color: topTab === k ? "var(--c-ink-1)" : "var(--c-ink-3)",
              background: "transparent",
              border: "none",
              borderBottom: topTab === k ? "2px solid var(--c-ink-1)" : "2px solid transparent",
              marginBottom: -1,
              cursor: "pointer", fontFamily: "inherit",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {topTab === "trend" && (
        <>
          {timeline && <HealthTimeline events={timeline.events} since={timeline.since} asOf={timeline.as_of} />}
          <div className="surface" style={{ padding: "14px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
              <div className="h2">趨勢</div>
              {/* Chart picker — populated dynamically from /spc-trace so any
                  chart_name the simulator emits is selectable (xbar / R / S /
                  P / C / future). Was hardcoded to C/P/R; now it reflects the
                  actual data. */}
              <select
                value={activeChart}
                onChange={e => setActiveChart(e.target.value)}
                disabled={traces.length === 0}
                style={{
                  height: 28, padding: "0 10px", fontSize: 12,
                  border: "1px solid var(--c-line-strong)",
                  borderRadius: 6, background: "var(--c-bg)",
                  color: "var(--c-ink-1)", cursor: traces.length ? "pointer" : "not-allowed",
                  fontFamily: "inherit",
                }}
              >
                {traces.length === 0 && <option value="">(無資料)</option>}
                {traces.map(t => (
                  <option key={t.chart} value={t.chart}>
                    {t.chart.replace("_chart", "").toUpperCase()} chart
                  </option>
                ))}
              </select>
            </div>
            {trace ? (
              <SpcChart trace={trace} />
            ) : (
              <div className="micro" style={{ color: "var(--c-ink-3)", padding: 16 }}>
                {traces.length === 0 ? "(此機台 24h 內無 SPC trace)" : "(切換選單看其他 chart)"}
              </div>
            )}
          </div>
        </>
      )}

      {topTab === "lineage" && (
        <div data-tour-id="eqp-lineage" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* sub tabs */}
          <div style={{ display: "flex", gap: 4 }}>
            {([
              ["flow", "流程溯源"],
              ["params", "參數檢視"],
              ["topology", "拓樸圖"],
            ] as const).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setLineageSub(k as LineageSubTab)}
                className={`btn ${lineageSub === k ? "btn-primary" : "btn-ghost"}`}
                style={{ height: 26, padding: "0 12px", fontSize: 12 }}
              >
                {label}
              </button>
            ))}
          </div>

          {lineageSub === "flow" && <LineageView toolId={toolId} mode="flow" />}
          {lineageSub === "params" && <LineageView toolId={toolId} mode="params" />}
          {lineageSub === "topology" && <TopologyTab toolId={toolId} />}
        </div>
      )}
    </div>
  );
}
