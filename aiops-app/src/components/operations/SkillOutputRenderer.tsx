"use client";

/**
 * SkillOutputRenderer
 *
 * Shared render primitives for Skill findings output_schema.
 * Used by: skills/page.tsx, auto-patrols/page.tsx, AlarmCenter.tsx
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
// Renders the chart DSL produced by backend ChartMiddleware.
// DSL shape: {type, title, data, x, y, rules, highlight}
// One <ChartDSLRenderer> = one chart panel.

const RULE_COLOR: Record<string, string> = {
  danger: "#e53e3e",
  warning: "#dd6b20",
  center: "#4a5568",
};

export function ChartDSLRenderer({ chart }: { chart: ChartDSL }): React.ReactElement {
  if (chart.data.length === 0) {
    return (
      <div style={{ padding: 12, color: "#a0aec0", fontSize: 12, background: "#f7f8fc", borderRadius: 8 }}>
        {chart.title} — （無資料）
      </div>
    );
  }

  // Dispatch by chart type
  if (chart.type === "boxplot") return renderBoxplot(chart);
  if (chart.type === "heatmap") return renderHeatmap(chart);
  if (chart.type === "distribution") return renderDistribution(chart);
  return renderLineBarScatter(chart);
}

// ── Line / Bar / Scatter (+ multi-y / dual-axis / SPC rules / highlight) ─────
function renderLineBarScatter(chart: ChartDSL): React.ReactElement {
  const primaryY = chart.y ?? [];
  const secondaryY = chart.y_secondary ?? [];
  const plotType = chart.type === "bar" ? "bar" : "scatter";
  const mode = chart.type === "scatter" ? "markers" : "lines+markers";
  const seriesField = chart.series_field;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const traces: any[] = [];

  if (seriesField && primaryY.length === 1) {
    // v1.7: group rows by series_field → one colored trace per group
    // (e.g. one line per toolID). SPC rules overlay globally.
    const yKey = primaryY[0];
    const groups = new Map<string, Record<string, unknown>[]>();
    for (const row of chart.data) {
      const key = String(row[seriesField] ?? "default");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(row);
    }
    let gi = 0;
    groups.forEach((rows, name) => {
      const color = SERIES_COLORS[gi % SERIES_COLORS.length];
      traces.push({
        x: rows.map(r => r[chart.x]),
        y: rows.map(r => r[yKey]),
        name,
        type: plotType,
        mode: plotType === "bar" ? undefined : mode,
        line: chart.type === "line" ? { color, width: 2 } : undefined,
        marker: { color, size: 5 },
      });
      gi += 1;
    });
  } else {
    const xs = chart.data.map((r, i) => r[chart.x] ?? i);
    primaryY.forEach((yKey, idx) => {
      const color = SERIES_COLORS[idx % SERIES_COLORS.length];
      traces.push({
        x: xs,
        y: chart.data.map(r => r[yKey]),
        name: yKey,
        type: plotType,
        mode: plotType === "bar" ? undefined : mode,
        line: chart.type === "line" ? { color, width: 2 } : undefined,
        marker: { color, size: 5 },
      });
    });
    secondaryY.forEach((yKey, idx) => {
      const color = SERIES_COLORS[(primaryY.length + idx) % SERIES_COLORS.length];
      traces.push({
        x: xs,
        y: chart.data.map(r => r[yKey]),
        name: `${yKey} (r)`,
        type: plotType,
        mode: plotType === "bar" ? undefined : mode,
        yaxis: "y2",
        line: chart.type === "line" ? { color, width: 2, dash: "dot" } : undefined,
        marker: { color, size: 5 },
      });
    });
  }

  // Highlight (OOC) — applies regardless of series_field; overlays red rings
  // on rows where highlight.field === highlight.eq.
  if (chart.highlight?.field && primaryY.length > 0) {
    const hlField = chart.highlight.field;
    const hlEq = chart.highlight.eq;
    const yKey = primaryY[0];
    const hlRows = chart.data.filter(r => r[hlField] === hlEq);
    if (hlRows.length > 0) {
      traces.push({
        x: hlRows.map(r => r[chart.x]),
        y: hlRows.map(r => r[yKey]),
        name: "異常點",
        type: "scatter",
        mode: "markers",
        marker: { color: "#e53e3e", size: 11, symbol: "circle-open", line: { width: 2, color: "#e53e3e" } },
      });
    }
  }

  // Control lines + labels
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const shapes: any[] = (chart.rules ?? []).map(rule => {
    const color = rule.color ?? RULE_COLOR[rule.style ?? "center"] ?? "#a0aec0";
    const isSigma = rule.style === "sigma";
    return {
      type: "line",
      xref: "paper", x0: 0, x1: 1,
      yref: "y", y0: rule.value, y1: rule.value,
      line: {
        color,
        width: isSigma ? 1 : 1.5,
        dash: rule.style === "center" ? "dot" : (isSigma ? "dashdot" : "dash"),
      },
    };
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const annotations: any[] = (chart.rules ?? []).map(rule => {
    const color = rule.color ?? RULE_COLOR[rule.style ?? "center"] ?? "#a0aec0";
    return {
      xref: "paper", yref: "y",
      x: 1, y: rule.value, xanchor: "right", yanchor: "bottom",
      text: `${rule.label} ${rule.value.toFixed(2)}`,
      font: { size: 10, color },
      showarrow: false,
    };
  });

  const yAxisTitle = primaryY.length === 1 ? primaryY[0] : primaryY.join(", ");
  const showLegend = primaryY.length > 1 || secondaryY.length > 0;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const layout: any = {
    autosize: true,
    height: 260,
    margin: { l: 50, r: secondaryY.length > 0 ? 60 : 80, t: 12, b: 48 },
    paper_bgcolor: "transparent",
    plot_bgcolor: "#f7f8fc",
    font: { family: "Inter, sans-serif", size: 11 },
    showlegend: showLegend,
    legend: { orientation: "h", y: -0.25 },
    xaxis: { gridcolor: "#e2e8f0", title: chart.x },
    yaxis: { gridcolor: "#e2e8f0", title: yAxisTitle },
    shapes,
    annotations,
  };
  if (secondaryY.length > 0) {
    layout.yaxis2 = {
      gridcolor: "transparent",
      title: secondaryY.join(", "),
      overlaying: "y",
      side: "right",
    };
  }

  return (
    <div style={{ background: "#f7f8fc", borderRadius: 8, overflow: "hidden", marginBottom: 8 }}>
      <div style={{ padding: "6px 12px", fontSize: 12, fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0" }}>
        {chart.title}
      </div>
      <Plot
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        data={traces as any}
        layout={layout}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}

// ── Boxplot (group_by x / value y) ───────────────────────────────────────────
function renderBoxplot(chart: ChartDSL): React.ReactElement {
  const yKey = chart.y[0] ?? "value";
  // If chart.x is the pseudo "_all" (no group), drop it to fold into one box.
  const useGroups = chart.x !== "_all";
  const xs = useGroups ? chart.data.map(r => r[chart.x]) : undefined;
  const ys = chart.data.map(r => r[yKey]);

  return (
    <div style={{ background: "#f7f8fc", borderRadius: 8, overflow: "hidden", marginBottom: 8 }}>
      <div style={{ padding: "6px 12px", fontSize: 12, fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0" }}>
        {chart.title}
      </div>
      <Plot
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        data={[{
          type: "box",
          y: ys,
          x: xs,
          name: yKey,
          boxpoints: "outliers",
          marker: { color: "#4299e1" },
          line: { color: "#2b6cb0" },
        }] as any}
        layout={{
          autosize: true,
          height: 280,
          margin: { l: 50, r: 30, t: 12, b: 60 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "#f7f8fc",
          font: { family: "Inter, sans-serif", size: 11 },
          showlegend: false,
          xaxis: { gridcolor: "#e2e8f0", title: useGroups ? chart.x : "" },
          yaxis: { gridcolor: "#e2e8f0", title: yKey },
        }}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}

// ── Distribution (histogram bars + normal PDF curve + σ / USL / LSL lines) ───
function renderDistribution(chart: ChartDSL): React.ReactElement {
  const xs = chart.data.map(r => r["bin_center"]);
  const ys = chart.data.map(r => r["count"]);
  const barWidths = chart.data.map(r => {
    const l = r["bin_left"] as number | undefined;
    const ri = r["bin_right"] as number | undefined;
    return l != null && ri != null ? ri - l : undefined;
  });

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const traces: any[] = [
    {
      type: "bar",
      x: xs,
      y: ys,
      width: barWidths,
      marker: { color: "#4299e1", line: { color: "#2b6cb0", width: 0.5 } },
      name: "count",
      hovertemplate: "bin %{x:.2f}<br>count %{y}<extra></extra>",
    },
  ];
  if (chart.pdf_data && chart.pdf_data.length > 0) {
    traces.push({
      type: "scatter",
      mode: "lines",
      x: chart.pdf_data.map(p => p.x),
      y: chart.pdf_data.map(p => p.y),
      line: { color: "#4a5568", width: 2, dash: "solid" },
      name: "normal fit",
      hovertemplate: "x=%{x:.2f}<br>pdf=%{y:.2f}<extra></extra>",
    });
  }

  // σ / center / USL / LSL as vertical shapes (xref=x, yref=paper)
  // Use the exact same structure as horizontal rules but rotated.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const shapes: any[] = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const annotations: any[] = [];
  for (const rule of chart.rules ?? []) {
    const color = rule.color ?? RULE_COLOR[rule.style ?? "center"] ?? "#a0aec0";
    const isSigma = rule.style === "sigma";
    const isCenter = rule.style === "center";
    shapes.push({
      type: "line",
      xref: "x", x0: rule.value, x1: rule.value,
      yref: "paper", y0: 0, y1: 1,
      line: {
        color,
        width: isCenter ? 2 : (isSigma ? 1 : 1.5),
        dash: isCenter ? "solid" : (isSigma ? "dashdot" : "dash"),
      },
    });
    // Faint shaded bands for ±1σ / ±2σ / ±3σ pairs — applied later via stats
    annotations.push({
      xref: "x", yref: "paper",
      x: rule.value, y: 1, xanchor: "center", yanchor: "bottom",
      text: rule.label,
      font: { size: 10, color },
      showarrow: false,
    });
  }

  // Optional σ zone shaded bands (light background between ±1σ, ±2σ, ±3σ).
  if (chart.stats && chart.stats.sigma > 0) {
    const { mu, sigma } = chart.stats;
    const bandColors: Record<number, string> = { 1: "rgba(34,197,94,0.08)", 2: "rgba(234,179,8,0.06)", 3: "rgba(239,68,68,0.05)" };
    for (const k of [1, 2, 3]) {
      const inner = chart.rules?.some(r => r.style === "sigma" && Math.abs(Math.abs(r.value - mu) - k * sigma) < 1e-6);
      if (!inner) continue;
      shapes.push({
        type: "rect",
        xref: "x", x0: mu - k * sigma, x1: mu + k * sigma,
        yref: "paper", y0: 0, y1: 1,
        fillcolor: bandColors[k],
        line: { width: 0 },
        layer: "below",
      });
    }
  }

  const statsText = chart.stats
    ? `μ=${chart.stats.mu.toFixed(3)}   σ=${chart.stats.sigma.toFixed(3)}   n=${chart.stats.n}   skew=${chart.stats.skewness.toFixed(2)}`
    : "";

  return (
    <div style={{ background: "#f7f8fc", borderRadius: 8, overflow: "hidden", marginBottom: 8 }}>
      <div style={{ padding: "6px 12px", fontSize: 12, fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0", display: "flex", alignItems: "center", gap: 12 }}>
        <span>{chart.title}</span>
        {statsText && (
          <span style={{ fontSize: 10, color: "#718096", fontWeight: 400, fontFamily: "ui-monospace, monospace" }}>
            {statsText}
          </span>
        )}
      </div>
      <Plot
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        data={traces as any}
        layout={{
          autosize: true,
          height: 320,
          margin: { l: 50, r: 40, t: 24, b: 48 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "#f7f8fc",
          font: { family: "Inter, sans-serif", size: 11 },
          showlegend: false,
          bargap: 0.05,
          xaxis: { gridcolor: "#e2e8f0", title: chart.x, zeroline: false },
          yaxis: { gridcolor: "#e2e8f0", title: "count" },
          shapes,
          annotations,
        }}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}

// ── Heatmap (x / y / value_key) ──────────────────────────────────────────────
function renderHeatmap(chart: ChartDSL): React.ReactElement {
  const xKey = chart.x;
  const yKey = chart.y[0] ?? "y";
  const zKey = chart.value_key ?? "value";

  // Collect unique x/y labels (preserve first-seen order)
  const xLabels: string[] = [];
  const yLabels: string[] = [];
  for (const r of chart.data) {
    const xv = String(r[xKey]);
    const yv = String(r[yKey]);
    if (!xLabels.includes(xv)) xLabels.push(xv);
    if (!yLabels.includes(yv)) yLabels.push(yv);
  }
  // Build z matrix [y][x]
  const z: (number | null)[][] = yLabels.map(() => xLabels.map(() => null));
  for (const r of chart.data) {
    const xi = xLabels.indexOf(String(r[xKey]));
    const yi = yLabels.indexOf(String(r[yKey]));
    const v = r[zKey];
    if (xi >= 0 && yi >= 0 && typeof v === "number") z[yi][xi] = v;
  }

  return (
    <div style={{ background: "#f7f8fc", borderRadius: 8, overflow: "hidden", marginBottom: 8 }}>
      <div style={{ padding: "6px 12px", fontSize: 12, fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0" }}>
        {chart.title}
      </div>
      <Plot
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        data={[{
          type: "heatmap",
          x: xLabels,
          y: yLabels,
          z,
          colorscale: "RdBu",
          zmid: 0,
          hovertemplate: `${xKey}: %{x}<br>${yKey}: %{y}<br>${zKey}: %{z:.3f}<extra></extra>`,
        }] as any}
        layout={{
          autosize: true,
          height: Math.max(260, 30 * yLabels.length + 80),
          margin: { l: 100, r: 40, t: 12, b: 60 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "#f7f8fc",
          font: { family: "Inter, sans-serif", size: 11 },
          xaxis: { title: xKey, side: "bottom", automargin: true },
          yaxis: { title: yKey, automargin: true },
        }}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: "100%" }}
        useResizeHandler
      />
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
