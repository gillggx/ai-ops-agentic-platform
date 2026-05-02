"use client";

/**
 * SkillOutputRenderer
 *
 * Shared render primitives for Skill findings output_schema.
 * Used by: skills/page.tsx, auto-patrols/page.tsx, alarms/page.tsx
 *
 * Supported output_schema types:
 *   scalar       → number / string with optional unit
 *   table        → data table with schema-declared columns
 *   badge        → pass / fail / warning chip
 *   line_chart   → line chart (time-series, SPC trend, etc.)
 *   bar_chart    → bar chart (comparisons, distributions)
 *   scatter_chart→ scatter plot (correlation)
 *
 * Chart fields (for chart types):
 *   x_key         → which key in each record is the x-axis
 *   y_keys        → which keys are y-series (auto-colored)
 *   highlight_key → optional boolean key: true points get red markers
 */

import dynamic from "next/dynamic";
import { useMemo } from "react";

// ── Types ──────────────────────────────────────────────────────────────────────

export type OutputSchemaField = {
  key: string;
  type: string;        // "scalar"|"table"|"badge"|"line_chart"|"bar_chart"|"scatter_chart"|"multi_line_chart"
  label: string;
  unit?: string;
  description?: string;
  columns?: { key: string; label: string; type?: string }[];
  // Chart-specific
  x_key?: string;
  y_keys?: string[];
  y_key?: string;      // single y key for multi_line_chart
  group_key?: string;  // group data by this key → one chart per group
  highlight_key?: string;  // boolean field → mark true rows with red markers
};

export type SkillFindings = {
  condition_met: boolean;
  summary?: string;
  outputs?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  impacted_lots?: string[];
};

/** Chart DSL produced by backend ChartMiddleware + pipeline-builder block_chart. */
export type ChartDSL = {
  type: "line" | "bar" | "scatter" | "boxplot" | "heatmap" | "distribution";
  title: string;
  data: Record<string, unknown>[];
  x: string;
  y: string[];
  /** Secondary-axis series (dual Y); v3.3 multi-y support. */
  y_secondary?: string[];
  /** For heatmap: which record field holds the cell value (colour). */
  value_key?: string;
  /** For distribution: fitted normal PDF points (scaled to bar height). */
  pdf_data?: { x: number; y: number }[];
  /** For distribution: summary stats shown in top-right annotation. */
  stats?: { mu: number; sigma: number; n: number; skewness: number };
  rules?: {
    value: number;
    label: string;
    style?: "danger" | "warning" | "center" | "sigma";
    /** Optional per-rule colour override (used by sigma zones). */
    color?: string;
  }[];
  highlight?: { field: string; eq: unknown } | null;
  /** v1.7: when present, the renderer groups `data` by this field and
   *  emits one colored trace per distinct value (e.g. one line per toolID).
   *  SPC overlays (UCL/LCL/Center) stay as global rules. */
  series_field?: string;
};

// ── Plotly dynamic import (no SSR) ────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = dynamic(async () => {
  const Plotly = await import("plotly.js-dist-min");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const factory = (await import("react-plotly.js/factory")).default as (p: any) => React.ComponentType<any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return { default: factory((Plotly as any).default ?? Plotly) };
}, {
  ssr: false,
  loading: () => <div style={{ padding: 24, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>載入圖表中...</div>,
});

// ── Auto-color palette ─────────────────────────────────────────────────────────

const SERIES_COLORS = [
  "#48bb78", // green
  "#ed8936", // orange
  "#4299e1", // blue
  "#9f7aea", // purple
  "#38b2ac", // teal
  "#f56565", // red
  "#ecc94b", // yellow
];

// ── Chart renderer ─────────────────────────────────────────────────────────────

function ChartOutputRenderer({
  val, field,
}: {
  val: unknown;
  field: OutputSchemaField;
}): React.ReactElement {
  const plotlyType = field.type === "bar_chart" ? "bar"
                   : field.type === "scatter_chart" ? "scatter"
                   : "scatter"; // line_chart

  const mode = field.type === "bar_chart" ? undefined
             : field.type === "scatter_chart" ? "markers"
             : "lines+markers";

  const rows = Array.isArray(val) ? val as Record<string, unknown>[] : [];

  const traces = useMemo(() => {
    if (rows.length === 0) return [];
    const xKey = field.x_key ?? "index";
    const yKeys = field.y_keys ?? Object.keys(rows[0] ?? {}).filter(k => k !== xKey && k !== field.highlight_key);
    const xs = rows.map((r, i) => r[xKey] ?? i);

    const seriesTraces = yKeys.map((yk, idx) => ({
      x: xs,
      y: rows.map(r => r[yk]),
      name: yk,
      type: plotlyType,
      mode,
      line: field.type === "line_chart" ? { color: SERIES_COLORS[idx % SERIES_COLORS.length], width: 2 } : undefined,
      marker: { color: SERIES_COLORS[idx % SERIES_COLORS.length], size: 5 },
    }));

    // Highlight trace (e.g. OOC points in red)
    if (field.highlight_key) {
      const hlKey = field.highlight_key;
      const hlRows = rows.filter(r => r[hlKey]);
      if (hlRows.length > 0) {
        const xKey2 = field.x_key ?? "index";
        const yKey = yKeys[0];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        seriesTraces.push({
          x: hlRows.map((r, i) => r[xKey2] ?? rows.indexOf(r) ?? i),
          y: hlRows.map(r => r[yKey]),
          name: "異常點",
          type: "scatter",
          mode: "markers",
          marker: { color: "#e53e3e", size: 10, symbol: "circle-open", line: { width: 2, color: "#e53e3e" } } as any,
          line: undefined,
        } as any);
      }
    }

    return seriesTraces;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [val, field]);

  if (rows.length === 0) {
    return <span style={{ color: "#a0aec0", fontSize: 12 }}>（無資料）</span>;
  }

  return (
    <div style={{ background: "#f7f8fc", borderRadius: 8, overflow: "hidden" }}>
      <Plot
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        data={traces as any}
        layout={{
          autosize: true,
          height: 280,
          margin: { l: 45, r: 16, t: 24, b: 48 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "#f7f8fc",
          font: { family: "Inter, sans-serif", size: 11 },
          legend: { orientation: "h", y: -0.25, x: 0 },
          xaxis: { gridcolor: "#e2e8f0", title: field.x_key ?? "index" },
          yaxis: { gridcolor: "#e2e8f0" },
        }}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}

// ── Multi-chart renderer (one chart per group) ────────────────────────────────

function MultiChartRenderer({
  val, field,
}: {
  val: unknown;
  field: OutputSchemaField;
}): React.ReactElement {
  const rows = Array.isArray(val) ? val as Record<string, unknown>[] : [];
  const groupKey = field.group_key ?? "group";
  const xKey = field.x_key ?? "index";
  const yKey = field.y_key ?? field.y_keys?.[0] ?? "value";
  const highlightKey = field.highlight_key;

  // Group data by group_key
  const groups = useMemo(() => {
    const map = new Map<string, Record<string, unknown>[]>();
    for (const row of rows) {
      const group = String(row[groupKey] ?? "default");
      if (!map.has(group)) map.set(group, []);
      map.get(group)!.push(row);
    }
    return Array.from(map.entries());
  }, [rows, groupKey]);

  if (groups.length === 0) {
    return <span style={{ color: "#a0aec0", fontSize: 12 }}>（無資料）</span>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {groups.map(([groupName, groupRows], gi) => {
        const xs = groupRows.map((r, i) => r[xKey] ?? i);
        const ys = groupRows.map(r => r[yKey]);

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const traces: any[] = [
          {
            x: xs,
            y: ys,
            name: yKey,
            type: "scatter",
            mode: "lines+markers",
            line: { color: SERIES_COLORS[gi % SERIES_COLORS.length], width: 2 },
            marker: { color: SERIES_COLORS[gi % SERIES_COLORS.length], size: 5 },
          },
        ];

        // Highlight points
        if (highlightKey) {
          const hlRows = groupRows.filter(r => r[highlightKey]);
          if (hlRows.length > 0) {
            traces.push({
              x: hlRows.map((r, i) => r[xKey] ?? i),
              y: hlRows.map(r => r[yKey]),
              name: "異常點",
              type: "scatter",
              mode: "markers",
              marker: { color: "#e53e3e", size: 10, symbol: "circle-open" },
            });
          }
        }

        return (
          <div key={groupName} style={{ background: "#f7f8fc", borderRadius: 8, overflow: "hidden" }}>
            <div style={{ padding: "6px 12px", fontSize: 12, fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0" }}>
              {groupName}
            </div>
            <Plot
              data={traces as any}
              layout={{
                autosize: true,
                height: 200,
                margin: { l: 45, r: 16, t: 8, b: 40 },
                paper_bgcolor: "transparent",
                plot_bgcolor: "#f7f8fc",
                font: { family: "Inter, sans-serif", size: 10 },
                showlegend: false,
                xaxis: { gridcolor: "#e2e8f0", title: xKey },
                yaxis: { gridcolor: "#e2e8f0" },
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

// ── Primitive value renderer ───────────────────────────────────────────────────

function PrimitiveValue({ val }: { val: unknown }): React.ReactElement {
  if (val === null || val === undefined) return <span style={{ color: "#a0aec0" }}>—</span>;
  if (typeof val === "boolean")
    return val
      ? <span style={{ color: "#276749", fontWeight: 600 }}>✅ 是</span>
      : <span style={{ color: "#c53030", fontWeight: 600 }}>❌ 否</span>;
  if (typeof val === "number") return <strong style={{ color: "#2d3748" }}>{val}</strong>;
  if (typeof val === "string") return <span>{val}</span>;
  if (Array.isArray(val)) {
    if (val.length === 0) return <span style={{ color: "#a0aec0" }}>—</span>;
    if (typeof val[0] === "object" && val[0] !== null) {
      const cols = Object.keys(val[0] as Record<string, unknown>);
      return (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead><tr>{cols.map(c => (
              <th key={c} style={{ background: "#f7fafc", padding: "4px 10px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0", whiteSpace: "nowrap" }}>{c}</th>
            ))}</tr></thead>
            <tbody>{(val as Record<string, unknown>[]).map((row, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#f7fafc" }}>
                {cols.map(c => (
                  <td key={c} style={{ padding: "4px 10px", borderBottom: "1px solid #f7fafc" }}>
                    <PrimitiveValue val={row[c]} />
                  </td>
                ))}
              </tr>
            ))}</tbody>
          </table>
        </div>
      );
    }
    return (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {(val as unknown[]).map((v, i) => (
          <span key={i} style={{ background: "#edf2f7", padding: "2px 8px", borderRadius: 10, fontSize: 11, color: "#4a5568" }}>{String(v)}</span>
        ))}
      </div>
    );
  }
  return <code style={{ fontSize: 11, color: "#6b46c1" }}>{JSON.stringify(val)}</code>;
}

// ── RenderOutputValue (public) ─────────────────────────────────────────────────

export function RenderOutputValue({
  val, field,
}: {
  val: unknown;
  field?: OutputSchemaField;
}): React.ReactElement {
  const type = field?.type ?? "auto";
  if (val === null || val === undefined) return <span style={{ color: "#a0aec0" }}>—</span>;

  // Chart types
  if ((type === "line_chart" || type === "bar_chart" || type === "scatter_chart") && field) {
    return <ChartOutputRenderer val={val} field={field} />;
  }

  if (type === "multi_line_chart" && field) {
    return <MultiChartRenderer val={val} field={field} />;
  }

  if (type === "badge") {
    const label = Array.isArray(val) ? val.join(", ") : String(val);
    const isOk = /正常|pass|ok|false/i.test(label);
    return (
      <span style={{ padding: "2px 10px", borderRadius: 10, fontSize: 12, fontWeight: 600,
        background: isOk ? "#c6f6d5" : "#fed7d7", color: isOk ? "#276749" : "#c53030" }}>
        {label}
      </span>
    );
  }

  if (type === "scalar") {
    // Tolerate object values: extract .value or first numeric field
    let display: string;
    if (val != null && typeof val === "object" && !Array.isArray(val)) {
      const obj = val as Record<string, unknown>;
      display = String(obj.value ?? obj.total ?? obj.count ?? Object.values(obj).find(v => typeof v === "number") ?? JSON.stringify(obj));
    } else {
      display = String(val);
    }
    return (
      <span>
        <strong style={{ color: "#2d3748", fontSize: 15 }}>{display}</strong>
        {field?.unit && <span style={{ fontSize: 12, color: "#718096", marginLeft: 4 }}>{field.unit}</span>}
      </span>
    );
  }

  if (type === "table" && Array.isArray(val) && val.length > 0) {
    const cols = field?.columns ?? Object.keys(val[0] as Record<string, unknown>).map(k => ({ key: k, label: k }));
    return (
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>{cols.map(c => (
              <th key={c.key} style={{ background: "#f7fafc", padding: "4px 10px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0", whiteSpace: "nowrap" }}>
                {c.label}
              </th>
            ))}</tr>
          </thead>
          <tbody>
            {(val as Record<string, unknown>[]).map((row, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? "#fff" : "#f7fafc" }}>
                {cols.map(c => (
                  <td key={c.key} style={{ padding: "4px 10px", borderBottom: "1px solid #f7fafc" }}>
                    <PrimitiveValue val={row[c.key]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return <PrimitiveValue val={val} />;
}

// ── ChartDSLRenderer (public) ─────────────────────────────────────────────────
//
// Stage 4 dispatcher delegate. All real rendering now lives in the new SVG
// engine at @/components/pipeline-builder/charts. Both the alarm-detail
// RenderMiddleware path AND Pipeline Builder ResultsBody flow through this
// single function, so the SVG engine reaches every consumer in one cut.
//
// The Plotly-based ChartOutputRenderer / MultiChartRenderer above remain
// untouched — those handle output_schema-driven charts, a separate path
// that downstream consumers (dashboard, contract, ChartIntent, McpChart,
// etc.) also rely on. Migrating those is future work.
import SvgChartRenderer from "@/components/pipeline-builder/charts/SvgChartRenderer";
import "@/styles/chart-tokens.css";

export function ChartDSLRenderer({ chart }: { chart: ChartDSL }): React.ReactElement {
  return (
    <div className="pb-chart-card" style={{ width: "100%", marginBottom: 8 }}>
      <SvgChartRenderer spec={chart as unknown as Record<string, unknown>} />
    </div>
  );
}


export function ChartListRenderer({ charts }: { charts?: ChartDSL[] | null }): React.ReactElement | null {
  if (!charts || charts.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
      {charts.map((c, i) => <ChartDSLRenderer key={`${c.title}-${i}`} chart={c} />)}
    </div>
  );
}

// ── RenderMiddleware (public) ──────────────────────────────────────────────────

/** Output schema types whose data is rendered as charts via backend ChartMiddleware.
 *  These keys are skipped from RenderMiddleware's inline output rendering — the
 *  charts are drawn separately by <ChartListRenderer charts={tryRunResult.charts}/>. */
const CHART_MIDDLEWARE_TYPES = new Set([
  "spc_chart", "line_chart", "bar_chart", "scatter_chart", "multi_line_chart",
]);

export function RenderMiddleware({
  findings, outputSchema, charts,
}: {
  findings: SkillFindings;
  outputSchema?: OutputSchemaField[];
  charts?: ChartDSL[] | null;
}): React.ReactElement {
  const isNew = !!findings.outputs && Object.keys(findings.outputs).length > 0;
  const allEntries = isNew
    ? Object.entries(findings.outputs ?? {})
    : Object.entries(findings.evidence ?? {});

  // Skip outputs whose schema type is rendered via backend ChartMiddleware
  const dataEntries = allEntries.filter(([k]) => {
    const fieldSpec = outputSchema?.find(f => f.key === k);
    return !(fieldSpec?.type && CHART_MIDDLEWARE_TYPES.has(fieldSpec.type));
  });

  return (
    <div style={{ fontSize: 13 }}>
      {/* Condition banner — subdued colors */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "8px 12px", borderRadius: 6, marginBottom: 10,
        background: "#fff",
        border: "1px solid #e2e8f0",
        borderLeft: `4px solid ${findings.condition_met ? "#e53e3e" : "#48bb78"}`,
      }}>
        <span style={{ fontSize: 14 }}>{findings.condition_met ? "🔴" : "🟢"}</span>
        <div>
          <span style={{ fontWeight: 600, color: "#2d3748" }}>
            {findings.condition_met ? "條件達成 — 將觸發警報" : "條件未達成 — 不觸發警報"}
          </span>
          {findings.summary && (
            <div style={{ fontSize: 12, color: "#4a5568", marginTop: 2 }}>{findings.summary}</div>
          )}
        </div>
      </div>

      {/* Non-chart outputs (scalar / badge / table) */}
      {dataEntries.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {dataEntries.map(([k, v]) => {
            const fieldSpec = outputSchema?.find(f => f.key === k);
            const label = fieldSpec?.label ?? k.replace(/_/g, " ");
            return (
              <div key={k}>
                <div style={{
                  fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 3,
                  textTransform: "uppercase", letterSpacing: "0.3px",
                }}>
                  {label}
                  {fieldSpec?.description && (
                    <span style={{ fontWeight: 400, marginLeft: 4, textTransform: "none" }}>{fieldSpec.description}</span>
                  )}
                </div>
                <RenderOutputValue val={v} field={fieldSpec} />
              </div>
            );
          })}
        </div>
      )}

      {/* Chart DSL from backend ChartMiddleware (spc_chart, line_chart, etc.) */}
      <ChartListRenderer charts={charts} />


      {!isNew && dataEntries.length === 0 && (
        <div style={{ fontSize: 12, color: "#718096", fontStyle: "italic" }}>
          請重新生成診斷計畫以使用新格式顯示結果
        </div>
      )}

      {/* Impacted lots */}
      {(findings.impacted_lots ?? []).length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 4, textTransform: "uppercase" }}>受影響 Lots</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {(findings.impacted_lots ?? []).map((lot, i) => (
              <span key={i} style={{ background: "#fed7d7", color: "#c53030", padding: "2px 8px", borderRadius: 10, fontSize: 11, fontWeight: 500 }}>
                {lot}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
