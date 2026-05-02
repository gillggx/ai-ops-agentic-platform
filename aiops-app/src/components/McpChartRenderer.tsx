"use client";

/**
 * McpChartRenderer
 *
 * Renders AIOps MCP `ui_render` output via the SVG chart engine.
 * Supports:
 *   - Plotly JSON string(s) in `ui_render.charts[]` — adapted to ChartSpec.
 *   - matplotlib base64 PNG in `ui_render.chart_data` (data:image/png;base64,...)
 *   - table fallback (ui_render.type === "table" or no charts)
 *
 * Plotly is no longer a runtime dependency — the adapter normalises the most
 * common trace shapes (scatter+lines+markers, bar, box, histogram, heatmap)
 * into our internal ChartSpec; unsupported shapes render a placeholder card.
 *
 * Usage:
 *   <McpChartRenderer uiRender={output_data.ui_render} dataset={output_data.dataset} />
 */

import { useState } from "react";
import SvgChartRenderer from "@/components/pipeline-builder/charts/SvgChartRenderer";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface UiRender {
  type: "trend_chart" | "bar_chart" | "scatter_chart" | "table" | string;
  charts: string[];          // Plotly JSON strings OR base64 PNG data-URLs
  chart_data: string | null; // charts[0] alias (legacy compat)
}

interface PlotlyTrace {
  type?: string;
  mode?: string;
  name?: string;
  x?: unknown[];
  y?: unknown[];
  z?: unknown[][];
  text?: unknown[];
}

interface PlotlySpec {
  data: PlotlyTrace[];
  layout?: Record<string, unknown>;
  config?: Record<string, unknown>;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parsePlotlySpec(raw: string): PlotlySpec | null {
  try {
    const spec = JSON.parse(raw);
    if (spec && Array.isArray(spec.data)) return spec as PlotlySpec;
    return null;
  } catch {
    return null;
  }
}

function isBase64Png(s: string) {
  return typeof s === "string" && s.startsWith("data:image/");
}

function plotlyTitle(layout: Record<string, unknown> | undefined): string | undefined {
  if (!layout) return undefined;
  const t = layout.title;
  if (typeof t === "string") return t;
  if (t && typeof t === "object" && typeof (t as { text?: unknown }).text === "string") {
    return (t as { text: string }).text;
  }
  return undefined;
}

function axisTitle(layout: Record<string, unknown> | undefined, axis: "xaxis" | "yaxis"): string | undefined {
  const ax = layout?.[axis] as { title?: unknown } | undefined;
  if (!ax) return undefined;
  if (typeof ax.title === "string") return ax.title;
  if (ax.title && typeof ax.title === "object" && typeof (ax.title as { text?: unknown }).text === "string") {
    return (ax.title as { text: string }).text;
  }
  return undefined;
}

/**
 * Adapt a Plotly JSON spec into our internal ChartSpec.
 *
 * Returns null when the trace shape isn't covered — caller renders an
 * "unsupported" placeholder so the user still sees something useful.
 */
function plotlyToChartSpec(spec: PlotlySpec): Record<string, unknown> | null {
  const traces = (spec.data ?? []).filter(t => t && typeof t === "object");
  if (traces.length === 0) return null;

  const title = plotlyTitle(spec.layout);
  const xField = axisTitle(spec.layout, "xaxis") || "x";
  const yField = axisTitle(spec.layout, "yaxis") || "value";

  const first = traces[0];
  const traceType = (first.type || "scatter").toLowerCase();

  // ── histogram: fold all x[] into single histogram input ───────────
  if (traceType === "histogram") {
    const xs = (first.x ?? []) as number[];
    const data = xs.map(v => ({ [yField]: v }));
    return {
      __dsl: true,
      type: "histogram",
      title,
      data,
      x: yField,
      y: [yField],
    };
  }

  // ── box: each trace becomes one group ─────────────────────────────
  if (traceType === "box") {
    const data: Record<string, unknown>[] = [];
    traces.forEach((t, i) => {
      const ys = (t.y ?? []) as number[];
      const group = (t.name ?? `Series ${i + 1}`) as string;
      ys.forEach(v => data.push({ group, value: v }));
    });
    return {
      __dsl: true,
      type: "box_plot",
      title,
      data,
      x: "group",
      y: ["value"],
      group_by: "group",
    };
  }

  // ── heatmap: z[][] → flattened {x, y, value} rows ─────────────────
  if (traceType === "heatmap") {
    const z = (first.z ?? []) as number[][];
    const xs = (first.x ?? z[0]?.map((_, i) => i) ?? []) as unknown[];
    const ys = (first.y ?? z.map((_, i) => i) ?? []) as unknown[];
    const data: Record<string, unknown>[] = [];
    z.forEach((row, ri) => {
      row.forEach((v, ci) => {
        data.push({
          row: String(ys[ri] ?? ri),
          col: String(xs[ci] ?? ci),
          value: v,
        });
      });
    });
    return {
      __dsl: true,
      type: "heatmap",
      title,
      data,
      x: "col",
      y: ["row"],
      value_field: "value",
    };
  }

  // ── bar: one trace = single series, multi-trace = grouped bars ────
  if (traceType === "bar") {
    if (traces.length === 1) {
      const xs = (first.x ?? []) as unknown[];
      const ys = (first.y ?? []) as number[];
      const data = xs.map((x, i) => ({ [xField]: x, [yField]: ys[i] }));
      return {
        __dsl: true,
        type: "bar",
        title,
        data,
        x: xField,
        y: [yField],
      };
    }
    // Multi-trace bar → series_field with stacked rows.
    const data: Record<string, unknown>[] = [];
    traces.forEach((t, i) => {
      const xs = (t.x ?? []) as unknown[];
      const ys = (t.y ?? []) as number[];
      const series = (t.name ?? `Series ${i + 1}`) as string;
      xs.forEach((x, k) => data.push({ [xField]: x, [yField]: ys[k], series }));
    });
    return {
      __dsl: true,
      type: "bar",
      title,
      data,
      x: xField,
      y: [yField],
      series_field: "series",
    };
  }

  // ── scatter / scattergl: lines+markers → line, markers → scatter ──
  if (traceType === "scatter" || traceType === "scattergl") {
    const mode = (first.mode || "lines").toLowerCase();
    const isLine = mode.includes("lines");
    const chartType = isLine ? "line" : "scatter";

    if (traces.length === 1) {
      const xs = (first.x ?? []) as unknown[];
      const ys = (first.y ?? []) as number[];
      const data = xs.map((x, i) => ({ [xField]: x, [yField]: ys[i] }));
      return {
        __dsl: true,
        type: chartType,
        title,
        data,
        x: xField,
        y: [yField],
      };
    }
    // Multi-series → series_field
    const data: Record<string, unknown>[] = [];
    traces.forEach((t, i) => {
      const xs = (t.x ?? []) as unknown[];
      const ys = (t.y ?? []) as number[];
      const series = (t.name ?? `Series ${i + 1}`) as string;
      xs.forEach((x, k) => data.push({ [xField]: x, [yField]: ys[k], series }));
    });
    return {
      __dsl: true,
      type: chartType,
      title,
      data,
      x: xField,
      y: [yField],
      series_field: "series",
    };
  }

  return null;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PlotlyAdapted({ spec }: { spec: PlotlySpec }) {
  const chartSpec = plotlyToChartSpec(spec);
  if (!chartSpec) {
    const traceType = (spec.data?.[0]?.type as string) || "unknown";
    return (
      <div style={{
        padding: 16, textAlign: "center",
        border: "1px dashed #fcd34d", borderRadius: 6,
        background: "#fffbeb", color: "#92400e", fontSize: 12,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>
          ⚠ Plotly trace type not supported by SVG engine
        </div>
        <div>type=<code>{traceType}</code> — 此圖表類型暫未提供 SVG 對應元件。</div>
      </div>
    );
  }
  return <SvgChartRenderer spec={chartSpec} height={360} />;
}

function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows?.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ background: "#edf2f7" }}>
            {cols.map(c => (
              <th key={c} style={{ padding: "6px 10px", textAlign: "left", fontWeight: 600, color: "#4a5568", borderBottom: "1px solid #e2e8f0" }}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ background: i % 2 ? "#f7f8fc" : "#fff" }}>
              {cols.map(c => (
                <td key={c} style={{ padding: "5px 10px", color: "#2d3748", borderBottom: "1px solid #f0f0f0" }}>
                  {String(row[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export function McpChartRenderer({
  uiRender,
  dataset,
  compact = false,
}: {
  uiRender?: UiRender | null;
  dataset?: Record<string, unknown>[];
  compact?: boolean;
}) {
  const [activeTab, setActiveTab] = useState(0);

  if (!uiRender) return null;

  const charts = uiRender.charts ?? [];
  const plotlyCharts: PlotlySpec[] = [];
  const pngCharts: string[] = [];

  for (const c of charts) {
    if (isBase64Png(c)) {
      pngCharts.push(c);
    } else {
      const spec = parsePlotlySpec(c);
      if (spec) plotlyCharts.push(spec);
    }
  }

  // Also try chart_data (legacy single-chart field)
  if (plotlyCharts.length === 0 && pngCharts.length === 0 && uiRender.chart_data) {
    if (isBase64Png(uiRender.chart_data)) {
      pngCharts.push(uiRender.chart_data);
    } else {
      const spec = parsePlotlySpec(uiRender.chart_data);
      if (spec) plotlyCharts.push(spec);
    }
  }

  const hasCharts = plotlyCharts.length > 0 || pngCharts.length > 0;
  const hasTable = Array.isArray(dataset) && dataset.length > 0;

  if (!hasCharts && !hasTable) return null;

  const tabs: { label: string; type: "plotly" | "png" | "table"; idx: number }[] = [];
  plotlyCharts.forEach((_, i) => tabs.push({ label: `圖表 ${i + 1}`, type: "plotly", idx: i }));
  pngCharts.forEach((_, i) => tabs.push({ label: `圖片 ${i + 1}`, type: "png", idx: i }));
  if (hasTable) tabs.push({ label: `資料表 (${dataset!.length} 筆)`, type: "table", idx: 0 });

  const tab = tabs[activeTab] ?? tabs[0];

  return (
    <div style={{
      background: "#fff", borderRadius: 10,
      border: "1px solid #e2e8f0",
      overflow: "hidden",
    }}>
      {/* Tab bar (only show if multiple tabs) */}
      {tabs.length > 1 && (
        <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0", background: "#f7f8fc" }}>
          {tabs.map((t, i) => (
            <button key={i} onClick={() => setActiveTab(i)} style={{
              padding: "8px 16px", fontSize: 12, fontWeight: 600,
              border: "none", cursor: "pointer",
              background: activeTab === i ? "#fff" : "transparent",
              color: activeTab === i ? "#3182ce" : "#718096",
              borderBottom: activeTab === i ? "2px solid #3182ce" : "2px solid transparent",
            }}>{t.label}</button>
          ))}
        </div>
      )}

      {/* Content */}
      <div style={{ padding: compact ? 8 : 16 }}>
        {tab?.type === "plotly" && (
          <PlotlyAdapted spec={plotlyCharts[tab.idx]} />
        )}
        {tab?.type === "png" && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={pngCharts[tab.idx]} alt="chart" style={{ width: "100%", borderRadius: 6 }} />
        )}
        {tab?.type === "table" && (
          <DataTable rows={dataset!} />
        )}
      </div>
    </div>
  );
}
