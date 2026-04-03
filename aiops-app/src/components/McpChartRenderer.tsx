"use client";

/**
 * McpChartRenderer
 *
 * Renders AIOps MCP ui_render output.
 * Supports:
 *   - Plotly JSON string(s) in ui_render.charts[]
 *   - matplotlib base64 PNG in ui_render.chart_data (data:image/png;base64,...)
 *   - table fallback (ui_render.type === "table" or no charts)
 *
 * Usage:
 *   <McpChartRenderer uiRender={output_data.ui_render} dataset={output_data.dataset} />
 */

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";

// Plotly must be dynamically imported — no SSR support.
// Use factory pattern with plotly.js-dist-min to avoid loading the full bundle.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Plot = dynamic(async () => {
  const Plotly = await import("plotly.js-dist-min");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const createPlotlyComponent = (await import("react-plotly.js/factory")).default as (p: any) => React.ComponentType<any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const PlotComponent = createPlotlyComponent((Plotly as any).default ?? Plotly);
  return { default: PlotComponent };
}, {
  ssr: false,
  loading: () => (
    <div style={{ padding: 24, textAlign: "center", color: "#a0aec0", fontSize: 13 }}>
      載入圖表中...
    </div>
  ),
});

// ── Types ─────────────────────────────────────────────────────────────────────

export interface UiRender {
  type: "trend_chart" | "bar_chart" | "scatter_chart" | "table" | string;
  charts: string[];          // Plotly JSON strings OR base64 PNG data-URLs
  chart_data: string | null; // charts[0] alias (legacy compat)
}

interface PlotlySpec {
  data: object[];
  layout: object;
  config?: object;
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

// ── Sub-components ────────────────────────────────────────────────────────────

function PlotlyChart({ spec, title }: { spec: PlotlySpec; title?: string }) {
  const layout = useMemo(() => ({
    autosize: true,
    height: 360,
    margin: { l: 50, r: 20, t: title ? 55 : 30, b: 80 },
    paper_bgcolor: "transparent",
    plot_bgcolor: "#f7f8fc",
    font: { family: "Inter, sans-serif", size: 11 },
    ...(spec.layout as object),
  }), [spec.layout, title]);

  return (
    <Plot
      data={spec.data}
      layout={layout}
      config={{ responsive: true, displayModeBar: true, displaylogo: false }}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
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
          <PlotlyChart spec={plotlyCharts[tab.idx]} />
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
