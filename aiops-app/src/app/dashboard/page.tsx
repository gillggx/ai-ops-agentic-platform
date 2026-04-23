"use client";

/**
 * Dashboard — Equipment monitoring with dual-mode:
 *   Mode A (Fab Briefing): no toolId → fab-wide OOC heatmap + AI summary
 *   Mode B (Tool Deep Dive): ?toolId=EQP-XX → 6-tab data + OOC topology + AI diagnosis
 *
 * Key principles:
 *   - Single get_process_info call → frontend cache → zero API on tab switch
 *   - 5-minute auto-refresh with manual refresh button
 *   - Collapsible equipment sidebar (280px ↔ 48px)
 */

import { Suspense, useEffect, useState, useCallback, useRef, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import ReactMarkdown from "react-markdown";

// Lazy-load Plotly (no SSR)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = dynamic(async () => {
  const Plotly = await import("plotly.js-dist-min");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const factory = (await import("react-plotly.js/factory")).default as (p: any) => React.ComponentType<any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return { default: factory((Plotly as any).default ?? Plotly) };
}, { ssr: false, loading: () => <div style={{ padding: 24, textAlign: "center", color: "#a0aec0" }}>載入圖表...</div> });

// ── Types ─────────────────────────────────────────────────────────────────────

type ToolStatus = { tool_id: string; status: string };
type ProcessEvent = Record<string, unknown>;

// ── Constants ─────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes
const TABS = ["SPC", "APC", "DC", "RECIPE", "FDC", "EC"] as const;
type TabKey = typeof TABS[number];

const STATUS_COLOR: Record<string, string> = {
  Busy: "#48bb78", Idle: "#a0aec0", Maintenance: "#ed8936", Down: "#e53e3e",
};

// ── Styles ─────────────────────────────────────────────────────────────────────

const S = {
  page: { display: "flex", height: "100vh", background: "#f7f8fc", overflow: "hidden" } as React.CSSProperties,
  sidebar: (collapsed: boolean): React.CSSProperties => ({
    width: collapsed ? 48 : 220,
    minWidth: collapsed ? 48 : 220,
    background: "#f8f9fa",
    color: "#2d3748",
    display: "flex",
    flexDirection: "column",
    transition: "width 0.2s, min-width 0.2s",
    overflow: "hidden",
    borderRight: "1px solid #e2e8f0",
  }),
  sidebarHeader: { padding: "14px 16px", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", justifyContent: "space-between" } as React.CSSProperties,
  toolItem: (selected: boolean): React.CSSProperties => ({
    padding: "10px 16px",
    display: "flex",
    alignItems: "center",
    gap: 10,
    cursor: "pointer",
    background: selected ? "#e3f2fd" : "transparent",
    borderLeft: selected ? "3px solid #2b6cb0" : "3px solid transparent",
    fontSize: 13,
    color: "#2d3748",
    fontWeight: selected ? 600 : 400,
  }),
  main: { flex: 1, overflowY: "auto", minWidth: 0 } as React.CSSProperties,
  topPanel: { padding: "16px 24px", background: "#fff", borderBottom: "1px solid #e2e8f0", maxHeight: 240, overflowY: "auto" } as React.CSSProperties,
  bottomPanel: { flex: 1, display: "flex", overflow: "hidden" } as React.CSSProperties,
  dataPanel: { flex: 6, display: "flex", flexDirection: "column", overflow: "hidden", borderRight: "1px solid #e2e8f0" } as React.CSSProperties,
  topoPanel: { flex: 4, display: "flex", flexDirection: "column", overflow: "hidden", background: "#fafbfc" } as React.CSSProperties,
  tabBar: { display: "flex", borderBottom: "1px solid #e2e8f0", background: "#fff" } as React.CSSProperties,
  tab: (active: boolean): React.CSSProperties => ({
    padding: "8px 16px", fontSize: 12, fontWeight: active ? 700 : 400,
    color: active ? "#2b6cb0" : "#718096", cursor: "pointer",
    borderBottom: active ? "2px solid #2b6cb0" : "2px solid transparent",
    background: "transparent", border: "none",
  }),
  tabContent: { flex: 1, overflowY: "auto", padding: "16px 20px" } as React.CSSProperties,
  refreshBar: { display: "flex", alignItems: "center", gap: 8, padding: "6px 12px", fontSize: 11, color: "#718096", background: "#f7f8fc", borderBottom: "1px solid #e2e8f0" } as React.CSSProperties,
  badge: (color: string): React.CSSProperties => ({
    display: "inline-block", padding: "2px 8px", borderRadius: 10,
    fontSize: 10, fontWeight: 600, background: `${color}20`, color,
  }),
};

// ── Data fetch helpers ────────────────────────────────────────────────────────

async function fetchTools(): Promise<ToolStatus[]> {
  try {
    const r = await fetch("/api/ontology/tools");
    const d = await r.json();
    return Array.isArray(d) ? d : (d?.data ?? d?.tools ?? []);
  } catch { return []; }
}

async function fetchProcessInfo(toolId: string, limit = 50): Promise<{ total: number; events: ProcessEvent[] }> {
  try {
    const r = await fetch(`/api/ontology/process/info?toolID=${toolId}&limit=${limit}`);
    const d = await r.json();
    return { total: d?.total ?? 0, events: d?.events ?? [] };
  } catch { return { total: 0, events: [] }; }
}

async function fetchSummary(): Promise<Record<string, unknown>> {
  try {
    const r = await fetch("/api/ontology/process/summary?since=24h");
    const d = await r.json();
    return d ?? {};
  } catch { return {}; }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function BriefingPanel({ scope, toolId }: { scope: "fab" | "tool"; toolId?: string }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const fetchBriefing = useCallback(async () => {
    setLoading(true);
    setText("");
    try {
      const params = new URLSearchParams({ scope });
      if (toolId) params.set("toolId", toolId);
      const res = await fetch(`/api/admin/briefing?${params}`);
      const reader = res.body?.getReader();
      if (!reader) return;
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          // Accept both "data: {...}" (Python sse-starlette) and "data:{...}"
          // (Spring SseEmitter) — SSE spec allows either.
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).replace(/^\s/, "");
          try {
            const ev = JSON.parse(payload);
            if (ev.type === "chunk") setText(prev => prev + ev.text);
            else if (ev.type === "error") setText(prev => prev + `\n⚠️ ${ev.message}`);
          } catch { /* ignore */ }
        }
      }
    } catch (e) {
      setText(`⚠️ 簡報載入失敗: ${e}`);
    } finally {
      setLoading(false);
    }
  }, [scope, toolId]);

  useEffect(() => { fetchBriefing(); }, [fetchBriefing]);

  return (
    <div style={{ background: "#fff", border: "1px solid #e8e8e8", borderRadius: 8, overflow: "hidden", boxShadow: "0 1px 2px rgba(0,0,0,0.03)" }}>
      {/* Collapsible header */}
      <div onClick={() => setCollapsed(c => !c)} style={{
        padding: "14px 20px", background: "#fafafa", cursor: "pointer",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        borderBottom: collapsed ? "none" : "1px solid #e8e8e8",
        transition: "background 0.15s",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 18 }}>✨</span>
          <span style={{ fontSize: 14, fontWeight: 600, color: "#262626" }}>
            {scope === "fab" ? "AI Summary" : `AI Summary — ${toolId}`}
          </span>
          {loading && <span style={{ fontSize: 11, color: "#1890ff" }}>生成中...</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button onClick={(e) => { e.stopPropagation(); fetchBriefing(); }} style={{
            padding: "3px 10px", fontSize: 11, borderRadius: 4,
            border: "1px solid #d9d9d9", background: "#fff", cursor: "pointer", color: "#666",
          }}>
            🔄 重新生成
          </button>
          <span style={{ color: "#999", fontSize: 12, transition: "transform 0.3s", transform: collapsed ? "rotate(-180deg)" : "none" }}>
            ▼
          </span>
        </div>
      </div>

      {/* Content (collapsible) */}
      <div style={{
        maxHeight: collapsed ? 0 : "none",
        opacity: collapsed ? 0 : 1,
        padding: collapsed ? "0 20px" : "16px 20px",
        overflow: "hidden",
        transition: "opacity 0.3s ease, padding 0.3s ease",
      }}>
        <div style={{ fontSize: 13, lineHeight: 1.8, color: "#2d3748" }}>
          {text ? (
            <div>
              <ReactMarkdown>{text}</ReactMarkdown>
              {loading && <span style={{ display: "inline-block", width: 8, height: 16, background: "#1890ff", animation: "blink 1s step-end infinite", marginLeft: 2, verticalAlign: "text-bottom" }} />}
            </div>
          ) : loading ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#a0aec0" }}>
              <span style={{ display: "inline-block", width: 8, height: 16, background: "#1890ff", animation: "blink 1s step-end infinite" }} />
              <span>AI 正在分析資料並生成簡報...</span>
            </div>
          ) : (
            <span style={{ color: "#a0aec0" }}>（無簡報）</span>
          )}
        </div>
      </div>
      <style>{`@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }`}</style>
    </div>
  );
}

function DataTable({ data, columns }: { data: Record<string, unknown>[]; columns?: string[] }) {
  if (!data || data.length === 0) return <div style={{ color: "#a0aec0", fontSize: 12, padding: 16 }}>（無資料）</div>;
  const cols = columns ?? Object.keys(data[0]).filter(k => !["_id", "eventTime", "lotID", "toolID", "step", "objectName", "objectID", "last_updated_time", "updated_by"].includes(k));
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead><tr>{cols.map(c => (
          <th key={c} style={{ background: "#f7fafc", padding: "6px 10px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "2px solid #e2e8f0", whiteSpace: "nowrap" }}>{c}</th>
        ))}</tr></thead>
        <tbody>{data.map((row, i) => (
          <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#f7fafc" }}>
            {cols.map(c => (
              <td key={c} style={{ padding: "5px 10px", borderBottom: "1px solid #edf2f7", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                {typeof row[c] === "object" ? JSON.stringify(row[c]) : String(row[c] ?? "—")}
              </td>
            ))}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function SPCTab({ events }: { events: ProcessEvent[] }) {
  // Flatten SPC data for chart rendering
  const chartData = useMemo(() => {
    const flat: Record<string, unknown>[] = [];
    for (const ev of events) {
      const spc = (ev.SPC as Record<string, unknown>) ?? {};
      const charts = (spc.charts as Record<string, Record<string, unknown>>) ?? {};
      for (const [chartType, cd] of Object.entries(charts)) {
        flat.push({
          eventTime: ev.eventTime,
          chart_type: chartType,
          value: cd.value,
          ucl: cd.ucl,
          lcl: cd.lcl,
          is_ooc: cd.is_ooc,
          lotID: ev.lotID,
        });
      }
    }
    return flat;
  }, [events]);

  const groups = useMemo(() => {
    const g: Record<string, typeof chartData> = {};
    for (const row of chartData) {
      const ct = row.chart_type as string;
      (g[ct] ??= []).push(row);
    }
    return Object.entries(g).sort(([a], [b]) => a.localeCompare(b));
  }, [chartData]);

  const TITLE_MAP: Record<string, string> = {
    xbar_chart: "X-bar Chart", r_chart: "R Chart", s_chart: "S Chart", p_chart: "P Chart", c_chart: "C Chart",
  };

  if (groups.length === 0) return <div style={{ color: "#a0aec0", padding: 16 }}>（無 SPC 資料）</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {groups.map(([chartType, rows]) => {
        const xs = rows.map(r => String(r.eventTime).slice(5, 19));
        const ys = rows.map(r => r.value as number);
        const ucl = (rows[0]?.ucl as number) ?? 0;
        const lcl = (rows[0]?.lcl as number) ?? 0;
        const cl = ys.length > 0 ? ys.reduce((a, b) => a + b, 0) / ys.length : 0;
        const oocIdx = rows.map((r, i) => r.is_ooc ? i : -1).filter(i => i >= 0);

        return (
          <div key={chartType} style={{ background: "#fff", borderRadius: 8, border: "1px solid #e2e8f0", overflow: "hidden" }}>
            <div style={{ padding: "6px 12px", fontSize: 12, fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0" }}>
              {TITLE_MAP[chartType] ?? chartType}
            </div>
            <Plot
              data={[
                { x: xs, y: ys, type: "scatter", mode: "lines+markers", name: "value",
                  line: { color: "#48bb78", width: 2 }, marker: { size: 4, color: "#48bb78" } },
                ...(oocIdx.length > 0 ? [{
                  x: oocIdx.map(i => xs[i]),
                  y: oocIdx.map(i => ys[i]),
                  type: "scatter" as const, mode: "markers" as const, name: "OOC",
                  marker: { color: "#e53e3e", size: 10, symbol: "circle-open", line: { width: 2, color: "#e53e3e" } },
                }] : []),
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              ] as any}
              layout={{
                autosize: true, height: 180, margin: { l: 45, r: 16, t: 8, b: 36 },
                paper_bgcolor: "transparent", plot_bgcolor: "#fafbfc",
                font: { family: "Inter, sans-serif", size: 10 },
                showlegend: false,
                xaxis: { gridcolor: "#e2e8f0" },
                yaxis: { gridcolor: "#e2e8f0" },
                shapes: [
                  { type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: ucl, y1: ucl, line: { color: "#e53e3e", width: 1, dash: "dash" } },
                  { type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: lcl, y1: lcl, line: { color: "#e53e3e", width: 1, dash: "dash" } },
                  { type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: cl, y1: cl, line: { color: "#718096", width: 1, dash: "dot" } },
                ],
                annotations: [
                  { xref: "paper", yref: "y", x: 1, y: ucl, text: `UCL ${ucl}`, font: { size: 9, color: "#e53e3e" }, showarrow: false, xanchor: "right" },
                  { xref: "paper", yref: "y", x: 1, y: lcl, text: `LCL ${lcl}`, font: { size: 9, color: "#e53e3e" }, showarrow: false, xanchor: "right" },
                ],
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: "100%" }}
              useResizeHandler
            />
          </div>
        );
      })}
    </div>
  );
}

function APCTab({ events }: { events: ProcessEvent[] }) {
  const latest = events[0];
  if (!latest) return <div style={{ color: "#a0aec0", padding: 16 }}>（無資料）</div>;
  const apc = (latest.APC as Record<string, unknown>) ?? {};
  const params = (apc.parameters as Record<string, unknown>) ?? {};
  const ACTIVE = new Set(["etch_time_offset", "rf_power_bias", "gas_flow_comp", "ff_correction", "fb_correction"]);
  const rows = Object.entries(params).map(([k, v]) => ({
    parameter: k,
    value: typeof v === "number" ? v.toFixed(6) : String(v),
    type: ACTIVE.has(k) ? "🟢 Active" : "⚪ Passive",
  }));
  return <DataTable data={rows} columns={["parameter", "value", "type"]} />;
}

function DCTab({ events }: { events: ProcessEvent[] }) {
  const latest = events[0];
  if (!latest) return <div style={{ color: "#a0aec0", padding: 16 }}>（無資料）</div>;
  const dc = (latest.DC as Record<string, unknown>) ?? {};
  const params = (dc.parameters as Record<string, unknown>) ?? {};
  const rows = Object.entries(params).map(([k, v]) => ({
    sensor: k,
    value: typeof v === "number" ? v.toFixed(4) : String(v),
  }));
  return <DataTable data={rows} columns={["sensor", "value"]} />;
}

function RecipeTab({ events }: { events: ProcessEvent[] }) {
  const latest = events[0];
  if (!latest) return <div style={{ color: "#a0aec0", padding: 16 }}>（無資料）</div>;
  const recipe = (latest.RECIPE as Record<string, unknown>) ?? {};
  const version = recipe.recipe_version ?? "?";
  const params = (recipe.parameters as Record<string, unknown>) ?? {};
  const rows = Object.entries(params).map(([k, v]) => ({ parameter: k, value: String(v) }));
  return (
    <div>
      <div style={{ padding: "8px 0", fontSize: 13, fontWeight: 600, color: "#2d3748" }}>
        Recipe Version: <span style={S.badge("#2b6cb0")}>v{String(version)}</span>
      </div>
      <DataTable data={rows} columns={["parameter", "value"]} />
    </div>
  );
}

function FDCTab({ events }: { events: ProcessEvent[] }) {
  const latest = events[0];
  if (!latest) return <div style={{ color: "#a0aec0", padding: 16 }}>（無資料）</div>;
  const fdc = (latest.FDC as Record<string, unknown>) ?? {};
  const classif = String(fdc.classification ?? "UNKNOWN");
  const classifColor = classif === "FAULT" ? "#e53e3e" : classif === "WARNING" ? "#dd6b20" : "#48bb78";
  return (
    <div style={{ padding: 8 }}>
      <div style={{ marginBottom: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Classification: </span>
        <span style={S.badge(classifColor)}>{classif}</span>
      </div>
      {fdc.fault_code ? <div style={{ fontSize: 12, color: "#4a5568", marginBottom: 4 }}>Fault Code: <strong>{String(fdc.fault_code)}</strong></div> : null}
      {fdc.confidence ? <div style={{ fontSize: 12, color: "#4a5568", marginBottom: 4 }}>Confidence: <strong>{String(fdc.confidence)}</strong></div> : null}
      {fdc.description ? <div style={{ fontSize: 12, color: "#4a5568", marginBottom: 4 }}>Description: {String(fdc.description)}</div> : null}
      {Array.isArray(fdc.contributing_sensors) && (fdc.contributing_sensors as string[]).length > 0 ? (
        <div style={{ fontSize: 12, color: "#4a5568" }}>
          Contributing Sensors: {(fdc.contributing_sensors as string[]).join(", ")}
        </div>
      ) : null}
    </div>
  );
}

function ECTab({ events }: { events: ProcessEvent[] }) {
  const latest = events[0];
  if (!latest) return <div style={{ color: "#a0aec0", padding: 16 }}>（無資料）</div>;
  const ec = (latest.EC as Record<string, unknown>) ?? {};
  const constants = (ec.constants as Record<string, Record<string, unknown>>) ?? {};
  const statusColor = (s: string) => s === "ALERT" ? "#e53e3e" : s === "DRIFT" ? "#dd6b20" : "#48bb78";
  const rows = Object.entries(constants).map(([k, v]) => ({
    constant: k,
    value: String(v.value ?? "—"),
    nominal: String(v.nominal ?? "—"),
    deviation: `${v.deviation_pct ?? "—"}%`,
    status: String(v.status ?? "—"),
    unit: String(v.unit ?? ""),
  }));
  return (
    <div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead><tr>
          {["Constant", "Value", "Nominal", "Deviation", "Status", "Unit"].map(h => (
            <th key={h} style={{ background: "#f7fafc", padding: "6px 10px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "2px solid #e2e8f0" }}>{h}</th>
          ))}
        </tr></thead>
        <tbody>{rows.map((row, i) => (
          <tr key={row.constant} style={{ background: i % 2 === 0 ? "#fff" : "#f7fafc" }}>
            <td style={{ padding: "5px 10px", borderBottom: "1px solid #edf2f7", fontWeight: 600 }}>{row.constant}</td>
            <td style={{ padding: "5px 10px", borderBottom: "1px solid #edf2f7" }}>{row.value}</td>
            <td style={{ padding: "5px 10px", borderBottom: "1px solid #edf2f7" }}>{row.nominal}</td>
            <td style={{ padding: "5px 10px", borderBottom: "1px solid #edf2f7" }}>{row.deviation}</td>
            <td style={{ padding: "5px 10px", borderBottom: "1px solid #edf2f7" }}>
              <span style={S.badge(statusColor(row.status))}>{row.status}</span>
            </td>
            <td style={{ padding: "5px 10px", borderBottom: "1px solid #edf2f7", color: "#a0aec0" }}>{row.unit}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

// ── Process Trace & Inspector Panel ──────────────────────────────────────────

type DeepDiveMode = "trend" | "trace";
type TraceNodeType = "RECIPE" | "FDC" | "EC" | "TOOL" | "LOT" | "SPC" | "APC" | "DC";

interface TraceNode {
  id: string;
  type: TraceNodeType;
  label: string;
  color: string;
  x: number;
  y: number;
}

function ProcessTracePanel({ events, toolId }: { events: ProcessEvent[]; toolId: string }) {
  // Group events by lotID, pick recent 10 lots
  const lots = useMemo(() => {
    const lotMap = new Map<string, ProcessEvent[]>();
    for (const ev of events) {
      const lid = String(ev.lotID ?? "?");
      if (!lotMap.has(lid)) lotMap.set(lid, []);
      lotMap.get(lid)!.push(ev);
    }
    return [...lotMap.entries()].slice(0, 10);
  }, [events]);

  const [selectedLotIdx, setSelectedLotIdx] = useState(0);
  const [selectedNode, setSelectedNode] = useState<TraceNodeType | null>(null);

  const selectedLot = lots[selectedLotIdx];
  const lotId = selectedLot?.[0] ?? "—";
  const lotEvents = selectedLot?.[1] ?? [];
  const latestEvent = lotEvents[0];

  // Determine node statuses from latest event
  const spcStatus = String(latestEvent?.spc_status ?? "PASS");
  const fdcClassif = String((latestEvent?.FDC as Record<string, unknown>)?.classification ?? "NORMAL");
  const recipeVer = String((latestEvent?.RECIPE as Record<string, unknown>)?.recipe_version ?? "?");

  // Build hierarchical topology nodes (left-to-right flow)
  // Layer 1 (x=60):  Recipe, FDC, EC  (upstream context)
  // Layer 2 (x=220): Tool             (center)
  // Layer 3 (x=380): Lot              (process entity)
  // Layer 4 (x=540): SPC, APC, DC     (downstream results)
  const topoNodes: TraceNode[] = useMemo(() => [
    { id: "recipe", type: "RECIPE", label: `Recipe v${recipeVer}`, color: "#38a169", x: 60, y: 60 },
    { id: "fdc",    type: "FDC",    label: `FDC: ${fdcClassif}`, color: fdcClassif === "FAULT" ? "#e53e3e" : fdcClassif === "WARNING" ? "#dd6b20" : "#38a169", x: 60, y: 150 },
    { id: "ec",     type: "EC",     label: "EC Constants", color: "#805ad5", x: 60, y: 240 },
    { id: "tool",   type: "TOOL",   label: toolId, color: "#3182ce", x: 220, y: 150 },
    { id: "lot",    type: "LOT",    label: lotId, color: spcStatus === "OOC" ? "#e53e3e" : "#3182ce", x: 380, y: 150 },
    { id: "spc",    type: "SPC",    label: `SPC: ${spcStatus}`, color: spcStatus === "OOC" ? "#e53e3e" : "#48bb78", x: 540, y: 60 },
    { id: "apc",    type: "APC",    label: "APC Params", color: "#d69e2e", x: 540, y: 150 },
    { id: "dc",     type: "DC",     label: "DC Sensors", color: "#718096", x: 540, y: 240 },
  ], [toolId, lotId, spcStatus, fdcClassif, recipeVer]);

  // Edges: upstream → tool → lot → downstream
  const edges: [string, string][] = [
    ["recipe", "tool"], ["fdc", "tool"], ["ec", "tool"],
    ["tool", "lot"],
    ["lot", "spc"], ["lot", "apc"], ["lot", "dc"],
  ];

  // Inspector data based on selected node
  const inspectorData = useMemo(() => {
    if (!latestEvent || !selectedNode) return null;
    switch (selectedNode) {
      case "SPC": {
        const spc = (latestEvent.SPC as Record<string, unknown>) ?? {};
        const charts = (spc.charts as Record<string, Record<string, unknown>>) ?? {};
        return Object.entries(charts).map(([k, v]) => ({
          chart: k, value: String(v.value ?? "—"), ucl: String(v.ucl ?? "—"),
          lcl: String(v.lcl ?? "—"), is_ooc: v.is_ooc ? "🔴 OOC" : "✅ PASS",
        }));
      }
      case "APC": {
        const apc = (latestEvent.APC as Record<string, unknown>) ?? {};
        const params = (apc.parameters as Record<string, unknown>) ?? {};
        const ACTIVE = new Set(["etch_time_offset", "rf_power_bias", "gas_flow_comp", "ff_correction", "fb_correction"]);
        return Object.entries(params).map(([k, v]) => ({
          parameter: k, value: typeof v === "number" ? v.toFixed(6) : String(v),
          type: ACTIVE.has(k) ? "Active" : "Passive",
        }));
      }
      case "DC": {
        const dc = (latestEvent.DC as Record<string, unknown>) ?? {};
        const params = (dc.parameters as Record<string, unknown>) ?? {};
        return Object.entries(params).map(([k, v]) => ({
          sensor: k, value: typeof v === "number" ? v.toFixed(4) : String(v),
        }));
      }
      case "RECIPE": {
        const recipe = (latestEvent.RECIPE as Record<string, unknown>) ?? {};
        const params = (recipe.parameters as Record<string, unknown>) ?? {};
        return [
          { field: "recipe_version", value: String(recipe.recipe_version ?? "—") },
          ...Object.entries(params).map(([k, v]) => ({ field: k, value: String(v) })),
        ];
      }
      case "FDC": {
        const fdc = (latestEvent.FDC as Record<string, unknown>) ?? {};
        return [
          { field: "classification", value: String(fdc.classification ?? "—") },
          { field: "fault_code", value: String(fdc.fault_code ?? "—") },
          { field: "confidence", value: String(fdc.confidence ?? "—") },
          { field: "description", value: String(fdc.description ?? "—") },
          { field: "contributing_sensors", value: Array.isArray(fdc.contributing_sensors) ? (fdc.contributing_sensors as string[]).join(", ") : "—" },
        ];
      }
      case "EC": {
        const ec = (latestEvent.EC as Record<string, unknown>) ?? {};
        const constants = (ec.constants as Record<string, Record<string, unknown>>) ?? {};
        return Object.entries(constants).map(([k, v]) => ({
          constant: k, value: String(v.value ?? "—"), nominal: String(v.nominal ?? "—"),
          deviation: `${v.deviation_pct ?? "—"}%`, status: String(v.status ?? "—"),
        }));
      }
      case "TOOL":
        return [
          { field: "toolID", value: toolId },
          { field: "status", value: String(latestEvent.toolID ?? toolId) },
          { field: "step", value: String(latestEvent.step ?? "—") },
          { field: "eventTime", value: String(latestEvent.eventTime ?? "—") },
        ];
      case "LOT":
        return [
          { field: "lotID", value: lotId },
          { field: "step", value: String(latestEvent.step ?? "—") },
          { field: "spc_status", value: spcStatus },
          { field: "fdc_classification", value: fdcClassif },
          { field: "eventTime", value: String(latestEvent.eventTime ?? "—") },
          { field: "events_count", value: String(lotEvents.length) },
        ];
      default:
        return null;
    }
  }, [latestEvent, selectedNode, toolId, lotId, spcStatus, fdcClassif, lotEvents.length]);

  if (lots.length === 0) {
    return <div style={{ padding: 24, textAlign: "center", color: "#a0aec0" }}>（無製程事件可溯源）</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {/* ── Timeline: lot selector ── */}
      <div style={{
        display: "flex", gap: 0, background: "#fff", border: "1px solid #e2e8f0",
        borderRadius: "8px 8px 0 0", overflow: "hidden",
      }}>
        {lots.map(([lid, evs], idx) => {
          const hasOOC = evs.some(e => e.spc_status === "OOC");
          const isSelected = idx === selectedLotIdx;
          return (
            <div key={lid} onClick={() => { setSelectedLotIdx(idx); setSelectedNode(null); }}
              style={{
                flex: 1, padding: "10px 8px", cursor: "pointer", textAlign: "center",
                background: isSelected ? "#ebf4ff" : "transparent",
                borderBottom: isSelected ? "3px solid #2b6cb0" : "3px solid transparent",
                borderRight: idx < lots.length - 1 ? "1px solid #edf2f7" : "none",
                transition: "background 0.15s",
              }}>
              <div style={{ fontSize: 11, fontWeight: isSelected ? 700 : 500, color: isSelected ? "#2b6cb0" : "#4a5568" }}>
                {lid}
              </div>
              <div style={{ fontSize: 9, color: hasOOC ? "#e53e3e" : "#a0aec0", marginTop: 2 }}>
                {hasOOC ? "🔴 OOC" : "✅"} · {evs.length} events
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Topology + Inspector ── */}
      <div style={{ display: "flex", border: "1px solid #e2e8f0", borderTop: "none", borderRadius: "0 0 8px 8px", overflow: "hidden", minHeight: 320 }}>
        {/* SVG Topology */}
        <div style={{ flex: 3, background: "#fafbfc", position: "relative" }}>
          <div style={{ padding: "8px 12px", fontSize: 11, fontWeight: 600, color: "#718096", borderBottom: "1px solid #e2e8f0" }}>
            製程溯源拓撲 — {lotId} ({String(latestEvent?.eventTime ?? "").slice(0, 19)})
          </div>
          <svg viewBox="0 0 600 300" style={{ width: "100%", height: "calc(100% - 32px)" }}>
            <defs>
              <filter id="trace-shadow" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="1" stdDeviation="2" floodColor="#00000015" />
              </filter>
              <filter id="trace-glow" x="-40%" y="-40%" width="180%" height="180%">
                <feDropShadow dx="0" dy="0" stdDeviation="5" floodColor="#e53e3e" floodOpacity="0.35" />
              </filter>
              <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                <polygon points="0 0, 8 3, 0 6" fill="#cbd5e1" />
              </marker>
            </defs>

            {/* Edges with arrows */}
            {edges.map(([fromId, toId]) => {
              const from = topoNodes.find(n => n.id === fromId)!;
              const to = topoNodes.find(n => n.id === toId)!;
              return (
                <line key={`${fromId}-${toId}`}
                  x1={from.x + 36} y1={from.y} x2={to.x - 36} y2={to.y}
                  stroke="#cbd5e1" strokeWidth={1.5} markerEnd="url(#arrowhead)"
                />
              );
            })}

            {/* Nodes */}
            {topoNodes.map(n => {
              const isActive = selectedNode === n.type;
              const isOOC = n.type === "SPC" && spcStatus === "OOC";
              return (
                <g key={n.id} onClick={() => setSelectedNode(n.type)} style={{ cursor: "pointer" }}>
                  <rect
                    x={n.x - 34} y={n.y - 22} width={68} height={44} rx={8}
                    fill={isActive ? `${n.color}15` : "#fff"}
                    stroke={n.color} strokeWidth={isActive ? 2.5 : 1.5}
                    filter={isOOC ? "url(#trace-glow)" : "url(#trace-shadow)"}
                  />
                  <text x={n.x} y={n.y - 6} textAnchor="middle" fontSize={9} fill="#718096" fontWeight={600} dominantBaseline="central">
                    {n.type}
                  </text>
                  <text x={n.x} y={n.y + 9} textAnchor="middle" fontSize={8} fill="#2d3748" fontWeight={500} dominantBaseline="central">
                    {n.label.length > 12 ? n.label.slice(0, 12) + "…" : n.label}
                  </text>
                </g>
              );
            })}

            {/* Layer labels */}
            <text x={60} y={285} textAnchor="middle" fontSize={9} fill="#a0aec0" fontStyle="italic">上游設定</text>
            <text x={220} y={285} textAnchor="middle" fontSize={9} fill="#a0aec0" fontStyle="italic">設備</text>
            <text x={380} y={285} textAnchor="middle" fontSize={9} fill="#a0aec0" fontStyle="italic">批次</text>
            <text x={540} y={285} textAnchor="middle" fontSize={9} fill="#a0aec0" fontStyle="italic">製程結果</text>
          </svg>
        </div>

        {/* Inspector Panel */}
        <div style={{ flex: 2, borderLeft: "1px solid #e2e8f0", background: "#fff", display: "flex", flexDirection: "column" }}>
          <div style={{ padding: "8px 12px", fontSize: 11, fontWeight: 600, color: "#718096", borderBottom: "1px solid #e2e8f0" }}>
            {selectedNode ? `📋 Inspector — ${selectedNode}` : "📋 Inspector"}
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
            {!selectedNode ? (
              <div style={{ padding: 16, textAlign: "center", color: "#a0aec0", fontSize: 12 }}>
                ← 點擊拓撲圖上的節點查看詳細資料
              </div>
            ) : inspectorData && inspectorData.length > 0 ? (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
                <thead><tr>
                  {Object.keys(inspectorData[0]).map(k => (
                    <th key={k} style={{ background: "#f7fafc", padding: "5px 8px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "2px solid #e2e8f0", whiteSpace: "nowrap" }}>{k}</th>
                  ))}
                </tr></thead>
                <tbody>{inspectorData.map((row, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#f7fafc" }}>
                    {Object.values(row).map((v, j) => (
                      <td key={j} style={{ padding: "4px 8px", borderBottom: "1px solid #edf2f7", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" }}>
                        {String(v)}
                      </td>
                    ))}
                  </tr>
                ))}</tbody>
              </table>
            ) : (
              <div style={{ padding: 16, textAlign: "center", color: "#a0aec0", fontSize: 12 }}>（此節點無資料）</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function OOCTopologyPanel({ events, lastUpdate, onRefresh }: { events: ProcessEvent[]; lastUpdate: string; onRefresh: () => void }) {
  // Find most recent OOC event
  const oocEvent = useMemo(() => events.find(e => e.spc_status === "OOC"), [events]);

  if (!oocEvent) {
    return (
      <div style={{ ...S.topoPanel, alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", color: "#a0aec0" }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>✅</div>
          <div style={{ fontSize: 13 }}>近期無 OOC 事件</div>
        </div>
      </div>
    );
  }

  // Build topology nodes from the OOC event
  const nodes = [
    { id: "spc", label: `SPC: ${oocEvent.spc_status}`, type: "SPC", color: "#e53e3e", isCenter: true },
    { id: "lot", label: `${oocEvent.lotID}`, type: "LOT", color: "#3182ce", isCenter: false },
    { id: "tool", label: `${oocEvent.toolID}`, type: "TOOL", color: "#3182ce", isCenter: false },
    { id: "recipe", label: `${String(oocEvent.recipeID ?? (oocEvent.RECIPE as Record<string, unknown>)?.objectID ?? "?")} v${(oocEvent.RECIPE as Record<string, unknown>)?.recipe_version ?? "?"}`, type: "RECIPE", color: "#38a169", isCenter: false },
    { id: "apc", label: `${oocEvent.apcID ?? "APC"}`, type: "APC", color: "#d69e2e", isCenter: false },
    { id: "fdc", label: `FDC: ${(oocEvent.FDC as Record<string, unknown>)?.classification ?? "?"}`, type: "FDC",
      color: (oocEvent.FDC as Record<string, unknown>)?.classification === "FAULT" ? "#e53e3e" : "#38a169", isCenter: false },
  ];

  // Radial layout: SPC center, others orbit
  const cx = 200, cy = 175, radius = 120;
  const positions = nodes.map((n, i) => {
    if (n.isCenter) return { x: cx, y: cy };
    const angle = (2 * Math.PI * (i - 1)) / (nodes.length - 1) - Math.PI / 2;
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });

  return (
    <div style={S.topoPanel}>
      <div style={S.refreshBar}>
        <span>最後更新：{lastUpdate}</span>
        <button onClick={onRefresh} style={{ padding: "2px 8px", fontSize: 10, borderRadius: 4, border: "1px solid #cbd5e0", background: "#fff", cursor: "pointer" }}>⟳</button>
        <span style={{ marginLeft: "auto", fontSize: 10, color: "#a0aec0" }}>5 分鐘自動更新</span>
      </div>
      <div style={{ padding: "12px 16px", fontSize: 12, fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0" }}>
        🔴 最近一次 OOC — {String(oocEvent.eventTime).slice(0, 19)}
      </div>
      <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
        <svg viewBox="0 0 400 350" style={{ width: "100%", height: "100%" }}>
          {/* SVG filter for drop shadow */}
          <defs>
            <filter id="node-shadow" x="-30%" y="-30%" width="160%" height="160%">
              <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#00000020" />
            </filter>
            <filter id="ooc-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feDropShadow dx="0" dy="0" stdDeviation="6" floodColor="#e53e3e" floodOpacity="0.4" />
            </filter>
          </defs>

          {/* Edges: outer nodes connect to center (SPC) */}
          {nodes.slice(1).map((n, i) => (
            <line key={`e-${n.id}`}
              x1={positions[0].x} y1={positions[0].y}
              x2={positions[i + 1].x} y2={positions[i + 1].y}
              stroke="#cbd5e1" strokeWidth={2} strokeLinecap="round"
            />
          ))}

          {/* Nodes */}
          {nodes.map((n, i) => {
            const r = n.isCenter ? 38 : 30;
            const pos = positions[i];
            return (
              <g key={n.id} style={{ cursor: "pointer" }}>
                {/* Circle with shadow / glow */}
                <circle
                  cx={pos.x} cy={pos.y} r={r}
                  fill="#fff"
                  stroke={n.color}
                  strokeWidth={n.isCenter ? 3.5 : 2.5}
                  filter={n.isCenter ? "url(#ooc-glow)" : "url(#node-shadow)"}
                />
                {/* Type label (above) */}
                <text
                  x={pos.x} y={pos.y - 6}
                  textAnchor="middle" fontSize={10} fill="#718096" fontWeight={600}
                  dominantBaseline="central"
                >
                  {n.type}
                </text>
                {/* Value label (below) */}
                <text
                  x={pos.x} y={pos.y + 10}
                  textAnchor="middle" fontSize={9} fill="#2d3748" fontWeight={500}
                  dominantBaseline="central"
                >
                  {n.label.length > 14 ? n.label.slice(0, 14) + "…" : n.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function FabHeatmap({ summary }: { summary: Record<string, unknown> }) {
  const byToolStep = (summary.by_tool_step as Array<Record<string, unknown>>) ?? [];
  const byTool = (summary.by_tool as Array<Record<string, unknown>>) ?? [];
  const byStep = (summary.by_step as Array<Record<string, unknown>>) ?? [];

  if (byTool.length === 0) {
    return <div style={{ padding: 24, textAlign: "center", color: "#a0aec0" }}>（等待資料累積...）</div>;
  }

  // Build heatmap from by_tool_step cross table
  const toolIds = [...new Set(byToolStep.map(r => String(r.toolID)))].sort();
  const steps = [...new Set(byToolStep.map(r => String(r.step)))].sort();

  // Build 2D matrix: rows=steps, cols=tools, values=OOC rate
  const zMatrix: number[][] = [];
  const textMatrix: string[][] = [];
  for (const step of steps) {
    const row: number[] = [];
    const textRow: string[] = [];
    for (const tool of toolIds) {
      const cell = byToolStep.find(r => r.toolID === tool && r.step === step);
      const count = Number(cell?.count ?? 0);
      const ooc = Number(cell?.ooc_count ?? 0);
      const rate = count > 0 ? (ooc / count * 100) : 0;
      row.push(Math.round(rate * 10) / 10);
      textRow.push(`${ooc}/${count} (${rate.toFixed(1)}%)`);
    }
    zMatrix.push(row);
    textMatrix.push(textRow);
  }

  // Fallback: if no by_tool_step data yet, show simple bar chart
  if (zMatrix.length === 0 || toolIds.length === 0) {
    const ids = byTool.map(t => String(t.toolID));
    const rates = byTool.map(t => {
      const c = Number(t.count ?? 0);
      const o = Number(t.ooc_count ?? 0);
      return c > 0 ? (o / c * 100) : 0;
    });
    return (
      <div style={{ padding: "16px 24px" }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "#1a202c", marginBottom: 12 }}>全廠 OOC Rate by Tool (24h)</div>
        <Plot
          data={[{ x: ids, y: rates, type: "bar",
            marker: { color: rates.map(r => r > 30 ? "#e53e3e" : r > 15 ? "#ed8936" : "#48bb78") },
            text: rates.map(r => `${r.toFixed(1)}%`), textposition: "outside",
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          }] as any}
          layout={{ autosize: true, height: 250, margin: { l: 40, r: 16, t: 8, b: 40 },
            paper_bgcolor: "transparent", plot_bgcolor: "#fafbfc",
            font: { family: "Inter, sans-serif", size: 11 },
            xaxis: { title: "Machine" }, yaxis: { title: "OOC %" },
          }}
          config={{ responsive: true, displayModeBar: false }}
          style={{ width: "100%" }} useResizeHandler
        />
      </div>
    );
  }

  return (
    <div style={{ padding: "16px 24px" }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: "#1a202c", marginBottom: 12 }}>
        全廠 SPC OOC Rate Heatmap — Tool × Step (24h)
      </div>
      <Plot
        data={[{
          z: zMatrix,
          x: toolIds,
          y: steps,
          type: "heatmap",
          colorscale: [
            [0, "#f0fff4"],     // 0% — green
            [0.15, "#c6f6d5"],  // 15%
            [0.25, "#fefcbf"],  // 25% — yellow
            [0.40, "#fbd38d"],  // 40% — orange
            [0.60, "#feb2b2"],  // 60%
            [1, "#e53e3e"],     // 100% — red
          ],
          text: textMatrix,
          texttemplate: "%{text}",
          hovertemplate: "Tool: %{x}<br>Step: %{y}<br>OOC Rate: %{z:.1f}%<extra></extra>",
          showscale: true,
          colorbar: { title: "OOC %", titleside: "right" },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        }] as any}
        layout={{
          autosize: true,
          height: Math.max(200, steps.length * 40 + 80),
          margin: { l: 80, r: 80, t: 8, b: 50 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "#fafbfc",
          font: { family: "Inter, sans-serif", size: 11 },
          xaxis: { title: "Machine", side: "bottom" },
          yaxis: { title: "Step", autorange: "reversed" as const },
        }}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: "100%" }}
        useResizeHandler
      />
      {/* Summary stats below heatmap */}
      <div style={{ display: "flex", gap: 24, marginTop: 16 }}>
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "12px 20px", flex: 1 }}>
          <div style={{ fontSize: 11, color: "#718096", textTransform: "uppercase", letterSpacing: "0.5px" }}>Total Events</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#1a202c" }}>{String(summary.total_events ?? 0)}</div>
        </div>
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "12px 20px", flex: 1 }}>
          <div style={{ fontSize: 11, color: "#718096", textTransform: "uppercase", letterSpacing: "0.5px" }}>OOC Count</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#e53e3e" }}>{String(summary.ooc_count ?? 0)}</div>
        </div>
        <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 8, padding: "12px 20px", flex: 1 }}>
          <div style={{ fontSize: 11, color: "#718096", textTransform: "uppercase", letterSpacing: "0.5px" }}>OOC Rate</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: "#dd6b20" }}>{String(summary.ooc_rate ?? "0%")}</div>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function DashboardInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const toolId = searchParams.get("toolId");

  const [tools, setTools] = useState<ToolStatus[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>("SPC");
  const [deepDiveMode, setDeepDiveMode] = useState<DeepDiveMode>("trend");
  const [events, setEvents] = useState<ProcessEvent[]>([]);
  const [summary, setSummary] = useState<Record<string, unknown>>({});
  const [lastUpdate, setLastUpdate] = useState("");
  const [loading, setLoading] = useState(false);
  const refreshTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Fetch tool list on mount
  useEffect(() => {
    fetchTools().then(setTools);
  }, []);

  // Fetch data when toolId changes
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      if (toolId) {
        const result = await fetchProcessInfo(toolId, 50);
        setEvents(result.events);
      } else {
        const result = await fetchSummary();
        setSummary(result);
      }
      setLastUpdate(new Date().toLocaleTimeString("zh-TW", { hour12: false }));
    } finally {
      setLoading(false);
    }
  }, [toolId]);

  useEffect(() => { loadData(); }, [loadData]);

  // 5-minute auto-refresh
  useEffect(() => {
    refreshTimerRef.current = setInterval(loadData, REFRESH_INTERVAL);
    return () => { if (refreshTimerRef.current) clearInterval(refreshTimerRef.current); };
  }, [loadData]);

  const selectTool = (id: string | null) => {
    if (id) {
      router.push(`/dashboard?toolId=${id}`);
    } else {
      router.push("/dashboard");
    }
  };

  const TAB_COMPONENTS: Record<TabKey, React.ReactNode> = {
    SPC: <SPCTab events={events} />,
    APC: <APCTab events={events} />,
    DC: <DCTab events={events} />,
    RECIPE: <RecipeTab events={events} />,
    FDC: <FDCTab events={events} />,
    EC: <ECTab events={events} />,
  };

  return (
    <div style={S.page}>
      {/* ── Sidebar ────────────────────────────────────────── */}
      <div style={S.sidebar(sidebarCollapsed)}>
        <div style={S.sidebarHeader}>
          {!sidebarCollapsed && <span style={{ fontSize: 13, fontWeight: 700, color: "#1a202c" }}>🏭 設備清單</span>}
          <button onClick={() => setSidebarCollapsed(c => !c)}
            style={{ background: "none", border: "none", color: "#718096", cursor: "pointer", fontSize: 14, padding: "2px 4px" }}>
            {sidebarCollapsed ? "▶" : "◀"}
          </button>
        </div>
        {/* Fab overview button */}
        <div style={{ ...S.toolItem(!toolId), borderLeftColor: !toolId ? "#4299e1" : "transparent" }}
          onClick={() => selectTool(null)}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#4299e1" }} />
          {!sidebarCollapsed && <span>全廠總覽</span>}
        </div>
        {/* Tool list */}
        {tools.map(t => (
          <div key={t.tool_id} style={S.toolItem(toolId === t.tool_id)}
            onClick={() => selectTool(t.tool_id)}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: STATUS_COLOR[t.status] ?? "#a0aec0" }} />
            {!sidebarCollapsed && (
              <>
                <span style={{ flex: 1 }}>{t.tool_id}</span>
                <span style={{ fontSize: 10, color: "#718096" }}>{t.status}</span>
              </>
            )}
          </div>
        ))}
      </div>

      {/* ── Main Content — single vertical scroll ────────────── */}
      <div style={S.main}>
        <div style={{ padding: 20 }}>
          {/* AI Summary (collapsible) */}
          <BriefingPanel
            scope={toolId ? "tool" : "fab"}
            toolId={toolId ?? undefined}
          />

          {toolId ? (
            /* Mode B: Tool Deep Dive — top-level tabs */
            <div style={{ marginTop: 20 }}>
              {/* Top-level mode tabs */}
              <div style={{ display: "flex", gap: 0, marginBottom: 16 }}>
                {([
                  { key: "trend" as DeepDiveMode, icon: "📈", label: "趨勢分析" },
                  { key: "trace" as DeepDiveMode, icon: "🔍", label: "製程溯源" },
                ] as const).map(m => (
                  <button key={m.key} onClick={() => setDeepDiveMode(m.key)} style={{
                    padding: "10px 20px", fontSize: 13, fontWeight: deepDiveMode === m.key ? 700 : 400,
                    color: deepDiveMode === m.key ? "#2b6cb0" : "#718096",
                    background: deepDiveMode === m.key ? "#ebf4ff" : "#fff",
                    border: "1px solid #e2e8f0",
                    borderBottom: deepDiveMode === m.key ? "2px solid #2b6cb0" : "1px solid #e2e8f0",
                    cursor: "pointer", borderRadius: m.key === "trend" ? "8px 0 0 0" : "0 8px 0 0",
                  }}>
                    {m.icon} {m.label}
                  </button>
                ))}
                {loading && <span style={{ marginLeft: 12, padding: "10px 0", fontSize: 11, color: "#4299e1", alignSelf: "center" }}>載入中...</span>}
              </div>

              {deepDiveMode === "trend" ? (
                /* 趨勢分析: 6-tab data only */
                <div>
                  <div style={S.tabBar}>
                    {TABS.map(t => (
                      <button key={t} style={S.tab(activeTab === t)} onClick={() => setActiveTab(t)}>
                        {t}
                      </button>
                    ))}
                  </div>
                  <div style={{ padding: "12px 0" }}>
                    {TAB_COMPONENTS[activeTab]}
                  </div>
                </div>
              ) : (
                /* 製程溯源: Process Trace & Inspector */
                <ProcessTracePanel events={events} toolId={toolId} />
              )}
            </div>
          ) : (
            /* Mode A: Fab Overview */
            <div style={{ marginTop: 20 }}>
              <FabHeatmap summary={summary} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


export default function DashboardPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "#a0aec0" }}>載入中...</div>}>
      <DashboardInner />
    </Suspense>
  );
}
